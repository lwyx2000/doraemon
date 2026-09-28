"""Valuation router — 股债利差估值分位 + 拥挤度端点。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from models import ApiResponse
from services.valuation_service import get_broad_index_valuation, get_index_spread_history, get_single_index_valuation, get_industry_valuation

router = APIRouter(tags=["valuation"])


@router.get("/broad-indices", response_model=ApiResponse[list[dict]])
def broad_index_valuation() -> ApiResponse[list[dict]]:
    """宽基指数估值分位 + 拥挤度一览。

    返回 12 个宽基指数的：
    - 当前 PB / PE(TTM) / ROE均值
    - 股债利差 = ROE均值/PB − 10Y国债 + 0.3×CPI
    - 估值分位（0-100，越小=越便宜）
    - 拥挤度（0-100，越小=相对越便宜）
    - PB历史（最近120月）和利差历史（最近120月）

    由于计算涉及多个 AkShare 接口，首次请求较慢（约30-60秒），结果缓存1小时。
    """
    data, meta = get_broad_index_valuation()
    return ApiResponse(data=data, meta=meta)


@router.get("/indices/{index_name}", response_model=ApiResponse[dict])
def single_index_valuation(
    index_name: str,
) -> ApiResponse[dict]:
    """单个指数的详细估值数据。

    Args:
        index_name: 指数名称（如 沪深300）或代码（如 000300）
    """
    data, meta = get_single_index_valuation(index_name)
    if data is None:
        return ApiResponse(code=404, message=f"未找到指数: {index_name}", data=None)
    return ApiResponse(data=data, meta=meta)


@router.get("/indices/{index_name}/spread-history", response_model=ApiResponse[list[dict]])
def index_spread_history(
    index_name: str,
) -> ApiResponse[list[dict]]:
    """单指数股债利差历史序列（全量，供前端估值带图表按时间窗口截取）。

    每个数据点包含：date, spread(股债利差%), pb, yield_10y(10Y国债%), roe_mean, earnings_yield。
    """
    data, meta = get_index_spread_history(index_name)
    return ApiResponse(data=data, meta=meta)


@router.get("/industries", response_model=ApiResponse[list[dict]])
def industry_valuation() -> ApiResponse[list[dict]]:
    """申万一级行业估值分位 + 拥挤度一览。

    行业 PE/PB 历史来自本地 DuckDB base_sw_sector_daily（由网关 sw_index_first_info
    每日累积，上游稳定可用），拥挤度分母用全A PB(000985)。历史样本不足时仍返回数据但
    meta.insufficientHistory=True，前端展示「累积中」提示。
    """
    data, meta = get_industry_valuation()
    return ApiResponse(data=data, meta=meta)
