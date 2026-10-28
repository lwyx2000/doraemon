"""Broker account service — 用户自定义券商账号（持仓页筛选/导入可选）。

与 holdings_service 一致：
- mock 模式使用进程内存存储；
- DuckDB 模式首次使用时懒创建 biz_broker_accounts 表。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from database.sqlite_connection import get_biz_db
from core.config import USE_MOCK_DATA

_TABLES_READY = False

# mock 模式内存存储
_mock_accounts: dict[str, list[dict]] = {}


# ============================================================
# DuckDB 懒建表
# ============================================================

def _generate_code(existing: set[str]) -> str:
    """生成每用户唯一的券商 code：BRK- + 6 位大写 hex。"""
    for _ in range(20):
        code = "BRK-" + uuid.uuid4().hex[:6].upper()
        if code not in existing:
            return code
    return "BRK-" + uuid.uuid4().hex[:8].upper()  # 极端兜底


def _ensure_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY or USE_MOCK_DATA:
        return
    db = get_biz_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_broker_accounts (
            id         VARCHAR PRIMARY KEY,
            fk_user BIGINT NOT NULL,
            broker     VARCHAR(50) NOT NULL,
            account    VARCHAR(50) DEFAULT '',
            code       VARCHAR(20) DEFAULT '',
            created_at VARCHAR,
            updated_at VARCHAR
        )
        """
    )
    # 兼容老表：补 code 列（已存在则忽略），并回填空 code
    try:
        db.execute("ALTER TABLE biz_broker_accounts ADD COLUMN code VARCHAR(20) DEFAULT ''")
    except Exception:
        pass
    _backfill_codes()
    _TABLES_READY = True


def _backfill_codes() -> None:
    """为历史空 code 行生成每用户唯一的 code（幂等，仅处理空值）。"""
    db = get_biz_db()
    rows = db.fetchall(
        "SELECT id, fk_user FROM biz_broker_accounts WHERE code IS NULL OR code = ''",
        [],
    )
    if not rows:
        return
    used_by_user: dict[str, set[str]] = {}
    for rid, fk_user in rows:
        used = used_by_user.setdefault(fk_user, set())
        for r in db.fetchall(
            "SELECT code FROM biz_broker_accounts WHERE fk_user = ? AND code <> ''",
            [fk_user],
        ):
            used.add(r[0])
    for rid, fk_user in rows:
        used = used_by_user.setdefault(fk_user, set())
        code = _generate_code(used)
        used.add(code)
        db.execute("UPDATE biz_broker_accounts SET code = ? WHERE id = ?", [code, rid])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# CRUD
# ============================================================

def _load_accounts(user_id: str) -> list[dict]:
    if USE_MOCK_DATA:
        return _mock_accounts.setdefault(user_id, [])
    _ensure_tables()
    db = get_biz_db()
    rows = db.fetchall(
        "SELECT id, broker, account, code, created_at, updated_at "
        "FROM biz_broker_accounts WHERE fk_user = ? ORDER BY created_at",
        [user_id],
    )
    return [
        {
            "id": r[0], "broker": r[1], "account": r[2] or "", "code": r[3] or "",
            "created_at": r[4], "updated_at": r[5],
        }
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
    db = get_biz_db()
    db.execute("DELETE FROM biz_broker_accounts WHERE id = ?", [item["id"]])
    db.execute(
        "INSERT INTO biz_broker_accounts (id, fk_user, broker, account, code, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [item["id"], user_id, item["broker"], item["account"], item.get("code", ""), item["created_at"], item["updated_at"]],
    )


def list_broker_accounts(user_id: str) -> list[dict]:
    return _load_accounts(user_id)


def get_broker_by_code(user_id: str, code: str) -> dict | None:
    """按 code 查找该用户下的券商；不存在/不匹配返回 None。"""
    code = (code or "").strip()
    if not code:
        return None
    for a in _load_accounts(user_id):
        if a.get("code") == code:
            return a
    return None


def create_broker_account(user_id: str, broker: str, account: str = "") -> dict | None:
    """新增券商账号；同 (broker, account) 已存在时返回 None（路由返回 409）。
    自动生成每用户唯一的券商 code（BRK- + 6 位 hex）。"""
    broker = (broker or "").strip()
    account = (account or "").strip()
    if not broker:
        return None
    existing = _load_accounts(user_id)
    for a in existing:
        if a["broker"] == broker and (a["account"] or "") == account:
            return None
    now = _now_iso()
    used = {a["code"] for a in existing if a.get("code")}
    code = _generate_code(used)
    item = {"id": str(uuid.uuid4()), "broker": broker, "account": account, "code": code, "created_at": now, "updated_at": now}
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
    db = get_biz_db()
    row = db.fetchone(
        "SELECT count(*) FROM biz_broker_accounts WHERE id = ? AND fk_user = ?",
        [account_id, user_id],
    )
    if not row or row[0] == 0:
        return False
    db.execute("DELETE FROM biz_broker_accounts WHERE id = ?", [account_id])
    return True
