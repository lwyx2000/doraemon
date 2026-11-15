"""成交记录服务 — 无鉴权外部接口写入的成交数据独立存储（biz_trades）。

2026-11-14 改造（按资金账号）：
- 覆盖维度从 ``(user, trade_date)`` 改为 ``(user, broker_account, trade_date)``：
  一次请求可传多个资金账号，多账号分次 POST 也不会互相删掉；
- 老数据（broker_account 为空）在首次带账号上传时被本账号吸收，不产生重复；
- direction 支持逆回购购回 / 新股入帐 / 资金流水，quantity 允许负数；
- amount 显式优先（逆回购 price 是年化利率而非单价），并落库成交编号、
  委托编号、业务名、分项费用、原始行，供对账与费率分析；
- ``mode=merge`` 按 trade_id 幂等 upsert；``dry_run=1`` 只校验不写库。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from database.sqlite_connection import get_biz_db
from core.config import USE_MOCK_DATA
from services.external_upload_service import account_of, normalize_direction

_TABLES_READY = False
_mock_trades: dict[str, list[dict]] = {}

# 方向枚举（扩展）：cash / other 类只入库展示，不参与盈亏与费率统计
TRADE_DIRECTIONS: set[str] = {
    "buy", "sell", "repo_sell", "repo_buy", "new_issue",
    "dividend", "interest", "cash_in", "cash_out", "other",
}

# 新增列及 SQLite 类型（旧库通过 ALTER 增量补齐）
_TRADE_EXTRA_COLS = (
    ("broker_account", "VARCHAR", "''"),
    ("trade_id", "VARCHAR", None),
    ("order_no", "VARCHAR", None),
    ("biz", "VARCHAR", "''"),
    ("entry_type", "VARCHAR", "'trade'"),
    ("settle_date", "VARCHAR", None),
    ("commission", "DOUBLE", None),
    ("stamp_tax", "DOUBLE", None),
    ("transfer_fee", "DOUBLE", None),
    ("other_fee", "DOUBLE", None),
    ("fee_total", "DOUBLE", None),
    ("net_amount", "DOUBLE", None),
    ("currency", "VARCHAR", "'CNY'"),
    ("raw", "VARCHAR", None),
)


def _ensure_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY or USE_MOCK_DATA:
        return
    db = get_biz_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_trades (
            id           VARCHAR PRIMARY KEY,
            fk_user      BIGINT NOT NULL,
            trade_date   VARCHAR(10) NOT NULL,   -- 归属交易日 YYYY-MM-DD
            code         VARCHAR(20) NOT NULL,
            name         VARCHAR(100) DEFAULT '',
            type         VARCHAR(20) DEFAULT 'stock',
            broker       VARCHAR(50) DEFAULT '',
            account      VARCHAR(50) DEFAULT '',
            direction    VARCHAR(20) NOT NULL,
            price        DOUBLE NOT NULL,
            quantity     DOUBLE NOT NULL,
            amount       DOUBLE,                  -- 成交额（显式优先）
            fee          DOUBLE,                  -- 手续费（兼容旧字段）
            trade_time   VARCHAR(20),
            source       VARCHAR(50) DEFAULT '',
            created_at   VARCHAR,
            broker_account VARCHAR DEFAULT '',
            trade_id     VARCHAR,
            order_no     VARCHAR,
            biz          VARCHAR DEFAULT '',
            entry_type   VARCHAR DEFAULT 'trade',
            settle_date  VARCHAR,
            commission   DOUBLE,
            stamp_tax    DOUBLE,
            transfer_fee DOUBLE,
            other_fee    DOUBLE,
            fee_total    DOUBLE,
            net_amount   DOUBLE,
            currency     VARCHAR DEFAULT 'CNY',
            raw          VARCHAR
        )
        """
    )
    for col, dtype, default in _TRADE_EXTRA_COLS:
        try:
            if default is None:
                db.execute(f"ALTER TABLE biz_trades ADD COLUMN {col} {dtype}")
            else:
                db.execute(f"ALTER TABLE biz_trades ADD COLUMN {col} {dtype} DEFAULT {default}")
        except Exception as e:  # noqa: BLE001
            if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                import sys
                print(f"[MIGRATE] biz_trades.{col}: {e!r}", file=sys.stderr, flush=True)
    db.execute("CREATE INDEX IF NOT EXISTS idx_biz_trades_user_acct_date ON biz_trades(fk_user, broker_account, trade_date)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_biz_trades_user_tradeid ON biz_trades(fk_user, trade_id)")
    _TABLES_READY = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None  # NaN 过滤
    except (TypeError, ValueError):
        return None


