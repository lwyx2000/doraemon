"""Strategy router — endpoints for strategy CRUD and execution."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from models import ApiResponse, Strategy, StrategyCreate, StrategyUpdate
from services.strategy_service import (
    get_strategies,
    create_strategy,
    update_strategy,
    delete_strategy,
    execute_strategy,
)
from core.deps import get_current_user

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=ApiResponse[list[Strategy]])
async def list_strategies(user_id: str = Depends(get_current_user)):
    data = get_strategies(user_id)
    return ApiResponse(data=data)


@router.post("", response_model=ApiResponse[Strategy])
async def create_strategy_endpoint(body: StrategyCreate, user_id: str = Depends(get_current_user)):
    data = create_strategy(user_id, body.name, body.target_asset, [r.model_dump() for r in body.rules])
    return ApiResponse(data=data)


@router.put("/{strategy_id}", response_model=ApiResponse[Strategy])
async def update_strategy_endpoint(strategy_id: str, body: StrategyUpdate, user_id: str = Depends(get_current_user)):
    data = update_strategy(user_id, strategy_id, body.name, body.active)
    if data is None:
        return ApiResponse(code=404, message="Not found", data=None)
    return ApiResponse(data=data)


@router.delete("/{strategy_id}", response_model=ApiResponse[dict])
async def delete_strategy_endpoint(strategy_id: str, user_id: str = Depends(get_current_user)):
    deleted = delete_strategy(user_id, strategy_id)
    if not deleted:
        return ApiResponse(code=404, message="Not found", data=None)
    return ApiResponse(data={"deleted": True})


@router.post("/{strategy_id}/execute", response_model=ApiResponse[list[dict]])
async def execute_strategy_endpoint(strategy_id: str, date: str | None = Query(None), user_id: str = Depends(get_current_user)):
    data = execute_strategy(user_id, strategy_id, date)
    return ApiResponse(data=data)
