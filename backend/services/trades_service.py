"""成交记录服务 — 无鉴权外部接口写入的成交数据独立存储（biz_trades）。

设计（按用户要求）：
- 每张表按 (fk_user, trade_date) 维度：上传某交易日数据 = 先删除该用户该日全部旧记录，
  再全量插入（覆盖）；新 trade_date 直接全量新增，互不干扰；
- 历史交易日数据不被覆盖（只覆盖同日期）；
- 历史（旧）成交数据保留在表中，不删除（与持仓覆盖历史 biz_holdings_history 思路一致，
  但成交是「按日期全量覆盖」而非「逐行覆盖」，故成交表本身即留存各日期全量快照）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from database.sqlite_connection import get_biz_db
from core.config import USE_MOCK_DATA

_TABLES_READY = False
_mock_trades: dict[str, list[dict]] = {}

# 成交方向枚举
TRADE_DIRECTIONS: set[str] = {"buy", "sell"}


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
            direction    VARCHAR(10) NOT NULL,    -- buy / sell
            price        DOUBLE NOT NULL,
            quantity     DOUBLE NOT NULL,
            amount       DOUBLE,                  -- 成交额（价×量）
            fee          DOUBLE,                  -- 手续费
            trade_time   VARCHAR(20),             -- 成交时间（可选，YYYY-MM-DD HH:MM:SS）
            source       VARCHAR(50) DEFAULT '',  -- 来源程序
            created_at   VARCHAR
        )
        """
    )
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
    user_id: str, trade_date: str, items: list[dict], source: str = ""
) -> dict:
    """按 (user, trade_date) 覆盖：删除该用户该日旧记录后全量插入。

    返回 {deleted, inserted, failed}。新 trade_date 因无旧记录，deleted=0、直接新增。
    校验失败的行进入 failed（不中断其余行写入）。
    """
    invalid: list[dict] = []
    valid: list[dict] = []
    for idx, raw in enumerate(items):
        code = str(raw.get("code") or "").strip()
        direction = str(raw.get("direction") or "").strip().lower()
        price = _safe_float(raw.get("price"))
        quantity = _safe_float(raw.get("quantity"))
        if not code:
            invalid.append({"index": idx, "code": code, "reason": "缺少 code"})
            continue
        if direction not in TRADE_DIRECTIONS:
            invalid.append({"index": idx, "code": code, "reason": f"未知 direction: {direction}（须 buy/sell）"})
            continue
        if price is None or quantity is None or price <= 0 or quantity <= 0:
            invalid.append({"index": idx, "code": code, "reason": "price/quantity 须为正数值"})
            continue
        amount = raw.get("amount")
        amount = _safe_float(amount) if amount not in (None, "") else round(price * quantity, 2)
        fee = raw.get("fee")
        fee = _safe_float(fee) if fee not in (None, "") else None
        valid.append({
            "id": str(uuid.uuid4()),
            "code": code,
            "name": str(raw.get("name") or ""),
            "type": str(raw.get("type") or "stock"),
            "broker": str(raw.get("broker") or ""),
            "account": str(raw.get("account") or ""),
            "direction": direction,
            "price": price,
            "quantity": quantity,
            "amount": amount,
            "fee": fee,
            "trade_time": str(raw.get("trade_time") or "") or None,
            "source": source,
            "created_at": _now_iso(),
        })

    if USE_MOCK_DATA:
        trades = _mock_trades.setdefault(user_id, [])
        # 覆盖：删旧插新
        trades[:] = [t for t in trades if t["trade_date"] != trade_date]
        for v in valid:
            v["trade_date"] = trade_date
            trades.append(v)
        return {"deleted": 0, "inserted": len(valid), "failed": invalid}

    _ensure_tables()
    db = get_biz_db()
    del_cur = db.execute(
        "DELETE FROM biz_trades WHERE fk_user = ? AND trade_date = ?",
        [user_id, trade_date],
    )
    deleted = del_cur.rowcount
    if valid:
        db.executemany(
            "INSERT INTO biz_trades "
            "(id, fk_user, trade_date, code, name, type, broker, account, direction, "
            "price, quantity, amount, fee, trade_time, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [v["id"], user_id, trade_date, v["code"], v["name"], v["type"],
                 v["broker"], v["account"], v["direction"], v["price"],
                 v["quantity"], v["amount"], v["fee"], v["trade_time"],
                 v["source"], v["created_at"]]
                for v in valid
            ],
        )
    return {"deleted": deleted, "inserted": len(valid), "failed": invalid}


def get_trades(user_id: str, trade_date: Optional[str] = None) -> list[dict]:
    """查询成交记录；trade_date 非空时按日过滤。按 (交易日期, 成交时间, id) 升序。"""
    if USE_MOCK_DATA:
        trades = _mock_trades.get(user_id, [])
        if trade_date:
            trades = [t for t in trades if t["trade_date"] == trade_date]
        return sorted(trades, key=lambda t: (t["trade_date"], t.get("trade_time") or "", t["id"]))
    _ensure_tables()
    db = get_biz_db()
    if trade_date:
        rows = db.fetchall(
            "SELECT id, fk_user, trade_date, code, name, type, broker, account, direction, "
            "price, quantity, amount, fee, trade_time, source, created_at "
            "FROM biz_trades WHERE fk_user = ? AND trade_date = ? "
            "ORDER BY trade_time, id",
            [user_id, trade_date],
        )
    else:
        rows = db.fetchall(
            "SELECT id, fk_user, trade_date, code, name, type, broker, account, direction, "
            "price, quantity, amount, fee, trade_time, source, created_at "
            "FROM biz_trades WHERE fk_user = ? ORDER BY trade_date, trade_time, id",
            [user_id],
        )
    return [
        {
            "id": r[0], "fk_user": r[1], "trade_date": r[2], "code": r[3], "name": r[4],
            "type": r[5], "broker": r[6] or "", "account": r[7] or "",
            "direction": r[8], "price": float(r[9]), "quantity": float(r[10]),
            "amount": None if r[11] is None else float(r[11]),
            "fee": None if r[12] is None else float(r[12]),
            "trade_time": r[13], "source": r[14] or "", "created_at": r[15],
        }
        for r in rows
    ]


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
