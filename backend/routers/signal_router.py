"""Signal router — 买卖点信号生成与策略监控订阅。

端点：
- GET  /strategies          策略目录（前端下拉 + 动态参数）
- POST /generate            {symbol, strategy_id, params?} → 买卖点信号
- GET  /tracked            当前用户订阅的 (标的物×策略) 列表
- POST /tracked            {symbol, name?, strategy_id, params?} → 新增监控
- DELETE /tracked/{id}     取消监控
- GET  /tracked/refresh    重算所有订阅组合的当前信号（系统持续跟踪表现）
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.deps import get_current_user
from models import ApiResponse
from services import signal_service

router = APIRouter(tags=["signals"])


class GenerateRequest(BaseModel):
    symbol: str
    strategy_id: str
    params: Optional[dict[str, Any]] = None


class TrackedCreate(BaseModel):
    symbol: str
    strategy_id: str
    name: Optional[str] = None
    params: Optional[dict[str, Any]] = None


@router.get("/strategies", response_model=ApiResponse[list[dict]])
def strategies() -> ApiResponse[list[dict]]:
    """策略目录。"""
    return ApiResponse(data=signal_service.get_catalog())


@router.post("/generate", response_model=ApiResponse[dict])
def generate(body: GenerateRequest, user_id: str = Depends(get_current_user)) -> ApiResponse[dict]:
    """对单个标的物按策略生成买卖点信号。"""
    try:
        data = signal_service.generate_signal(body.symbol, body.strategy_id, body.params)
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)
    return ApiResponse(data=data)


@router.get("/tracked", response_model=ApiResponse[list[dict]])
def list_tracked(user_id: str = Depends(get_current_user)) -> ApiResponse[list[dict]]:
    """当前用户订阅的 (标的物×策略) 组合。"""
    return ApiResponse(data=signal_service.get_tracked(user_id))


@router.post("/tracked", response_model=ApiResponse[dict])
def add_tracked(body: TrackedCreate, user_id: str = Depends(get_current_user)) -> ApiResponse[dict]:
    """新增一个监控组合。同一标的物可叠加多个不同策略。"""
    try:
        data = signal_service.add_tracked(user_id, body.symbol, body.name, body.strategy_id, body.params or {})
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)
    return ApiResponse(data=data)


@router.delete("/tracked/{rec_id}", response_model=ApiResponse[dict])
def remove_tracked(rec_id: str, user_id: str = Depends(get_current_user)) -> ApiResponse[dict]:
    """取消监控。"""
    signal_service.remove_tracked(user_id, rec_id)
    return ApiResponse(data={"ok": True})


@router.get("/tracked/refresh", response_model=ApiResponse[list[dict]])
def refresh_tracked(user_id: str = Depends(get_current_user)) -> ApiResponse[list[dict]]:
    """重算所有订阅组合的当前信号。"""
    return ApiResponse(data=signal_service.compute_tracked_signals(user_id))
