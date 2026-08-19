"""REITs router — list endpoint with analysis filters."""

from fastapi import APIRouter, Query

from models import ApiResponse, ReitItem
from services.reits_service import get_reits

router = APIRouter(tags=["reits"])


@router.get("/reits", response_model=ApiResponse[list[ReitItem]])
def list_reits(
    asset_type: str | None = Query(
        None, description="Asset type, e.g. 产业园, 仓储物流, 水务, 高速公路"
    ),
    min_dividend: float | None = Query(None, description="Minimum dividend rate"),
    nav_level: str | None = Query(
        None, description="NAV premium level: discount, fair, premium"
    ),
    sustainability: str | None = Query(
        None, description="Dividend sustainability: sustainable, watch, at_risk"
    ),
):
    data = get_reits(
        asset_type=asset_type,
        min_dividend=min_dividend,
        nav_level=nav_level,
        sustainability=sustainability,
    )
    return ApiResponse(data=data)
