"""Fund router — fund list and closed-end fund analysis endpoints."""

from fastapi import APIRouter, Query

from models import ApiResponse, ClosedFundAnalysis, FundItem
from services.fund_service import get_closed_fund_analysis, get_funds

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
