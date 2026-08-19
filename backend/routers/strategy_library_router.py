"""Strategy library router — 经典实盘策略库 + 绩效监控。

端点（注册于 /api/v1/strategy-library）：
- GET  /library                     策略库目录（来源/实盘背景/参数 schema）
- POST /library/{id}/backtest       回测绩效 + 当前持仓建议
- GET  /tracked                     我的跟踪列表
- POST /tracked                     加入跟踪 {library_id, params?}
- DELETE /tracked/{rec_id}          取消跟踪
- GET  /tracked/refresh             重算全部跟踪策略表现（写当日快照）
- POST /symbol-backtest             单标的×技术策略 绩效（复用信号实验室引擎）
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.deps import get_current_user
from models import ApiResponse
from services import strategy_library_service as svc

router = APIRouter(tags=["strategy-library"])


class TrackedCreate(BaseModel):
    library_id: str
    params: Optional[dict[str, Any]] = None


class BacktestRequest(BaseModel):
    params: Optional[dict[str, Any]] = None


class SymbolBacktestRequest(BaseModel):
    symbol: str
    strategy_id: str
    params: Optional[dict[str, Any]] = None


@router.get("/library", response_model=ApiResponse[list[dict]])
def library() -> ApiResponse[list[dict]]:
    """策略库目录。"""
    return ApiResponse(data=svc.get_library())


@router.post("/library/{strategy_id}/backtest", response_model=ApiResponse[dict])
def backtest(strategy_id: str, body: BacktestRequest | None = None, user_id: str = Depends(get_current_user)) -> ApiResponse[dict]:
    """对策略库策略执行回测（轮动）或计算实时组合（双低转债）。"""
    params = (body.params if body else None) or {}
    try:
        data = svc.run_backtest(strategy_id, params)
    except ValueError as e:
        return ApiResponse(code=404, message=str(e), data=None)
    return ApiResponse(data=data)


@router.get("/tracked", response_model=ApiResponse[list[dict]])
def list_tracked(user_id: str = Depends(get_current_user)) -> ApiResponse[list[dict]]:
    return ApiResponse(data=svc.get_tracked(user_id))


@router.post("/tracked", response_model=ApiResponse[dict])
def add_tracked(body: TrackedCreate, user_id: str = Depends(get_current_user)) -> ApiResponse[dict]:
    try:
        data = svc.add_tracked(user_id, body.library_id, body.params)
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)
    return ApiResponse(data=data)


@router.delete("/tracked/{rec_id}", response_model=ApiResponse[dict])
def remove_tracked(rec_id: str, user_id: str = Depends(get_current_user)) -> ApiResponse[dict]:
    svc.remove_tracked(user_id, rec_id)
    return ApiResponse(data={"ok": True})


@router.get("/tracked/refresh", response_model=ApiResponse[list[dict]])
def refresh_tracked(user_id: str = Depends(get_current_user)) -> ApiResponse[list[dict]]:
    """重算全部跟踪策略最新表现并写入当日绩效快照。"""
    return ApiResponse(data=svc.refresh_tracked(user_id))


@router.post("/symbol-backtest", response_model=ApiResponse[dict])
def symbol_backtest(body: SymbolBacktestRequest, user_id: str = Depends(get_current_user)) -> ApiResponse[dict]:
    """单标的 × 技术策略（信号实验室 6 策略）的执行绩效。"""
    try:
        data = svc.backtest_symbol_signal(body.symbol, body.strategy_id, body.params)
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)
    if data.get("error"):
        return ApiResponse(code=400, message=data["error"], data=None)
    return ApiResponse(data=data)
