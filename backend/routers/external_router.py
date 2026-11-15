"""外部数据上传路由（无鉴权）：委托 / 资金 / 交割单 / 券商注册 / 统一批量 + 按账号查询。

设计目标（2026-11-14）：
- 「所有可以传的数据都传给它」：除持仓、成交外补齐当日委托、资金面板、JSON 交割单；
- 「按账号来传」：每个端点都支持逐条 broker_account，统一批量端点一次 POST 传多个账号；
- 「预留多账号」：数据全部按 (user, broker_account, trade_date) 隔离，单人局域网只传
  一个账号时行为与旧接口一致，多账号只是 accounts 数组多几项；
- 「中间交互」：dry_run 预演、按账号返回明细、失败逐条带原始 item、上传记录留痕。

页面侧查询同时支持 JWT（浏览器）与 username/user_id（外部预检）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from core.deps import (
    oauth2_scheme,
    resolve_external_user_id,
    _resolve_user,
)
from models import ApiResponse
from services.external_upload_service import split_by_account, resolve_groups
from services.external_data_service import (
    account_overview,
    import_balance,
    import_orders,
    import_settlements_json,
    list_balances,
    list_external_settlements,
    list_orders,
    purge_accounts,
    register_broker,
)
from services.holdings_service import import_holdings
from services.trades_service import get_trades, import_trades
from services.import_log_service import add_import_log

router = APIRouter(tags=["external"])


def _truthy(v: Any) -> bool:
    return str(v if v is not None else "").strip().lower() in ("1", "true", "yes", "on")


def _check_date(d: str) -> str:
    d = str(d or "").strip()
    if len(d) != 10 or d[4:5] != "-" or d[7:8] != "-":
        raise HTTPException(status_code=400, detail="trade_date 必须为 YYYY-MM-DD")
    return d


def _page_or_external_user(
    user_id: Optional[int] = Query(None),
    username: Optional[str] = Query(None),
    token: Optional[str] = Depends(oauth2_scheme),
) -> str:
    """浏览器带 JWT；外部程序可显式传 username / user_id。"""
    if user_id is not None or username:
        return resolve_external_user_id(user_id, username)
    return _resolve_user(token)


def _scoped_items(items: list[dict], acc: str, broker: str) -> list[dict]:
    out = []
    for it in items or []:
        d = dict(it)
        d.setdefault("broker_account", acc)
        d.setdefault("broker", broker)
        out.append(d)
    return out


def _resolve_items(user_id: str, items: list[dict], default_account: str,
                   broker_name: str | None, remark: str | None,
                   terminal: str | None) -> tuple[list[tuple[str, str, list[dict]]], list[dict]]:
    """按资金账号分组 + 逐账号解析券商，返回 [(account, broker_name, items), ...]。"""
    groups, failed = split_by_account(items, default_account)
    resolved, rf = resolve_groups(user_id, groups, broker_name, remark, terminal)
    failed.extend(rf)
    return [(acc, g["broker_name"], g["items"]) for acc, g in resolved.items()], failed


# ============================================================
# 单类数据端点（无鉴权）
# ============================================================

@router.post("/orders/import", response_model=ApiResponse[dict])
def orders_import(body: dict = Body(...)):
    """当日委托上传。字段：order_no/code/name/side/price/quantity/filled_qty/
    filled_price/order_time/status/raw；按 (user, 资金账号, trade_date) 覆盖。"""
    uid = resolve_external_user_id(body.get("user_id"), body.get("username"))
    td = _check_date(body.get("trade_date"))
    dry, source = _truthy(body.get("dry_run")), str(body.get("source") or "api")
    items = body.get("items") or []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items 必须是数组")
    groups, failed = _resolve_items(uid, items, str(body.get("account") or ""),
                                    body.get("broker_name"), body.get("remark"), body.get("terminal"))
    total = {"deleted": 0, "inserted": 0, "failed": list(failed),
             "by_account": [], "dry_run": dry}
    for acc, bname, group_items in groups:
        res = import_orders(uid, td, group_items, source=source,
                            default_account=acc, dry_run=dry)
        total["deleted"] += res.get("deleted", 0)
        total["inserted"] += res.get("inserted", 0)
        total["failed"].extend(res.get("failed", []))
        total["by_account"].append({"account": acc, "broker": bname,
                                    "inserted": res.get("inserted", 0),
                                    "failed": len(res.get("failed", []))})
        if not dry:
            add_import_log(uid, "orders", source, acc, bname, res, total=len(group_items))
    return ApiResponse(data=total)


@router.post("/account/balance/import", response_model=ApiResponse[dict])
def balance_import(body: dict = Body(...)):
    """资金面板上传。``balance`` 为扁平对象（总资产/可用/市值/当日盈亏…），
    也可用 ``items`` 一次传多个账号。按 (user, 资金账号, trade_date) 覆盖，留历史快照。"""
    uid = resolve_external_user_id(body.get("user_id"), body.get("username"))
    td = _check_date(body.get("trade_date"))
    dry, source = _truthy(body.get("dry_run")), str(body.get("source") or "api")
    acc = str(body.get("account") or body.get("broker_account") or "").strip()
    if acc:
        register_broker(uid, acc, str(body.get("broker_name") or ""),
                        body.get("terminal"), str(body.get("remark") or ""))
    payload = {"balance": body.get("balance")} if isinstance(body.get("balance"), dict) else body
    res = import_balance(uid, td, payload, account=acc, source=source, dry_run=dry)
    if not dry:
        add_import_log(uid, "balance", source, acc, str(body.get("broker_name") or ""),
                       res, total=len(body.get("items") or [1]))
    return ApiResponse(data=res)


@router.post("/settlements/import", response_model=ApiResponse[dict])
def settlements_import(body: dict = Body(...)):
    """无鉴权 JSON 交割单：分项费用 / 成交编号 / 业务名 / 原始行，
    写入 biz_settlements，现有费率、已清仓、做T分析可直接消费。"""
    uid = resolve_external_user_id(body.get("user_id"), body.get("username"))
    td = _check_date(body.get("trade_date"))
    dry, source = _truthy(body.get("dry_run")), str(body.get("source") or "api")
    items = body.get("items") or []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items 必须是数组")
    groups, failed = _resolve_items(uid, items, str(body.get("account") or ""),
                                    body.get("broker_name"), body.get("remark"), body.get("terminal"))
    total = {"deleted": 0, "inserted": 0, "failed": list(failed),
             "by_account": [], "dry_run": dry}
    for acc, bname, group_items in groups:
        res = import_settlements_json(uid, td, group_items, account=acc,
                                      source=source, dry_run=dry)
        total["deleted"] += res.get("deleted", 0)
        total["inserted"] += res.get("inserted", 0)
        total["failed"].extend(res.get("failed", []))
        total["by_account"].append({"account": acc, "broker": bname,
                                    "inserted": res.get("inserted", 0)})
        if not dry:
            add_import_log(uid, "settlements", source, acc, bname, res, total=len(group_items))
    return ApiResponse(data=total)


@router.post("/brokers/import", response_model=ApiResponse[dict])
def brokers_import(body: dict = Body(...)):
    """预注册券商 / 资金账号（避免首次上传因名字没对上而静默失败）。
    ``brokers`` 数组或单账号字段 account + broker_name。"""
    uid = resolve_external_user_id(body.get("user_id"), body.get("username"))
    entries = body.get("brokers")
    if not isinstance(entries, list) or not entries:
        entries = [body]
    results = []
    for e in entries:
        results.append(register_broker(
            uid, str(e.get("account") or e.get("broker_account") or ""),
            str(e.get("broker_name") or e.get("name") or ""),
            e.get("terminal"), str(e.get("remark") or ""),
        ))
    return ApiResponse(data={"results": results, "count": len(results)})


# ============================================================
# 统一批量端点：一次 POST 传所有账号的所有数据
# ============================================================

@router.post("/external/batch", response_model=ApiResponse[dict])
def external_batch(body: dict = Body(...)):
    """一次请求把多个资金账号的持仓 / 成交 / 委托 / 资金 / 交割单全部传上来。

    body::

        {
          "username": "trader", "source": "brokerAuto", "trade_date": "2026-11-14",
          "dry_run": 0,
          "accounts": [
            {"account": "666622117166", "broker_name": "华泰证券",
             "holdings": [...], "trades": [...], "orders": [...],
             "balance": {...}, "settlements": [...]},
            {"account": "262700008483", "broker_name": "银河证券", ...}
          ]
        }

    不带 accounts 时退化为单账号：直接读顶层的 holdings / trades / orders /
    balance / settlements。任意一类数据省略 = 不更新该类；传空数组 = 清空该类
    （配合按账号覆盖语义）。返回值按账号、按数据类型分别给明细，方便对账。
    """
    uid = resolve_external_user_id(body.get("user_id"), body.get("username"))
    td = _check_date(body.get("trade_date") or datetime.now().strftime("%Y-%m-%d"))
    dry, source = _truthy(body.get("dry_run")), str(body.get("source") or "api")
    default_account = str(body.get("account") or body.get("broker_account") or "").strip()

    acc_list = body.get("accounts")
    if not isinstance(acc_list, list) or not acc_list:
        acc_list = [{
            "account": default_account,
            "broker_name": body.get("broker_name"),
            "terminal": body.get("terminal"),
            "remark": body.get("remark"),
            "holdings": body.get("holdings"),
            "trades": body.get("trades"),
            "orders": body.get("orders"),
            "balance": body.get("balance"),
            "settlements": body.get("settlements"),
        }]

    # 可选：批量预注册券商
    for b in (body.get("brokers") or []):
        if isinstance(b, dict):
            register_broker(uid, str(b.get("account") or ""),
                            str(b.get("broker_name") or ""), b.get("terminal"),
                            str(b.get("remark") or ""))

    results: list[dict] = []
    grand = {"added": 0, "updated": 0, "removed": 0, "deleted": 0,
             "inserted": 0, "failed": 0}
    for a in acc_list:
        acc = str(a.get("account") or a.get("broker_account") or default_account or "").strip()
        if not acc:
            results.append({"account": "", "error": "缺少资金账号"})
            grand["failed"] += 1
            continue
        bname = str(a.get("broker_name") or body.get("broker_name") or "").strip()
        reg = register_broker(uid, acc, bname, a.get("terminal") or body.get("terminal"),
                              str(a.get("remark") or ""))
        bname = bname or reg.get("broker_name") or ""
        parts: dict[str, dict] = {}
        acc_failed = 0

        def _log(kind: str, res: dict, n: int):
            if not dry:
                add_import_log(uid, kind, source, acc, bname, res, total=n)

        holdings = a.get("holdings")
        if isinstance(holdings, list):
            mode = str(a.get("holdings_mode") or body.get("holdings_mode") or "replace").lower()
            res = import_holdings(uid, _scoped_items(holdings, acc, bname), source=source,
                                  default_account=acc,
                                  mode=mode if mode in ("merge", "replace") else "replace",
                                  dry_run=dry)
            parts["holdings"] = res
            _log("holdings", res, len(holdings))
            grand["added"] += res.get("added", 0)
            grand["updated"] += res.get("updated", 0)
            grand["removed"] += res.get("removed", 0)
            acc_failed += len(res.get("failed", []))

        trades = a.get("trades")
        if isinstance(trades, list):
            mode = str(a.get("trades_mode") or body.get("trades_mode") or "replace").lower()
            res = import_trades(uid, td, _scoped_items(trades, acc, bname), source=source,
                                default_account=acc,
                                mode=mode if mode in ("merge", "replace") else "replace",
                                dry_run=dry)
            parts["trades"] = res
            _log("trades", res, len(trades))
            grand["deleted"] += res.get("deleted", 0)
            grand["inserted"] += res.get("inserted", 0)
            acc_failed += len(res.get("failed", []))

        orders = a.get("orders")
        if isinstance(orders, list):
            res = import_orders(uid, td, _scoped_items(orders, acc, bname), source=source,
                                default_account=acc, dry_run=dry)
            parts["orders"] = res
            _log("orders", res, len(orders))
            grand["inserted"] += res.get("inserted", 0)
            acc_failed += len(res.get("failed", []))

        balance = a.get("balance")
        if balance is not None:
            payload = {"items": balance} if isinstance(balance, list) else {"balance": balance}
            res = import_balance(uid, td, payload, account=acc, source=source, dry_run=dry)
            parts["balance"] = res
            _log("balance", res, len(balance) if isinstance(balance, list) else 1)
            grand["inserted"] += res.get("inserted", 0)
            acc_failed += len(res.get("failed", []))

        settlements = a.get("settlements")
        if isinstance(settlements, list):
            res = import_settlements_json(uid, td, _scoped_items(settlements, acc, bname),
                                          account=acc, source=source, dry_run=dry)
            parts["settlements"] = res
            _log("settlements", res, len(settlements))
            grand["inserted"] += res.get("inserted", 0)
            acc_failed += len(res.get("failed", []))

        grand["failed"] += acc_failed
        results.append({"account": acc, "broker": bname, "parts": parts,
                        "failed": acc_failed})

    return ApiResponse(data={
        "ok": True, "dry_run": dry, "trade_date": td,
        "account_count": len(results), "results": results, "totals": grand,
    })


# ============================================================
# 一次性清理（局域网单人使用）：只保留一个登录账号的数据
# ============================================================

@router.post("/external/purge", response_model=ApiResponse[dict])
def external_purge(body: dict = Body(...)):
    """一次性清理：只保留 ``username`` 名下 ``keep_accounts`` 的业务数据。

    用于清掉历史遗留的其它登录账号、探测账号（TESTAPI-* / E2E / TESTACC）
    与旧版无资金账号的残留行。默认 ``dry_run=1`` 只预演；真实执行必须
    ``confirm="PURGE"`` 且 ``dry_run=0``。不动 ``biz_users``（登录账号行）。

    body::

        {
          "username": "trader",
          "keep_accounts": ["600000135371", "666622117166", "262700008483"],
          "confirm": "PURGE",
          "dry_run": 1
        }
    """
    uid = resolve_external_user_id(
        body.get("user_id"),
        body.get("username") or body.get("keep_username") or "trader",
    )
    keep_accounts = body.get("keep_accounts")
    if not isinstance(keep_accounts, list):
        raise HTTPException(status_code=400, detail="keep_accounts 必须是数组")
    dry = _truthy(body.get("dry_run", 1))
    try:
        res = purge_accounts(uid, keep_accounts, dry_run=dry,
                             confirm=str(body.get("confirm") or ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(data=res)


# ============================================================
# 按账号查询（页面 / 外部预检）
# ============================================================

@router.get("/external/overview", response_model=ApiResponse[dict])
def overview(uid: str = Depends(_page_or_external_user)):
    """账号总览：每个资金账号的持仓 / 成交 / 委托 / 资金 / 上传次数与最后同步时间。"""
    return ApiResponse(data=account_overview(uid))


@router.get("/external/accounts", response_model=ApiResponse[list[dict]])
def accounts(uid: str = Depends(_page_or_external_user)):
    return ApiResponse(data=account_overview(uid)["accounts"])


@router.get("/external/orders", response_model=ApiResponse[list[dict]])
def orders(
    broker_account: Optional[str] = Query(None),
    trade_date: Optional[str] = Query(None),
    limit: int = Query(500),
    uid: str = Depends(_page_or_external_user),
):
    return ApiResponse(data=list_orders(uid, broker_account, trade_date, limit))


@router.get("/external/balances", response_model=ApiResponse[list[dict]])
def balances(
    broker_account: Optional[str] = Query(None),
    limit: int = Query(120),
    uid: str = Depends(_page_or_external_user),
):
    return ApiResponse(data=list_balances(uid, broker_account, limit))


@router.get("/external/settlements", response_model=ApiResponse[list[dict]])
def settlements(
    broker_account: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(2000),
    uid: str = Depends(_page_or_external_user),
):
    return ApiResponse(data=list_external_settlements(uid, broker_account, date_from, date_to, limit))


@router.get("/external/trades", response_model=ApiResponse[list[dict]])
def external_trades(
    broker_account: Optional[str] = Query(None),
    trade_date: Optional[str] = Query(None),
    limit: int = Query(2000),
    uid: str = Depends(_page_or_external_user),
):
    return ApiResponse(data=get_trades(uid, trade_date=trade_date,
                                       broker_account=broker_account, limit=limit))
