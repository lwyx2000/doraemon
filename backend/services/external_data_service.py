"""外部数据扩展（按资金账号）：当日委托 / 资金面板 / JSON 交割单 / 账号总览。

brokerAuto 除了持仓与成交，还有委托、资金面板、交割单等数据。此前 9080 只有
「JWT + Excel」的交割单入口，机器定时上传不方便；本模块补齐无鉴权 JSON 通道，
并统一按 ``(user, broker_account, trade_date)`` 覆盖，保证多账号互不串数据。

表：
- biz_orders            当日委托（按账号按日覆盖）
- biz_account_balances  资金面板（按账号按日 upsert，保留历史快照）
- biz_settlements       复用已有交割单表，补充 broker_account / biz / raw 列
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from database.sqlite_connection import get_biz_db
from core.config import USE_MOCK_DATA
from services.external_upload_service import account_of, normalize_direction
from services.terminal_broker_service import (
    get_broker_by_account,
    list_brokers,
    resolve_or_create_broker_for_upload,
    update_broker,
)

_TABLES_READY = False
_mock_orders: dict[str, list[dict]] = {}
_mock_balances: dict[str, list[dict]] = {}
_mock_settlements: dict[str, list[dict]] = {}

_BALANCE_KEYS = (
    "total_asset", "available", "withdrawable", "market_value",
    "position_profit", "today_profit", "today_profit_pct",
    "frozen", "buy_unfilled",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _ensure_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY or USE_MOCK_DATA:
        return
    db = get_biz_db()
    db.execute(
        """CREATE TABLE IF NOT EXISTS biz_orders (
            id TEXT PRIMARY KEY, fk_user INTEGER NOT NULL, trade_date TEXT NOT NULL,
            broker_account TEXT DEFAULT '', broker TEXT DEFAULT '', sub_account TEXT DEFAULT '',
            order_no TEXT DEFAULT '', code TEXT DEFAULT '', name TEXT DEFAULT '',
            type TEXT DEFAULT '', side TEXT DEFAULT '', direction TEXT DEFAULT '',
            price REAL, quantity REAL, filled_qty REAL, filled_price REAL, amount REAL,
            order_time TEXT, status TEXT DEFAULT '', status_note TEXT DEFAULT '',
            source TEXT DEFAULT '', raw TEXT, created_at TEXT)"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS biz_account_balances (
            id TEXT PRIMARY KEY, fk_user INTEGER NOT NULL, trade_date TEXT NOT NULL,
            broker_account TEXT NOT NULL DEFAULT '', broker TEXT DEFAULT '',
            balance_json TEXT, total_asset REAL, available REAL, withdrawable REAL,
            market_value REAL, position_profit REAL, today_profit REAL,
            today_profit_pct REAL, frozen REAL, buy_unfilled REAL,
            source TEXT DEFAULT '', created_at TEXT)"""
    )
    # 旧库补齐 biz_settlements 的按账号字段（CREATE TABLE IF NOT EXISTS 不会加列）
    for col, dtype, default in (
        ("broker_account", "TEXT", "''"),
        ("sub_account", "TEXT", "''"),
        ("order_no", "TEXT", "''"),
        ("biz", "TEXT", "''"),
        ("raw", "TEXT", None),
    ):
        try:
            if default is None:
                db.execute(f"ALTER TABLE biz_settlements ADD COLUMN {col} {dtype}")
            else:
                db.execute(f"ALTER TABLE biz_settlements ADD COLUMN {col} {dtype} DEFAULT {default}")
        except Exception as e:  # noqa: BLE001
            if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                import sys
                print(f"[MIGRATE] biz_settlements.{col}: {e!r}", file=sys.stderr, flush=True)
    db.execute("CREATE INDEX IF NOT EXISTS idx_biz_orders_user_acct_date ON biz_orders(fk_user, broker_account, trade_date)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_biz_settle_user_acct ON biz_settlements(fk_user, broker_account, trade_date)")
    _TABLES_READY = True


# ============================================================
# 当日委托
# ============================================================

def import_orders(
    user_id: str, trade_date: str, items: list[dict], source: str = "",
    default_account: str = "", dry_run: bool = False, mode: str = "replace",
) -> dict:
    """按 (user, broker_account, trade_date) 覆盖上传当日委托。"""
    valid, failed = [], []
    by_account: dict[str, dict] = {}
    for idx, raw in enumerate(items or []):
        acc = account_of(raw, default_account)
        code = str(raw.get("code") or "").strip()
        order_no = str(raw.get("order_no") or "").strip()
        if not code and not order_no:
            failed.append({"index": idx, "account": acc, "reason": "缺少 code / order_no", "item": raw})
            continue
        direction, _ = normalize_direction(raw.get("side") or raw.get("direction"),
                                           str(raw.get("biz") or ""))
        price, quantity = _f(raw.get("price")), _f(raw.get("quantity"))
        filled_qty = _f(raw.get("filled_qty") or raw.get("filled"))
        amount = _f(raw.get("amount"))
        if amount is None and price is not None and quantity is not None:
            amount = round(price * quantity, 2)
        valid.append({
            "id": str(uuid.uuid4()), "broker_account": acc,
            "broker": str(raw.get("broker") or ""),
            "sub_account": str(raw.get("sub_account") or raw.get("account") or ""),
            "order_no": order_no, "code": code, "name": str(raw.get("name") or ""),
            "type": str(raw.get("type") or ""), "side": str(raw.get("side") or ""),
            "direction": direction, "price": price, "quantity": quantity,
            "filled_qty": filled_qty, "filled_price": _f(raw.get("filled_price")),
            "amount": amount, "order_time": str(raw.get("order_time") or "") or None,
            "status": str(raw.get("status") or raw.get("status_note") or ""),
            "status_note": str(raw.get("status_note") or ""),
            "source": source,
            "raw": (str(raw.get("raw"))[:4000] if raw.get("raw") not in (None, "") else None),
            "created_at": _now_iso(),
        })
        by_account.setdefault(acc, {"account": acc, "broker": valid[-1]["broker"],
                                    "inserted": 0, "failed": 0})["inserted"] += 1
    for f in failed:
        by_account.setdefault(str(f.get("account") or ""),
                              {"account": str(f.get("account") or ""), "broker": "",
                               "inserted": 0, "failed": 0})["failed"] += 1

    accounts = sorted({v["broker_account"] for v in valid if v["broker_account"]})
    if not accounts and default_account:
        accounts = [str(default_account).strip()]

    if USE_MOCK_DATA:
        store = _mock_orders.setdefault(user_id, [])
        ph = accounts
        deleted = len([t for t in store if t["trade_date"] == trade_date
                       and ((t.get("broker_account") or "") in ph or not (t.get("broker_account") or ""))])
        if not dry_run:
            store[:] = [t for t in store if not (t["trade_date"] == trade_date
                        and ((t.get("broker_account") or "") in ph or not (t.get("broker_account") or "")))]
            for v in valid:
                v["trade_date"] = trade_date
                store.append(v)
        return {"deleted": deleted, "inserted": 0 if dry_run else len(valid),
                "failed": failed, "by_account": list(by_account.values()), "dry_run": bool(dry_run)}

    _ensure_tables()
    db = get_biz_db()
    ph = ",".join("?" * len(accounts)) if accounts else ""
    clause = (f"(broker_account IN ({ph}) OR broker_account='' OR broker_account IS NULL)"
              if ph else "1=1")
    params = [user_id, trade_date] + accounts
    if dry_run:
        row = db.fetchone(
            f"SELECT count(*) FROM biz_orders WHERE fk_user=? AND trade_date=? AND {clause}", params)
        return {"deleted": 0, "inserted": 0, "would_delete": row[0] if row else 0,
                "would_insert": len(valid), "failed": failed,
                "by_account": list(by_account.values()), "dry_run": True}
    deleted = db.execute(
        f"DELETE FROM biz_orders WHERE fk_user=? AND trade_date=? AND {clause}", params).rowcount
    if valid:
        db.executemany(
            "INSERT INTO biz_orders (id, fk_user, trade_date, broker_account, broker, "
            "sub_account, order_no, code, name, type, side, direction, price, quantity, "
            "filled_qty, filled_price, amount, order_time, status, status_note, source, raw, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [[v["id"], user_id, trade_date, v["broker_account"], v["broker"], v["sub_account"],
              v["order_no"], v["code"], v["name"], v["type"], v["side"], v["direction"],
              v["price"], v["quantity"], v["filled_qty"], v["filled_price"], v["amount"],
              v["order_time"], v["status"], v["status_note"], v["source"], v["raw"], v["created_at"]]
             for v in valid],
        )
    return {"deleted": deleted, "inserted": len(valid), "failed": failed,
            "by_account": list(by_account.values()), "dry_run": False}


def list_orders(user_id: str, broker_account: str | None = None,
                trade_date: str | None = None, limit: int = 500) -> list[dict]:
    if USE_MOCK_DATA:
        rows = _mock_orders.get(user_id, [])
        if broker_account:
            rows = [r for r in rows if (r.get("broker_account") or "") == broker_account]
        if trade_date:
            rows = [r for r in rows if r.get("trade_date") == trade_date]
        return sorted(rows, key=lambda r: (r.get("trade_date") or "", r.get("order_time") or ""), reverse=True)[:limit]
    _ensure_tables()
    db = get_biz_db()
    where, params = ["fk_user = ?"], [user_id]
    if broker_account:
        where.append("broker_account = ?")
        params.append(broker_account)
    if trade_date:
        where.append("trade_date = ?")
        params.append(trade_date)
    params.append(int(limit))
    rows = db.fetchall(
        "SELECT id, trade_date, broker_account, broker, sub_account, order_no, code, name, "
        "type, side, direction, price, quantity, filled_qty, filled_price, amount, "
        "order_time, status, status_note, source, created_at "
        f"FROM biz_orders WHERE {' AND '.join(where)} "
        "ORDER BY trade_date DESC, order_time DESC, id DESC LIMIT ?", params)
    keys = ("id", "trade_date", "broker_account", "broker", "sub_account", "order_no", "code",
            "name", "type", "side", "direction", "price", "quantity", "filled_qty",
            "filled_price", "amount", "order_time", "status", "status_note", "source", "created_at")
    return [dict(zip(keys, r)) for r in rows]


# ============================================================
# 资金面板
# ============================================================

def import_balance(
    user_id: str, trade_date: str, payload: dict, account: str = "",
    source: str = "", dry_run: bool = False,
) -> dict:
    """上传资金面板。payload 可为 ``{"balance": {...}}``、扁平 dict，或
    ``{"items": [{"broker_account":..., "balance":{...}}, ...]}``（多账号一次传）。"""
    entries: list[tuple[str, dict]] = []
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if isinstance(raw_items, list) and raw_items:
        for it in raw_items:
            acc = account_of(it, account)
            bal = it.get("balance") if isinstance(it.get("balance"), dict) else it
            entries.append((acc, dict(bal)))
    else:
        bal = payload.get("balance") if isinstance(payload, dict) and isinstance(payload.get("balance"), dict) else payload
        entries.append((account_of(payload if isinstance(payload, dict) else {}, account), dict(bal)))

    inserted, failed, by_account = 0, [], []
    for acc, bal in entries:
        if not acc:
            failed.append({"account": "", "reason": "缺少资金账号", "item": bal})
            continue
        if dry_run:
            inserted += 1
            by_account.append({"account": acc, "inserted": 1, "failed": 0})
            continue
        row = {"id": str(uuid.uuid4()), "trade_date": trade_date, "broker_account": acc,
               "broker": str(bal.get("broker") or ""),
               "balance_json": json.dumps(bal, ensure_ascii=False),
               "source": source, "created_at": _now_iso()}
        for k in _BALANCE_KEYS:
            row[k] = _f(bal.get(k))
        if USE_MOCK_DATA:
            store = _mock_balances.setdefault(user_id, [])
            store[:] = [x for x in store if not (x["trade_date"] == trade_date and x["broker_account"] == acc)]
            store.append(row)
        else:
            _ensure_tables()
            db = get_biz_db()
            db.execute("DELETE FROM biz_account_balances WHERE fk_user=? AND broker_account=? AND trade_date=?",
                       [user_id, acc, trade_date])
            db.execute(
                "INSERT INTO biz_account_balances (id, fk_user, trade_date, broker_account, broker, "
                "balance_json, total_asset, available, withdrawable, market_value, position_profit, "
                "today_profit, today_profit_pct, frozen, buy_unfilled, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [row["id"], user_id, row["trade_date"], row["broker_account"], row["broker"],
                 row["balance_json"], *[row[k] for k in _BALANCE_KEYS], row["source"], row["created_at"]],
            )
        inserted += 1
        by_account.append({"account": acc, "inserted": 1, "failed": 0})
    return {"inserted": 0 if dry_run else inserted,
            "would_insert": inserted if dry_run else 0,
            "failed": failed, "by_account": by_account, "dry_run": bool(dry_run)}


def list_balances(user_id: str, broker_account: str | None = None,
                  limit: int = 120) -> list[dict]:
    if USE_MOCK_DATA:
        rows = _mock_balances.get(user_id, [])
        if broker_account:
            rows = [r for r in rows if (r.get("broker_account") or "") == broker_account]
        return sorted(rows, key=lambda r: (r.get("trade_date") or "", r.get("created_at") or ""), reverse=True)[:limit]
    _ensure_tables()
    db = get_biz_db()
    where, params = ["fk_user = ?"], [user_id]
    if broker_account:
        where.append("broker_account = ?")
        params.append(broker_account)
    params.append(int(limit))
    rows = db.fetchall(
        "SELECT id, trade_date, broker_account, broker, balance_json, total_asset, available, "
        "withdrawable, market_value, position_profit, today_profit, today_profit_pct, "
        "frozen, buy_unfilled, source, created_at "
        f"FROM biz_account_balances WHERE {' AND '.join(where)} "
        "ORDER BY trade_date DESC, created_at DESC LIMIT ?", params)
    keys = ("id", "trade_date", "broker_account", "broker", "balance_json", "total_asset",
            "available", "withdrawable", "market_value", "position_profit", "today_profit",
            "today_profit_pct", "frozen", "buy_unfilled", "source", "created_at")
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        try:
            d["balance"] = json.loads(d.pop("balance_json") or "{}")
        except (ValueError, TypeError):
            d["balance"] = {}
        out.append(d)
    return out


# ============================================================
# JSON 交割单（无鉴权，喂现有费率 / 已清仓分析）
# ============================================================

def import_settlements_json(
    user_id: str, trade_date: str, items: list[dict], account: str = "",
    source: str = "", dry_run: bool = False, mode: str = "replace",
) -> dict:
    """写入 biz_settlements；按 (user, broker_account, trade_date) 覆盖或按 trade_id 去重。"""
    valid, failed = [], []
    for idx, raw in enumerate(items or []):
        acc = account_of(raw, account)
        code = str(raw.get("code") or "").strip()
        direction, entry_type = normalize_direction(raw.get("direction"), str(raw.get("biz") or ""))
        if raw.get("entry_type"):
            entry_type = str(raw["entry_type"])
        if not code and entry_type == "trade":
            failed.append({"index": idx, "account": acc, "reason": "成交行缺少 code", "item": raw})
            continue
        price, quantity = _f(raw.get("price")) or 0.0, _f(raw.get("quantity")) or 0.0
        amount = _f(raw.get("amount"))
        if amount is None:
            amount = round(price * quantity, 2)
        commission = _f(raw.get("commission")) or 0.0
        stamp_tax = _f(raw.get("stamp_tax")) or 0.0
        transfer_fee = _f(raw.get("transfer_fee")) or 0.0
        other_fee = _f(raw.get("other_fee")) or 0.0
        fee_total = _f(raw.get("fee_total"))
        if fee_total is None:
            fee_total = commission + stamp_tax + transfer_fee + other_fee
        tid = str(raw.get("trade_id") or "") or f"fp:{abs(hash((trade_date, code, direction, price, quantity, raw.get('trade_time'))))}"
        valid.append({
            "id": str(uuid.uuid4()), "broker_account": acc,
            "trade_date": str(raw.get("trade_date") or trade_date),
            "settle_date": str(raw.get("settle_date") or "") or None,
            # 多账号可能复用同一个成交编号，加账号前缀避免撞唯一索引
            "trade_id": f"{acc}:{tid}" if acc else tid,
            "code": code, "name": str(raw.get("name") or ""),
            "type": str(raw.get("type") or "stock"),
            "broker": str(raw.get("broker") or ""),
            "account": str(raw.get("sub_account") or raw.get("account") or ""),
            "direction": direction, "entry_type": entry_type,
            "price": price, "quantity": quantity, "amount": amount,
            "commission": commission, "stamp_tax": stamp_tax,
            "transfer_fee": transfer_fee, "other_fee": other_fee,
            "fee_total": fee_total,
            "net_amount": _f(raw.get("net_amount") or raw.get("occ_amount")),
            "trade_time": str(raw.get("trade_time") or "") or None,
            "currency": str(raw.get("currency") or "CNY"),
            "order_no": str(raw.get("order_no") or ""),
            "biz": str(raw.get("biz") or ""),
            "raw": (str(raw.get("raw"))[:4000] if raw.get("raw") not in (None, "") else None),
            "source": source, "created_at": _now_iso(),
        })
    accounts = sorted({v["broker_account"] for v in valid if v["broker_account"]})
    if not accounts and account:
        accounts = [str(account).strip()]

    if USE_MOCK_DATA:
        store = _mock_settlements.setdefault(user_id, [])
        deleted = 0
        if not dry_run:
            store[:] = [x for x in store if not (
                x["trade_date"] == trade_date and (x.get("broker_account") or "") in accounts)]
            store.extend(valid)
        return {"deleted": deleted, "inserted": 0 if dry_run else len(valid),
                "failed": failed, "by_account": [{"account": a, "inserted": len(valid), "failed": 0} for a in accounts],
                "dry_run": bool(dry_run)}

    _ensure_tables()
    db = get_biz_db()
    ph = ",".join("?" * len(accounts)) if accounts else ""
    clause = (f"(broker_account IN ({ph}) OR broker_account='' OR broker_account IS NULL)"
              if ph else "1=1")
    params = [user_id, trade_date] + accounts
    if dry_run:
        row = db.fetchone(
            f"SELECT count(*) FROM biz_settlements WHERE fk_user=? AND trade_date=? AND {clause}", params)
        return {"deleted": 0, "inserted": 0, "would_delete": row[0] if row else 0,
                "would_insert": len(valid), "failed": failed,
                "by_account": [{"account": a, "inserted": len(valid), "failed": 0} for a in accounts],
                "dry_run": True}
    deleted = db.execute(
        f"DELETE FROM biz_settlements WHERE fk_user=? AND trade_date=? AND {clause}", params).rowcount
    if valid:
        db.executemany(
            "INSERT INTO biz_settlements (id, fk_user, trade_date, settle_date, trade_id, "
            "code, name, type, broker, account, direction, entry_type, price, quantity, "
            "amount, commission, stamp_tax, transfer_fee, other_fee, fee_total, net_amount, "
            "trade_time, currency, source, created_at, broker_account, sub_account, order_no, biz, raw) "
            "VALUES (" + ",".join(["?"] * 30) + ")",
            [[v["id"], user_id, v["trade_date"], v["settle_date"], v["trade_id"], v["code"],
              v["name"], v["type"], v["broker"], v["account"], v["direction"], v["entry_type"],
              v["price"], v["quantity"], v["amount"], v["commission"], v["stamp_tax"],
              v["transfer_fee"], v["other_fee"], v["fee_total"], v["net_amount"],
              v["trade_time"], v["currency"], v["source"], v["created_at"],
              v["broker_account"], v["account"], v["order_no"], v["biz"], v["raw"]]
             for v in valid],
        )
    return {"deleted": deleted, "inserted": len(valid), "failed": failed,
            "by_account": [{"account": a, "inserted": len(valid), "failed": 0} for a in accounts],
            "dry_run": False}


def list_external_settlements(user_id: str, broker_account: str | None = None,
                              date_from: str | None = None, date_to: str | None = None,
                              limit: int = 2000) -> list[dict]:
    _ensure_tables()
    db = get_biz_db()
    where, params = ["fk_user = ?"], [user_id]
    if broker_account:
        where.append("broker_account = ?")
        params.append(broker_account)
    if date_from:
        where.append("trade_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("trade_date <= ?")
        params.append(date_to)
    params.append(int(limit))
    rows = db.fetchall(
        "SELECT id, trade_date, settle_date, trade_id, code, name, type, broker, account, "
        "direction, entry_type, price, quantity, amount, commission, stamp_tax, transfer_fee, "
        "other_fee, fee_total, net_amount, trade_time, currency, source, broker_account, biz, raw "
        f"FROM biz_settlements WHERE {' AND '.join(where)} "
        "ORDER BY trade_date DESC, trade_time DESC LIMIT ?", params)
    keys = ("id", "trade_date", "settle_date", "trade_id", "code", "name", "type", "broker",
            "account", "direction", "entry_type", "price", "quantity", "amount", "commission",
            "stamp_tax", "transfer_fee", "other_fee", "fee_total", "net_amount", "trade_time",
            "currency", "source", "broker_account", "biz", "raw")
    return [dict(zip(keys, r)) for r in rows]


# ============================================================
# 券商注册 / 账号总览
# ============================================================

def register_broker(user_id: str, account: str, broker_name: str = "",
                    terminal: str | None = None, remark: str = "") -> dict:
    acc = str(account or "").strip()
    if not acc:
        return {"ok": False, "reason": "缺少资金账号"}
    broker = resolve_or_create_broker_for_upload(
        user_id, acc, name=broker_name or None, remark=remark, terminal_id=terminal)
    if broker is None:
        return {"ok": False, "reason": "券商创建失败"}
    # 显式注册 / 批量上传带券商名时允许纠正历史误填的名（多账号混批常见）
    if broker_name and broker["name"] != broker_name:
        updated = update_broker(user_id, broker["id"], name=broker_name)
        if updated:
            broker = updated
    return {"ok": True, "account": acc, "broker_id": broker["id"],
            "broker_name": broker["name"], "terminal_id": broker["fk_terminal"]}


def account_overview(user_id: str) -> dict:
    """账号总览：把持仓 / 成交 / 委托 / 资金 / 上传记录按资金账号聚合。

    单人局域网通常只有 1~2 个账号；多账号时自动展开，不需要改任何配置。
    """
    accounts: dict[str, dict] = {}

    def _slot(acc: str, broker: str = "") -> dict:
        d = accounts.setdefault(acc, {
            "account": acc, "broker": broker, "alias": "",
            "holding_count": 0, "holding_market_value": 0.0, "holding_cost": 0.0,
            "trade_count": 0, "order_count": 0, "settlement_count": 0,
            "balance_count": 0, "last_upload": None, "last_data_at": None,
            "balance": None,
        })
        if broker and not d["broker"]:
            d["broker"] = broker
        return d

    for b in list_brokers(user_id):
        _slot(b.get("account") or "", b.get("name") or "")

    if USE_MOCK_DATA:
        return {"accounts": list(accounts.values()), "account_count": len(accounts)}
    _ensure_tables()
    db = get_biz_db()

    def _rows(sql: str, params: list | None = None) -> list[tuple]:
        try:
            return db.fetchall(sql, params or [user_id])
        except Exception:  # noqa: BLE001
            return []

    for r in _rows("SELECT COALESCE(broker_account,''), broker, count(*), "
                   "SUM(COALESCE(client_market_value,0)), SUM(cost_price*quantity), MAX(updated_at) "
                   "FROM biz_holdings WHERE fk_user=? AND (is_closed=0 OR is_closed IS NULL) "
                   "GROUP BY 1,2"):
        d = _slot(r[0], r[1] or "")
        d["holding_count"] += r[2] or 0
        d["holding_market_value"] += r[3] or 0.0
        d["holding_cost"] += r[4] or 0.0
        if r[5] and (not d["last_data_at"] or str(r[5]) > d["last_data_at"]):
            d["last_data_at"] = str(r[5])
    for sql, key in (
        ("SELECT COALESCE(broker_account,''), count(*), MAX(created_at) FROM biz_trades WHERE fk_user=? GROUP BY 1", "trade_count"),
        ("SELECT COALESCE(broker_account,''), count(*), MAX(created_at) FROM biz_orders WHERE fk_user=? GROUP BY 1", "order_count"),
        ("SELECT COALESCE(broker_account,''), count(*), MAX(created_at) FROM biz_settlements WHERE fk_user=? GROUP BY 1", "settlement_count"),
        ("SELECT COALESCE(broker_account,''), count(*), MAX(created_at) FROM biz_account_balances WHERE fk_user=? GROUP BY 1", "balance_count"),
        ("SELECT COALESCE(broker_code,''), MAX(created_at) FROM biz_import_log WHERE fk_user=? GROUP BY 1", "last_upload"),
    ):
        for r in _rows(sql):
            d = _slot(r[0])
            if key == "last_upload":
                if r[1] and (not d["last_upload"] or str(r[1]) > d["last_upload"]):
                    d["last_upload"] = str(r[1])
            else:
                d[key] += r[1] or 0
                if len(r) > 2 and r[2] and (not d["last_data_at"] or str(r[2]) > d["last_data_at"]):
                    d["last_data_at"] = str(r[2])

    # 每个账号最新一条资金面板
    for r in _rows("SELECT broker_account, total_asset, available, withdrawable, market_value, "
                   "position_profit, today_profit, today_profit_pct, frozen, buy_unfilled, trade_date "
                   "FROM biz_account_balances WHERE fk_user=? ORDER BY trade_date DESC, created_at DESC"):
        d = _slot(r[0])
        if d["balance"] is None:
            d["balance"] = dict(zip(
                ("total_asset", "available", "withdrawable", "market_value", "position_profit",
                 "today_profit", "today_profit_pct", "frozen", "buy_unfilled", "trade_date"), r[1:]))

    for d in accounts.values():
        d["holding_market_value"] = round(d["holding_market_value"], 2)
        d["holding_cost"] = round(d["holding_cost"], 2)
    out = sorted(accounts.values(), key=lambda x: (-x["holding_market_value"], x["account"]))
    return {
        "accounts": out,
        "account_count": len(out),
        "totals": {
            "holding_count": sum(d["holding_count"] for d in out),
            "trade_count": sum(d["trade_count"] for d in out),
            "order_count": sum(d["order_count"] for d in out),
            "settlement_count": sum(d["settlement_count"] for d in out),
            "total_asset": round(sum((d["balance"] or {}).get("total_asset") or 0 for d in out), 2),
            "available": round(sum((d["balance"] or {}).get("available") or 0 for d in out), 2),
            "today_profit": round(sum((d["balance"] or {}).get("today_profit") or 0 for d in out), 2),
        },
    }
