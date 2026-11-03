"""Fund router — fund list and closed-end fund analysis endpoints."""

from fastapi import APIRouter, Query

from models import ApiResponse, ClosedFundAnalysis, FundItem
from services.fund_service import get_closed_fund_analysis, get_funds
from services.fund_rotation_service import get_rotation_groups

router = APIRouter(tags=["funds"])


@router.get("/funds", response_model=ApiResponse[list[FundItem]])
def funds(
    type: str | None = Query(default=None),
    min_premium: float | None = Query(default=None),
    feasibility: str | None = Query(default=None),
    date: str | None = Query(default=None),
    force: bool = Query(default=False, description="True 穿透 30s 列表缓存，强制重扫上游"),
) -> ApiResponse[list[FundItem]]:
    """Return funds with arbitrage analysis."""
    data, meta = get_funds(
        fund_type=type,
        min_premium=min_premium,
        feasibility=feasibility,
        date=date,
        force=force,
    )
    return ApiResponse(data=data, meta=meta)


@router.get("/funds/closed/analysis", response_model=ApiResponse[list[ClosedFundAnalysis]])
def closed_fund_analysis() -> ApiResponse[list[ClosedFundAnalysis]]:
    """Return closed-end fund analysis sorted by score."""
    data, meta = get_closed_fund_analysis()
    return ApiResponse(data=data, meta=meta)


@router.get("/funds/rotation-groups", response_model=ApiResponse[list[dict]])
def rotation_groups(force: bool = Query(default=False, description="穿透 120s 缓存")) -> ApiResponse[list[dict]]:
    """同标的跨基金溢价轮动：按「扣成本后价差」降序，给出卖高买低的换仓候选。

    组内一律同口径比（自算 est_premium_pct 优先，覆盖不足时退官方 premium_pct），
    净值失效（stale）的成员剔除并在 warnings 点名——见 fund_rotation_service 注释。
    """
    data, meta = get_rotation_groups(force=force)
    return ApiResponse(data=data, meta=meta)

