"""市场复盘图表服务 — 公众号「每周市场复盘」11 图取数 + 计算 + 缓存。

数据流
------
    本模块 ──HTTP──> AkShare WebAPI 网关（core.config.AKSHARE_API_BASE 的 /api/ak 通用透传）
                        │
                        └─ 任意 akshare 函数经网关代理返回（list[dict]，列名为 akshare 原生中文/英文）

设计要点
------
- **全部走数据网关**：只调用 ``services.akshare_client.akshare_request``，不直连本地 akshare、不引入本地 akshare 依赖。
- **强缓存 + 后台刷新**：网关仅 2 个 worker，慢的 akshare 调用会占满 worker 导致连接超时；
  故每个图表结果缓存 6 小时，未命中时**后台线程**刷新、本次先返回已有（可能为空）数据，绝不阻塞请求线程。
- **取数失败返回空 + meta 标记**：绝不伪造数值。
- **网关熔断器 + 新鲜度标注（行情源韧性）**：所有取数经 ``_gw`` 封装，连续失败达阈值后整体熔断，
  熔断期间停止打网关、改回退历史好数据并标记 ``stale``；served 数据附 ``stale/ageMinutes/lastOkTime/breakerOpen``，前端可判别"活的"还是"旧的"。

计算均为纯 Python（后端运行环境不保证有 pandas），保证可移植。
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timedelta

from services.akshare_client import akshare_request
from core.config import AKSHARE_API_BASE

# ---------------------------------------------------------------------------
# 数据源标识（meta.dataSource）
# ---------------------------------------------------------------------------
_AKSHARE_HOST = AKSHARE_API_BASE.rstrip("/").split("://")[-1]
_DATA_SOURCE = f"AkShare WebAPI ({_AKSHARE_HOST})"


def _build_meta(ok: bool, note: str = "", gateway_empty: bool = False) -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "isMock": False,
        "dataSource": "网关无数据" if gateway_empty else _DATA_SOURCE,
        "gatewayEmpty": gateway_empty,
        "updateTime": now if ok else None,
        "note": note or None,
    }


# ---------------------------------------------------------------------------
# 网关级熔断器（行情源韧性 P2）
# ---------------------------------------------------------------------------
class _GatewayBreaker:
    """网关整体熔断：连续失败达阈值后，短时间内停止打网关、改走缓存/空态，避免雪崩。

    - 所有图表共用一个网关(AKSHARE_API_BASE)，故用一个全局熔断器即可。
    - 熔断开启期间：取数层直接返回 None（快失败），get_chart 对有历史好数据的图表改回退旧数据(标 stale)。
    - 熔断在 open_seconds 后自动半开，下一次成功即复位。
    """

    def __init__(self, threshold: int = 5, open_seconds: int = 60):
        self.threshold = threshold
        self.open_seconds = open_seconds
        self._lock = threading.Lock()
        self._failures = 0
        self._open_until = 0.0

    def allow(self) -> bool:
        with self._lock:
            return time.time() >= self._open_until

    def success(self) -> None:
        with self._lock:
            self._failures = 0

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.threshold:
                self._open_until = time.time() + self.open_seconds
                print(f"[MarketCharts] 网关熔断器开启，{self.open_seconds}s 内停止打网关")

    @property
    def open(self) -> bool:
        with self._lock:
            return time.time() < self._open_until


_BREAKER = _GatewayBreaker(threshold=5, open_seconds=60)


def _gw(method: str, params: dict | None = None, retries: int = 1, timeout: int = 8):
    """经熔断器的网关调用封装：成功复位、失败计数；熔断中直接返回 None（快失败）。"""
    if not _BREAKER.allow():
        print(f"[MarketCharts] 网关熔断中，跳过 {method}")
        return None
    try:
        data = akshare_request(method, params, retries=retries, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        print(f"[MarketCharts] {method} 网关异常: {e}")
        data = None
    if data is None:
        _BREAKER.failure()
    else:
        _BREAKER.success()
    return data


# ---------------------------------------------------------------------------
# 指数 / 基金代码映射（Wind 私有指数用公开代理替代，详见各 builder 注释）
# ---------------------------------------------------------------------------
CODES = {
    "zz_quan_zhi": "000985",   # 中证全指（万得全A 代理）
    "hs300": "000300",         # 沪深300
    "zz_pian_gu": "930950",    # 中证偏股基金指数
    "zz_hongli": "000922",     # 中证红利（价格）
    "hs300_value": "000919",   # 沪深300价值
    "hs300_growth": "000918",  # 沪深300成长
    "gz_value100": "980082",   # 国证价值100
    "gz_growth100": "980083",  # 国证成长100
}
# 一级债基代理：易方达增强回报A（110017，长历史主动债基，近似一级债基上限）
FUND_TIER1_BOND = "110017"
# 万得偏债混合型基金指数代理：易方达稳健收益B（110008，长历史偏债混合）
FUND_PIANZHAI_HUNHE = "110008"
# 中证港股通高股息投资指数（CNY）
HK_HIGHDIV = "930914"


# ===========================================================================
# 通用工具
# ===========================================================================
def _safe_float(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _pick(row: dict, *keys, default=None):
    """按候选键取字段，先做精确匹配，再忽略大小写匹配一次。"""
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    lk = {str(k).lower() for k in keys}
    for k, v in row.items():
        if str(k).lower() in lk and v not in (None, ""):
            return v
    return default


_DATE_KEYS = ("日期", "date", "净值日期", "trade_date", "时间")
_CLOSE_KEYS = ("收盘", "close", "指数", "收盘点位", "point", "price", "现价")
_NAV_KEYS = ("单位净值", "nav", "net_value", "累计净值", "累计单位净值")
_PE_KEYS = ("滚动市盈率", "pe_ttm", "pe", "市盈率", "市盈率ttm")
_YIELD_KEYS = ("10年", "10y", "10年国债", "收益率")  # bond_china_yield 的 10Y 列
_US10Y_KEYS = ("10年", "10y", "10年国债", "us10y", "美国10年")


def _normalize(rows, value_keys, date_keys=_DATE_KEYS) -> list[tuple[str, float]]:
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        d = _pick(r, *date_keys)
        v = _safe_float(_pick(r, *value_keys))
        if d and v is not None:
            out.append((str(d)[:10], v))
    out.sort(key=lambda x: x[0])
    return out


# ===========================================================================
# 取数封装（全部经网关）
# ===========================================================================
def _index_csindex(symbol: str, start: str, end: str | None = None, timeout: int = 30):
    p = {"symbol": symbol, "start_date": start}
    if end:
        p["end_date"] = end
    return _gw("stock_zh_index_hist_csindex", p, retries=2, timeout=timeout)


def _index_zh_a(symbol: str, start: str, end: str | None = None, timeout: int = 30):
    p = {"symbol": symbol, "period": "daily", "start_date": start}
    if end:
        p["end_date"] = end
    return _gw("index_zh_a_hist", p, retries=2, timeout=timeout)


def _index_cni(symbol: str, start: str, end: str | None = None, timeout: int = 30):
    p = {"symbol": symbol, "start_date": start}
    if end:
        p["end_date"] = end
    return _gw("index_hist_cni", p, retries=2, timeout=timeout)


def _fund_nav(symbol: str, start: str, end: str | None = None, timeout: int = 30):
    p = {"symbol": symbol, "start_date": start}
    if end:
        p["end_date"] = end
    return _gw("fund_open_fund_daily_em", p, retries=2, timeout=timeout)


def _hk_index(symbol: str, start: str, end: str | None = None, timeout: int = 30):
    p = {"symbol": symbol, "start_date": start}
    if end:
        p["end_date"] = end
    return _gw("stock_hk_index_daily_em", p, retries=2, timeout=timeout)


def _index_pe(symbol: str, timeout: int = 35) -> list[tuple[str, float]]:
    rows = _gw("stock_index_pe_lg", {"symbol": symbol}, retries=2, timeout=timeout)
    return _normalize(rows, _PE_KEYS)


def _index_dividend(symbol: str, timeout: int = 35) -> list[tuple[str, float]]:
    """中证红利股息率（历史）。优先从 stock_zh_index_value_csindex 解析时间序列/最新值。

    该接口在不同 akshare 版本下结构不一（可能为 dict 当前值，或含历史序列），做容错解析。
    """
    raw = _gw("stock_zh_index_value_csindex", {"symbol": symbol}, retries=2, timeout=timeout)
    if not raw:
        return []
    # 情况1：list[dict] 时间序列，含 股息率 / dividend_yield 列
    if isinstance(raw, list):
        out = _normalize(raw, ("股息率", "dividend_yield", "股息率率"))
        if out:
            return out
    # 情况2：dict 当前值
    if isinstance(raw, dict):
        dy = _safe_float(_pick(raw, "股息率", "dividend_yield", "股息率率"))
        if dy is not None:
            return [(datetime.now().strftime("%Y-%m-%d"), dy)]
    return []


# 中债 10Y 历史（分段拉取，复用 market_service 已验证的写法，独立缓存）
_CHINA10Y: dict = {"data": None, "ts": 0, "loading": False, "lock": threading.Lock()}
_CHINA10Y_TTL = 6 * 3600


def _china_10y_history() -> dict[str, float]:
    now = time.time()
    with _CHINA10Y["lock"]:
        if _CHINA10Y["data"] is not None and (now - _CHINA10Y["ts"]) < _CHINA10Y_TTL:
            return _CHINA10Y["data"]
        if _CHINA10Y["loading"]:
            return _CHINA10Y["data"] or {}
        _CHINA10Y["loading"] = True

    def _bg():
        try:
            end = datetime.now()
            start = end.replace(year=end.year - 10)
            result: dict[str, float] = {}
            cur = start
            attempts = 0
            while cur < end and attempts < 11:
                attempts += 1
                nxt = min(cur.replace(year=cur.year + 1), end)
                df = _gw(
                    "bond_china_yield",
                    {"start_date": cur.strftime("%Y%m%d"), "end_date": nxt.strftime("%Y%m%d")},
                    retries=1, timeout=25,
                )
                if df and isinstance(df, list):
                    for row in df:
                        d = str(_pick(row, "日期", "date") or "")[:10]
                        v = _safe_float(_pick(row, *("10年", "10y", "收益率")))
                        if d and v is not None:
                            result[d] = v
                cur = nxt
            if result:
                with _CHINA10Y["lock"]:
                    _CHINA10Y["data"] = result
                    _CHINA10Y["ts"] = time.time()
                    _CHINA10Y["loading"] = False
                return
        except Exception as e:  # noqa: BLE001
            print(f"[China10Y] 后台刷新异常: {e}")
        with _CHINA10Y["lock"]:
            _CHINA10Y["loading"] = False

    threading.Thread(target=_bg, daemon=True).start()
    return _CHINA10Y["data"] or {}


def _us_10y_history() -> dict[str, float]:
    """美债 10Y 历史（单次调用，失败时返回空）。"""
    df = _gw("bond_zh_us_rate", {}, retries=2, timeout=35)
    result: dict[str, float] = {}
    if isinstance(df, list):
        for row in df:
            d = str(_pick(row, "日期", "date") or "")[:10]
            v = _safe_float(_pick(row, *_US10Y_KEYS))
            if d and v is not None:
                result[d] = v
    elif isinstance(df, dict):
        d = str(_pick(df, "日期", "date") or datetime.now().strftime("%Y-%m-%d"))[:10]
        v = _safe_float(_pick(df, *_US10Y_KEYS))
        if v is not None:
            result[d] = v
    return result


# ===========================================================================
# 计算（纯 Python）
# ===========================================================================
def _ma(series: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(series)
    if n <= 0:
        return out
    for i in range(n - 1, len(series)):
        window = series[i - n + 1 : i + 1]
        vals = [v for v in window if v is not None]
        if vals:
            out[i] = sum(vals) / len(vals)
    return out


def _bollinger(series: list[float], n: int, k: float = 2.0):
    mid: list[float | None] = [None] * len(series)
    upper: list[float | None] = [None] * len(series)
    lower: list[float | None] = [None] * len(series)
    for i in range(n - 1, len(series)):
        window = [v for v in series[i - n + 1 : i + 1] if v is not None]
        if len(window) < 2:
            continue
        m = sum(window) / len(window)
        var = sum((x - m) ** 2 for x in window) / (len(window) - 1)
        sd = math.sqrt(var)
        mid[i] = m
        upper[i] = m + k * sd
        lower[i] = m - k * sd
    return mid, upper, lower


def _rolling_annualized(points: list[tuple[str, float]], days: int, ppy: int = 252) -> list[float | None]:
    vals = [v for _, v in points]
    out: list[float | None] = [None] * len(points)
    for i in range(days, len(points)):
        p0 = vals[i - days]
        p1 = vals[i]
        if p0 and p0 > 0:
            out[i] = ((p1 / p0) ** (ppy / days) - 1) * 100
    return out


def _log_regression(points: list[tuple[str, float]], sigma: float = 1.5):
    """对数回归 + ±sigma 置信带（exp 回指数空间）。返回 (dates, actual, fitted, upper, lower)。"""
    dates = [d for d, _ in points]
    ys = [math.log(max(v, 1e-9)) for _, v in points]
    n = len(ys)
    if n < 3:
        return dates, [v for _, v in points], [None] * n, [None] * n, [None] * n
    xs = list(range(n))
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return dates, [v for _, v in points], [None] * n, [None] * n, [None] * n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    resid = [ys[i] - (intercept + slope * xs[i]) for i in range(n)]
    sd = math.sqrt(sum(r * r for r in resid) / (n - 2))
    actual = [v for _, v in points]
    fitted = [math.exp(intercept + slope * i) for i in range(n)]
    upper = [math.exp(intercept + slope * i + sigma * sd) for i in range(n)]
    lower = [math.exp(intercept + slope * i - sigma * sd) for i in range(n)]
    return dates, actual, fitted, upper, lower


def _normalize_base(points: list[tuple[str, float]], base: float = 100.0) -> list[float | None]:
    if not points:
        return []
    first = next((v for _, v in points if v is not None), None)
    if first in (None, 0):
        return [None] * len(points)
    return [v / first * base if v is not None else None for _, v in points]


def _return_diff(
    a: list[tuple[str, float]], b: list[tuple[str, float]], n: int = 40
) -> tuple[list[str], list[float | None]]:
    """a 相对 b 的 n 日收益差 = (a 的 n 日收益) - (b 的 n 日收益)，按共同日期对齐。"""
    map_a = {d: v for d, v in a}
    map_b = {d: v for d, v in b}
    dates = sorted(set(map_a) & set(map_b))
    out: list[float | None] = []
    for d in dates:
        ia = map_a[d]
        ib = map_b[d]
        # 找 n 个交易日前的日期
        idx = dates.index(d)
        if idx < n:
            out.append(None)
            continue
        pa = ia
        pb = ib
        pda = map_a.get(dates[idx - n])
        pdb = map_b.get(dates[idx - n])
        if pa and pda and pb and pdb and pda > 0 and pdb > 0:
            out.append((pa / pda - 1) - (pb / pdb - 1))
        else:
            out.append(None)
    return dates, out


def _ma_of_series(values: list[float | None], n: int) -> list[float | None]:
    return _ma([v if v is not None else 0.0 for v in values], n) if values else []


def _align_to_dates(src: list[tuple[str, float]], dates: list[str]) -> list[float | None]:
    m = {d: v for d, v in src}
    return [m.get(d) for d in dates]


# ===========================================================================
# 各图表 builder
# ===========================================================================
def _empty(title: str, note: str) -> dict:
    return {
        "title": title,
        "description": "",
        "layout": "single",
        "primary": {"dates": [], "series": []},
        "meta": _build_meta(False, note, gateway_empty=True),
    }


def _b_five_year_anchor() -> dict:
    title = "Wind全A五年之锚"
    desc = "以中证全指（万得全A 代理）价格对比其 5 年(1260 交易日)均线；价格高于均线+15% 时可暂停定投，大幅偏离时考虑动态再平衡。"
    rows = _index_zh_a(CODES["zz_quan_zhi"], "20180101")
    pts = _normalize(rows, _CLOSE_KEYS)
    if len(pts) < 60:
        return _empty(title, "中证全指历史不足，取数失败")
    dates = [d for d, _ in pts]
    vals = [v for _, v in pts]
    ma5 = _ma(vals, 1260)
    upper = [v * 1.15 if v is not None else None for v in ma5]
    meta = _build_meta(True)
    return {
        "title": title, "description": desc, "layout": "single",
        "primary": {
            "dates": dates,
            "series": [
                {"name": "中证全指", "data": vals},
                {"name": "5年均线", "data": ma5},
                {"name": "均线+15%", "data": upper},
            ],
        },
        "meta": meta,
    }


def _b_equity_bond_gap() -> dict:
    title = "中美视角下的A股股债性价比"
    desc = "股票相对债券性价比 = 1/沪深300PE_TTM − 10Y国债收益率。分别用中债(内资视角)与美债(美元资金视角)计算两条曲线；数值越高股票越具吸引力。"
    pe = _index_pe("沪深300")
    if not pe:
        return _empty(title, "沪深300 PE 取数失败")
    china = _china_10y_history()
    us = _us_10y_history()
    pe_map = {d: v for d, v in pe}
    dates = sorted(pe_map)
    china_gap, us_gap = [], []
    for d in dates:
        pe_v = pe_map[d]
        if not pe_v or pe_v <= 0:
            china_gap.append(None); us_gap.append(None); continue
        ey = 1.0 / pe_v * 100
        c = china.get(d) or _nearest(china, d)
        u = us.get(d) or _nearest(us, d)
        china_gap.append(round(ey - c, 2) if c is not None else None)
        us_gap.append(round(ey - u, 2) if u is not None else None)
    meta = _build_meta(bool(china and us))
    note = "" if (china and us) else "（中债/美债一端缺失，仅显示可得曲线）"
    meta["note"] = note or None
    return {
        "title": title, "description": desc, "layout": "single",
        "primary": {
            "dates": dates,
            "series": [
                {"name": "股债性价比(中债视角)", "data": china_gap},
                {"name": "股债性价比(美债视角)", "data": us_gap},
            ],
        },
        "meta": meta,
    }


def _b_jiucaier() -> dict:
    title = "韭圈儿神奇指标"
    desc = "用偏债混合型基金(易方达稳健收益B 代理万得偏债混合基金指数)对比沪深300全收益(沪深300代理)，观察股债相对强弱的顶/底线索（理论依据弱，仅供参考）。"
    bond = _fund_nav(FUND_PIANZHAI_HUNHE, "20180101")
    hs = _index_csindex(CODES["hs300"], "20180101")
    bpts = _normalize(bond, _NAV_KEYS)
    hpts = _normalize(hs, _CLOSE_KEYS)
    if not bpts or not hpts:
        return _empty(title, "偏债混合基金或沪深300 取数失败")
    bnorm = _normalize_base(bpts)
    hnorm = _normalize_base(hpts)
    dates = sorted(set(d for d, _ in bpts) & set(d for d, _ in hpts))
    b = _align_to_dates([(d, bnorm[i]) for i, d in enumerate(d for d, _ in bpts)], dates)
    h = _align_to_dates([(d, hnorm[i]) for i, d in enumerate(d for d, _ in hpts)], dates)
    meta = _build_meta(True)
    return {
        "title": title, "description": desc, "layout": "single",
        "primary": {
            "dates": dates,
            "series": [
                {"name": "偏债混合基金(归一)", "data": b},
                {"name": "沪深300(归一)", "data": h},
            ],
        },
        "meta": meta,
    }


def _b_equity_fund_3y_roll() -> dict:
    title = "偏股基金3年滚动年化收益"
    desc = "中证偏股基金指数(930950) 3 年滚动年化收益；历史经验 +30% 提示泡沫、-10% 提示底部。"
    rows = _index_csindex(CODES["zz_pian_gu"], "20150101")
    pts = _normalize(rows, _CLOSE_KEYS)
    if len(pts) < 756:
        return _empty(title, "偏股基金指数历史不足（需≥3年）")
    dates = [d for d, _ in pts]
    roll = _rolling_annualized(pts, 756)
    meta = _build_meta(True)
    return {
        "title": title, "description": desc, "layout": "single",
        "primary": {
            "dates": dates,
            "series": [{"name": "3年滚动年化%", "data": roll}],
            "thresholds": [
                {"yAxis": 30, "label": "+30% 泡沫", "color": "rgba(220,38,38,0.6)"},
                {"yAxis": -10, "label": "-10% 底部", "color": "rgba(59,130,246,0.6)"},
            ],
        },
        "meta": meta,
    }


def _b_equity_vs_tier1() -> dict:
    title = "偏股基金与一级债基顶部共振"
    desc = "中证偏股基金指数(930950) 对比一级债基(易方达增强回报A 代理)，自 2007-12-31 归一；用债券累计收益代表偏股基金顶部参考。"
    eq = _index_csindex(CODES["zz_pian_gu"], "20070101")
    bd = _fund_nav(FUND_TIER1_BOND, "20070101")
    epts = _normalize(eq, _CLOSE_KEYS)
    bpts = _normalize(bd, _NAV_KEYS)
    if not epts or not bpts:
        return _empty(title, "偏股基金或一级债基 取数失败")
    en = _normalize_base(epts)
    bn = _normalize_base(bpts)
    dates = sorted(set(d for d, _ in epts) & set(d for d, _ in bpts))
    e = _align_to_dates([(d, en[i]) for i, d in enumerate(d for d, _ in epts)], dates)
    b = _align_to_dates([(d, bn[i]) for i, d in enumerate(d for d, _ in bpts)], dates)
    meta = _build_meta(True)
    return {
        "title": title, "description": desc, "layout": "single",
        "primary": {
            "dates": dates,
            "series": [
                {"name": "偏股基金指数(归一)", "data": e},
                {"name": "一级债基(归一, 顶部参考)", "data": b},
            ],
        },
        "meta": meta,
    }


def _b_rotation_prism(value_code: str, growth_code: str, title: str, desc: str) -> dict:
    """规模/风格轮动三棱镜通用实现。

    比值 = 价值指数 / 成长指数；信号三条件（凑齐 2 个即关注轮动）：
      1) 比值上穿/下穿 252 日布林带；
      2) 比值跌破 5 年(1260)均线；
      3) 40 日收益差(成长−价值)的 252 日均线上下穿 0。
    """
    vrows = _index_csindex(value_code, "20150101")
    grows = _index_csindex(growth_code, "20150101")
    vpts = _normalize(vrows, _CLOSE_KEYS)
    gpts = _normalize(grows, _CLOSE_KEYS)
    if not vpts or not gpts:
        return _empty(title, "价值/成长指数 取数失败")
    vmap = {d: v for d, v in vpts}
    gmap = {d: v for d, v in gpts}
    dates = sorted(set(vmap) & set(gmap))
    if len(dates) < 1260:
        return _empty(title, "价值/成长指数历史不足（需≥5年）")
    vv = [vmap[d] for d in dates]
    gg = [gmap[d] for d in dates]
    ratio = [vv[i] / gg[i] if gg[i] else None for i in range(len(dates))]
    mid, up, low = _bollinger([r if r is not None else 0.0 for r in ratio], 252, 2.0)
    ma5 = _ma([r if r is not None else 0.0 for r in ratio], 1260)
    # 40 日收益差（成长−价值）
    g_ret = _rolling_window_return(gg, 40)
    v_ret = _rolling_window_return(vv, 40)
    diff = [g_ret[i] - v_ret[i] if g_ret[i] is not None and v_ret[i] is not None else None for i in range(len(dates))]
    diff_ma = _ma([d if d is not None else 0.0 for d in diff], 252)
    # 当前信号计数
    sig = _prism_signals(ratio, mid, up, low, ma5, diff, diff_ma, dates)
    meta = _build_meta(True, sig)
    return {
        "title": title, "description": desc, "layout": "prism",
        "primary": {
            "dates": dates,
            "series": [
                {"name": "比值(价值/成长)", "data": ratio},
                {"name": "252日布林上轨", "data": up},
                {"name": "252日布林下轨", "data": low},
                {"name": "5年均线", "data": ma5},
            ],
        },
        "secondary": {
            "dates": dates,
            "series": [
                {"name": "40日收益差(成长−价值)", "data": diff},
                {"name": "收益差252日均线", "data": diff_ma},
            ],
            "thresholds": [{"yAxis": 0, "label": "0轴", "color": "rgba(107,114,128,0.6)"}],
        },
        "meta": meta,
    }


def _b_dividend_yield() -> dict:
    title = "中证红利股息率追踪"
    desc = "中证红利历史股息率走势，叠加股息率与 10Y 中债的差值(股票风险溢价)。股息率数据取决于上游覆盖，缺失时该曲线为空。"
    dy = _index_dividend(CODES["zz_hongli"])
    china = _china_10y_history()
    if not dy:
        return _empty(title, "上游未提供中证红利历史股息率（接口未覆盖）")
    dates = [d for d, _ in dy]
    dyv = [v for _, v in dy]
    spread = []
    dy_map = {d: v for d, v in dy}
    for d in dates:
        c = china.get(d) or _nearest(china, d)
        spread.append(round(dy_map[d] - c, 2) if c is not None else None)
    meta = _build_meta(True)
    return {
        "title": title, "description": desc, "layout": "single",
        "primary": {
            "dates": dates,
            "series": [
                {"name": "中证红利股息率%", "data": dyv},
                {"name": "股息率−10Y中债(风险溢价%)", "data": spread},
            ],
        },
        "meta": meta,
    }


def _b_dividend_40d_diff() -> dict:
    title = "中证红利40日收益差跟踪"
    desc = "中证红利相对中证全指(万得全A代理)的 40 日收益差；过高时勿追高红利，回落至零轴附近再考虑。"
    h = _index_csindex(CODES["zz_hongli"], "20180101")
    a = _index_zh_a(CODES["zz_quan_zhi"], "20180101")
    hpts = _normalize(h, _CLOSE_KEYS)
    apts = _normalize(a, _CLOSE_KEYS)
    if not hpts or not apts:
        return _empty(title, "中证红利或中证全指 取数失败")
    dates, diff = _return_diff(hpts, apts, 40)
    if not dates:
        return _empty(title, "数据对齐失败")
    meta = _build_meta(True)
    return {
        "title": title, "description": desc, "layout": "single",
        "primary": {
            "dates": dates,
            "series": [{"name": "红利−全A 40日收益差", "data": diff}],
            "thresholds": [{"yAxis": 0, "label": "0轴", "color": "rgba(107,114,128,0.6)"}],
        },
        "meta": meta,
    }


def _b_dividend_regression() -> dict:
    title = "中证红利指数回归曲线"
    desc = "中证红利价格指数自 2016 年以来的对数回归曲线，叠加 ±1.5σ 置信带；下轨可作绝对收益视角买点参考。"
    rows = _index_csindex(CODES["zz_hongli"], "20160101")
    pts = _normalize(rows, _CLOSE_KEYS)
    if len(pts) < 60:
        return _empty(title, "中证红利历史不足")
    dates, actual, fitted, upper, lower = _log_regression(pts, 1.5)
    meta = _build_meta(True)
    return {
        "title": title, "description": desc, "layout": "single",
        "primary": {
            "dates": dates,
            "series": [
                {"name": "中证红利(实际)", "data": actual},
                {"name": "对数回归", "data": fitted},
                {"name": "+1.5σ", "data": upper},
                {"name": "−1.5σ", "data": lower},
            ],
        },
        "meta": meta,
    }


def _b_dividend_ah_40d_diff() -> dict:
    title = "红利A股港股40日收益差跟踪"
    desc = "中证红利相对中证港股通高股息(930914)的 40 日收益差；过高时多配港股高股息，过低时侧重中证红利。"
    h = _index_csindex(CODES["zz_hongli"], "20180101")
    hk = _hk_index(HK_HIGHDIV, "20180101")
    hpts = _normalize(h, _CLOSE_KEYS)
    hkpts = _normalize(hk, _CLOSE_KEYS)
    if not hpts or not hkpts:
        return _empty(title, "中证红利或港股通高股息 取数失败（可能代码未覆盖）")
    dates, diff = _return_diff(hpts, hkpts, 40)
    if not dates:
        return _empty(title, "数据对齐失败")
    meta = _build_meta(True)
    return {
        "title": title, "description": desc, "layout": "single",
        "primary": {
            "dates": dates,
            "series": [{"name": "红利−港股高股息 40日收益差", "data": diff}],
            "thresholds": [{"yAxis": 0, "label": "0轴", "color": "rgba(107,114,128,0.6)"}],
        },
        "meta": meta,
    }


# ===========================================================================
# 轮动三棱镜辅助
# ===========================================================================
def _rolling_window_return(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(n, len(values)):
        p0 = values[i - n]
        p1 = values[i]
        if p0 and p0 > 0:
            out[i] = p1 / p0 - 1
    return out


def _nearest(mapping: dict[str, float], date: str) -> float | None:
    if not mapping:
        return None
    if date in mapping:
        return mapping[date]
    keys = sorted(mapping)
    # 取不晚于 date 的最近一个
    cand = None
    for k in keys:
        if k <= date:
            cand = k
        else:
            break
    return mapping.get(cand) if cand else None


def _prism_signals(ratio, mid, up, low, ma5, diff, diff_ma, dates) -> str:
    """统计最近一日三条件命中数，返回可读提示。"""
    i = len(dates) - 1
    if i < 0:
        return ""
    hits = 0
    msgs = []
    r = ratio[i]
    # 条件2：比值 < 5年线
    if r is not None and ma5[i] is not None and r < ma5[i]:
        hits += 1
        msgs.append("比值低于5年线")
    # 条件1：比值贴近布林上下轨（近 1% 内）
    if r is not None and up[i] is not None and low[i] is not None:
        if r >= up[i] * 0.99 or r <= low[i] * 1.01:
            hits += 1
            msgs.append("比值触布林带")
    # 条件3：40日收益差252均线穿越0附近
    if diff[i] is not None and diff_ma[i] is not None:
        if (diff[i] - diff_ma[i]) * (diff[i]) < 0 or abs(diff_ma[i]) < 0.005:
            hits += 1
            msgs.append("收益差252均线近0轴")
    return f"当前命中 {hits}/3 个轮动信号" + ("：" + "、".join(msgs) if msgs else "")


# ===========================================================================
# 图表注册表 + 缓存调度
# ===========================================================================
CHARTS: list[dict] = [
    {"id": "five_year_anchor", "builder": _b_five_year_anchor, "title": "Wind全A五年之锚",
     "desc": "中证全指(万得全A代理) vs 5年均线+15%"},
    {"id": "equity_bond_gap", "builder": _b_equity_bond_gap, "title": "中美股债性价比",
     "desc": "沪深300PE倒数 − 中债/美债10Y"},
    {"id": "jiucaier", "builder": _b_jiucaier, "title": "韭圈儿神奇指标",
     "desc": "偏债混合(代理) vs 沪深300"},
    {"id": "equity_fund_3y_roll", "builder": _b_equity_fund_3y_roll, "title": "偏股基金3年滚动年化",
     "desc": "930950 3年滚动年化 +30%/-10%"},
    {"id": "equity_vs_tier1", "builder": _b_equity_vs_tier1, "title": "偏股vs一级债基",
     "desc": "930950 vs 易方达增强回报(代理)"},
    {"id": "size_rotation", "builder": lambda: _b_rotation_prism(CODES["hs300_value"], CODES["hs300_growth"],
        "规模风格轮动三棱镜", "沪深300价值 vs 沪深300成长"),
     "title": "规模风格轮动三棱镜", "desc": "300价值 vs 300成长"},
    {"id": "growth_value100", "builder": lambda: _b_rotation_prism(CODES["gz_value100"], CODES["gz_growth100"],
        "成长100/价值100轮动三棱镜", "国证价值100 vs 国证成长100"),
     "title": "成长100/价值100三棱镜", "desc": "国证价值100 vs 国证成长100"},
    {"id": "dividend_yield", "builder": _b_dividend_yield, "title": "中证红利股息率",
     "desc": "股息率 + (股息率−10Y中债)"},
    {"id": "dividend_40d_diff", "builder": _b_dividend_40d_diff, "title": "中证红利40日收益差",
     "desc": "红利 vs 全A 40日差"},
    {"id": "dividend_regression", "builder": _b_dividend_regression, "title": "中证红利回归曲线",
     "desc": "对数回归 + 1.5σ 带"},
    {"id": "dividend_ah_40d_diff", "builder": _b_dividend_ah_40d_diff, "title": "红利A股港股40日差",
     "desc": "红利 vs 港股通高股息 40日差"},
]


_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 6 * 3600
_REFRESH_SEM = threading.Semaphore(2)  # 限制并发刷新，避免打满网关 2 个 worker


def _compute(chart: dict) -> dict:
    try:
        payload = chart["builder"]()
        payload["id"] = chart["id"]
        return payload
    except Exception as e:  # noqa: BLE001
        print(f"[MarketCharts] {chart['id']} 计算异常: {e}")
        return _empty(chart["title"], f"计算异常: {e}")


def _serve(entry: dict, now: float) -> dict:
    """返回带新鲜度标注的图表数据副本（不修改缓存本体）。"""
    data = entry.get("data") or _empty("", "无数据")
    last = entry.get("last_ok_ts")
    age_min = int((now - last) / 60) if last else None
    stale = last is not None and (now - last) > _CACHE_TTL
    meta = dict(data.get("meta") or {})
    meta["stale"] = bool(stale)
    meta["ageMinutes"] = age_min
    meta["lastOkTime"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last)) if last else None
    meta["breakerOpen"] = _BREAKER.open
    out = dict(data)
    out["meta"] = meta
    return out


def get_chart(chart_id: str, force: bool = False) -> dict | None:
    chart = next((c for c in CHARTS if c["id"] == chart_id), None)
    if not chart:
        return None
    now = time.time()
    with _CACHE_LOCK:
        entry = _CACHE.get(chart_id)
        if entry and not force and (now - entry["ts"]) < _CACHE_TTL:
            return _serve(entry, now)
        if entry and entry.get("loading"):
            return _serve(entry, now)  # 刷新中，返回已有（可能为空）
        # 熔断中且有历史好数据：直接回退旧数据(标 stale)，不再打网关
        if not _BREAKER.allow() and entry and entry.get("last_ok_ts"):
            return _serve(entry, now)
        # 触发后台刷新（携带旧 last_ok_ts，刷新失败也不丢历史新鲜度基准）
        _CACHE[chart_id] = {
            "data": (entry["data"] if entry else _empty(chart["title"], "刷新中")),
            "ts": entry["ts"] if entry else 0,
            "loading": True,
            "last_ok_ts": entry.get("last_ok_ts") if entry else None,
        }

    def _bg():
        try:
            with _REFRESH_SEM:
                data = _compute(chart)
            with _CACHE_LOCK:
                ok = bool((data.get("meta") or {}).get("updateTime"))
                _CACHE[chart_id] = {
                    "data": data,
                    "ts": time.time(),
                    "loading": False,
                    "last_ok_ts": time.time() if ok else (entry.get("last_ok_ts") if entry else None),
                }
        except Exception as e:  # noqa: BLE001
            print(f"[MarketCharts] {chart_id} 后台刷新异常: {e}")
            with _CACHE_LOCK:
                if chart_id in _CACHE:
                    _CACHE[chart_id]["loading"] = False

    threading.Thread(target=_bg, daemon=True).start()
    with _CACHE_LOCK:
        return _serve(_CACHE[chart_id], now)


def get_all_charts(force: bool = False) -> list[dict]:
    return [get_chart(c["id"], force=force) for c in CHARTS]


def list_charts() -> list[dict]:
    return [{"id": c["id"], "title": c["title"], "description": c["desc"]} for c in CHARTS]
