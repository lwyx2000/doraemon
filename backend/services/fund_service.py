"""Fund service — LOF/QDII/closed-end fund data with arbitrage analysis.

真实数据来源：AkShare WebAPI 的 fund_rank 加工接口（新浪/同花顺基金涨跌排行，
覆盖 ETF/LOF/封闭式基金的 代码/名称/最新价/涨跌幅/成交额）。取数失败时返回空列表，
不使用 mock 数据。

说明：iopv / 溢价率 / 折溢价分位 / 套利收益 需要基金净值(NAV)源，当前 akshare 通用接口
未直接提供，故置 0（表示“暂无该数据源”，而非虚构数值），由分析层据此标注。

ETF 增强指标（仅 doraemon 侧计算，无需上游改动）：
- 估值：宽基 ETF 按名称匹配跟踪指数 → 复用上游 index_valuation 的 PE/PE 百分位（1h 缓存）；
- K线指标：动量(近20日涨幅的组内百分位)/网格(60日高低点)/日波动率，来自上游 /api/quote/kline
  type=ETF；懒加载 + 后台线程预热 + 1h 进程内缓存，首次访问部分指标为空，随后自动补全。
"""

from __future__ import annotations

import json
import math
import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import requests

from core.config import AKSHARE_API_BASE, USE_MOCK_DATA
from services.meta_utils import gateway_no_data_meta, real_meta_base, mock_meta
from services.akshare_client import get_session
from services.cross_border_valuation import attach_estimated_valuations
from services.est_nav_history_service import attach_valuation_errors
from services.fund_premium_history_service import attach_premium_stats
from services.futures_basis_service import attach_basis_diagnostics
from utils.arbitrage import analyze_arbitrage
from utils.closed_fund import analyze_closed_fund
import mock_data


def _processed_data_request(category: str, params: dict | None = None, retries: int = 3) -> dict | list | None:
    """调用加工数据统一入口 (/api/processed_data)

    ⚠️ 网关多副本已知问题（2026-11-03 实测）：`subtype=all` 在**部分副本上返回 404**
    （22 字节错误体），命中率约 50%。共享 Session 的 keep-alive 一旦接到坏副本就会
    「稳定 404」——同一 URL 用 curl 或新建连接却能 200。所以这里 404 后必须强制换连接
    （Connection: close + 丢弃 Session），否则重试 3 次全打在同一台坏副本上白费。
    """
    url = f"{AKSHARE_API_BASE}/api/processed_data"
    request_params = {"category": category}
    if params:
        request_params.update(params)

    for attempt in range(retries):
        try:
            print(f"[Fund Service] 调用 {category} (尝试 {attempt + 1}/{retries})...")
            # 第 2 次起强制不复用连接，绕开可能已绑定的坏副本
            headers = {"Connection": "close"} if attempt else None
            response = get_session().get(url, params=request_params, timeout=30, headers=headers)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 200:
                print(f"[Fund Service] {category} 返回错误: {result.get('message')}")
                return None

            data = result.get("data")
            data_info = len(data) if isinstance(data, list) else '对象'
            print(f"[Fund Service] {category} 成功，返回 {data_info} 数据")
            return data

        except requests.exceptions.HTTPError as e:
            # 404/5xx 多半是命中缺路由的副本：把 Session 的连接池丢掉，下次重新握手
            status = getattr(e.response, "status_code", None)
            print(f"[Fund Service] {category} HTTP {status} (attempt {attempt + 1}/{retries})"
                  + ("，疑似命中网关缺路由副本，已丢弃连接" if status == 404 else ""))
            if status == 404:
                try:
                    get_session().close()
                except Exception:
                    pass
        except requests.exceptions.Timeout:
            print(f"[Fund Service] {category} 超时 (attempt {attempt + 1}/{retries})")
        except requests.exceptions.ConnectionError as e:
            print(f"[Fund Service] {category} 连接错误: {e} (attempt {attempt + 1}/{retries})")
        except Exception as e:
            print(f"[Fund Service] {category} 错误: {e} (attempt {attempt + 1}/{retries})")

        if attempt < retries - 1:
            time.sleep(1)

    print(f"[Fund Service] {category} 所有重试失败")
    return None


def _pick(row: dict, *keys: str, default=None):
    """按候选键名取值（兼容新浪/同花顺等不同列名）。"""
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return default


