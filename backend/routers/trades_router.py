"""成交数据路由 — 无鉴权外部接口：按交易日覆盖上传 + 查询。

设计（按用户要求）：
- POST /trades/import：上传某交易日成交，按 (user, trade_date) 全量覆盖（旧删新插）；
  新 trade_date 直接新增。调用方须以 user_id / username 指明归属用户。
- GET  /trades：按 user_id / username + 可选 trade_date 查询成交记录。
- GET  /trades/dates：列出该用户所有有成交的交易日。
全部无 JWT 鉴权（机器 / 外部程序调用）。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from models import ApiResponse, TradeUploadRequest
from services.trades_service import get_trades, import_trades, list_trade_dates
from services.terminal_broker_service import resolve_or_create_broker_for_upload
from services.import_log_service import add_import_log
from core.deps import resolve_external_user_id

router = APIRouter(prefix="/trades", tags=["trades"])


def _validate_trade_date(trade_date: str) -> None:
    if (
        not trade_date
        or len(trade_date) != 10
        or trade_date[4] != "-"
        or trade_date[7] != "-"
    ):
        raise HTTPException(status_code=400, detail="trade_date 必须为 YYYY-MM-DD")


@router.post("/import", response_model=ApiResponse[dict])
def import_trades_endpoint(body: TradeUploadRequest):
    """【无鉴权】成交数据上传：按 (user, trade_date) 覆盖（同日期旧记录删除后全量重插），
    新 trade_date 自动新增。调用方须以 user_id 或 username 指明归属用户。

    券商归属由 account（客户端自传主标识）决定，broker_code 为其历史别名；
    两者皆空 → 整批条目进入 failed（不整体拒绝），并在上传记录留痕；
    该 account 首见时按上传携带的 broker_name / remark 自动建券商（落默认终端或指定 terminal）。
    """
    _validate_trade_date(body.trade_date)
    user_id = resolve_external_user_id(body.user_id, body.username)
    account = (body.account or body.broker_code or "").strip()
    if not account:
        failed = [
            {"index": i, "code": str(it.code or ""), "reason": "account（券商账号）缺失"}
            for i, it in enumerate(body.items)
        ]
        result = {"deleted": 0, "inserted": 0, "failed": failed}
        add_import_log(user_id, "trades", body.source or "api", "", "", result, total=len(body.items))
        return ApiResponse(data=result)
    broker = resolve_or_create_broker_for_upload(
        user_id, account,
        name=body.broker_name, remark=body.remark, terminal_id=body.terminal,
    )
    if broker is None:
        failed = [
            {"index": i, "code": str(it.code or ""), "reason": "account（券商账号）缺失"}
            for i, it in enumerate(body.items)
        ]
        result = {"deleted": 0, "inserted": 0, "failed": failed}
        add_import_log(user_id, "trades", body.source or "api", account, "", result, total=len(body.items))
        return ApiResponse(data=result)
    # batch-level 券商名决定每条记录的 broker，覆盖逐条自带 broker
    items = [it.model_dump() for it in body.items]
    for it in items:
        it["broker"] = broker["name"]
    result = import_trades(user_id, body.trade_date, items, source=body.source or "api")
    add_import_log(user_id, "trades", body.source or "api", account, broker["name"], result, total=len(items))
    return ApiResponse(data=result)


@router.get("", response_model=ApiResponse[list[dict]])
def list_trades(
    user_id: Optional[int] = Query(None),
    username: Optional[str] = Query(None),
    trade_date: Optional[str] = Query(None),
):
    """查询成交记录：可按 trade_date 过滤；user_id / username 二选一。"""
    uid = resolve_external_user_id(user_id, username)
    return ApiResponse(data=get_trades(uid, trade_date=trade_date))


@router.get("/dates", response_model=ApiResponse[list[str]])
def trade_dates(
    user_id: Optional[int] = Query(None),
    username: Optional[str] = Query(None),
):
    """列出该用户所有有成交记录的交易日（升序）。"""
    uid = resolve_external_user_id(user_id, username)
    return ApiResponse(data=list_trade_dates(uid))