def import_trades(
    user_id: str,
    trade_date: str,
    items: list[dict],
    source: str = "",
    default_account: str = "",
    mode: str = "replace",
    dry_run: bool = False,
) -> dict:
    """按 (user, broker_account, trade_date) 覆盖上传成交。

    - 逐条 ``broker_account`` 优先，缺省用顶层 ``default_account``；
    - 老数据 broker_account 为空时会被本批账号吸收，避免重复；
    - 多账号同日分次上传互不干扰（只删本批涉及账号的当日行）；
    - ``mode=merge`` 按 trade_id 幂等 upsert；``dry_run`` 只校验不写库；
    - 返回 ``by_account`` 分项统计，便于调用方核对每个账号。
    """
    invalid: list[dict] = []
    valid: list[dict] = []
    by_account: dict[str, dict] = {}

    for idx, raw in enumerate(items or []):
        code = str(raw.get("code") or "").strip()
        direction, entry_type = normalize_direction(raw.get("direction"), str(raw.get("biz") or ""))
        if raw.get("entry_type"):
            entry_type = str(raw["entry_type"])
        price = _safe_float(raw.get("price"))
        quantity = _safe_float(raw.get("quantity"))
        acc = account_of(raw, default_account)
        if not code:
            invalid.append({"index": idx, "code": code, "account": acc, "reason": "缺少 code", "item": raw})
            continue
        if price is None or quantity is None or price < 0 or quantity == 0:
            invalid.append({"index": idx, "code": code, "account": acc,
                            "reason": "price/quantity 须为数值（quantity 可负、不可为 0）", "item": raw})
            continue

        amount = _safe_float(raw.get("amount")) if raw.get("amount") not in (None, "") else None
        if amount is None:
            amount = round(price * quantity, 2) if price > 0 and quantity > 0 else 0.0
        fee = _safe_float(raw.get("fee")) if raw.get("fee") not in (None, "") else None
        commission = _safe_float(raw.get("commission")) or 0.0
        stamp_tax = _safe_float(raw.get("stamp_tax")) or 0.0
        transfer_fee = _safe_float(raw.get("transfer_fee")) or 0.0
        other_fee = _safe_float(raw.get("other_fee")) or 0.0
        fee_total = _safe_float(raw.get("fee_total"))
        if fee_total is None:
            fee_total = fee if fee is not None else (commission + stamp_tax + transfer_fee + other_fee)
        if fee is None:
            fee = fee_total or None

        valid.append({
            "id": str(uuid.uuid4()),
            "code": code, "name": str(raw.get("name") or ""),
            "type": str(raw.get("type") or "stock"),
            "broker": str(raw.get("broker") or ""),
            "account": str(raw.get("sub_account") or raw.get("account") or ""),
            "broker_account": acc,
            "direction": direction, "entry_type": entry_type,
            "price": price, "quantity": quantity,
            "amount": amount, "fee": fee,
            "commission": commission, "stamp_tax": stamp_tax,
            "transfer_fee": transfer_fee, "other_fee": other_fee,
            "fee_total": fee_total,
            "net_amount": _safe_float(raw.get("net_amount")),
            "trade_id": str(raw.get("trade_id") or "") or None,
            "order_no": str(raw.get("order_no") or "") or None,
            "biz": str(raw.get("biz") or ""),
            "settle_date": str(raw.get("settle_date") or "") or None,
            "currency": str(raw.get("currency") or "CNY"),
            "trade_time": str(raw.get("trade_time") or "") or None,
            "raw": (str(raw.get("raw"))[:4000] if raw.get("raw") not in (None, "") else None),
            "source": source, "created_at": _now_iso(),
        })

    accounts = sorted({v["broker_account"] for v in valid if v["broker_account"]})
    if not accounts and default_account:
        accounts = [str(default_account).strip()]

    for v in valid:
        stat = by_account.setdefault(v["broker_account"], {
            "account": v["broker_account"], "broker": v["broker"],
            "inserted": 0, "failed": 0,
        })
        stat["inserted"] += 1
    for f in invalid:
        by_account.setdefault(str(f.get("account") or ""), {
            "account": str(f.get("account") or ""), "broker": "",
            "inserted": 0, "failed": 0,
        })["failed"] += 1

    insert_sql = (
        "INSERT INTO biz_trades "
        "(id, fk_user, trade_date, code, name, type, broker, account, direction, "
        "price, quantity, amount, fee, trade_time, source, created_at, "
        "broker_account, trade_id, order_no, biz, entry_type, settle_date, "
        "commission, stamp_tax, transfer_fee, other_fee, fee_total, net_amount, currency, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    def _params(v):
        return [v["id"], user_id, trade_date, v["code"], v["name"], v["type"],
                v["broker"], v["account"], v["direction"], v["price"],
                v["quantity"], v["amount"], v["fee"], v["trade_time"],
                v["source"], v["created_at"], v["broker_account"], v["trade_id"],
                v["order_no"], v["biz"], v["entry_type"], v["settle_date"],
                v["commission"], v["stamp_tax"], v["transfer_fee"], v["other_fee"],
                v["fee_total"], v["net_amount"], v["currency"], v["raw"]]

    if USE_MOCK_DATA:
        trades = _mock_trades.setdefault(user_id, [])
        if mode == "merge":
            ids = {v["trade_id"] for v in valid if v["trade_id"]}
            trades[:] = [t for t in trades if not (t.get("trade_id") and t["trade_id"] in ids)]
            deleted = 0
        else:
            keep = [t for t in trades if not (
                t["trade_date"] == trade_date and (
                    (t.get("broker_account") or "") in accounts or not (t.get("broker_account") or "")
                ))]
            deleted = len(trades) - len(keep)
            trades[:] = keep
        if not dry_run:
            for v in valid:
                v["trade_date"] = trade_date
                trades.append(v)
        return {"deleted": deleted, "inserted": 0 if dry_run else len(valid),
                "failed": invalid, "by_account": list(by_account.values()),
                "dry_run": bool(dry_run), "would_insert": len(valid) if dry_run else 0}

    _ensure_tables()
    db = get_biz_db()
    deleted = 0
    if dry_run:
        if mode == "merge":
            ids = [v["trade_id"] for v in valid if v["trade_id"]]
            for tid in ids:
                row = db.fetchone("SELECT count(*) FROM biz_trades WHERE fk_user=? AND trade_id=?", [user_id, tid])
                deleted += row[0] if row else 0
        else:
            ph = ",".join("?" * len(accounts)) if accounts else ""
            clause = (f"(broker_account IN ({ph}) OR broker_account='' OR broker_account IS NULL)"
                      if ph else "1=1")
            row = db.fetchone(
                f"SELECT count(*) FROM biz_trades WHERE fk_user=? AND trade_date=? AND {clause}",
                [user_id, trade_date] + accounts,
            )
            deleted = row[0] if row else 0
        return {"deleted": 0, "inserted": 0, "failed": invalid,
                "by_account": list(by_account.values()), "dry_run": True,
                "would_delete": deleted, "would_insert": len(valid)}

    if mode == "merge":
        for v in valid:
            if v["trade_id"]:
                deleted += db.execute(
                    "DELETE FROM biz_trades WHERE fk_user = ? AND trade_id = ?",
                    [user_id, v["trade_id"]],
                ).rowcount
    else:
        ph = ",".join("?" * len(accounts)) if accounts else ""
        clause = (f"(broker_account IN ({ph}) OR broker_account='' OR broker_account IS NULL)"
                  if ph else "1=1")
        deleted = db.execute(
            f"DELETE FROM biz_trades WHERE fk_user = ? AND trade_date = ? AND {clause}",
            [user_id, trade_date] + accounts,
        ).rowcount
    if valid:
        db.executemany(insert_sql, [_params(v) for v in valid])
    return {"deleted": deleted, "inserted": len(valid), "failed": invalid,
            "by_account": list(by_account.values()), "dry_run": False}


_TRADE_SELECT = (
    "SELECT id, fk_user, trade_date, code, name, type, broker, account, direction, "
    "price, quantity, amount, fee, trade_time, source, created_at, "
    "broker_account, trade_id, order_no, biz, entry_type, settle_date, "
    "commission, stamp_tax, transfer_fee, other_fee, fee_total, net_amount, currency, raw "
    "FROM biz_trades"
)


def _trade_row(r: tuple) -> dict:
    def f(v):
        return None if v is None else float(v)
    return {
        "id": r[0], "fk_user": r[1], "trade_date": r[2], "code": r[3], "name": r[4],
        "type": r[5], "broker": r[6] or "", "account": r[7] or "",
        "direction": r[8], "price": float(r[9]), "quantity": float(r[10]),
        "amount": f(r[11]), "fee": f(r[12]), "trade_time": r[13],
        "source": r[14] or "", "created_at": r[15],
        "broker_account": r[16] or "", "trade_id": r[17] or "",
        "order_no": r[18] or "", "biz": r[19] or "",
        "entry_type": r[20] or "trade", "settle_date": r[21],
        "commission": f(r[22]), "stamp_tax": f(r[23]), "transfer_fee": f(r[24]),
        "other_fee": f(r[25]), "fee_total": f(r[26]), "net_amount": f(r[27]),
        "currency": r[28] or "CNY", "raw": r[29],
    }


def get_trades(
    user_id: str,
    trade_date: Optional[str] = None,
    broker_account: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """查询成交记录；可按交易日 / 资金账号过滤。按 (日期, 时间, id) 升序。"""
    if USE_MOCK_DATA:
        trades = _mock_trades.get(user_id, [])
        if trade_date:
            trades = [t for t in trades if t["trade_date"] == trade_date]
        if broker_account:
            trades = [t for t in trades if (t.get("broker_account") or "") == broker_account]
        trades = sorted(trades, key=lambda t: (t["trade_date"], t.get("trade_time") or "", t["id"]))
        return trades[:limit] if limit else trades
    _ensure_tables()
    db = get_biz_db()
    where, params = ["fk_user = ?"], [user_id]
    if trade_date:
        where.append("trade_date = ?")
        params.append(trade_date)
    if broker_account:
        where.append("broker_account = ?")
        params.append(broker_account)
    sql = f"{_TRADE_SELECT} WHERE {' AND '.join(where)} ORDER BY trade_date, trade_time, id"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return [_trade_row(r) for r in db.fetchall(sql, params)]


def list_trade_dates(user_id: str) -> list[str]:
    """列出该用户所有有成交记录的交易日（升序去重）。"""
    if USE_MOCK_DATA:
        return sorted({t["trade_date"] for t in _mock_trades.get(user_id, [])})
    _ensure_tables()
    db = get_biz_db()
    rows = db.fetchall(
        "SELECT DISTINCT trade_date FROM biz_trades WHERE fk_user = ? ORDER BY trade_date",
        [user_id],
    )
    return [r[0] for r in rows]
