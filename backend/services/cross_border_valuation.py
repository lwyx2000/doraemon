"""跨境 LOF/QDII 篮子自算估值服务（参考 lofarb arbcore 自算估值移植）。

核心公式（lofarb unified_valuation.basket_valuation 的矩阵形态，doraemon 无
Woody hedge 数据，魔法公式即其单组件特例，直接走矩阵公式）：

    est_nav = nav * (1 + position/100 * (Σ w_i * (P_i_now/P_i_base) * (fx_now/fx_base) - 1))

- nav / nav_date：53 网关 fund_rank 提供的真实净值与净值日期；
- P_i_base：净值日期对应的底层市场收盘价。美股 T 日收盘在北京时间 T+1 凌晨落地，
  QDII 净值日（中国交易日）T 反映的是 T-1 美股收盘 → us 篮子基准日 = nav_date - 1；
  A股/港股/境内期货的净值与行情同日 → 基准日 = nav_date；
- P_i_now：优先实时报价（新浪 gb_/腾讯/期货 hf_），非交易时段退回最新日K收盘；
- fx：篮子货币兑 CNY 变化（新浪 fx_susdcny/fx_shkdcny/fx_sjpycny，
  base=昨收=now-涨跌额，now=现价）。

第二种方法：指数跟踪法（method="index"，移植 lofarb step11_simple_static_valuation）。
用于「有 position 但篮子为空」的港股恒生系 LOF：

    est_nav = nav * (1 + position/100 * (idx_now/idx_base * fx_now/fx_base - 1))

- idx_now：新浪港股指数实时（hkHSI 字段布局与 A 股相反：[3]昨收 [6]现价）；
- idx_base：腾讯 hkfqkline 日K在 nav_date 当日的收盘。港股与 A 股同交易日历，
  净值日 T 的净值即反映 T 日收盘，故基准日 = nav_date（不是美股口径的 nav_date-1）。
- 质量门限：指数只是代理时，它解释不了的净值波动会变成估值噪声。配置里带实测
  残差 index_fit_resid_pct，超过 _INDEX_MIN_RESID 一律不出数（铁律：宁可显示 '-'）。

第三种方法：期货结算价口径（method="futures"，pure 模式，移植 lofarb step12）。
用于「持仓≈单一期货合约」的商品 LOF/ETF（161226 沪银、159985 豆粕）：

    est_nav = nav * (1 + position/100 * (fut_now/fut_base * fx_now/fx_base - 1))

- fut_base：**nav_date 当日的结算价**。实测（2026-10-29，57 个交易日，见下）：
  内盘商品基金的净值按当日结算价估值，既不是收盘价，也不是滞后一日。

      口径                    161226 残差   159985 残差
      结算价 · 当日基准         0.061%        0.233%   ← 采用
      收盘价 · 当日基准         1.290%        0.525%
      结算价 · 滞后一日         2.045%        0.726%
      收盘价 · 滞后一日         1.949%        0.642%

  161226 的 beta=1.0001 / R²=0.9991 近乎恒等；换用收盘价则 R² 掉到 0.61。
  注意 AG0 2026-10-28 收盘 13010、结算 13099，相差 0.68% —— 用收盘就把这个
  期现口径差当成了基金涨跌。
- fut_now：净值已滞后（最新交易日 > nav_date）时直接用最新交易日结算价，与 base
  完全同源且无盘中噪声；只有 nav_date 本身就是最新交易日、结算价尚未产生时，
  才退回实时最新价（输出里用 est_futures_price_kind 标明 settle / live）。
- 缺 lofarb 的 calibration（期现折算系数，Woody 私有数据）→ 只能 pure 模式：
  期货即唯一成分，不折算现货。见 undo.md §A。

第四种取数形态：日经 225 现货（method="index" + feed="jp"，不是新方法）。
日本 15:00 收盘 = 北京时间 14:00，早于 A 股收盘，故与港股一样「基准日 = nav_date」。
差别只在两处取数：

- 指数：index_global_hist_em(symbol="日经225") → 日期/最新价（已收盘日即收盘价）。
- 汇率：**人民币中间价** currency_boc_safe → 日期/日元（表里是「100 日元兑人民币」，
  要除以 100），不是新浪 fx_sjpycny 的即期。实测即期 0.0422089 vs 中间价 0.042453，
  日变化差 0.11%/天；而基金估值用中间价（口径与标定一致才可验收）。所以这里把两腿
  **预先相乘**成「人民币计价的日经」序列，_estimate_by_index 只需一条序列，
  汇率误差也不会二次叠加。

网关的日经源只有一个（index_global_hist_em，走东财 push2his）且极慢：9705 条、52~92s、
不支持按日期裁剪。2026-10-29 实测该上游在网关侧长期故障 —— 网关 /api/datasource/status
里 eastmoney 连续失败 13 次、degraded，而同网关走新浪/外汇局/东财基金的方法全部正常；
穷尽 8 轮、30+ 替代端点（见 undo.md §P.3）后确认无第二条路。
所以做成「慢腿 + 后台预热」，不进 5 分钟快照的同步路径（见 _JP_DAILY_TTL）。
网关也没有日经实时源（index_global_spot_em 30s+ 超时），因此不设实时腿：
日本 14:00 收盘，A 股收盘后日K末根即当日收盘；14:00 前日K末根仍等于净值日，
此时 ratio 恒为 1，_estimate_by_index 直接不出数（不是给出 est_nav = nav 的假值）。

为什么不用日经期货 NKY（原配置如此）：外盘期货无结算价且含基差，实测残差
0.427~0.559%，全部超门限；换现货后 0.126~0.206%。513520 现货仍达 0.307%
（14/71 天单日误差 >0.5%，散布型）→ 按铁律不出数，见 undo.md §O。
另：网关没有外盘期货日K（futures_foreign_hist 对 NKD/NK/N225 恒返回 500），
所以 feed 前缀为 hf_ 的外盘腿在日K/实时两支里一律跳过。

数据源（2026-10-29 起 T2 相关的一律走数据网关 /api/ak）：
- 走网关：期货日K futures_zh_daily_sina（含 settle）/ 期货实时 futures_zh_spot；
          日经现货 index_global_hist_em；人民币中间价 currency_boc_safe。
- 仍直连（T0/T1 遗留，早于网关恢复，见 undo.md §P）：
          新浪美股日K US_MinKService.getDailyK（JSONP）、美股实时 gb_；
          新浪A股日K/实时（SZ159560 组件）、新浪港股指数 hkHSI 等；
          腾讯港股日K/实时 ifzq.gtimg.cn / qt.gtimg.cn；
          新浪汇率 fx_susdcny / fx_shkdcny / fx_sjpycny。

铁律（继承 lofarb）：position 缺失/篮子缺失/基准价缺失 → 不估算（返回 None，
前端显示 '-'），绝不静默兜底造数。

缓存：5 分钟 TTL 后台守护线程刷新快照，请求路径只读快照（与
_attach_kline_metrics 预热模式一致）；快照未就绪时本轮不估算，下轮自动补上。
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta

from services.akshare_client import akshare_request, get_session

SNAPSHOT_TTL = 300  # 秒

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "qdii_baskets.json"
)

_CURRENCY_FIELD = {"USD": "fx_susdcny", "HKD": "fx_shkdcny", "JPY": "fx_sjpycny"}

# 需要预取的数据清单（由配置推导）
_us_symbols: set[str] = set()
_a_symbols: set[str] = set()        # 形如 SZ159560
_hk_symbols: set[str] = set()       # 形如 00700
_future_symbols: set[str] = set()   # 形如 NKY / AG0 / M0
_future_feed: dict[str, str] = {}   # sym -> 新浪 list 代码（nf_AG0 / hf_NK）
_currencies: set[str] = set()
_hk_index_symbols: set[str] = set()  # 形如 hkHSI / hkHSCEI（method=index 的基金）
_jp_index_symbols: set[str] = set()  # 形如 jpN225cny（日经现货已按人民币中间价合腿）

# 取数腿代号 -> (指数名, 中间价列名)。两列都经数据网关取，见 _load_jp_daily_sync。
_JP_INDEX_LEGS = {
    "jpN225cny": ("日经225", "日元"),
}

# 日经日K 是「慢腿」：网关 index_global_hist_em 每次返回全量 9705 条（不支持按日期裁剪），
# 实测 52~92s、约 1/3 概率报 500；currency_boc_safe 另有 7~9s。放进 5 分钟快照的同步
# 路径会把美股/港股/期货一起拖住，所以单独做缓存：
#   - TTL 4 小时（日K 一天只变一次，4 小时绰绰有余）；
#   - 失败后 1 小时内不重试。上游是**长期**故障（不是偶发抖动），一轮失败要烧掉 92s，
#     退避太短等于拿后台线程空转；1 小时退避下一天最多 24 轮 ≈ 37 分钟，可接受，
#     而网关一旦修好也能在 1 小时内自动恢复；
#   - 刷新永远在后台线程，主快照只用「当前缓存」；首次为空时日经暂不出数。
_JP_DAILY_TTL = 4 * 3600
_JP_RETRY_AFTER_FAIL = 60 * 60
_jp_daily_state: dict = {"data": {}, "at": 0.0, "ok": False, "busy": False}
_jp_daily_lock = threading.Lock()

# 指数代理质量门限。依据：2026-10-28 对 14 只港股恒生系 LOF 逐日实测
#   resid = std(nav 日收益率 - position * 指数日收益率)
# 真·恒生指数跟踪的 3 只残差仅 0.07~0.08%；用大盘代理细分指数时升到 0.67~0.97%。
# LOF 典型溢价约 0.5%，残差 >=0.3% 时噪声已能吞掉大半信号 → 出数会误导。
_INDEX_MIN_RESID = 0.30
# 基准日与净值日允许的最大间隔（自然日）。超过说明日K断档或净值滞后过久。
_INDEX_MAX_BASE_LAG_DAYS = 7

# 期货口径的质量门限与基准日容差。与指数用同一把尺子：残差是「解释不了的净值波动」，
# 与估值误差同量纲。实测 161226=0.061% / 159985=0.233%，所以 0.30 对它们是宽松的；
# 设门限是为了挡住「配错了合约」这种退化情形（那时残差会跳到 1% 以上）。
_FUTURES_MIN_RESID = 0.30
_FUTURES_MAX_BASE_LAG_DAYS = 7

_config: dict = {}
_config_lock = threading.Lock()

_snapshot: dict | None = None
_snapshot_lock = threading.Lock()
_refresh_thread: threading.Thread | None = None


# ---------------------------------------------------------------- 配置加载

def _load_config() -> dict:
    global _config, _us_symbols, _a_symbols, _hk_symbols, _future_symbols, _future_feed, _currencies
    global _hk_index_symbols, _jp_index_symbols
    with _config_lock:
        if _config:
            return _config
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                _config = json.load(f).get("funds", {})
        except Exception as e:
            print(f"[CrossBorderValuation] 篮子配置加载失败: {e}")
            _config = {}
        _us_symbols, _a_symbols, _hk_symbols, _future_symbols, _currencies = set(), set(), set(), set(), set()
        _hk_index_symbols = set()
        _jp_index_symbols = set()
        _future_feed = {}
        for cfg in _config.values():
            _currencies.add(cfg.get("currency", "USD"))
            idx = cfg.get("index") or {}
            if idx.get("market") == "hk_index" and idx.get("symbol"):
                _hk_index_symbols.add(idx["symbol"])
            # feed=jp 走东财日经现货腿（与港股的 store / 取数源都不同）
            if idx.get("feed") == "jp" and idx.get("symbol"):
                _jp_index_symbols.add(idx["symbol"])
            # method=futures 的合约不在 basket 里，必须单独收集，否则日K/实时都不会取
            fut = cfg.get("futures") or {}
            if fut.get("symbol"):
                _future_symbols.add(fut["symbol"])
                _future_feed[fut["symbol"]] = fut.get("feed", fut["symbol"])
            for c in cfg.get("basket", []):
                mkt, sym = c.get("market"), c.get("symbol", "")
                if mkt == "us":
                    _us_symbols.add(sym)
                elif mkt == "a":
                    _a_symbols.add(sym)
                elif mkt == "hk":
                    _hk_symbols.add(sym)
                elif mkt in ("cn_future", "japan_future"):
                    _future_symbols.add(sym)
                    _future_feed[sym] = c.get("feed", sym)
        n_index = sum(1 for v in _config.values()
                      if (v.get("method") or ("index" if v.get("index") else "basket")) == "index")
        print(
            f"[CrossBorderValuation] 篮子配置加载: {len(_config)} 只基金, "
            f"美股 {len(_us_symbols)} / A股 {len(_a_symbols)} / 港股 {len(_hk_symbols)} / "
            f"期货 {len(_future_symbols)} / 指数跟踪 {n_index} 只 "
            f"(港股指数 {sorted(_hk_index_symbols)} / 日经 {sorted(_jp_index_symbols)}) / "
            f"币种 {sorted(_currencies)}"
        )
        # 日经慢腿首次预热：不等它，起了就让它在后台跑，几分钟后快照就有数
        if _jp_index_symbols:
            _jp_daily_kick()
        return _config


# ---------------------------------------------------------------- 行情解析工具

def _get(url: str, timeout: int = 12) -> str:
    resp = get_session().get(
        url, timeout=timeout,
        headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"},
    )
    return resp.content.decode("gbk", "ignore")


def _f(v) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError):
        return None


def _norm_date(s: str) -> str:
    """'2026/10/15' / '2026-10-15 00:00:00' / '20261015' → 'YYYY-MM-DD'。"""
    digits = re.sub(r"\D", "", str(s))[:8]
    if len(digits) == 8:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def _parse_jsonp_array(text: str) -> list[dict]:
    """JSONP `/*xxx*/v_usXOP([{...},...]);` → list[dict]。"""
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    return json.loads(text[start:end + 1])


# ---------------------------------------------------------------- 各市场抓取

def _fetch_us_daily(snaps: dict) -> None:
    """新浪美股日K（US_MinKService.getDailyK，JSONP，d=日期 c=收盘）：
    {symbol: [(date, close), ...]}，取最近 60 根。"""
    out = {}
    for sym in sorted(_us_symbols):
        try:
            text = _get(
                "https://stock.finance.sina.com.cn/usstock/api/jsonp.php"
                f"/var%20_/US_MinKService.getDailyK?symbol={sym}&___qn=3",
                timeout=15,
            )
            t = text[text.find("(") + 1:text.rfind(")")]
            bars = json.loads(t)
            pairs = []
            for b in bars[-60:]:
                d = _norm_date(b.get("d"))
                c = _f(b.get("c"))
                if d and c:
                    pairs.append((d, c))
            if pairs:
                out[sym] = pairs
        except Exception as e:
            print(f"[CrossBorderValuation] 美股日K {sym} 失败: {type(e).__name__}: {e}")
    snaps["us_daily"] = out
    print(f"[CrossBorderValuation] 美股日K命中 {len(out)}/{len(_us_symbols)}")


def _fetch_us_realtime(snaps: dict) -> None:
    """新浪美股实时：gb_ 前缀小写，[1]=现价（仅盘中有增量，收盘后与日K末根一致）。
    变量名为 hq_str_gb_xxx（非 v_ 前缀）。"""
    out = {}
    syms = sorted(_us_symbols)
    for i in range(0, len(syms), 15):
        batch = syms[i:i + 15]
        try:
            text = _get("https://hq.sinajs.cn/list=" + ",".join("gb_" + s.lower() for s in batch))
            for m in re.finditer(r'hq_str_gb_(\w+)="([^"]*)"', text):
                fields = m.group(2).split(",")
                price = _f(fields[1]) if len(fields) > 1 else None
                if price:
                    out[m.group(1).upper()] = price
        except Exception as e:
            print(f"[CrossBorderValuation] 美股实时批量失败: {e}")
    snaps["us_rt"] = out
    print(f"[CrossBorderValuation] 美股实时命中 {len(out)}/{len(_us_symbols)}")


def _fetch_fx(snaps: dict) -> None:
    """新浪汇率 hq_str_fx_xxx：[1]现价(买) [3]昨收 [17]日期。
    验证：现-昨收 = [11]涨跌额，[10]为涨跌%。base=昨收=[3]。"""
    out = {}
    need = [(_CURRENCY_FIELD[c], c) for c in sorted(_currencies) if c in _CURRENCY_FIELD]
    if need:
        try:
            text = _get("https://hq.sinajs.cn/list=" + ",".join(f for f, _ in need))
            for m in re.finditer(r'hq_str_(fx_\w+)="([^"]*)"', text):
                fields = m.group(2).split(",")
                if len(fields) > 17:
                    now = _f(fields[1])
                    prev = _f(fields[3])
                    code = {"fx_susdcny": "USD", "fx_shkdcny": "HKD", "fx_sjpycny": "JPY"}.get(m.group(1))
                    if code and now and prev and prev > 0:
                        out[code] = {"now": now, "base": prev, "date": fields[17]}
        except Exception as e:
            print(f"[CrossBorderValuation] 汇率抓取失败: {e}")
    out.setdefault("CNY", {"now": 1.0, "base": 1.0, "date": ""})
    snaps["fx"] = out


def _fetch_a_share(snaps: dict) -> None:
    """A股组件（如 SZ159560）：新浪实时 list=（[2]昨收 [3]现价 [30]日期）。
    A股与基金净值同日历：现价含今日盘中/收盘增量，昨收≈净值基准后起点。"""
    rt = {}
    for sym in sorted(_a_symbols):
        try:
            text = _get(f"https://hq.sinajs.cn/list={sym.lower()}", timeout=8)
            for m in re.finditer(r'hq_str_(\w+)="([^"]*)"', text):
                fields = m.group(2).split(",")
                if len(fields) > 30:
                    price = _f(fields[3])
                    prev = _f(fields[2])
                    if price and prev:
                        rt[sym] = {"now": price, "prev_close": prev, "date": fields[30]}
        except Exception as e:
            print(f"[CrossBorderValuation] A股实时 {sym} 失败: {e}")
    snaps["a_rt"] = rt


def _fetch_hk(snaps: dict) -> None:
    """腾讯港股个股实时 r_hkXXXXX（[3]现价 [4]昨收）。
    与期货同构近似：基准=昨收（昨收及之前已入净值），现价含盘中增量。"""
    rt = {}
    for sym in sorted(_hk_symbols):
        try:
            resp = get_session().get(
                f"https://qt.gtimg.cn/q=r_hk{sym}", timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            text = resp.content.decode("gbk", "ignore")
            m = re.search(r'"([^"]*)"', text)
            if m:
                fields = m.group(1).split("~")
                if len(fields) > 4:
                    price, prev = _f(fields[3]), _f(fields[4])
                    if price and prev:
                        rt[sym] = {"now": price, "prev_close": prev, "date": ""}
        except Exception as e:
            print(f"[CrossBorderValuation] 港股实时 {sym} 失败: {e}")
    snaps["hk_rt"] = rt


def _fetch_futures(snaps: dict) -> None:
    """内盘期货实时（走数据网关 futures_zh_spot）：最新价 + 昨结算。

    只服务 _estimate_by_futures 的 live 分支（nav_date == 最新交易日、当日结算价还没出）。
    日终估值一律走 _fetch_futures_daily 的结算价，不依赖这里。

    网关返回体只有中文名（白银连续/豆粕连续）、没有合约代码，因此按**请求顺序**对齐，
    再用「昨结算 ≈ 日K末根结算价」做自洽校验：真的串位时两者会明显偏离。
    外盘（feed 前缀 hf_，如 hf_NK 大阪日经）网关没有实时源（futures_foreign_hist 恒 500），
    这一支直接跳过 —— 日经改吃现货口径，见 _load_jp_daily_sync。
    """
    out: dict[str, dict] = {}
    inner: list[tuple[str, str]] = []
    for sym in sorted(_future_symbols):
        feed = _future_feed.get(sym, sym)
        if not feed.startswith("nf_"):
            print(f"[CrossBorderValuation] 期货实时 {sym} 跳过：网关无外盘实时（{feed}）")
            continue
        inner.append((sym, feed.split("_", 1)[1]))

    rows: list = []
    if inner:
        got = akshare_request(
            "futures_zh_spot",
            {"symbol": ",".join(code for _, code in inner), "market": "CF"},
            retries=1, timeout=15,
        )
        rows = got if isinstance(got, list) else []
        if len(rows) != len(inner):
            print(f"[CrossBorderValuation] 期货实时数量不匹配 {len(rows)}/{len(inner)}，全丢弃")
            rows = []

    daily = snaps.get("futures_daily") or {}
    today = datetime.now().strftime("%Y-%m-%d")
    for (sym, code), r in zip(inner, rows):
        price, prev = _f(r.get("current_price")), _f(r.get("last_settle_price"))
        if not (price and prev):
            print(f"[CrossBorderValuation] 期货实时 {sym} 字段不全")
            continue
        # 自洽校验：网关实时不返回合约代码，只能按请求顺序对齐，怕串位。
        # last_settle_price 的语义是「**上一交易日**结算价」，所以参照点要跟着日K走：
        # 日K末根已是今天（当日结算已公布）→ 比倒数第二根；否则 → 比末根。
        # 不知道这一层会误杀：10-29 的 AG0 日K末根 12918（今日）、实时 last_settle 13099（昨日），
        # 直接比末根就判定「串位」了。各品种结算公布时间不同（AG0 已出、M0 未出），两边都要兼容。
        pairs = (daily.get(sym) or {}).get("pairs") or []
        if pairs:
            ref = (pairs[-2][1] if (len(pairs) >= 2 and pairs[-1][0] == today)
                   else pairs[-1][1])
            if abs(prev / ref - 1.0) > 0.01:
                print(f"[CrossBorderValuation] 期货实时 {sym} 昨结算 {prev} 与日K参照 "
                      f"{ref} 不符，疑似串位，丢弃")
                continue
        # 网关实时不返回日期；live 分支本来就只用于「当天还在交易」的场景，
        # 且 price_date 只用于展示，取本地日期即可
        out[sym] = {"now": price, "prev_close": prev, "date": today,
                    "list": f"gateway:futures_zh_spot:{code}"}
    snaps["futures"] = out
    if _future_symbols:
        print(f"[CrossBorderValuation] 期货实时命中 {len(out)}/{len(_future_symbols)}")


def _fetch_futures_daily(snaps: dict) -> None:
    """期货日K（走数据网关 futures_zh_daily_sina），取**结算价**。

    网关返回 [{date, open, high, low, close, volume, hold, settle}]，settle 就是
    商品基金净值口径。为什么不复用实时值：实时给的是「最新价」，不是结算价 ——
    实测 AG0 2026-10-28 收盘 13010 / 结算 13099，差 0.68%，把这个差当涨跌就废了。
    某天若缺结算价，宁可跳过该天（kind 不混用），也不拿收盘价顶替。

    外盘（feed 前缀 hf_，如 hf_NK 大阪日经）网关无日K源，直接跳过；
    日经改吃现货口径，见 _load_jp_daily_sync。
    """
    out: dict[str, dict] = {}
    for sym in sorted(_future_symbols):
        feed = _future_feed.get(sym, sym)
        if not feed.startswith("nf_"):
            print(f"[CrossBorderValuation] 期货日K {sym} 跳过：网关无外盘日K（{feed}）")
            continue
        code = feed.split("_", 1)[1]
        rows = akshare_request("futures_zh_daily_sina", {"symbol": code},
                              retries=1, timeout=20)
        pairs = []
        for r in (rows if isinstance(rows, list) else [])[-60:]:
            d, px = _norm_date(str(r.get("date") or "")), _f(r.get("settle"))
            if not d or not px:
                continue          # 缺结算价 → 跳过该天，不拿收盘价混口径
            pairs.append((d, px))
        if pairs:
            out[sym] = {"pairs": pairs, "kind": "settle"}
    snaps["futures_daily"] = out
    print(f"[CrossBorderValuation] 期货日K命中 {len(out)}/{len(_future_symbols)}")


def _load_jp_daily_sync() -> dict[str, list[tuple[str, float]]]:
    """同步拉日经现货 + 人民币中间价日K，按日期交集相乘 → 人民币计价序列。

    两条腿都走数据网关：
      - 指数 index_global_hist_em(symbol="日经225") → 日期/最新价（已收盘日即收盘价）
      - 汇率 currency_boc_safe → 日期/日元，**表里是「100 日元兑人民币」**，要除以 100

    为什么在取数层就把两条腿乘起来：_estimate_by_index 的公式是 idx_ratio × fx_ratio，
    合腿后只剩一条序列，汇率不会二次叠加误差，也不必给指数口径单开汇率分支。

    实测耗时 60~100s，只能由 _jp_daily_load 在后台线程里调。
    """
    # 这条腿在网关侧长期不可用（东财 push2his 出网故障）：2026-10-29 实测 8 轮全失败，
    # 每次要么 92s 后 500、要么读超时。仍保留 1 次重试（对偶发抖动有效，且成功时 52~92s
    # 本就要等这么久），失败后交给 _JP_RETRY_AFTER_FAIL 的 1 小时退避。
    raw = akshare_request("index_global_hist_em", {"symbol": "日经225"},
                          retries=1, timeout=120)
    if not isinstance(raw, list) or not raw:
        print("[CrossBorderValuation] 日经日K 网关返回空（将在 "
              f"{_JP_RETRY_AFTER_FAIL // 60} 分钟后重试，期间沿用旧缓存）")
        return {}
    idx: dict[str, float] = {}
    for r in raw:
        d, c = _norm_date(str(r.get("日期") or "")), _f(r.get("最新价"))
        if d and c:
            idx[d] = c

    boc = akshare_request("currency_boc_safe", retries=1, timeout=90)
    fx: dict[str, float] = {}
    for r in (boc if isinstance(boc, list) else []):
        # 网关字段名偶有空格变体（如 "港 元"），按「包含」匹配更稳
        col = next((k for k in r if "日元" in str(k)), None)
        d = _norm_date(str(r.get("日期") or ""))
        v = _f(r.get(col)) if col else None
        if d and v:
            fx[d] = v / 100.0
    if not fx:
        print("[CrossBorderValuation] 人民币中间价 网关返回空")
        return {}

    out: dict[str, list[tuple[str, float]]] = {}
    for sym, (_idx_name, _fx_col) in _JP_INDEX_LEGS.items():
        pairs = [(d, idx[d] * fx[d]) for d in sorted(idx) if d in fx]
        if pairs:
            out[sym] = pairs[-90:]
    print(f"[CrossBorderValuation] 日经日K 网关 指数{len(idx)}条 / 中间价{len(fx)}条 "
          f"→ 合腿 {len(out)}/{len(_JP_INDEX_LEGS)} 条腿")
    return out


def _jp_daily_load() -> None:
    """后台线程体：加载慢腿并更新缓存。失败时把 at 推到退避期后再试。"""
    data: dict = {}
    try:
        data = _load_jp_daily_sync()
    except Exception as e:
        print(f"[CrossBorderValuation] 日经日K 慢腿异常: {type(e).__name__}: {e}")
    with _jp_daily_lock:
        _jp_daily_state["at"] = time.time()
        _jp_daily_state["busy"] = False
        if data:
            _jp_daily_state["data"] = data
            _jp_daily_state["ok"] = True
        else:
            _jp_daily_state["ok"] = False


def _jp_daily_kick() -> None:
    """缓存过期 / 失败退避到期时起后台线程预热；永不阻塞调用方。"""
    now = time.time()
    with _jp_daily_lock:
        if _jp_daily_state["busy"]:
            return
        ttl = _JP_DAILY_TTL if _jp_daily_state["ok"] else _JP_RETRY_AFTER_FAIL
        if now - _jp_daily_state["at"] < ttl:
            return
        _jp_daily_state["busy"] = True
    threading.Thread(target=_jp_daily_load, daemon=True).start()


def _fetch_jp_index_daily(snaps: dict) -> None:
    """把日经慢腿缓存塞进快照（过期则顺手起后台预热，本轮仍用旧数据）。

    日本 15:00 收盘 = 北京时间 14:00，早于 A 股，所以 A 股收盘后拿到的日K末根
    就是当日收盘价（已定盘，不是盘中噪声）。网关没有日经实时源
    （index_global_spot_em 30s+ 超时），因此不设实时腿，现值一律取日K末根 ——
    代价是盘中 14:00 前日经 ETF 不出数，由 _estimate_by_index 显式挡住。
    """
    _jp_daily_kick()
    store = snaps.setdefault("jp_index", {})
    with _jp_daily_lock:
        data = dict(_jp_daily_state["data"])
    for sym, pairs in data.items():
        store.setdefault(sym, {}).update({"daily": pairs})
    if _jp_index_symbols:
        n = sum(1 for s in _jp_index_symbols if (store.get(s) or {}).get("daily"))
        print(f"[CrossBorderValuation] 日经指数日K命中 {n}/{len(_jp_index_symbols)}")



def _fetch_hk_index(snaps: dict) -> None:
    """港股指数实时（新浪 hq.sinajs.cn/list=hkHSI,hkHSCEI,hkHSTECH）。

    字段布局与 A 股相反，必须单独解析，不能复用 _fetch_a_share：
        [0]英文代码 [1]中文名 [2]今开 [3]昨收 [4]最高 [5]最低
        [6]现价 [7]涨跌额 [8]涨跌幅% [11]成交量 [12]成交额
        [15]52周高 [16]52周低 [17]日期(YYYY/MM/DD) [18]时间
    自洽校验（2026-10-28 实测）：[6]-[3] == [7] == 53.510，
    且 53.510/23041.320 == 0.232% == [8]。
    A 股 sz159560 则是 [2]昨收 [3]现价——顺序正好相反。
    """
    out: dict[str, dict] = {}
    if _hk_index_symbols:
        try:
            text = _get("https://hq.sinajs.cn/list=" + ",".join(sorted(_hk_index_symbols)))
            for m in re.finditer(r'hq_str_(\w+)="([^"]*)"', text):
                sym, body = m.group(1), m.group(2)
                f = body.split(",") if body else []
                if len(f) < 19:
                    continue
                now, prev = _f(f[6]), _f(f[3])
                if now and prev:
                    out[sym] = {"now": now, "prev_close": prev,
                                "date": _norm_date(f[17]), "daily": []}
        except Exception as e:
            print(f"[CrossBorderValuation] 港股指数实时失败: {e}")
    snaps["hk_index"] = out
    if _hk_index_symbols:
        print(f"[CrossBorderValuation] 港股指数实时命中 {len(out)}/{len(_hk_index_symbols)}")


def _fetch_hk_index_daily(snaps: dict) -> None:
    """港股指数历史日K（腾讯 hkfqkline，2026-10-28 实测为唯一可用源）。

    新浪 HK_IndexService.getDayK 两个域名分别返回 Service not valid / not found，
    网关 stock_hk_index_daily_em 超时；腾讯可取 60 根：
        GET web.ifzq.gtimg.cn/appstock/app/hkfqkline/get
            ?_var=kline_dayqfq&param=hkHSI,day,,,60,qfq
    字段顺序是 [0]日期 [1]开 [2]收 [3]高 [4]低，不是常见的「开高低收」。
    校验：高 > 开/收 > 低（实测 23157.40 > 23083.99 > 23023.04）。
    """
    store = snaps.setdefault("hk_index", {})
    for sym in sorted(_hk_index_symbols):
        try:
            resp = get_session().get(
                "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
                f"?_var=kline_dayqfq&param={sym},day,,,60,qfq",
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
            )
            txt = resp.content.decode("utf-8", "ignore")
            payload = json.loads(txt[txt.find("=") + 1:])
            bars = ((payload.get("data") or {}).get(sym) or {}).get("day") or []
            pairs = []
            for b in bars[-60:]:
                d, c = _norm_date(b[0]), _f(b[2])   # [2] 收盘
                if d and c:
                    pairs.append((d, c))
            if pairs:
                store.setdefault(sym, {}).update({"daily": pairs})
        except Exception as e:
            print(f"[CrossBorderValuation] 港股指数日K {sym} 失败: {type(e).__name__}: {e}")
    if _hk_index_symbols:
        n = sum(1 for v in store.values() if v.get("daily"))
        print(f"[CrossBorderValuation] 港股指数日K命中 {n}/{len(_hk_index_symbols)}")


# ---------------------------------------------------------------- 快照管理

def _build_snapshot() -> dict | None:
    snaps: dict = {"ts": time.time()}
    _fetch_us_daily(snaps)
    _fetch_us_realtime(snaps)
    _fetch_fx(snaps)
    if _a_symbols:
        _fetch_a_share(snaps)
    if _hk_symbols:
        _fetch_hk(snaps)
    if _future_symbols:
        # 先日K再实时：实时腿要拿日K末根的结算价做「没串位」自洽校验
        _fetch_futures_daily(snaps)
        _fetch_futures(snaps)
    if _hk_index_symbols:
        _fetch_hk_index(snaps)
        _fetch_hk_index_daily(snaps)
    if _jp_index_symbols:
        # 只塞慢腿缓存；刷新在后台线程，不拖住这一轮快照
        _fetch_jp_index_daily(snaps)
    if (not snaps.get("us_daily") and not snaps.get("futures")
            and not snaps.get("hk_index") and not snaps.get("jp_index")):
        print("[CrossBorderValuation] 快照无有效行情，本轮不产出估值")
        return None
    return snaps


def _ensure_snapshot() -> dict | None:
    """返回可用快照；过期则起后台线程刷新，本次仍用旧快照（请求路径不阻塞）。"""
    global _refresh_thread, _snapshot
    with _snapshot_lock:
        snap = _snapshot
        fresh = snap is not None and (time.time() - snap["ts"]) < SNAPSHOT_TTL
    if fresh:
        return snap
    # 需要刷新（首次或过期）：后台线程执行，未就绪前沿用旧快照
    with _snapshot_lock:
        if _refresh_thread is not None and _refresh_thread.is_alive():
            return _snapshot
        _refresh_thread = threading.Thread(target=_refresh_loop_once, daemon=True)
        _refresh_thread.start()
    return snap  # 可能为 None（首轮尚未完成）


def _refresh_loop_once() -> None:
    global _snapshot
    try:
        new = _build_snapshot()
        if new:
            with _snapshot_lock:
                _snapshot = new
    except Exception as e:
        print(f"[CrossBorderValuation] 快照刷新异常: {type(e).__name__}: {e}")


# ---------------------------------------------------------------- 估值计算

def _base_close(pairs: list[tuple[str, float]] | None, base_date: str) -> tuple[str, float] | None:
    """取 ≤ base_date 的最后一根收盘；若净值日早于全部行情，退回最早一根（近似）。"""
    if not pairs or not base_date:
        return None
    best = None
    for d, c in pairs:
        if d <= base_date:
            best = (d, c)
    return best or (pairs[0] if pairs else None)


def _component_now(snap: dict, sym: str, mkt: str) -> dict | None:
    """组件现价 + 行情日。us：实时优先(盘中)退回日K末根；a/hk：现价/昨收/日期。"""
    if mkt == "us":
        rt = snap.get("us_rt", {}).get(sym)
        daily = snap.get("us_daily", {}).get(sym)
        last = daily[-1] if daily else None
        if rt:
            return {"now": rt, "date": last[0] if last else ""}
        return {"now": last[1], "date": last[0]} if last else None
    if mkt in ("cn_future", "japan_future"):
        r = snap.get("futures", {}).get(sym)
        return {"now": r["now"], "date": r.get("date") or "", "prev_close": r.get("prev_close")} if r else None
    store = snap.get("a_rt") if mkt == "a" else snap.get("hk_rt", {})
    r = (store or {}).get(sym)
    return {"now": r["now"], "date": r.get("date") or "", "prev_close": r.get("prev_close")} if r else None


def _method_of(cfg: dict) -> str:
    """估值方法分派。缺省 basket；未写 method 但配了 index 的按 index 处理。"""
    m = cfg.get("method")
    if m in ("basket", "index", "futures"):
        return m
    if m:
        print(f"[CrossBorderValuation] 未知 method={m!r}，降级为 basket")
    return "index" if cfg.get("index") else "basket"


def _estimate_one(snap: dict, fund: dict, cfg: dict) -> dict | None:
    method = _method_of(cfg)
    if method == "index":
        return _estimate_by_index(snap, fund, cfg)
    if method == "futures":
        return _estimate_by_futures(snap, fund, cfg)
    nav = fund.get("nav")
    nav_date = _norm_date(fund.get("nav_date") or "")
    position = cfg.get("position")
    basket = cfg.get("basket") or []
    # 铁律：position / 篮子 / nav / nav_date 缺一不估
    if not nav or nav <= 0 or not nav_date:
        return None
    if position is None or cfg.get("uncertain") or not basket:
        return None

    fx_map = snap.get("fx", {})
    base_dt = datetime.strptime(nav_date, "%Y-%m-%d")
    us_base_date = (base_dt - timedelta(days=1)).strftime("%Y-%m-%d")  # 美股收盘滞后一个北京日

    w_change = 0.0
    price_date = ""
    for c in basket:
        sym, mkt, w = c["symbol"], c["market"], (c.get("weight") or 0) / 100.0
        if w <= 0:
            continue
        cur = c.get("currency") or cfg.get("currency", "USD")
        fx = fx_map.get(cur)
        if not fx:
            return None
        if mkt == "us":
            # 美股跨日历：基准=≤(nav_date-1)的最后一根收盘（净值已反映其前全部收盘），
            # 现价=实时/末根；末根若已入净值则比值≈1，无失真
            pairs = snap.get("us_daily", {}).get(sym)
            got = _component_now(snap, sym, mkt)
            bp = _base_close(pairs, us_base_date)
            if not got or not bp:
                return None  # 任一组件缺数据 → 整体不估（暴露缺失）
            base, now = bp[1], got["now"]
            price_date = max(price_date, got.get("date") or "")
        else:
            # a/hk/期货：与基金净值同市场日历，昨收已入净值 → 基准=昨收，现价=今日
            got = _component_now(snap, sym, mkt)
            if not got or not got.get("prev_close"):
                return None
            base, now = got["prev_close"], got["now"]
            price_date = max(price_date, got.get("date") or "")
        w_change += w * (now / base) * (fx["now"] / fx["base"])
    if w_change <= 0:
        return None

    est_nav = nav * (1.0 + (position / 100.0) * (w_change - 1.0))
    if not math.isfinite(est_nav) or est_nav <= 0:
        return None
    out = {
        "est_nav": round(est_nav, 4),
        "est_base_date": nav_date,
        "est_price_date": price_date,
        "est_position": position,
        "est_method": "basket",
    }
    price = fund.get("price")
    if price:
        out["est_premium_pct"] = round((price - est_nav) / est_nav * 100.0, 2)
    return out


def _estimate_by_index(snap: dict, fund: dict, cfg: dict) -> dict | None:
    """单指数代理估值（移植 lofarb step11_simple_static_valuation）。

        est_nav = nav * (1 + position/100 * (idx_now/idx_base * fx_now/fx_base - 1))

    港股与 A 股同交易日历：净值日 T 的净值已反映 T 日收盘，故基准日 = nav_date。
    与矩阵公式在「单成分、权重 100%」时代数等价，所以没有新增公式，只换了取数路径。

    质量门限：配置里的 index_fit_resid_pct 是逐日实测的残差标准差（%），
    即「该指数解释不了的净值波动」。超过 _INDEX_MIN_RESID 时，
    出数的噪声会盖过溢价本身，按铁律返回 None 由前端显示 '-'。
    """
    nav = fund.get("nav")
    nav_date = _norm_date(fund.get("nav_date") or "")
    position = cfg.get("position")
    idx = cfg.get("index") or {}
    # 铁律：nav / position / 指数映射 / 质量标定 缺一不估
    if not nav or nav <= 0 or not nav_date:
        return None
    if position is None or cfg.get("uncertain") or not idx.get("symbol"):
        return None
    # index_fit_err_pct 是 walk-forward 平均绝对误差（就是真实估值误差），
    # index_fit_resid_pct 是 OLS 残差标准差。两者同量纲，都按同一门限；
    # 前者优先：残差会被个别净值口径异常日抬高，平均误差才是「每天出数有多准」。
    resid = cfg.get("index_fit_err_pct")
    if resid is None:
        resid = cfg.get("index_fit_resid_pct")
    # 默认按门限拒绝；配置里显式 index_allow_weak=true 才放行弱代理（前端必须标注）
    if resid is None or (resid > _INDEX_MIN_RESID and not cfg.get("index_allow_weak")):
        return None

    fx = (snap.get("fx") or {}).get(cfg.get("currency", "HKD"))
    if not fx or not fx.get("base"):
        return None

    # feed=jp 的序列在 jp_index，且已折成人民币计价（见 _fetch_jp_index_daily）
    store = snap.get("jp_index" if idx.get("feed") == "jp" else "hk_index") or {}
    got = store.get(idx["symbol"])
    if not got:
        return None

    daily = got.get("daily") or []
    bp = _base_close(daily, nav_date)
    if not bp:
        return None
    if bp[0] > nav_date:
        return None   # 日K窗口不覆盖净值日，基准价会取到未来收盘
    lag = (datetime.strptime(nav_date, "%Y-%m-%d")
           - datetime.strptime(bp[0], "%Y-%m-%d")).days
    if lag > _INDEX_MAX_BASE_LAG_DAYS:
        return None   # 日K断档或净值滞后过久，基准日对不上

    # 日经只有日K（网关无实时源）：末根即当日收盘。若末根仍等于净值日，
    # 说明日本新一天的收盘还没到（北京时间 14:00 前），此时 ratio 恒为 1、
    # 算出来就是净值本身，出数只会误导 —— 直接不出。
    if idx.get("feed") == "jp" and daily and daily[-1][0] <= nav_date:
        return None

    price_date = got.get("date") or (daily[-1][0] if daily else "")
    if price_date and price_date < nav_date:
        return None   # 指数行情早于净值日 = 陈旧快照

    now = got.get("now") or (daily[-1][1] if daily else None)
    if not now:
        return None

    idx_ratio = now / bp[1]
    fx_ratio = fx["now"] / fx["base"]
    est_nav = nav * (1.0 + (position / 100.0) * (idx_ratio * fx_ratio - 1.0))
    if not math.isfinite(est_nav) or est_nav <= 0:
        return None

    out = {
        "est_nav": round(est_nav, 4),
        "est_base_date": bp[0],
        "est_price_date": price_date or bp[0],
        "est_position": position,
        "est_method": "index",
        "est_index_symbol": idx["symbol"],
        "est_index_resid_pct": resid,
    }
    if cfg.get("index_is_proxy"):
        out["est_index_proxy"] = True
    price = fund.get("price")
    if price:
        out["est_premium_pct"] = round((price - est_nav) / est_nav * 100.0, 2)
    return out


def _estimate_by_futures(snap: dict, fund: dict, cfg: dict) -> dict | None:
    """期货结算价口径 pure 模式（移植 lofarb realtime_futures_analysis 的 pure 分支）。

        est_nav = nav * (1 + position/100 * (fut_now/fut_base * fx_now/fx_base - 1))

    与 _estimate_by_index 同构，三处不同：
    1) 基准/现价优先用**结算价**，因为内盘商品基金按结算价估净值
       （实测换成交价，161226 残差 0.061% → 1.290%）；
    2) 净值滞后时现价取「最新交易日结算价」而不是实时最新价：结算是日终定盘口径，
       与 base 同源，且不受盘中噪声影响；
    3) 无 calibration（期现折算系数）→ 不折算现货，纯期货口径。
    """
    nav = fund.get("nav")
    nav_date = _norm_date(fund.get("nav_date") or "")
    position = cfg.get("position")
    fut = cfg.get("futures") or {}
    sym = fut.get("symbol")
    # 铁律：nav / position / 合约 / 质量标定 缺一不估
    if not nav or nav <= 0 or not nav_date:
        return None
    if position is None or cfg.get("uncertain") or not sym:
        return None
    resid = cfg.get("futures_fit_resid_pct")
    if resid is None or (resid > _FUTURES_MIN_RESID and not cfg.get("futures_allow_weak")):
        return None

    fx = (snap.get("fx") or {}).get(cfg.get("currency", "CNY"))
    if not fx or not fx.get("base"):
        return None

    got = (snap.get("futures_daily") or {}).get(sym) or {}
    pairs = got.get("pairs") or []
    kind = got.get("kind") or "settle"
    bp = _base_close(pairs, nav_date)
    if not bp:
        return None
    if bp[0] > nav_date:
        return None   # 日K窗口不覆盖净值日，基准价会取到未来结算价
    lag = (datetime.strptime(nav_date, "%Y-%m-%d")
           - datetime.strptime(bp[0], "%Y-%m-%d")).days
    if lag > _FUTURES_MAX_BASE_LAG_DAYS:
        return None   # 日K断档或净值滞后过久，基准日对不上

    if pairs[-1][0] > nav_date:
        # 净值滞后：最新交易日已定盘，用结算价，与 base 同源
        now, price_date, now_kind = pairs[-1][1], pairs[-1][0], kind
    else:
        # nav_date 就是最新交易日：结算价还没出，只能退回实时最新价
        rt = (snap.get("futures") or {}).get(sym) or {}
        now = rt.get("now")
        price_date = _norm_date(rt.get("date") or "") or bp[0]
        now_kind = "live"
    if not now or now <= 0:
        return None

    fut_ratio = now / bp[1]
    fx_ratio = fx["now"] / fx["base"]
    est_nav = nav * (1.0 + (position / 100.0) * (fut_ratio * fx_ratio - 1.0))
    if not math.isfinite(est_nav) or est_nav <= 0:
        return None

    out = {
        "est_nav": round(est_nav, 4),
        "est_base_date": bp[0],
        "est_price_date": price_date,
        "est_position": position,
        "est_method": "futures",
        "est_futures_symbol": sym,
        "est_futures_price_kind": now_kind,      # settle=已定盘 / live=盘中最新价
        "est_futures_resid_pct": resid,
    }
    price = fund.get("price")
    if price:
        out["est_premium_pct"] = round((price - est_nav) / est_nav * 100.0, 2)
    return out


def attach_estimated_valuations(funds: list[dict]) -> None:
    """给基金列表就地附加篮子自算估值字段（est_*）；不满足条件则不写（前端显示 '-'）。"""
    if not funds:
        return
    config = _load_config()
    if not config:
        return
    hit = [f for f in funds if str(f.get("code", "")) in config]
    if not hit:
        return
    snap = _ensure_snapshot()
    if not snap:
        return  # 首轮快照未就绪，下一轮列表刷新自然补上
    n_ok = 0
    by_method: dict[str, int] = {}
    for fund in hit:
        cfg = config[str(fund.get("code"))]
        try:
            est = _estimate_one(snap, fund, cfg)
        except Exception as e:
            print(f"[CrossBorderValuation] {fund.get('code')} 估算异常: {e}")
            est = None
        if est:
            fund.update(est)
            n_ok += 1
            key = est.get("est_method", "basket")
            by_method[key] = by_method.get(key, 0) + 1
    print(f"[CrossBorderValuation] 篮子自算估值命中 {n_ok}/{len(hit)} 只 {by_method}")
