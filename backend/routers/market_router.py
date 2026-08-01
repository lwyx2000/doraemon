"""Market router — macro, indices, and K-line endpoints."""

from fastapi import APIRouter, Query

from models import ApiResponse, IndexValuation, KlineItem, MacroData
from services.market_service import (
    get_index_history,
    get_indices,
    get_kline,
    get_macro_data,
)

router = APIRouter(tags=["market"])


@router.get("/macro", response_model=ApiResponse[MacroData])
async def macro() -> ApiResponse[MacroData]:
    """Return macro indicator data."""
    data = get_macro_data()
    return ApiResponse(data=data)


@router.get("/indices", response_model=ApiResponse[list[IndexValuation]])
async def indices(
    category: str | None = Query(default=None),
    date: str | None = Query(default=None),
) -> ApiResponse[list[IndexValuation]]:
    """Return index valuations, optionally filtered by category."""
    data = get_indices(category=category, date=date)
    return ApiResponse(data=data)


@router.get("/indices/{code}/history", response_model=ApiResponse[list[dict]])
async def index_history(
    code: str,
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
) -> ApiResponse[list[dict]]:
    """Return mock K-line history for an index."""
    data = get_index_history(code=code, start_date=start_date, end_date=end_date)
    return ApiResponse(data=data)


@router.get("/quote/kline", response_model=ApiResponse[list[KlineItem]])
async def kline(
    code: str = Query(...),
    type: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
) -> ApiResponse[list[KlineItem]]:
    """Return mock K-line data for a quote code."""
    data = get_kline(
        code=code, type=type, start_date=start_date, end_date=end_date
    )
    return ApiResponse(data=data)
