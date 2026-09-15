"""Valuation router — 股债利差估值分位 + 拥挤度端点。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from models import ApiResponse
from services.valuation_service import get_broad_index_valuation, get_single_index_valuation

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