def _safe_float(value, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def _classify(name: str, code: str) -> tuple[str, str]:
    """基于名称/代码轻量分类（非虚构数据）。

    注意："香港" 必须与 "港股" 并列——161124「香港小盘」、501025「香港银行」等
    名字里只有"香港"，漏了会掉进 industry，连带 holding_days 按境内 T+1 算。

    供 ETF / LOF 共用（etf_service 亦复用）。
    """
    n = name
    if any(k in n for k in ("纳指", "纳斯达克", "标普", "道琼斯", "德国", "法国", "日经", "恒生", "港股", "香港", "美国", "海外", "中概", "原油", "黄金")):
        return "cross_border", "跨境"
    if any(k in n for k in ("沪深300", "中证500", "中证1000", "上证50", "创业板", "科创50", "科创", "中证A500", "深证", "上证")):
        return "broad", "宽基"
    return "industry", "行业"


# ============================================================
# ETF 增强指标：估值（宽基→指数PE百分位）+ K线（动量/网格/波动率）
# ============================================================

# 宽基 ETF 名称关键词 → 上游 index_valuation 的指数名（长关键词在前，避免"中证100"命中"中证1000"）
_ETF_INDEX_KEYWORDS: list[tuple[str, str]] = [
    ("中证1000", "中证1000"),
    ("沪深300", "沪深300"),
    ("中证500", "中证500"),
    ("上证50", "上证50"),
    ("上证380", "上证380"),
    ("上证180", "上证180"),
    ("中证800", "中证800"),
    ("中证100", "中证100"),
    ("深证红利", "深证红利"),
    ("深证100", "深证100"),
    ("创业板", "创业板50"),
]

# K线指标缓存: code -> (ts, metrics|None)；成功/失败均缓存 1h，避免重复请求
_ETF_KLINE_CACHE: dict[str, tuple[float, dict | None]] = {}
_ETF_KLINE_TTL = 3600
_ETF_KLINE_LOCK = threading.Lock()
_ETF_KLINE_WARMING = False
# 回看约 130 自然日 ≈ 60+ 交易日，覆盖 20 日动量 + 60 日网格区间
_ETF_KLINE_LOOKBACK_DAYS = 130

# 指数估值缓存: (ts, {index_name: {pe, pe_percentile}})
_INDEX_VAL_CACHE: dict[str, tuple[float, dict[str, dict]]] = {}
_INDEX_VAL_TTL = 3600
_INDEX_VAL_LOCK = threading.Lock()


# --- K线指标 ---

def _kline_request_quiet(code: str) -> list | None:
    """静默调用上游 /api/quote/kline (type=ETF, 前复权日线)，失败返回 None（不刷屏日志）。"""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=_ETF_KLINE_LOOKBACK_DAYS)).isoformat()
    try:
        resp = get_session().get(
            f"{AKSHARE_API_BASE}/api/quote/kline",
            params={"code": code, "type": "ETF", "start_date": start, "end_date": end},
            timeout=12,
        )
        result = resp.json()
        if result.get("code") == 200 and isinstance(result.get("data"), list):
            return result["data"]
    except Exception:
        pass
    return None


def _compute_kline_metrics(rows: list) -> dict | None:
    """从日 K 线计算 动量/网格/波动率 指标（启发式，非收益承诺）。

    - momentum_ret20: 近 20 交易日涨幅(%)，供组内百分位排成 momentum_score(0-100)
    - daily_volatility: 日收益率标准差(%)，同时改善套利 T+N 敞口估算
    - grid_low/high: 近 60 交易日最低/最高价（网格区间）
    - grid_step: ≈1.5×日波动率，钳制在 1%~5%
    - grid_yield_est: ≈60%×年化波动率，钳制 50% 以内（网格可捕捉的波动收益上限估计）
    """
    rows = [r for r in rows if r.get("close") is not None]
    rows.sort(key=lambda r: str(r.get("date", "")))
    closes = [float(r["close"]) for r in rows]
    if len(closes) < 20:
        return None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    daily_vol = statistics.pstdev(rets) * 100 if rets else 0.0
    ret20 = (closes[-1] / closes[-20] - 1) * 100
    recent = rows[-60:]
    try:
        grid_low = min(float(r.get("low") or r.get("close")) for r in recent)
        grid_high = max(float(r.get("high") or r.get("close")) for r in recent)
    except (TypeError, ValueError):
        grid_low = grid_high = closes[-1]
    step = round(min(5.0, max(1.0, daily_vol * 1.5)), 1)
    annual_vol = daily_vol * math.sqrt(250)
    yield_est = round(min(50.0, annual_vol * 0.6), 1)
    return {
        "momentum_ret20": round(ret20, 2),
        "daily_volatility": round(daily_vol, 2),
        "grid_low": round(grid_low, 3),
        "grid_high": round(grid_high, 3),
        "grid_step": step,
        "grid_yield_est": yield_est,
    }


def _fetch_kline_metrics(code: str) -> dict | None:
    """取单只 ETF 的 K 线指标（带 1h 缓存，会发网络请求）。仅供后台预热线程调用。"""
    now = time.time()
    with _ETF_KLINE_LOCK:
        cached = _ETF_KLINE_CACHE.get(code)
        if cached and now - cached[0] < _ETF_KLINE_TTL:
            return cached[1]
    rows = _kline_request_quiet(code)
    metrics = _compute_kline_metrics(rows) if rows else None
    with _ETF_KLINE_LOCK:
        _ETF_KLINE_CACHE[code] = (now, metrics)
    return metrics


def _kline_metrics_cached(code: str) -> dict | None:
    """只读缓存取 K 线指标（不发网络请求），请求路径专用。"""
    now = time.time()
    with _ETF_KLINE_LOCK:
        cached = _ETF_KLINE_CACHE.get(code)
        if cached and now - cached[0] < _ETF_KLINE_TTL:
            return cached[1]
    return None


def _warm_etf_kline(codes: list[str]) -> None:
    """后台线程预热缺失的 ETF K 线指标（幂等，已在跑则忽略）。"""
    global _ETF_KLINE_WARMING
    if not codes:
        return
    with _ETF_KLINE_LOCK:
        if _ETF_KLINE_WARMING:
            return
        _ETF_KLINE_WARMING = True

    def _worker() -> None:
        global _ETF_KLINE_WARMING
        try:
            with ThreadPoolExecutor(max_workers=8) as ex:
                list(ex.map(_fetch_kline_metrics, codes))
            print(f"[ETF K线] 指标预热完成：{len(codes)} 只")
        except Exception as e:
            print(f"[ETF K线] 预热异常: {type(e).__name__}: {e}")
        finally:
            with _ETF_KLINE_LOCK:
                _ETF_KLINE_WARMING = False

    threading.Thread(target=_worker, name="etf-kline-warm", daemon=True).start()


