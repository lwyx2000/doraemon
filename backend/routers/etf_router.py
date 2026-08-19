"""ETF router — ETF list and arbitrage opportunity endpoints."""

from fastapi import APIRouter, Query

from models import ApiResponse, EtfFund
from services.etf_service import get_etf_arbitrage_opportunities, get_etfs

router = APIRouter(tags=["etfs"])


@router.get("/etfs", response_model=ApiResponse[list[EtfFund]])
def etfs(
    category: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
    min_premium: float | None = Query(default=None),
    feasibility: str | None = Query(default=None),
) -> ApiResponse[list[EtfFund]]:
    """Return ETFs with arbitrage analysis."""
    data = get_etfs(
        category=category,
        strategy=strategy,
        min_premium=min_premium,
        feasibility=feasibility,
    )
    return ApiResponse(data=data)


@router.get("/etfs/arbitrage", response_model=ApiResponse[list[EtfFund]])
def etf_arbitrage() -> ApiResponse[list[EtfFund]]:
    """Return ETF arbitrage opportunities."""
    data = get_etf_arbitrage_opportunities()
    return ApiResponse(data=data)
