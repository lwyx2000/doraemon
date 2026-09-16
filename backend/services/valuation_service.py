"""Valuation service — 股债利差估值分位 + 拥挤度计算。

基于「韭菜投资学」估值体系：
1. 股债利差 = ROE均值/PB − 10Y国债收益率 + 0.3×CPI同比
   估值分位 = 该利差在历史中的百分位（越小=越便宜）
2. 拥挤度 = (指数PB / 基准PB) 在历史中的百分位（衡量行业/指数间相对估值）

数据源（全部走远程 AkShare WebAPI 网关，不依赖本地 akshare）：
- services.index_pb_pe（B：自建聚合源）→ 按成分股市值/市净率/市盈率聚合还原指数 PB/PE 月度历史
  （网关方法 index_stock_cons_csindex + stock_zh_valuation_baidu，替代已失效的 legulegu）
- market_service._fetch_10y_history → 10年期国债收益率历史
- 网关 /api/ak?method=macro_china_cpi → CPI 同比

缓存策略：
- PB/PE 历史数据按指数缓存 12 小时（月度数据日内不变）
- 估值结果缓存 1 小时
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from core.config import USE_MOCK_DATA
from services.akshare_client import akshare_request
from services.index_pb_pe import get_index_pb_pe

# ============================================================
# 配置
# ============================================================

# 支持的宽基指数列表（乐咕乐股接口支持的全部）
BROAD_INDEX_LIST: list[dict] = [
    {"name": "上证50",   "code": "000016"},
    {"name": "沪深300",  "code": "000300"},
    {"name": "上证380",  "code": "000009"},
    {"name": "创业板50", "code": "399673"},
    {"name": "中证500",  "code": "000905"},
    {"name": "上证180",  "code": "000010"},
    {"name": "深证红利", "code": "399324"},
    {"name": "深证100",  "code": "399330"},
    {"name": "中证1000", "code": "000852"},
    {"name": "上证红利", "code": "000015"},
    {"name": "中证100",  "code": "000903"},
    {"name": "中证800",  "code": "000906"},
]

# 基准指数：用中证800（沪深300+中证500）替代万得全A
BENCHMARK_INDEX = "中证800"
BENCHMARK_CODE = "000906"  # 中证800 的 csindex 代码
# 基准指数回退顺序：网关偶发抖动导致某指数 PB 取数失败时，依次尝试其它基准，
# 避免单次网关失败就让整个估值返回空。
BENCHMARK_FALLBACKS = ["沪深300", "上证50", "中证500"]
BENCHMARK_FALLBACK_CODES = ["000300", "000016", "000905"]

# ROE 均值计算窗口（近5-7年，取5年=60个月）
ROE_WINDOW_MONTHS = 60

# 拥挤度历史起点（文档推荐2010年6月，但乐咕数据从2005年起，统一用2005年）
CROWDING_START_DATE = "2005-01-01"

# 通胀调整系数
CPI_ADJUST_FACTOR = 0.3

# ============================================================
# 缓存
# ============================================================

_pb_cache: dict[str, Any] = {}  # key: index_name → {data, ts}
_pe_cache: dict[str, Any] = {}  # key: index_name → {data, ts}
_cpi_cache: dict[str, Any] = {}  # {data, ts}
_result_cache: dict[str, Any] = {}  # key: "broad" → {data, ts}
_CACHE_TTL_DATA = 12 * 3600  # 月度数据缓存12小时
_CACHE_TTL_RESULT = 3600     # 结果缓存1小时
_cache_lock = threading.Lock()

# ============================================================
# 数据源存活探测（避免上游 legulegu 接口挂掉时逐个指数重试 → 120s+ 超时 → nginx 499 白屏）
# ============================================================
_SOURCE_DOWN: dict[str, float] = {"ts": 0.0}  # 记录上次判定为不可用的时刻；为 0 表示未判定
_SOURCE_DOWN_TTL = 300  # 判定不可用后 5 分钟内直接复用结论，不再重复探测


def _check_source_available() -> bool:
    """探测远程网关的指数 PB 接口是否可用。

    返回 True=可用；False=不可用。
    - 命中结论后 5 分钟内复用，避免每次请求都打网关。
    - 若网关整体 500（如 legulegu 改版/反爬），立即整体降级，而非逐个指数重试 120s+。
    - 单次探测 + 短超时：上游 legulegu 死时会一直挂到超时，故探测超时不宜过长（5s 足够判定）。
    """
    now = time.time()
    if _SOURCE_DOWN.get("ts", 0) > 0 and (now - _SOURCE_DOWN["ts"]) < _SOURCE_DOWN_TTL:
        return False
    probe = akshare_request("index_stock_cons_csindex", {"symbol": BENCHMARK_CODE}, retries=1, timeout=8)
    if probe:
        _SOURCE_DOWN["ts"] = 0.0
        return True
    _SOURCE_DOWN["ts"] = now
    return False


def _unavailable_meta(reason: str) -> dict:
    """数据源不可用时的统一 meta（前端据此展示友好横幅，而非白屏/499）。"""
    m = _build_meta(False, "远程网关(估值数据源暂不可用)")
    m["status"] = "unavailable"
    m["message"] = (
        "估值数据源（远程网关指数成分股/个股市净率聚合接口）暂不可用，通常为上游数据接口异常。"
        "功能已优雅降级，请稍后重试。"
    )
    return m


# ============================================================
# 数据获取层
# ============================================================

def _get_pb_history(index_code: str) -> list[dict]:
    """获取指数 PB 月度历史（B：网关侧自聚合源）。

    Returns:
        [{"date": "2005-04-29", "pb": 1.89, "index_value": 932.40}, ...]（按日期升序）
    """
    now = time.time()
    cached = _pb_cache.get(index_code)
    if cached and (now - cached["ts"]) < _CACHE_TTL_DATA:
        return cached["data"]

    pb_rows, _ = get_index_pb_pe(index_code)
    if not pb_rows:
        return []

    result = sorted(pb_rows, key=lambda x: x["date"])
    _pb_cache[index_code] = {"data": result, "ts": now}
    return result


def _get_pe_history(index_code: str) -> list[dict]:
    """获取指数 PE 月度历史（B：网关侧自聚合源）。

    Returns:
        [{"date": "2005-04-29", "pe_ttm": 15.2, "pe_static": 14.8, "index_value": 932.40}, ...]
    """
    now = time.time()
    cached = _pe_cache.get(index_code)
    if cached and (now - cached["ts"]) < _CACHE_TTL_DATA:
        return cached["data"]

    _, pe_rows = get_index_pb_pe(index_code)
    if not pe_rows:
        return []

    result = sorted(pe_rows, key=lambda x: x["date"])
    _pe_cache[index_code] = {"data": result, "ts": now}
    return result


def _get_cpi_yoy() -> float | None:
    """获取最新 CPI 同比（%）（走远程 AkShare WebAPI 网关）。"""
    now = time.time()
    cached = _cpi_cache.get("data")
    if cached is not None and (now - _cpi_cache.get("ts", 0)) < _CACHE_TTL_DATA:
        return cached

    rows = akshare_request("macro_china_cpi", retries=2, timeout=12)
    if not rows:
        return None

    # 网关返回按时间倒序，取首条的最新全国同比
    latest = rows[0]
    cpi_yoy = latest.get("全国-同比增长")
    result = float(cpi_yoy) if cpi_yoy is not None else None

    _cpi_cache["data"] = result
    _cpi_cache["ts"] = now
    return result


def _get_10y_treasury_yield() -> float | None:
    """获取最新 10 年期国债收益率（%）。"""
    try:
        from services.market_service import _fetch_10y_history, _10Y_CACHE
        yld_map = _fetch_10y_history()
        if not yld_map:
            # 等待后台线程加载（最多等 30 秒）
            for _ in range(15):
                time.sleep(2)
                yld_map = _fetch_10y_history()
                if yld_map:
                    break
        if not yld_map:
            return None
        latest_date = max(yld_map.keys())
        return yld_map[latest_date]
    except Exception as e:
        print(f"[Valuation] 获取10Y国债失败: {e}")
        return None

def _get_10y_treasury_yield_by_date(date_str: str) -> float | None:
    """获取指定日期最近的 10 年期国债收益率（%）。

    Args:
        date_str: 'YYYY-MM-DD' 格式
    """
    try:
        from services.market_service import _fetch_10y_history
        yld_map = _fetch_10y_history()
        if not yld_map:
            return None
        target = date_str[:10]
        candidates = [d for d in yld_map.keys() if d <= target]
        if not candidates:
            return None
        return yld_map[max(candidates)]
    except Exception:
        return None


# ============================================================
# 计算层
# ============================================================

def _compute_roe_history(pb_data: list[dict], pe_data: list[dict]) -> list[dict]:
    """从 PB 和 PE 历史反推 ROE 历史。

    ROE = PB / PE  (因为 PB = PE × ROE)

    Returns:
        [{"date": ..., "roe": 0.12, "pb": 1.5, "pe_ttm": 12.5}, ...]
    """
    # 以 PB 为主表，按日期关联 PE
    pe_map: dict[str, float] = {}
    for pe_item in pe_data:
        d = pe_item["date"]
        pe_val = pe_item.get("pe_ttm")
        if pe_val and pe_val > 0:
            pe_map[d] = pe_val

    result = []
    for pb_item in pb_data:
        d = pb_item["date"]
        pb_val = pb_item.get("pb")
        pe_val = pe_map.get(d)

        if pb_val and pe_val and pe_val > 0:
            roe = pb_val / pe_val
            result.append({
                "date": d,
                "roe": roe,
                "pb": pb_val,
                "pe_ttm": pe_val,
            })
        # PE 为负或缺失时跳过（无法计算 ROE）

    return result


def _compute_roe_mean(roe_data: list[dict], window_months: int = ROE_WINDOW_MONTHS) -> float | None:
    """计算近 N 个月的 ROE 均值。"""
    if not roe_data:
        return None
    # 取最近 window_months 条
    recent = roe_data[-window_months:]
    roe_values = [r["roe"] for r in recent if r.get("roe") is not None and r["roe"] > 0]
    if not roe_values:
        return None
    return sum(roe_values) / len(roe_values)


def _percentile(value: float, history: list[float]) -> float:
    """计算 value 在 history 序列中的百分位（0-100）。

    返回值 = 比历史上百分之多少的时候更大（即升序百分位）。
    """
    if not history:
        return 50.0
    below = sum(1 for v in history if v <= value)
    return round(below / len(history) * 100, 2)


def _compute_spread_history(
    roe_data: list[dict],
    benchmark_name: str,
    cpi_yoy: float,
) -> list[dict]:
    """计算股债利差历史序列。

    利差 = ROE均值/PB − 国债收益率 + 0.3×CPI

    注意：ROE均值用整个历史的滚动均值（取近5年均值，不够5年用全部），
    CPI 用最新值（历史 CPI 月度数据获取较慢，用最新值做近似）。

    Returns:
        [{"date": ..., "spread": 0.045, "pb": 1.5, "yield_10y": 2.8, "roe_mean": 0.12}, ...]
    """
    if not roe_data:
        return []

    # 预先触发国债收益率加载（避免逐日查询时每次都等待）
    _get_10y_treasury_yield()

    # 预计算每个时点的滚动 ROE 均值（近5年）
    roe_values = [r["roe"] for r in roe_data if r.get("roe") is not None and r["roe"] > 0]

    result = []
    for i, item in enumerate(roe_data):
        d = item["date"]
        pb_val = item.get("pb")
        if not pb_val or pb_val <= 0:
            continue

        # 滚动 ROE 均值：取当前及之前 ROE_WINDOW_MONTHS 个值
        window_start = max(0, i - ROE_WINDOW_MONTHS + 1)
        window_roes = [roe_values[j] for j in range(window_start, min(i + 1, len(roe_values)))]
        if not window_roes:
            continue
        roe_mean = sum(window_roes) / len(window_roes)

        # 收益率 = ROE均值 / PB
        earnings_yield = roe_mean / pb_val

        # 国债收益率
        yld_10y = _get_10y_treasury_yield_by_date(d)
        if yld_10y is None:
            continue

        # 股债利差（单位：%）
        spread = earnings_yield * 100 - yld_10y + CPI_ADJUST_FACTOR * cpi_yoy

        result.append({
            "date": d,
            "spread": round(spread, 4),
            "pb": round(pb_val, 4),
            "yield_10y": yld_10y,
            "roe_mean": round(roe_mean, 4),
            "earnings_yield": round(earnings_yield * 100, 4),
        })

    return result


# ============================================================
# 主接口
# ============================================================

def get_broad_index_valuation() -> tuple[list[dict], dict]:
    """获取所有宽基指数的估值分位和拥挤度。

    Returns:
        (data, meta)
        data: [{"name", "code", "pb", "pe_ttm", "roe_mean", "spread", "valuation_percentile",
                 "crowding", "yield_10y", "cpi_yoy", "pb_history", "spread_history"}, ...]
        meta: {"isMock", "dataSource", "updateTime"}
    """
    if USE_MOCK_DATA:
        return [], {"isMock": True, "dataSource": "MOCK", "mockTime": None,
                     "updateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    now = time.time()
    with _cache_lock:
        cached = _result_cache.get("broad")
        if cached and (now - cached["ts"]) < _CACHE_TTL_RESULT:
            return cached["data"], _build_meta(False, "缓存(1h)")

    # 数据源存活探测：上游 legulegu 接口异常时整体快速降级，避免长时间挂起(499)
    if not _check_source_available():
        return [], _unavailable_meta("legulegu 指数 PE/PB 接口不可用")

    # 获取 CPI 和国债收益率
    cpi_yoy = _get_cpi_yoy()
    if cpi_yoy is None:
        cpi_yoy = 0.0  # CPI 取不到时用 0 近似
    yield_10y = _get_10y_treasury_yield()

    # 获取基准指数 PB 历史（带回退，避免单次网关抖动致整体返回空）
    benchmark_used = BENCHMARK_CODE
    benchmark_pb = _get_pb_history(BENCHMARK_CODE)
    if not benchmark_pb:
        for alt in BENCHMARK_FALLBACK_CODES:
            benchmark_pb = _get_pb_history(alt)
            if benchmark_pb:
                benchmark_used = alt
                break
    if not benchmark_pb:
        m = _build_meta(False, "基准指数PB获取失败(远程网关)")
        m["status"] = "unavailable"
        m["message"] = "基准指数 PB 获取失败，估值暂不可用，请稍后重试。"
        return [], m

    benchmark_pb_map: dict[str, float] = {item["date"]: item["pb"] for item in benchmark_pb if item.get("pb")}

    start_ts = time.time()
    _HARD_DEADLINE = 45  # 秒：任何情况下整体处理不得超过此值（防止上游偶发挂起拖垮接口）

    results: list[dict] = []

    for idx_info in BROAD_INDEX_LIST:
        if time.time() - start_ts > _HARD_DEADLINE:
            break
        idx_name = idx_info["name"]
        idx_code = idx_info["code"]

        # 获取 PB 和 PE 历史
        pb_data = _get_pb_history(idx_code)
        pe_data = _get_pe_history(idx_code)

        if not pb_data:
            continue

        # 当前 PB
        current_pb = pb_data[-1].get("pb") if pb_data else None
        current_pe = pe_data[-1].get("pe_ttm") if pe_data else None

        # ROE 历史
        roe_data = _compute_roe_history(pb_data, pe_data)
        roe_mean = _compute_roe_mean(roe_data)

        # 股债利差历史
        spread_history = _compute_spread_history(roe_data, idx_name, cpi_yoy)

        # 当前利差和估值分位
        current_spread = spread_history[-1]["spread"] if spread_history else None
        valuation_percentile = None
        if current_spread is not None and len(spread_history) > 1:
            # 估值分位 = 比历史上百分之多少的时候更贵 = 100 - 利差升序百分位
            spread_values = [s["spread"] for s in spread_history if s["spread"] is not None]
            spread_pct = _percentile(current_spread, spread_values)
            valuation_percentile = round(100 - spread_pct, 2)

        # 拥挤度 = (指数PB / 基准PB) 的历史分位
        crowding = None
        ratio_history: list[float] = []
        for pb_item in pb_data:
            d = pb_item["date"]
            pb_val = pb_item.get("pb")
            bench_pb = benchmark_pb_map.get(d)
            if pb_val and bench_pb and bench_pb > 0:
                ratio_history.append(pb_val / bench_pb)

        if ratio_history and current_pb:
            # 找当前 ratio
            current_bench_pb = benchmark_pb_map.get(pb_data[-1]["date"])
            if current_bench_pb and current_bench_pb > 0:
                current_ratio = current_pb / current_bench_pb
                crowding = _percentile(current_ratio, ratio_history)

        # PB 历史数据（精简，只返回最近120个月给前端画图）
        pb_history = pb_data[-120:] if len(pb_data) > 120 else pb_data

        # 利差历史（精简，最近120个月）
        spread_hist_short = spread_history[-120:] if len(spread_history) > 120 else spread_history

        results.append({
            "name": idx_name,
            "code": idx_code,
            "pb": round(current_pb, 4) if current_pb else None,
            "pe_ttm": round(current_pe, 2) if current_pe else None,
            "roe_mean": round(roe_mean * 100, 2) if roe_mean else None,  # 转为百分比
            "spread": round(current_spread, 2) if current_spread else None,
            "valuation_percentile": valuation_percentile,
            "crowding": crowding,
            "yield_10y": yield_10y,
            "cpi_yoy": cpi_yoy,
            "pb_history": pb_history,
            "spread_history": spread_hist_short,
            "is_benchmark": idx_name == benchmark_used,
        })

    if not results:
        # 探测通过但全部指数取数失败（如网关部分抖动/整体超时），统一降级为不可用
        return [], _unavailable_meta("估值计算超时或数据源异常")

    # 按估值分位升序排列（最便宜的在前）
    results.sort(key=lambda x: x.get("valuation_percentile") or 50)

    with _cache_lock:
        _result_cache["broad"] = {"data": results, "ts": now}

    return results, _build_meta(False, f"远程网关(基准={benchmark_used}, 成分股聚合PB/PE + 国债 + CPI)")


def get_single_index_valuation(index_name: str) -> tuple[dict | None, dict]:
    """获取单个指数的详细估值数据。

    Returns:
        (data, meta)
    """
    if USE_MOCK_DATA:
        return None, {"isMock": True, "dataSource": "MOCK", "mockTime": None,
                      "updateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # 先获取全部列表找到对应数据
    all_data, meta = get_broad_index_valuation()
    for item in all_data:
        if item["name"] == index_name or item["code"] == index_name:
            return item, meta
    return None, _build_meta(False, f"未找到指数: {index_name}")


def _build_meta(is_mock: bool, data_source: str) -> dict:
    """构建 meta 信息。"""
    return {
        "isMock": is_mock,
        "dataSource": data_source,
        "mockTime": None,
        "updateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_index_spread_history(index_name: str) -> tuple[list[dict], dict]:
    """获取单指数的股债利差历史完整序列（供前端估值带图表）。

    返回全量历史序列（不截断120月），前端按时间窗口自行截取。

    Returns:
        (data, meta) — data 为 [{date, spread, pb, yield_10y, roe_mean, earnings_yield}, ...]
    """
    if USE_MOCK_DATA:
        return [], {"isMock": True, "dataSource": "MOCK", "mockTime": None,
                     "updateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # 先获取全部列表，从中找到目标指数的利差历史（复用已有计算+缓存）
    all_data, meta = get_broad_index_valuation()
    target_code = None
    for item in all_data:
        if item["name"] == index_name or item["code"] == index_name:
            target_code = item["code"]
            # spread_history 是最近120月，这里返回全量需重新计算
            break
    if target_code is None:
        return [], _build_meta(False, f"未找到指数: {index_name}")

    # 重新获取该指数的全量利差历史（不受120月截断）
    cpi_yoy = _get_cpi_yoy()
    if cpi_yoy is None:
        cpi_yoy = 0.0

    pb_data = _get_pb_history(target_code)
    pe_data = _get_pe_history(target_code)
    if not pb_data:
        return [], _build_meta(False, "该指数无PB历史数据")

    roe_data = _compute_roe_history(pb_data, pe_data)
    spread_history = _compute_spread_history(roe_data, index_name, cpi_yoy)

    # 返回全量序列
    out = []
    for s in spread_history:
        out.append({
            "date": s["date"],
            "spread": s["spread"],
            "pb": s["pb"],
            "yield_10y": s["yield_10y"],
            "roe_mean": s["roe_mean"],
            "earnings_yield": s["earnings_yield"],
        })

    return out, meta
