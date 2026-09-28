"""Signal router — 买卖点信号生成与策略监控订阅。

端点：
- GET  /strategies          策略目录（前端下拉 + 动态参数）
- POST /generate            {symbol, strategy_id, params?} → 买卖点信号
- POST /tactical/batch      {symbols[]} → 批量战术信号快照（偏离度/RSI/布林）
- POST /winrate/scan        {symbols[], strategy_id, params?} → 历史胜率扫描 + 凯利仓位
- GET  /tracked            当前用户订阅的 (标的物×策略) 列表
- POST /tracked            {symbol, name?, strategy_id, params?} → 新增监控
- DELETE /tracked/{id}     取消监控
- GET  /tracked/refresh    重算所有订阅组合的当前信号（系统持续跟踪表现）
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from services import signal_service, winrate_service

from core.deps import get_current_user
from models import ApiResponse

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


class TacticalBatchRequest(BaseModel):
    symbols: list[str]


class WinrateScanRequest(BaseModel):
    symbols: list[str]
    strategy_id: str
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


@router.post("/tactical/batch", response_model=ApiResponse[list[dict]])
def tactical_batch(body: TacticalBatchRequest, user_id: str = Depends(get_current_user)) -> ApiResponse[list[dict]]:
    """批量战术信号快照（MA20偏离度 / RSI14 / 布林位置），当日缓存。"""
    if not body.symbols:
        return ApiResponse(code=400, message="symbols 不能为空", data=None)
    if len(body.symbols) > 200:
        return ApiResponse(code=400, message="单次最多计算 200 只标的", data=None)
    return ApiResponse(data=signal_service.tactical_batch(body.symbols))


@router.post("/winrate/scan", response_model=ApiResponse[dict])
def winrate_scan(body: WinrateScanRequest, user_id: str = Depends(get_current_user)) -> ApiResponse[dict]:
    """批量胜率扫描（次日收盘买入、持有N日收盘卖出、扣成本），当日缓存。"""
    if not body.symbols:
        return ApiResponse(code=400, message="symbols 不能为空", data=None)
    if len(body.symbols) > 200:
        return ApiResponse(code=400, message="单次最多扫描 200 只标的", data=None)
    if body.strategy_id not in {s["id"] for s in signal_service.STRATEGY_CATALOG}:
        return ApiResponse(code=400, message=f"未知策略 {body.strategy_id}", data=None)
    return ApiResponse(data=winrate_service.scan_winrate(body.symbols, body.strategy_id, body.params or {}))


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