def _attach_kline_metrics(funds: list[dict]) -> None:
    """K 线指标挂载：仅读缓存（不发网络请求，保证请求路径低延迟）；

    缺失码由后台线程预热，首次访问网格/轮动/波动率为空（前端显示 -），
    预热完成后（约 1-2 分钟）自动补全，后续 1h 内命中缓存。
    """
    etfs = [f for f in funds if f.get("type") == "etf"]
    if not etfs:
        return
    missing: list[str] = []
    for f in etfs:
        m = _kline_metrics_cached(f["code"])
        if not m:
            missing.append(f["code"])
            continue
        f["momentum_ret20"] = m["momentum_ret20"]
        f["daily_volatility"] = m["daily_volatility"]
        f["grid_low"] = m["grid_low"]
        f["grid_high"] = m["grid_high"]
        f["grid_step"] = m["grid_step"]
        f["grid_yield_est"] = m["grid_yield_est"]
    # 动量得分：近 20 日涨幅在本次全量 ETF 中的百分位 0-100
    with_ret = [f for f in etfs if "momentum_ret20" in f]
    if with_ret:
        sorted_rets = sorted(f["momentum_ret20"] for f in with_ret)
        n = len(sorted_rets)
        for f in with_ret:
            rank = sum(1 for s in sorted_rets if s <= f["momentum_ret20"])
            f["momentum_score"] = round(rank / n * 100)
            f.pop("momentum_ret20", None)  # 中间量不返回
    if missing:
        _warm_etf_kline(missing)


# --- 估值（宽基 ETF → 指数 PE 百分位）---

def _get_index_valuation_map() -> dict[str, dict]:
    """宽基指数 PE/PE百分位 map（复用 market_service.get_realtime_indices，1h 缓存）。"""
    now = time.time()
    with _INDEX_VAL_LOCK:
        cached = _INDEX_VAL_CACHE.get("all")
        if cached and now - cached[0] < _INDEX_VAL_TTL:
            return cached[1]
    val_map: dict[str, dict] = {}
    try:
        from services.market_service import get_realtime_indices

        for idx in get_realtime_indices():
            name = idx.get("name", "")
            pe = idx.get("pe")
            pct = idx.get("pePercentile")
            if name and pe and pct:
                val_map[name] = {"pe": pe, "pe_percentile": pct}
    except Exception as e:
        print(f"[ETF 估值] 指数估值获取失败: {e}")
    with _INDEX_VAL_LOCK:
        _INDEX_VAL_CACHE["all"] = (now, val_map)
    return val_map


def _attach_index_valuation(funds: list[dict]) -> None:
    """宽基 ETF → 跟踪指数 PE/PE百分位 → val_category（<30 低估 / >70 高估）。"""
    val_map = _get_index_valuation_map()
    if not val_map:
        return
    for f in funds:
        name = str(f.get("name", ""))
        for kw, idx in _ETF_INDEX_KEYWORDS:
            if kw in name:
                iv = val_map.get(idx)
                if iv:
                    f["pe"] = iv["pe"]
                    f["pe_percentile"] = iv["pe_percentile"]
                    pct = iv["pe_percentile"]
                    f["val_category"] = "undervalued" if pct < 30 else ("overvalued" if pct > 70 else "normal")
                break


# ==================== 溢价双口径诊断 + 净值陈旧度（2026-11-03） ====================
#
# 这两项都源自《无敌哥估值说明文档》的实测结论，不上新数据源，纯本地计算。

#: 净值日落后多少个交易日算「滞后」/「失效」。
#: 跨境 QDII 的官方净值本来就 T-1~T-2 公布，0~2 是常态，不该报警；从 T+3 起，
#: 锚定净值已经在用「几天前的仓位」外推，position 误差累积开始盖过溢价本身
#: （本项目实测 position 残差 0.3%/日量级）；T+5 起折溢价读数基本不可用于下单。
#: 对应文档 5.4「下单前三道检查」第①条：EST 日期不是最近交易日就作废 ——
#: 513800 挂着 2025-09-29 的 EST 还在显示 14.67% 溢价，就是这个坑的教科书样本。
_NAV_LAG_LEVELS: tuple[tuple[int, str], ...] = ((2, "fresh"), (4, "lag"))


def _nav_lag_level(lag: int) -> str:
    for limit, name in _NAV_LAG_LEVELS:
        if lag <= limit:
            return name
    return "stale"


def _attach_premium_diagnostics(funds: list[dict]) -> None:
    """挂 ``premium_gap``（口径差）与 ``nav_lag_days`` / ``nav_stale_level``（陈旧度）。

    ``premium_gap = 官方口径溢价 − 自算口径溢价``：官方口径的分母是基金公司公布的
    净值（跨境品种常是 T-1 的，ETF 的盘中参考净值还含汇率口径差异），自算口径的
    分母是 ``est_nav``。文档 5.2 实测：同一标的的 **ETF 类「官方 EST」系统性高于
    「参考 EST」约 0.7~0.8%**（513100：官方 1.984 vs 参考 1.969），换算成溢价反而
    低 0.7~0.9 个点（16.70% vs 17.58%）；LOF 类两者只差 0.02%。

    也就是说：同一张表里 **ETF 的 ``premium_pct`` 天然比 LOF 偏低近 1 个点**，
    按它横向排序会系统性高估 LOF、低估 ETF。把差值显式列出来，比在每个页面
    写一段免责声明有用 —— 用户看到的不是「我们口径可能不同」而是具体差了多少。

    陈旧度则回答文档 5.4 的第①道检查：净值锚是不是当天的。

    ⚠️ 日历未预热时**跳过陈旧度**（只算口径差）：``latest_trading_day()`` 首次调用会
    去网关拉全量交易日历，实测 30s 级。``/funds`` 是全站高频接口，不能为了一次
    请求陪它等 30s；预热由 ``est_nav_snapshot_job`` 启动时的异步线程负责，
    通常几十秒内就位，之后的请求自动带上陈旧度。
    """
    try:
        from services import trading_calendar as tc

        if not tc.is_loaded():
            print("[Fund Service] 交易日历未预热，本次跳过净值陈旧度（仅算口径差）")
            _attach_premium_gap_only(funds)
            return
        ref = tc.latest_trading_day()
        trading_days_between = tc.trading_days_between
    except Exception as e:
        print(f"[Fund Service] 陈旧度计算跳过（交易日历不可用）: {type(e).__name__}: {e}")
        return

    hit_gap = _attach_premium_gap_only(funds)
    hit_lag = 0
    for f in funds:
        nd = str(f.get("nav_date") or "")[:10]
        if not nd:
            continue
        try:
            d = datetime.strptime(nd, "%Y-%m-%d").date()
        except ValueError:
            continue
        # 统计 nav_date **之后**的交易日数：昨天 → 1（常态），今天 → 0（已出）
        lag = trading_days_between(d + timedelta(days=1), ref)
        f["nav_lag_days"] = lag
        f["nav_stale_level"] = _nav_lag_level(lag)
        hit_lag += 1

    if hit_gap or hit_lag:
        print(f"[Fund Service] 溢价诊断：口径差 {hit_gap} 只 / 陈旧度 {hit_lag} 只")


