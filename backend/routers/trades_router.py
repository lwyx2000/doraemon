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
from services.external_upload_service import split_by_account, resolve_groups
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
    """【无鉴权】成交数据上传：按 (user, broker_account, trade_date) 覆盖。

    - 顶层 account 为整批默认资金账号，逐条 broker_account 可覆盖 → 一次可传多个账号；
    - 多账号同日分次 POST 互不删除（只删本批涉及账号的当日行）；
    - direction 支持回购购回 / 新股入帐 / 资金流水，quantity 允许负，amount 显式优先；
    - 落库成交编号 / 委托编号 / 业务名 / 分项费用 / 原始行，供对账与费率分析；
    - ``mode=merge`` 按 trade_id 幂等；``dry_run=1`` 只校验不写库。
    """
    _validate_trade_date(body.trade_date)
    user_id = resolve_external_user_id(body.user_id, body.username)
    default_account = (body.account or body.broker_code or "").strip()
    source = body.source or "api"
    dry = int(body.dry_run or 0) == 1
    mode = str(body.mode or "replace").strip().lower()
    if mode not in ("replace", "merge"):
        mode = "replace"

    items = [it.model_dump() for it in body.items]
    groups, failed = split_by_account(items, default_account)
    resolved, resolve_failed = resolve_groups(
        user_id, groups, body.broker_name, body.remark, body.terminal)
    failed.extend(resolve_failed)

    totals = {"deleted": 0, "inserted": 0, "failed": list(failed),
              "by_account": [], "dry_run": dry}
    for acc, g in resolved.items():
        res = import_trades(
            user_id, body.trade_date, g["items"], source=source,
            default_account=acc, mode=mode, dry_run=dry,
        )
        totals["deleted"] += res.get("deleted", 0)
        totals["inserted"] += res.get("inserted", 0)
        totals["failed"].extend(res.get("failed", []))
        totals["by_account"].append({
            "account": acc, "broker": g["broker_name"],
            "inserted": res.get("inserted", 0), "deleted": res.get("deleted", 0),
            "failed": len(res.get("failed", [])),
        })
        if not dry:
            add_import_log(user_id, "trades", source, acc, g["broker_name"],
                           res, total=len(g["items"]))
    if not resolved:
        add_import_log(user_id, "trades", source, default_account, "",
                       {"failed": failed}, total=len(items))
    if dry:
        totals["would_insert"] = totals["inserted"]
        totals["inserted"] = totals["deleted"] = 0
    return ApiResponse(data=totals)


@router.get("", response_model=ApiResponse[list[dict]])
def list_trades(
    user_id: Optional[int] = Query(None),
    username: Optional[str] = Query(None),
    trade_date: Optional[str] = Query(None),
    broker_account: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
):
    """查询成交记录：可按 trade_date / broker_account 过滤；user_id / username 二选一。"""
    uid = resolve_external_user_id(user_id, username)
    return ApiResponse(data=get_trades(uid, trade_date=trade_date,
                                       broker_account=broker_account, limit=limit))


@router.get("/dates", response_model=ApiResponse[list[str]])
def trade_dates(
    user_id: Optional[int] = Query(None),
    username: Optional[str] = Query(None),
):
    """列出该用户所有有成交记录的交易日（升序）。"""
    uid = resolve_external_user_id(user_id, username)
    return ApiResponse(data=list_trade_dates(uid))
