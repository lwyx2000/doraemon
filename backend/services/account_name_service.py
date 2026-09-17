"""Account name service — 用户自定义账户名（普通/两融/信用等），独立于券商表。

与 broker_account_service 一致：
- mock 模式使用进程内存存储；
- DuckDB 模式首次使用时懒创建 biz_account_names 表。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from database.connection import get_db
from core.config import USE_MOCK_DATA

_TABLES_READY = False

# mock 模式内存存储
_mock_account_names: dict[str, list[dict]] = {}


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
        CREATE TABLE IF NOT EXISTS biz_account_names (
            id         VARCHAR PRIMARY KEY,
            fk_user BIGINT NOT NULL,
            name       VARCHAR(50) NOT NULL,
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

def _load_names(user_id: str) -> list[dict]:
    if USE_MOCK_DATA:
        return _mock_account_names.setdefault(user_id, [])
    _ensure_tables()
    db = get_db()
    rows = db.fetchall(
        "SELECT id, name, created_at, updated_at "
        "FROM biz_account_names WHERE fk_user = ? ORDER BY created_at",
        [user_id],
    )
    return [
        {"id": r[0], "name": r[1], "created_at": r[2], "updated_at": r[3]}
        for r in rows
    ]


def _save_name(user_id: str, item: dict) -> None:
    if USE_MOCK_DATA:
        names = _mock_account_names.setdefault(user_id, [])
        for i, a in enumerate(names):
            if a["id"] == item["id"]:
                names[i] = item
                return
        names.append(item)
        return
    _ensure_tables()
    db = get_db()
    db.execute("DELETE FROM biz_account_names WHERE id = ?", [item["id"]])
    db.execute(
        "INSERT INTO biz_account_names (id, fk_user, name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [item["id"], user_id, item["name"], item["created_at"], item["updated_at"]],
    )


def list_account_names(user_id: str) -> list[dict]:
    return _load_names(user_id)


def create_account_name(user_id: str, name: str) -> dict | None:
    """新增账户名；同名已存在时返回 None（路由返回 409）。"""
    name = (name or "").strip()
    if not name:
        return None
    for a in _load_names(user_id):
        if a["name"] == name:
            return None
    now = _now_iso()
    item = {"id": str(uuid.uuid4()), "name": name, "created_at": now, "updated_at": now}
    _save_name(user_id, item)
    return item


def update_account_name(user_id: str, name_id: str, name: str) -> dict | None:
    """更新账户名；不存在或 name 为空时返回 None。"""
    name = (name or "").strip()
    if not name:
        return None
    for a in _load_names(user_id):
        if a["id"] == name_id:
            a["name"] = name
            a["updated_at"] = _now_iso()
            _save_name(user_id, a)
            return a
    return None


def delete_account_name(user_id: str, name_id: str) -> bool:
    names = _load_names(user_id)
    if USE_MOCK_DATA:
        before = len(names)
        names[:] = [a for a in names if a["id"] != name_id]
        return len(names) < before
    _ensure_tables()
    db = get_db()
    row = db.fetchone(
        "SELECT count(*) FROM biz_account_names WHERE id = ? AND fk_user = ?",
        [name_id, user_id],
    )
    if not row or row[0] == 0:
        return False
    db.execute("DELETE FROM biz_account_names WHERE id = ?", [name_id])
    return True
