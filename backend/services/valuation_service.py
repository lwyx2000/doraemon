"""Valuation service — 股债利差估值分位 + 拥挤度计算。

基于「韭菜投资学」估值体系：
1. 股债利差 = ROE均值/PB − 10Y国债收益率 + 0.3×CPI同比
   估值分位 = 该利差在历史中的百分位（越小=越便宜）
2. 拥挤度 = (指数PB / 基准PB) 在历史中的百分位（衡量行业/指数间相对估值）

数据源：
- akshare.stock_index_pb_lg  → 宽基指数 PB 历史（月度，2005年起）
- akshare.stock_index_pe_lg  → 宽基指数 PE 历史（月度，2005年起）
- market_service._fetch_10y_history → 10年期国债收益率历史
- akshare.macro_china_cpi → CPI 同比

缓存策略：
- PB/PE 历史数据按指数缓存 12 小时（月度数据日内不变）
- 估值结果缓存 1 小时
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Any

from core.config import USE_MOCK_DATA

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
# 数据获取层
# ============================================================

def _get_pb_history(index_name: str) -> list[dict]:
    """获取指数 PB 月度历史数据。

    Returns:
        [{"date": "2005-04-29", "pb": 1.89, "index_value": 932.40}, ...]
    """
    now = time.time()
    cached = _pb_cache.get(index_name)
    if cached and (now - cached["ts"]) < _CACHE_TTL_DATA:
        return cached["data"]

    try:
        import akshare as ak
        df = ak.stock_index_pb_lg(symbol=index_name)
    except Exception as e:
        print(f"[Valuation] stock_index_pb_lg({index_name}) 失败: {e}")
        return []

    if df is None or len(df) == 0:
        return []

    result = []
    for _, row in df.iterrows():
        pb_val = row.get("市净率")
        result.append({
            "date": str(row.get("日期", "")),
            "pb": float(pb_val) if pb_val is not None else None,
            "index_value": float(row.get("指数", 0)) if row.get("指数") is not None else None,
        })

    result.sort(key=lambda x: x["date"])
    _pb_cache[index_name] = {"data": result, "ts": now}
    return result


def _get_pe_history(index_name: str) -> list[dict]:
    """获取指数 PE 月度历史数据。

    Returns:
        [{"date": "2005-04-29", "pe_ttm": 15.2, "pe_static": 14.8, ...}, ...]
    """
    now = time.time()
    cached = _pe_cache.get(index_name)
    if cached and (now - cached["ts"]) < _CACHE_TTL_DATA:
        return cached["data"]

    try:
        import akshare as ak
        df = ak.stock_index_pe_lg(symbol=index_name)
    except Exception as e:
        print(f"[Valuation] stock_index_pe_lg({index_name}) 失败: {e}")
        return []

    if df is None or len(df) == 0:
        return []

    result = []
    for _, row in df.iterrows():
        pe_ttm = row.get("滚动市盈率")
        result.append({
            "date": str(row.get("日期", "")),
            "pe_ttm": float(pe_ttm) if pe_ttm is not None else None,
            "pe_static": float(row.get("静态市盈率", 0)) if row.get("静态市盈率") is not None else None,
            "index_value": float(row.get("指数", 0)) if row.get("指数") is not None else None,
        })

    result.sort(key=lambda x: x["date"])
    _pe_cache[index_name] = {"data": result, "ts": now}
    return result


def _get_cpi_yoy() -> float | None:
    """获取最新 CPI 同比（%）。"""
    now = time.time()
    cached = _cpi_cache.get("data")
    if cached and (now - _cpi_cache.get("ts", 0)) < _CACHE_TTL_DATA:
        return cached

    try:
        import akshare as ak
        df = ak.macro_china_cpi()
    except Exception as e:
        print(f"[Valuation] macro_china_cpi 失败: {e}")
        return None

    if df is None or len(df) == 0:
        return None

    # 最新月份的全国同比
    latest = df.iloc[0]  # 数据按时间倒序排列
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

    # 获取 CPI 和国债收益率
    cpi_yoy = _get_cpi_yoy()
    if cpi_yoy is None:
        cpi_yoy = 0.0  # CPI 取不到时用 0 近似
    yield_10y = _get_10y_treasury_yield()

    # 获取基准指数 PB 历史
    benchmark_pb = _get_pb_history(BENCHMARK_INDEX)
    if not benchmark_pb:
        return [], _build_meta(False, "基准指数PB获取失败")

    benchmark_pb_map: dict[str, float] = {item["date"]: item["pb"] for item in benchmark_pb if item.get("pb")}

    results: list[dict] = []

    for idx_info in BROAD_INDEX_LIST:
        idx_name = idx_info["name"]
        idx_code = idx_info["code"]

        # 获取 PB 和 PE 历史
        pb_data = _get_pb_history(idx_name)
        pe_data = _get_pe_history(idx_name)

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
            "is_benchmark": idx_name == BENCHMARK_INDEX,
        })

    # 按估值分位升序排列（最便宜的在前）
    results.sort(key=lambda x: x.get("valuation_percentile") or 50)

    with _cache_lock:
        _result_cache["broad"] = {"data": results, "ts": now}

    return results, _build_meta(False, "AkShare (stock_index_pb_lg + 国债 + CPI)")


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
