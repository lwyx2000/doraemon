"""Broker account service — 用户自定义券商账号（持仓页筛选/导入可选）。

与 holdings_service 一致：
- mock 模式使用进程内存存储；
- DuckDB 模式首次使用时懒创建 biz_broker_accounts 表。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from database.connection import get_db
from core.config import USE_MOCK_DATA

_TABLES_READY = False

# mock 模式内存存储
_mock_accounts: dict[str, list[dict]] = {}


# ============================================================
# DuckDB 懒建表
# ============================================================

def _ensure_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY or USE_MOCK_DATA:
        return
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_broker_accounts (
            id         VARCHAR PRIMARY KEY,
            fk_users    UUID NOT NULL,
            broker     VARCHAR(50) NOT NULL,
            account    VARCHAR(50) DEFAULT '',
            created_at VARCHAR,
            updated_at VARCHAR
        )
        """
    )
    _TABLES_READY = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# CRUD
# ============================================================

def _load_accounts(user_id: str) -> list[dict]:
    if USE_MOCK_DATA:
        return _mock_accounts.setdefault(user_id, [])
    _ensure_tables()
    db = get_db()
    rows = db.fetchall(
        "SELECT id, broker, account, created_at, updated_at "
        "FROM biz_broker_accounts WHERE fk_users = ? ORDER BY created_at",
        [user_id],
    )
    return [
        {"id": r[0], "broker": r[1], "account": r[2] or "", "created_at": r[3], "updated_at": r[4]}
        for r in rows
    ]


def _save_account(user_id: str, item: dict) -> None:
    if USE_MOCK_DATA:
        accounts = _mock_accounts.setdefault(user_id, [])
        for i, a in enumerate(accounts):
            if a["id"] == item["id"]:
                accounts[i] = item
                return
        accounts.append(item)
        return
    _ensure_tables()
    db = get_db()
    db.execute("DELETE FROM biz_broker_accounts WHERE id = ?", [item["id"]])
    db.execute(
        "INSERT INTO biz_broker_accounts (id, fk_users, broker, account, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [item["id"], user_id, item["broker"], item["account"], item["created_at"], item["updated_at"]],
    )


def list_broker_accounts(user_id: str) -> list[dict]:
    return _load_accounts(user_id)


def create_broker_account(user_id: str, broker: str, account: str = "") -> dict | None:
    """新增券商账号；同 (broker, account) 已存在时返回 None（路由返回 409）。"""
    broker = (broker or "").strip()
    account = (account or "").strip()
    if not broker:
        return None
    for a in _load_accounts(user_id):
        if a["broker"] == broker and (a["account"] or "") == account:
            return None
    now = _now_iso()
    item = {"id": str(uuid.uuid4()), "broker": broker, "account": account, "created_at": now, "updated_at": now}
    _save_account(user_id, item)
    return item


def update_broker_account(user_id: str, account_id: str, broker: str, account: str = "") -> dict | None:
    """更新券商账号；不存在或 broker 为空时返回 None。"""
    broker = (broker or "").strip()
    account = (account or "").strip()
    if not broker:
        return None
    for a in _load_accounts(user_id):
        if a["id"] == account_id:
            a["broker"] = broker
            a["account"] = account
            a["updated_at"] = _now_iso()
            _save_account(user_id, a)
            return a
    return None


def delete_broker_account(user_id: str, account_id: str) -> bool:
    accounts = _load_accounts(user_id)
    if USE_MOCK_DATA:
        before = len(accounts)
        accounts[:] = [a for a in accounts if a["id"] != account_id]
        return len(accounts) < before
    _ensure_tables()
    db = get_db()
    row = db.fetchone(
        "SELECT count(*) FROM biz_broker_accounts WHERE id = ? AND fk_users = ?",
        [account_id, user_id],
    )
    if not row or row[0] == 0:
        return False
    db.execute("DELETE FROM biz_broker_accounts WHERE id = ?", [account_id])
    return True