def _attach_premium_gap_only(funds: list[dict]) -> int:
    """只算口径差（不依赖交易日历，永不阻塞）。返回命中只数。"""
    hit = 0
    for f in funds:
        prem = f.get("premium_pct")
        est = f.get("est_premium_pct")
        # premium_pct==0 是部分源缺失时的占位值，不是真的平价，别拿它做差
        if prem is not None and est is not None and float(prem) != 0.0:
            f["premium_gap"] = round(float(prem) - float(est), 2)
            hit += 1
    return hit


def _merge_supplement_funds(funds: list[dict], fund_subtype: str) -> None:
    """并入补充池（麦蕊 fund_rank 口径外的、仍在正常交易的场内基金）。

    为什么需要：subtype=lof 只有 308 只，缺 164705/161831/160717 等；换 subtype=all
    也不是超集（与 lof 交集仅 207 只）。跨境 ETF 同理：subtype=etf 有 3724 只、
    all 有 5088 只，却都不含日经 3 只（实测 2026-10-30）。网关层面补不齐，只能
    本地白名单 + 自取行情。

    按条目自带 type 分流：subtype=lof 只并 lof 条目、=etf 只并 etf 条目、=all 全并。
    不这么做的话，513000 这类 ETF 会错落到 LOF tab（tab 筛选失真）。

    为什么放在请求路径外：ETF 条目一次批量走网关（2.4s），LOF 条目净值需逐只打
    网关（0.8~1.6s/只），放请求里会拖慢 /funds。故只读缓存，缺失由后台线程预热，
    首次访问这些行不出现，预热后自动补齐。
    """
    try:
        from services.lof_supplement import get_supplement_funds
    except Exception as e:
        print(f"[Fund Service] 补充池导入失败: {type(e).__name__}: {e}")
        return
    rows = get_supplement_funds()
    if not rows:
        return
    have = {f.get("code") for f in funds}
    added = 0
    for row in rows:
        code = row.get("code")
        if not code or code in have:
            continue
        row_type = str(row.get("type") or "lof")
        if fund_subtype in ("lof", "etf") and row_type != fund_subtype:
            continue
        # 与主链路同口径的分类/持有天数，避免 tab 筛选与 T+N 计算失真
        category, sub_category = _classify(row.get("name", ""), code)
        row["category"] = category
        row["sub_category"] = sub_category
        row["holding_days"] = 2 if category == "cross_border" else 1
        funds.append(row)
        have.add(code)
        added += 1
    if added:
        print(f"[Fund Service] 补充池并入 {added} 只（subtype={fund_subtype}）")


