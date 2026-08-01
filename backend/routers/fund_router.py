"""Fund router — fund list and closed-end fund analysis endpoints."""

from fastapi import APIRouter, Query

from models import ApiResponse, ClosedFundAnalysis, FundItem
from services.fund_service import get_closed_fund_analysis, get_funds

router = APIRouter(tags=["funds"])


@router.get("/funds", response_model=ApiResponse[list[FundItem]])
async def funds(
    type: str | None = Query(default=None),
    min_premium: float | None = Query(default=None),
    feasibility: str | None = Query(default=None),
    date: str | None = Query(default=None),
) -> ApiResponse[list[FundItem]]:
    """Return funds with arbitrage analysis."""
    data = get_funds(
        fund_type=type,
        min_premium=min_premium,
        feasibility=feasibility,
        date=date,
    )
    return ApiResponse(data=data)


@router.get("/funds/closed/analysis", response_model=ApiResponse[list[ClosedFundAnalysis]])
async def closed_fund_analysis() -> ApiResponse[list[ClosedFundAnalysis]]:
    """Return closed-end fund analysis sorted by score."""
    data = get_closed_fund_analysis()
    return ApiResponse(data=data)
