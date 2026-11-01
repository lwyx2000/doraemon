"""补充池 —— 麦蕊 fund_rank 覆盖不到、但仍在正常交易的场内基金（LOF / 跨境 ETF）。

背景（2026-10-28 实测）：53 网关 ``processed_data?category=fund_rank&subtype=lof``
只有 308 只，缺 164705/161831/160717/160322/161124 等仍在正常交易的港股系 LOF
（新浪有当日报价、东财有 T-1 净值）。换宽口径也不行：``subtype=all`` 与 ``lof``
交集只有 207 只，不是超集，拿不到这 5 只。所以只能自建补充池。

2026-10-30 追加：日经 3 只（513000/159866/513880）同样落在麦蕊口径外 —— 实测
``subtype=etf`` 3724 只、``subtype=all`` 5088 只均不含它们（只有 159985 在）。
它们能算出 est_nav，却因不在列表里导致整行不显示，所以一并并入本池。

取数分两段，**优先走网关**：

1. 网关段（ETF 口径，零直连）：``fund_etf_fund_daily_em`` 一次批量（2026-10-30 实测
   1690 条 / 2.4s），直接给出 市价 + 单位净值 + 净值日期。覆盖所有场内 ETF，
   所以日经 3 只不必碰新浪。注意该源 16:00~23:00 才更新当日数据，盘中取到的是
   **上一交易日收盘价**；但它同时给出的净值也是同一时点，故折溢价率仍自洽。

2. 直连段（LOF 口径，兜底）：网关侧没有可用的 LOF 行情源 —— ``fund_lof_spot_em`` /
   ``fund_lof_hist_em`` 都走东财 push2his 行情站，在该网关长期 500/超时
   （2026-10-30 复发实测：spot 92s→500、单只 hist 全超时）；``stock_zh_a_daily`` /
   ``stock_zh_a_hist_tx`` 传基金代码一律 500；``stock_zh_a_spot`` 5576 条全是 A 股
   且要 148s。所以只能走新浪个股实时 ``hq.sinajs.cn/list=sz164705,...``，一次批量。
   字段 [0]名称 [2]昨收 [3]现价 [9]成交额 [30]日期。
   实测与 fund_rank 的 成交额 严格 1:1（160924: 39357）。
   净值仍走网关 ``fund_open_fund_info_em``（逐只 0.8~1.6s）。

调用约定与 ``_attach_kline_metrics`` 一致：**请求路径只读缓存**，缺失由后台线程预热，
首次访问这部分基金不出现（不是出错），预热完成后自动并入，后续 1h 命中缓存。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

from services.akshare_client import akshare_request, get_session

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "lof_supplement.json",
)

# 网关 ETF 报价腿超时：实测成功 2.4s/1690 条。给 25s 而不是 60s —— 失败时这段
# 时间要整段等满，而 25s 已是成功耗时的 10 倍，够应付抖动；再长只是让缓存空更久。
_GW_QUOTE_TIMEOUT = 25

_SUPPLEMENT_TTL = 3600

# 本轮取数全失败时的重试间隔。不能用 TTL —— 网关抖一下就把缓存锁 1 小时，
# 用户看到的现象是「这几只明明有估值，页面上却一整个小时没有行」。
_RETRY_AFTER_EMPTY = 300
_SUPPLEMENT_CACHE: dict[str, object] = {"ts": 0.0, "rows": []}
_SUPPLEMENT_LOCK = threading.Lock()
_SUPPLEMENT_WARMING = False


def _load_entries() -> list[dict]:
    """读配置里的补充条目。配置缺失/损坏一律视为空（不猜代码）。

    两种写法都支持：
      "164705"                            等价于 {"code": "164705", "type": "lof"}
      {"code": "513000", "type": "etf"}   显式声明品类，决定它归到哪个 tab
    显式 type 是必要的：513000 这类是场内 ETF，按默认 lof 落到 LOF tab 会错位。
    """
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[LofSupplement] 配置读取失败: {type(e).__name__}: {e}")
        return []
    out: list[dict] = []
    for raw in cfg.get("codes") or []:
        if isinstance(raw, dict):
            code = str(raw.get("code") or "").strip()
            ftype = str(raw.get("type") or "lof").strip().lower()
        else:
            code, ftype = str(raw).strip(), "lof"
        # 场内基金代码 6 位：1 开头深市、5 开头沪市
        if len(code) != 6 or not code.isdigit() or code[0] not in ("1", "5"):
            continue
        if ftype not in ("lof", "etf"):
            print(f"[LofSupplement] {code} type={ftype!r} 不支持，按 lof 处理")
            ftype = "lof"
        out.append({"code": code, "type": ftype})
    return out


def _sina_symbol(code: str) -> str:
    return ("sh" if code.startswith("5") else "sz") + code


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _fetch_gateway_quotes(codes: list[str]) -> dict[str, dict]:
    """网关批量取场内 ETF 的 市价/净值/净值日（一次请求，零直连）。

    数据源 ``fund_etf_fund_daily_em`` 走天天基金域，与 push2his 行情站不同域 ——
    2026-10-30 实测同一时刻 fund_etf_spot_em 92s 后 500，而它 2.4s 返回 1690 条。
    两者不能混为一谈，这也是这条腿能用、spot 类不能用的原因。

    返回 {code: {name, price, nav, nav_date, change_pct, src}}；未覆盖的代码不出现
    （LOF 不在 ETF 表里，交给直连段）。
    """
    want = set(codes)
    if not want:
        return {}
    try:
        data = akshare_request("fund_etf_fund_daily_em", {}, retries=1,
                               timeout=_GW_QUOTE_TIMEOUT)
    except Exception as e:
        print(f"[LofSupplement] 网关 ETF 报价失败: {type(e).__name__}: {e}")
        return {}
    if not isinstance(data, list) or not data:
        print("[LofSupplement] 网关 ETF 报价为空，本轮交给直连段")
        return {}
    out: dict[str, dict] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        code = str(row.get("基金代码") or "").strip()
        if code not in want:
            continue
        price = _f(row.get("市价"))
        # 净值列名带日期（形如 "2026-10-29-单位净值"），取日期最新的那列
        nav, nav_date = None, ""
        for k in row:
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-单位净值$", str(k))
            if not m:
                continue
            v = _f(row.get(k))
            if v and v > 0 and (not nav_date or m.group(1) > nav_date):
                nav, nav_date = v, m.group(1)
        if not price or price <= 0 or not nav:
            continue
        out[code] = {
            "name": str(row.get("基金简称") or "").strip(),
            "price": price,
            "nav": nav,
            "nav_date": nav_date,
            # 上游「增长率」是**净值**日涨幅，不是场内价涨跌幅，直接沿用并靠 source 区分
            "change_pct": _f(str(row.get("增长率") or "").strip().rstrip("%")),
            "src": "gateway",
        }
    print(f"[LofSupplement] 网关 ETF 报价命中 {len(out)}/{len(want)} 只")
    return out


def _fetch_quotes(codes: list[str]) -> dict[str, dict]:
    """新浪批量实时报价（LOF 兜底 —— 网关侧没有可用的 LOF 行情源）。

    返回 {code: {name, price, prev_close, amount, date}}。
    """
    if not codes:
        return {}
    out: dict[str, dict] = {}
    try:
        text = get_session().get(
            "https://hq.sinajs.cn/list=" + ",".join(_sina_symbol(c) for c in codes),
            timeout=15,
            headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"},
        ).content.decode("gbk", "ignore")
    except Exception as e:
        print(f"[LofSupplement] 新浪报价失败: {type(e).__name__}: {e}")
        return {}
    for m in re.finditer(r'hq_str_(\w+)="([^"]*)"', text):
        f = (m.group(2) or "").split(",")
        # 停牌/退市时新浪返回空串或字段不足，直接跳过（不补 0）
        if len(f) < 32 or not f[3]:
            continue
        code = m.group(1)[2:]
        price, prev = _f(f[3]), _f(f[2])
        if not price or price <= 0:
            continue
        out[code] = {
            "name": f[0].strip(),
            "price": price,
            "prev_close": prev,
            # 单位与 fund_rank 的 volume 口径一致（成交额，元）
            "amount": _f(f[9]),
            "date": f[30].strip(),
        }
    return out


def _fetch_nav(code: str) -> tuple[float, str] | None:
    """网关取最新单位净值。返回 (nav, nav_date) 或 None。"""
    data = akshare_request(
        "fund_open_fund_info_em",
        {"symbol": code, "indicator": "单位净值走势"},
        retries=1,
        timeout=25,
    )
    if not isinstance(data, list) or not data:
        return None
    latest = None
    for row in data:
        if not isinstance(row, dict):
            continue
        if "净值日期" not in row or "单位净值" not in row:
            continue
        d = str(row.get("净值日期") or "")[:10]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            continue
        if latest is None or d > latest[1]:
            nav = _f(row.get("单位净值"))
            if nav and nav > 0:
                latest = (nav, d)
    return latest


def _build_row(code: str, ftype: str, name: str, price: float, nav: float,
               nav_date: str, volume, change_pct, src: str) -> dict:
    """按 fund_rank 同口径组装一行，保证并入后 tab 筛选 / 套利计算不失真。"""
    premium_pct = round((price - nav) / nav * 100.0, 4)
    return {
        "name": name,
        "code": code,
        "type": ftype,
        "price": price,
        # LOF/ETF 无 IOPV 概念，统一以 NAV 近似供前端展示（与主链路一致）
        "iopv": nav,
        "premium_pct": premium_pct,
        "premium_percentile": None,
        "net_arbitrage_yield": premium_pct,
        "nav": nav,
        "nav_date": nav_date,
        "volume": volume,
        "subscribe_limit": None,
        "is_suspended": False,
        "val_category": None,
        "change_pct": change_pct if change_pct is not None else 0.0,
        # 标记来源 + 走的哪条腿，便于排查「这行不是 fund_rank 来的」
        "source": f"lof_supplement:{src}",
    }


def _refresh() -> list[dict]:
    entries = _load_entries()
    if not entries:
        return []
    codes = [e["code"] for e in entries]
    type_of = {e["code"]: e["type"] for e in entries}

    # 第一段：网关 ETF 口径（自带净值，不必再逐只打净值接口）
    gw = _fetch_gateway_quotes(codes)
    rows: list[dict] = []
    rest: list[str] = []
    for code in codes:
        g = gw.get(code)
        if not g:
            if type_of[code] == "etf":
                # ETF 的规则是零直连：网关没给就不出数，宁可空着也不回退新浪。
                print(f"[LofSupplement] {code}(etf) 网关报价无命中，本轮不出"
                      f"（ETF 不走直连）")
                continue
            rest.append(code)
            continue
        rows.append(_build_row(code, type_of[code], g["name"], g["price"],
                               g["nav"], g["nav_date"], None,
                               g.get("change_pct"), "gateway_etf_daily"))

    # 第二段：网关覆盖不到的（LOF 口径）→ 新浪报价 + 网关净值
    if rest:
        quotes = _fetch_quotes(rest)
        nav_fails = 0
        for code in rest:
            q = quotes.get(code)
            if not q:
                print(f"[LofSupplement] {code} 无实时报价，跳过")
                continue
            nav_info = _fetch_nav(code)
            if not nav_info:
                # 熔断：网关整体不可用时逐只重试只是空转（单只超时 25s），
                # 2026-10-30 实测 8 只全超时会占住预热线程 260s，缓存一直为空。
                nav_fails += 1
                print(f"[LofSupplement] {code} 无净值，跳过（净值腿连续失败 {nav_fails}）")
                if nav_fails >= 2:
                    print("[LofSupplement] 净值腿连续失败，判定网关不可用，本轮中止")
                    break
                continue
            nav_fails = 0
            nav, nav_date = nav_info
            price = q["price"]
            change_pct = (round((price / q["prev_close"] - 1) * 100.0, 4)
                          if q.get("prev_close") else None)
            rows.append(_build_row(
                code, type_of[code], q["name"], price, nav, nav_date,
                int(q["amount"]) if q.get("amount") else None,
                change_pct, "sina_quote",
            ))

    n_gw = sum(1 for r in rows if str(r["source"]).endswith("gateway_etf_daily"))
    print(f"[LofSupplement] 补充池命中 {len(rows)}/{len(codes)} 只"
          f"（网关段 {n_gw} / 直连段 {len(rows) - n_gw}）")
    return rows


def _warm() -> None:
    global _SUPPLEMENT_WARMING
    try:
        rows = _refresh()
        with _SUPPLEMENT_LOCK:
            if rows:
                _SUPPLEMENT_CACHE["ts"] = time.time()
                _SUPPLEMENT_CACHE["rows"] = rows
            else:
                # 全空 = 本轮全失败（网关抖动/上游挂）：保留上一轮 rows（旧数据比空好），
                # 只把 ts 拨到「5 分钟后过期」，避免一次抖动造成 1 小时空窗。
                _SUPPLEMENT_CACHE["ts"] = (
                    time.time() - _SUPPLEMENT_TTL + _RETRY_AFTER_EMPTY
                )
                print(f"[LofSupplement] 本轮为空，{_RETRY_AFTER_EMPTY // 60} 分钟后重试"
                      f"（保留旧行 {len(_SUPPLEMENT_CACHE['rows'] or [])} 只）")
    except Exception as e:
        print(f"[LofSupplement] 预热失败: {type(e).__name__}: {e}")
    finally:
        _SUPPLEMENT_WARMING = False


def get_supplement_funds() -> list[dict]:
    """返回补充池基金（只读缓存）。空列表 = 尚未预热完成或取数失败，调用方按“无”处理。"""
    global _SUPPLEMENT_WARMING
    with _SUPPLEMENT_LOCK:
        rows = list(_SUPPLEMENT_CACHE["rows"] or [])
        fresh = (time.time() - float(_SUPPLEMENT_CACHE["ts"] or 0)) < _SUPPLEMENT_TTL
        need_warm = not fresh and not _SUPPLEMENT_WARMING
        if need_warm:
            _SUPPLEMENT_WARMING = True
    if need_warm:
        threading.Thread(target=_warm, name="lof-supplement", daemon=True).start()
    # TTL 内返回（可能为空：预热中或全部取数失败）
    return rows