def get_funds_from_api(fund_subtype: str = "etf") -> list[dict]:
    """从真实 API 获取基金排行数据。

    Args:
        fund_subtype: etf / lof / closed / all
    """
    data = _processed_data_request("fund_rank", {"subtype": fund_subtype})

    if not data or not isinstance(data, list):
        print(f"[Fund Service] 获取 {fund_subtype} 失败，返回空列表")
        return []

    funds = []
    for item in data:
        subtype_map = {
            "etf": "etf",
            "lof": "lof",
            "closed": "closed",
        }
        fund_type = subtype_map.get(fund_subtype, "etf")

        name = str(_pick(item, "名称", "基金名称", default=""))
        code = str(_pick(item, "代码", "基金代码", default=""))
        if not code:
            continue

        # 53 fund_rank 已直接提供 净值 / 溢价率 / 净值日期（实测为真实值），
        # 无需自算。此前因硬编码 0 导致 ETF/LOF 套利页整表 No Data（A 类根因）。
        nav = _safe_float(_pick(item, "净值"))
        premium_pct = _safe_float(_pick(item, "溢价率"))
        # IOPV 对 ETF≈NAV；LOF 无 IOPV 概念，统一以 NAV 近似供前端展示。
        iopv = nav if nav else 0.0

        # 名称 → 轻量分类（宽基/行业/跨境），替代此前硬编码 industry（导致网格/轮动/估值 tab 筛选全部失真）
        category, sub_category = _classify(name, code)
        # 麦蕊 申购状态(sgzt) → subscribe_limit："暂停申购"→资金容量 C 级(不可行)，"开放申购"→无限制
        subscribe_limit = _pick(item, "申购状态", "sgzt")
        is_suspended = bool(subscribe_limit) and any(k in str(subscribe_limit) for k in ("暂停", "停止"))
        # 成交额(元)/成交量(手)：新浪兜底源提供真实值；麦蕊源无此列 → None（前端显示 -，不虚构 0）
        vol_raw = _pick(item, "成交额", "成交量")
        volume = _safe_int(vol_raw) if vol_raw is not None else None
        # 跨境 ETF/LOF 份额 T+2 到账，境内 T+1
        holding_days = 2 if category == "cross_border" else 1

        funds.append({
            "name": name,
            "code": code,
            "type": fund_type,
            "category": category,
            "sub_category": sub_category,
            "price": _safe_float(_pick(item, "最新价", "实时价", "当前单位净值")),
            "iopv": iopv,
            "premium_pct": premium_pct,
            # 溢价分位是「自己攒的历史」算出来的（fund_premium_history_service 每日落库），
            # 这里先占位 None，由返回前的 attach_premium_stats 统一覆盖；样本<15 交易日时保持 None
            "premium_percentile": None,
            # 折溢价套利毛收益 = 溢价率（折价为负即反向套利空间），供 analyze_arbitrage 判定可行性。
            "net_arbitrage_yield": premium_pct,
            "nav": nav,
            "nav_date": _pick(item, "净值日期"),
            "volume": volume,
            "subscribe_limit": subscribe_limit,
            "is_suspended": is_suspended,
            "holding_days": holding_days,
            # 估值需 ETF 级 PE 历史（index_valuation 仅覆盖 8 个宽基指数），无源 → None
            "val_category": None,
            "change_pct": _safe_float(_pick(item, "涨跌幅", "增长率")),
            # 净值日期：跨境篮子自算估值的基准日（53 fund_rank 提供）
            "nav_date": _pick(item, "净值日期"),
        })

    # 补充池：网关麦蕊口径漏掉的仍在交易的场内基金 —— LOF（164705/161831/160717 等）
    # 与跨境 ETF（日经 3 只）。只读缓存不阻塞；必须在 attach_estimated_valuations
    # 之前并入，否则这几只算不出 est_nav（它们原本连行都不在列表里）。
    if fund_subtype in ("lof", "etf", "all"):
        _merge_supplement_funds(funds, fund_subtype)
    # ETF 增强指标：估值（宽基→指数PE百分位，etf/lof/all 均适用）+ K线（动量/网格/波动率，仅 etf）
    if fund_subtype in ("etf", "lof", "all"):
        _attach_index_valuation(funds)
    if fund_subtype == "etf":
        _attach_kline_metrics(funds)
    # 跨境 LOF/QDII 篮子自算估值（est_nav/est_premium_pct，参考 lofarb；缺数据不写）
    if fund_subtype in ("etf", "lof", "all"):
        attach_estimated_valuations(funds)
        # 估值误差自检（T3）：挂最近一次 est_nav 与真实净值的偏差 + 近 20 日 mae/max。
        # 只读 DuckDB 汇总缓存（TTL 120s），不发网络请求，放在返回前最后一步。
        attach_valuation_errors(funds)

    # 商品期货期现基差（仅 est_method=futures 的 161226/159985；诊断用，**不进 est_nav**）。
    # 挂在这里而不是 _estimate_by_futures 里，是因为它的数据源独立（网关 futures_spot_price_daily）
    # 且按天缓存——不该让估值快照去等一个每日只变一次的接口。
    attach_basis_diagnostics(funds)

    # 溢价双口径诊断 + 净值陈旧度（纯本地计算；对 closed 也适用，故放在 subtype 分支外）
    _attach_premium_diagnostics(funds)
    # 溢价率历史分位（读 DuckDB 汇总缓存 TTL 300s；样本不足时不写字段，前端显示 '-'）
    attach_premium_stats(funds)

    print(f"[Fund Service] 成功获取 {len(funds)} 个 {fund_subtype}")
    return funds


# 列表级 TTL 缓存（2026-10-16）：/funds 是全市场扫描型接口（LOF/ETF/封基
# 逐个上游取数再算套利），AlertCenter 一页加载就会打它。30s TTL +
# force 穿透（前端「刷新」显式传 force=1）。仅成功结果入缓存；
# 网关无数据（gatewayEmpty）不写，故障恢复无延迟。
_FUNDS_LIST_TTL = 30
_FUNDS_LIST_MAX_KEYS = 64
_FUNDS_LIST_CACHE: dict[tuple, tuple[float, tuple[list[dict], dict]]] = {}
_FUNDS_LIST_LOCK = threading.Lock()


