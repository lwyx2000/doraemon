"""交易台账路由 — 交割单导入 / 每日成交 / 已清仓 / 交易分析（全部需 JWT）。

事实源优先级：券商交割单 > 每日成交（biz_trades，作为补充且费用可能缺失）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from core.deps import get_current_user
from models import ApiResponse, DailyTradeImportRequest
from services.import_log_service import add_import_log
from services.trading_ledger_service import (
    clear_settlements,
    get_analysis,
    get_closed_rounds,
    get_daily_trades,
    import_daily,
    import_settlements,
    list_settlements,
)

router = APIRouter(prefix="/trading", tags=["trading"])

_ALLOWED_EXT = (".xlsx", ".xlsm", ".csv", ".txt")


@router.post("/import/settlement", response_model=ApiResponse[dict])
async def import_settlement_file(
    file: UploadFile = File(...),
    broker: str = Form(""),
    account: str = Form(""),
    mode: str = Form("merge"),
    user_id: str = Depends(get_current_user),
):
    """上传券商交割单（Excel/CSV）。mode=merge 按成交编号去重；mode=replace 先清空涉及交易日再导入。"""
    filename = file.filename or ""
    if not filename.lower().endswith(_ALLOWED_EXT):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xlsm / .csv / .txt 文件")
    if mode not in ("merge", "replace"):
        raise HTTPException(status_code=400, detail="mode 须为 merge 或 replace")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    try:
        result = import_settlements(user_id, content, filename, broker, account, mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    add_import_log(
        user_id, "settlements", "web", account, broker,
        {
            "added": result["inserted"], "updated": 0, "deleted": 0,
            "inserted": result["inserted"], "failed": result["failed"],
        },
        total=result["total"],
    )
    return ApiResponse(data=result)


@router.post("/import/daily", response_model=ApiResponse[dict])
def import_daily_trades(body: DailyTradeImportRequest, user_id: str = Depends(get_current_user)):
    """JWT 版每日成交导入：按 (用户, 交易日) 全量覆盖，与无鉴权 /trades/import 同一张表。"""
    d = (body.trade_date or "").strip()
    if len(d) != 10 or d[4:5] != "-" or d[7:8] != "-":
        raise HTTPException(status_code=400, detail="trade_date 必须为 YYYY-MM-DD")
    result = import_daily(user_id, d, [dict(it) for it in body.items], source=body.source or "web")
    add_import_log(user_id, "trades", body.source or "web", "", "", result, total=len(body.items))
    return ApiResponse(data=result)


@router.delete("/settlements", response_model=ApiResponse[dict])
def delete_settlements(
    trade_date: str = Query(..., description="YYYY-MM-DD，清空该交易日全部交割单记录"),
    user_id: str = Depends(get_current_user),
):
    """按交易日清空交割单，用于重新导入。"""
    if len(trade_date) != 10 or trade_date[4:5] != "-" or trade_date[7:8] != "-":
        raise HTTPException(status_code=400, detail="trade_date 必须为 YYYY-MM-DD")
    return ApiResponse(data=clear_settlements(user_id, trade_date))


@router.get("/settlements", response_model=ApiResponse[dict])
def settlements(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    code: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    limit: int = Query(5000, ge=1, le=50000),
    user_id: str = Depends(get_current_user),
):
    """交割单明细（含非交易资金流水），按成交日期倒序。"""
    return ApiResponse(data=list_settlements(user_id, date_from, date_to, code, direction, limit))


@router.get("/daily", response_model=ApiResponse[dict])
def daily_trades(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    code: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
):
    """每日成交：交割单成交行 + 每日成交补充行（去重后），附按日汇总。"""
    return ApiResponse(data=get_daily_trades(user_id, date_from, date_to, code))


@router.get("/closed", response_model=ApiResponse[dict])
def closed_rounds(user_id: str = Depends(get_current_user)):
    """已清仓回合（FIFO，含费用的真实已实现盈亏）+ 由流水重建的当前持仓。"""
    return ApiResponse(data=get_closed_rounds(user_id))


@router.get("/analysis", response_model=ApiResponse[dict])
def trading_analysis(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    user_id: str = Depends(get_current_user),
):
    """综合分析：做T / 已平仓胜率 / 费用摩擦 / 行为诊断 / 三方对账。"""
    return ApiResponse(data=get_analysis(user_id, date_from, date_to))
