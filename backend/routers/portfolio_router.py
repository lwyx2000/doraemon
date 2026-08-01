"""Portfolio router — portfolio list & add-item endpoints."""

from fastapi import APIRouter, Depends

from models import ApiResponse, Portfolio, PortfolioItemCreate
from services.portfolio_service import get_portfolios, add_portfolio_item
from core.deps import get_current_user

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


@router.get("", response_model=ApiResponse[list[Portfolio]])
async def list_portfolios(user_id: str = Depends(get_current_user)):
    data = get_portfolios(user_id)
    return ApiResponse(data=data)


@router.post("/{portfolio_id}/items", response_model=ApiResponse[dict])
async def add_portfolio_item_endpoint(
    portfolio_id: str,
    item: PortfolioItemCreate,
    user_id: str = Depends(get_current_user),
):
    data = add_portfolio_item(
        user_id=user_id,
        portfolio_id=portfolio_id,
        code=item.code,
        name=item.name,
        type=item.type,
        quantity=item.quantity,
        cost_price=item.cost_price,
    )
    return ApiResponse(data=data)