def get_funds(
    fund_type: str | None = None,
    min_premium: float | None = None,
    feasibility: str | None = None,
    date: str | None = None,
    use_api: bool = True,
    force: bool = False,
) -> tuple[list[dict], dict]:
    """Return (funds, meta) with attached arbitrage analysis (真实数据优先).

    Filters:
        fund_type:   match ``fund["type"]`` (etf/lof/qdii/closed).
        min_premium: include only funds with ``premium_pct >= min_premium``.
        feasibility: match ``arbitrage_analysis["feasibility"]``.
        date:        accepted for API compatibility (no-op).
        use_api:     保留参数以兼容旧调用；始终尝试真实取数。
        force:       True 穿透 30s 列表缓存，强制重扫上游（前端刷新用）。

    meta.gatewayEmpty=True 当且仅当上游数据源本身未返回任何数据（区别于过滤后为空）。
    """
    if USE_MOCK_DATA:
        funds_data = mock_data.MOCK_FUNDS
        result: list[dict] = []
        for fund in funds_data:
            if fund_type and fund.get("type") != fund_type:
                continue
            if min_premium is not None and fund.get("premium_pct", 0) < min_premium:
                continue
            analysis = analyze_arbitrage(fund)
            if feasibility and analysis["feasibility"] != feasibility:
                continue
            result.append({**fund, "arbitrage_analysis": analysis})
        return result, mock_meta()

    cache_key = (fund_type, min_premium, feasibility)
    if not force:
        with _FUNDS_LIST_LOCK:
            hit = _FUNDS_LIST_CACHE.get(cache_key)
            if hit and (time.time() - hit[0]) < _FUNDS_LIST_TTL:
                return hit[1]

    subtype_map = {
        "etf": "etf",
        "lof": "lof",
        "qdii": "etf",
        "closed": "closed",
    }
    if fund_type == "closed":
        # 封基走专用富集路径（腾讯补全场内价/成交额 + 折价率计算），
        # 避免列表页 premium_pct/volume 恒为 0（A 类根因）。
        funds_data = get_closed_funds_real() if use_api else []
    else:
        subtype = subtype_map.get(fund_type, "all")
        funds_data = get_funds_from_api(subtype) if use_api else []

    # 上游数据源本身无数据 → 网关无数据；有数据但过滤后为空 → 正常空（gatewayEmpty=False）
    gateway_empty = len(funds_data) == 0

    # 应用过滤和分析
    result: list[dict] = []
    for fund in funds_data:
        if min_premium is not None and fund.get("premium_pct", 0) < min_premium:
            continue

        analysis = analyze_arbitrage(fund)
        if feasibility and analysis["feasibility"] != feasibility:
            continue

        item = {**fund, "arbitrage_analysis": analysis}
        result.append(item)

    if gateway_empty:
        return result, gateway_no_data_meta()
    out = (result, real_meta_base(AKSHARE_API_BASE))
    with _FUNDS_LIST_LOCK:
        _FUNDS_LIST_CACHE[cache_key] = (time.time(), out)
        if len(_FUNDS_LIST_CACHE) > _FUNDS_LIST_MAX_KEYS:
            oldest = sorted(_FUNDS_LIST_CACHE, key=lambda k: _FUNDS_LIST_CACHE[k][0])
            for k in oldest[: len(_FUNDS_LIST_CACHE) - _FUNDS_LIST_MAX_KEYS]:
                _FUNDS_LIST_CACHE.pop(k, None)
    return out


def _get_closed_quotes_tencent(codes: list[str]) -> dict[str, dict]:
    """通过腾讯 qt.gtimg.cn 获取封闭基金场内实时行情（现价/涨跌幅/成交额）。

    53 的 fund_rank(closed) 仅给净值与收益率，无场内交易价；东方财富的
    fund_closed_end_em 在 53 上被掐，故用腾讯源降级。深交所代码前缀 sz、
    上交所前缀 sh。返回 {6位代码: {price, change_pct, volume(元)}}。
    """
    if not codes:
        return {}
    # 腾讯代码前缀：上交所 50/51 开头用 sh，其余 sz
    tencent_codes = [
        ("sh" if c.startswith(("50", "51")) else "sz") + c for c in codes
    ]
    result: dict[str, dict] = {}
    for i in range(0, len(tencent_codes), 8):
        batch = tencent_codes[i:i + 8]
        try:
            resp = get_session().get(
                "https://qt.gtimg.cn/q=" + ",".join(batch),
                timeout=10,
            )
            text = resp.content.decode("gbk", "ignore")
        except Exception as e:
            print(f"[Closed Fund] 腾讯行情请求失败: {e}")
            continue
        for m in re.finditer(r'v_(\w+)="([^"]*)"', text):
            body = m.group(2)
            if not body or "none_match" in body:
                continue
            f = body.split("~")
            if len(f) < 36:
                continue
            code6 = f[2]
            price = _safe_float(f[3])
            if price <= 0:
                continue
            change_pct = _safe_float(f[32])
            # f[35] 形如 "成交额(万元)/成交量(手)/..."，封闭基金专用格式
            amount_part = f[35].split("/")[0] if len(f) > 35 and f[35] else ""
            amount_wan = _safe_float(amount_part)  # 万元
            result[code6] = {
                "price": price,
                "change_pct": change_pct,
                "volume": int(amount_wan * 10000),  # 折算为元
            }
    print(f"[Closed Fund] 腾讯行情命中 {len(result)}/{len(codes)} 只")
    return result


# 天天基金净值缓存（净值日频，缓存 1 小时足够）
_NAV_CACHE: dict[str, tuple[float, str, float]] = {}  # code -> (nav, nav_date, expire_ts)
_NAV_TTL = 3600


def get_fund_nav_eastmoney(code: str) -> dict | None:
    """天天基金净值源 (fund.eastmoney.com pingzhongdata)。

    53 的 fund_rank(closed) 仅部分基金给净值，且东方财富基金净值接口
    (fund_open_fund_info_em 等) 在 53 上被掐。天天基金 CDN 对本机直连可用，
    返回 Data_netWorthTrend（含最新单位净值与日期）。缓存避免重复请求。
    """
    now = time.time()
    cached = _NAV_CACHE.get(code)
    if cached and cached[2] > now:
        return {"nav": cached[0], "nav_date": cached[1]}
    try:
        resp = get_session().get(
            f"https://fund.eastmoney.com/pingzhongdata/{code}.js",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://fundf10.eastmoney.com/",
            },
            timeout=12,
        )
        m = re.search(r"var Data_netWorthTrend\s*=\s*(\[.*?\]);", resp.text, re.S)
        if not m:
            return None
        arr = json.loads(m.group(1))
        if not arr:
            return None
        last = arr[-1]
        nav = _safe_float(last.get("y"))
        if not nav:
            return None
        ts = last.get("x", 0) / 1000
        nav_date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        _NAV_CACHE[code] = (nav, nav_date, now + _NAV_TTL)
        return {"nav": nav, "nav_date": nav_date}
    except Exception as e:
        print(f"[Closed Fund] 天天基金净值获取失败 {code}: {e}")
        return None


def _norm_code(code: str) -> str:
    """归一化基金代码为末 6 位数字，便于跨源匹配（集思录/53/腾讯可能带交易所前缀）"""
    digits = re.sub(r"\D", "", str(code))
    return digits[-6:] if len(digits) >= 6 else digits


def _fetch_jisilu_closed_nav() -> dict:
    """集思录封闭基金净值/折价率映射（归一化 code -> record）。

    作为更高优先级净值源补充；需 53 部署 akshareWebApi 的 jisilu 路由并配置 cookie（静态或动态）。
    任意失败（未部署/无 cookie/超时/网络异常）一律返回空 dict，不动现有 53+天天基金+硬编码兜底。
    """
    try:
        raw = _processed_data_request("jisilu", {"subtype": "closed_fund"}, retries=1)
        if not raw or not isinstance(raw, list):
            return {}
        # 打印一次列名，方便 53 实测校准中英文键名映射
        if raw:
            print(f"[Closed Fund] 集思录封闭基金列名样本: {list(raw[0].keys())}")
        mapping = {}
        for it in raw:
            code = _norm_code(_pick(it, "fund_id", "代码", "基金代码", default=""))
            if code:
                mapping[code] = it
        if mapping:
            print(f"[Closed Fund] 集思录封闭基金 {len(mapping)} 只已加载为净值补充源")
        return mapping
    except Exception as exc:
        print(f"[Closed Fund] 集思录净值源获取失败，回退现有源: {exc}")
        return {}


def _build_closed_funds_from_jisilu() -> list[dict]:
    """集思录封基列表（53 jisilu/closed_fund 路由 → /data/cf/cf_list + bond_list）。

    直接给出 现价/净值/折价率(discount_rt)/剩余年限(left_year)/年化折价率/
    到期日(maturity_dt)，#2 字段齐全。游客态约 20 只；53 配 jisilu cookie 返回全量。
    失败或空时返回 []，由调用方回退 53+腾讯路径。
    """
    try:
        raw = _processed_data_request("jisilu", {"subtype": "closed_fund"}, retries=1)
    except Exception as exc:
        print(f"[Closed Fund] 集思录封基列表获取异常: {exc}")
        return []
    if not raw or not isinstance(raw, list) or not raw:
        return []

    funds: list[dict] = []
    for rec in raw:
        code = str(_norm_code(_pick(rec, "fund_id", "代码", "基金代码", default="")))
        if not code:
            continue
        nav = _safe_float(_pick(rec, "fund_nav", "net_value", "净值", "单位净值"))
        price = _safe_float(_pick(rec, "price", "现价"))
        # 集思录 discount_rt 为正=折价；本项目 premium_pct 负=折价 → 取负。
        # 部分封基(临近到期/定开) discount_rt 为 "-"：回退按 (价-净值)/净值 计算。
        disc = _safe_float(_pick(rec, "discount_rt", "折价率", "折价"))
        if disc:
            premium = round(-disc, 2)
        elif nav and price:
            premium = round((price - nav) / nav * 100, 2)
        else:
            premium = 0.0
        left_year = _safe_float(_pick(rec, "left_year", "剩余年限", "剩余期限"))
        annualized = _safe_float(_pick(rec, "annualized", "annualize_dscnt_rt", "年化", "年化折价率"))
        end_date = _pick(rec, "end_date", "maturity_dt", "到期日", "到期时间")
        change = _safe_float(_pick(rec, "increase_rt", "涨跌幅"))
        vol = _safe_float(_pick(rec, "volume", "成交额"))
        # 集思录 volume 单位为万元 → 折算为元（与腾讯源口径一致）
        volume = int(vol * 10000) if vol else 0
        funds.append({
            "name": str(_pick(rec, "fund_nm", "名称", "基金名称", default="")),
            "code": code,
            "type": "closed",
            "price": price or 0,
            "iopv": 0,
            "premium_pct": premium,
            "premium_percentile": None,
            "net_arbitrage_yield": premium,
            "volume": volume,
            # 剩余年限统一为 parse_remaining_days 可解析的 "X Years" 字符串
            "remaining_term": f"{left_year} Years" if left_year else None,
            "annualized": annualized or None,
            "est_ytm": None,
            "maturity": end_date or None,
            "nav": nav,
            "nav_date": _pick(rec, "nav_dt", "nav_date", "净值日期"),
            "credit_rating": _pick(rec, "rate", "评级", "信用评级") or None,
            "underlying_type": None,
            "is_lof_convertible": None,
            "change_pct": change,
        })
    return funds


def _build_closed_funds_from_rank() -> list[dict]:
    """回退路径：53 fund_rank(closed) 给列表与净值，腾讯补全场内行情。

    53 的 closed 列表仅含净值/收益率（无场内价、无成交额、无剩余期限/到期日）。
    - 场内价/成交额/涨跌幅：腾讯 qt.gtimg.cn 降级
    - 折价率：有净值时按 (场内价-净值)/净值 计算，否则为 0（诚实置 0 非虚构）
    - remaining_term/maturity/credit_rating/underlying_type/is_lof_convertible：
      53 现有源不提供，置 None（前端容错显示空）
    """
    raw = _processed_data_request("fund_rank", {"subtype": "closed"})
    if not raw or not isinstance(raw, list):
        print("[Closed Fund] fund_rank(closed) 取数失败，返回空列表")
        return []

    # 集思录封闭基金净值源（更高优先级净值/折价率/剩余年限等，失败静默回退现有源）
    jsl_nav_map = _fetch_jisilu_closed_nav()

    funds: list[dict] = []
    jsl_premium_by_code: dict[str, float] = {}  # 集思录折价率(已转成本项目符号：负=折价)
    for item in raw:
        code = str(_pick(item, "代码", "基金代码", default=""))
        if not code:
            continue
        nav = _safe_float(_pick(item, "净值"), None)  # mairui 净值，可能为空
        nav_date = None
        # 53 未给净值时，用天天基金净值源降级补全
        if not nav:
            nav_info = get_fund_nav_eastmoney(code)
            if nav_info:
                nav = nav_info["nav"]
                nav_date = nav_info["nav_date"]
        # 集思录净值优先覆盖（最高优先级净值源）。LOF 端点仅提供 fund_nav(净值)/nav_dt(净值日期)/
        # discount_rt(折价率)；剩余年限/年化回报/到期日/评级等字段 LOF 不提供，保持 None 由现有源/前端容错。
        jsl = jsl_nav_map.get(_norm_code(code))
        jsl_nav = _safe_float(_pick(jsl, "fund_nav", "nav", "净值", "单位净值")) if jsl else None
        if jsl_nav:
            nav = jsl_nav
            jsl_nav_dt = _pick(jsl, "nav_dt", "nav_date", "净值日期") if jsl else None
            if jsl_nav_dt:
                nav_date = jsl_nav_dt
        # 集思录字段提取：剩余年限/年化/到期日/评级/折价率。
        # 路由可用时填充，否则保持 None（由前端容错显示空，不虚构）。
        # 集思录 discount_rt 为正=折价，与本项目 premium_pct(负=折价) 符号相反，故取负。
        jsl_discount = _safe_float(_pick(jsl, "discount_rt", "折价率", "折价")) if jsl else None
        jsl_left_year = _safe_float(_pick(jsl, "left_year", "剩余年限", "剩余期限")) if jsl else None
        jsl_annualized = _safe_float(_pick(jsl, "annualized", "年化", "年化收益")) if jsl else None
        jsl_end_date = _pick(jsl, "end_date", "到期日", "到期时间") if jsl else None
        jsl_rate = _pick(jsl, "rate", "评级", "信用评级") if jsl else None
        if jsl_discount:
            jsl_premium_by_code[code] = round(-jsl_discount, 2)
        # 剩余年限统一为 parse_remaining_days 可解析的 "X Years" 字符串
        remaining_term = f"{jsl_left_year} Years" if jsl_left_year else None
        funds.append({
            "name": str(_pick(item, "名称", "基金名称", default="")),
            "code": code,
            "type": "closed",
            "price": _safe_float(_pick(item, "最新价")) or 0,
            "iopv": 0,
            "premium_pct": 0,
            "premium_percentile": None,
            "net_arbitrage_yield": 0,
            "volume": 0,
            "remaining_term": remaining_term,
            "annualized": jsl_annualized or None,
            "est_ytm": None,
            "maturity": jsl_end_date,
            "nav": nav,
            "nav_date": nav_date,
            "credit_rating": jsl_rate,
            "underlying_type": None,
            "is_lof_convertible": None,
            "change_pct": _safe_float(_pick(item, "涨跌幅", "增长率")),
        })

    # 腾讯补全场内价 + 成交额 + 涨跌幅，并据净值算折价率
    quotes = _get_closed_quotes_tencent([f["code"] for f in funds])
    result: list[dict] = []
    for f in funds:
        q = quotes.get(f["code"])
        # 仅保留有真实场内交易的基金（腾讯未命中的多为场外 C 类，非场内封基）
        if not q or q["price"] <= 0:
            continue
        f["price"] = q["price"]
        f["volume"] = q["volume"]
        f["change_pct"] = q["change_pct"]
        jp = jsl_premium_by_code.get(f["code"])
        if jp is not None:
            # 集思录权威折价率优先
            f["premium_pct"] = jp
        elif f["nav"]:
            f["premium_pct"] = round((f["price"] - f["nav"]) / f["nav"] * 100, 2)
        result.append(f)

    print(f"[Closed Fund] 真实数据 {len(result)} 只（含腾讯行情补全，已过滤无场内交易品种）")
    return result


def get_closed_funds_real() -> list[dict]:
    """封闭基金真实数据。

    优先用集思录封基列表（53 jisilu/closed_fund 路由 → /data/cf/cf_list + bond_list）：
    直接给出 现价/净值/折价率/剩余年限/年化折价率/到期日，#2 字段齐全。
    游客态返回约 20 只；53 配 jisilu cookie 后返回全量（覆盖更多封基）。
    当集思录不可用（路由 500/空）时，回退 53 fund_rank(closed) + 腾讯行情补全。
    """
    jsl_funds = _build_closed_funds_from_jisilu()
    if jsl_funds:
        print(f"[Closed Fund] 集思录封基 {len(jsl_funds)} 只（#2 字段齐全）")
        return jsl_funds
    print("[Closed Fund] 集思录不可用，回退 53 fund_rank(closed) + 腾讯行情")
    return _build_closed_funds_from_rank()


def get_closed_fund_analysis(use_api: bool = True) -> tuple[list[dict], dict]:
    """Return (closed-end fund analysis, meta), sorted by score descending (真实数据优先)."""
    if USE_MOCK_DATA:
        funds_data = [f for f in mock_data.MOCK_FUNDS if f.get("type") == "closed"]
        result: list[dict] = []
        for fund in funds_data:
            result.append(analyze_closed_fund(fund))
        result.sort(key=lambda x: x.get("score", 0), reverse=True)
        return result, mock_meta()
    funds_data = get_closed_funds_real() if use_api else []
    gateway_empty = len(funds_data) == 0

    result: list[dict] = []
    for fund in funds_data:
        analysis = analyze_closed_fund(fund)
        result.append(analysis)

    result.sort(key=lambda x: x.get("score", 0), reverse=True)
    if gateway_empty:
        return result, gateway_no_data_meta()
    return result, real_meta_base(AKSHARE_API_BASE)
