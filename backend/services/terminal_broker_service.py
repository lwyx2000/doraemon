"""终端 / 券商管理 service（2026-11 重构）。

数据模型（见 database/init_sqlite.py 静态 DDL）：
- biz_terminals(id, fk_user, name, remark, created_at, updated_at)：一个终端（设备/渠道）可能挂多个券商；
- biz_brokers(id, fk_terminal, name, account, remark, created_at, updated_at)：券商由**客户端自传 account**
  （不再由后端生成 BRK-xxxx code）作为主标识，并补充 name（券商名）/ remark（备注）。

与 holdings/import 一致：
- mock 模式使用进程内存存储；
- DuckDB 模式表由 init_sqlite.py 静态 DDL 建好（biz_terminals / biz_brokers），本 service 直接读写。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from database.sqlite_connection import get_biz_db
from core.config import USE_MOCK_DATA

DEFAULT_TERMINAL_NAME = "默认终端"

# mock 模式内存存储
_mock_terminals: dict[str, list[dict]] = {}
_mock_brokers: dict[str, list[dict]] = {}


def _now_iso() -> str:
    # 与项目约定一致：后端时间串为容器 UTC naive 串（YYYY-MM-DD HH:MM:SS 由 isoformat 产生）
    return datetime.now().isoformat()


def _ensure_default_terminal_mock(user_id: str) -> str:
    """mock 模式：确保用户有一个默认终端，返回其 id。"""
    terminals = _mock_terminals.setdefault(user_id, [])
    for t in terminals:
        if t["name"] == DEFAULT_TERMINAL_NAME:
            return t["id"]
    tid = str(uuid.uuid4())
    terminals.append({
        "id": tid, "fk_user": user_id, "name": DEFAULT_TERMINAL_NAME,
        "remark": "", "created_at": _now_iso(), "updated_at": _now_iso(),
    })
    return tid


# ============================================================
# 终端 CRUD
# ============================================================

def get_or_create_default_terminal(user_id: str) -> dict:
    """保证每个用户至少有一个默认终端；返回该终端 dict。"""
    if USE_MOCK_DATA:
        tid = _ensure_default_terminal_mock(user_id)
        return next(t for t in _mock_terminals[user_id] if t["id"] == tid)
    db = get_biz_db()
    row = db.fetchone(
        "SELECT id, fk_user, name, remark, created_at, updated_at "
        "FROM biz_terminals WHERE fk_user = ? AND name = ?",
        [user_id, DEFAULT_TERMINAL_NAME],
    )
    if row:
        return _row_to_terminal(row)
    now = _now_iso()
    tid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO biz_terminals (id, fk_user, name, remark, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [tid, user_id, DEFAULT_TERMINAL_NAME, "", now, now],
    )
    return {
        "id": tid, "fk_user": user_id, "name": DEFAULT_TERMINAL_NAME,
        "remark": "", "created_at": now, "updated_at": now,
    }


def _row_to_terminal(r: tuple) -> dict:
    return {
        "id": r[0], "fk_user": str(r[1]), "name": r[2], "remark": r[3] or "",
        "created_at": r[4], "updated_at": r[5],
    }


def _row_to_broker(r: tuple) -> dict:
    return {
        "id": r[0], "fk_terminal": r[1], "name": r[2], "account": r[3] or "",
        "remark": r[4] or "", "created_at": r[5], "updated_at": r[6],
    }


def list_terminals(user_id: str) -> list[dict]:
    """列出用户所有终端，每个终端内嵌其券商列表（按 created_at 升序）。"""
    if USE_MOCK_DATA:
        terminals = [t.copy() for t in _mock_terminals.get(user_id, [])]
        brokers = _mock_brokers.get(user_id, [])
        by_terminal: dict[str, list[dict]] = {}
        for b in sorted(brokers, key=lambda x: x.get("created_at") or ""):
            by_terminal.setdefault(b["fk_terminal"], []).append(b.copy())
        for t in terminals:
            t["brokers"] = by_terminal.get(t["id"], [])
        return sorted(terminals, key=lambda x: x.get("created_at") or "")
    db = get_biz_db()
    rows = db.fetchall(
        "SELECT id, fk_user, name, remark, created_at, updated_at "
        "FROM biz_terminals WHERE fk_user = ? ORDER BY created_at",
        [user_id],
    )
    terminals = [_row_to_terminal(r) for r in rows]
    for t in terminals:
        brows = db.fetchall(
            "SELECT id, fk_terminal, name, account, remark, created_at, updated_at "
            "FROM biz_brokers WHERE fk_terminal = ? ORDER BY created_at",
            [t["id"]],
        )
        t["brokers"] = [_row_to_broker(r) for r in brows]
    return terminals


def create_terminal(user_id: str, name: str, remark: str = "") -> dict | None:
    """新增终端；同名（精确）已存在返回 None（路由 409）。"""
    name = (name or "").strip()
    remark = (remark or "").strip()
    if not name:
        return None
    existing = list_terminals(user_id)
    names = {t["name"] for t in existing}
    if name in names:
        return None
    now = _now_iso()
    tid = str(uuid.uuid4())
    if USE_MOCK_DATA:
        item = {"id": tid, "fk_user": user_id, "name": name, "remark": remark, "created_at": now, "updated_at": now}
        _mock_terminals.setdefault(user_id, []).append(item)
        item = item.copy()
        item["brokers"] = []
        return item
    db = get_biz_db()
    db.execute(
        "INSERT INTO biz_terminals (id, fk_user, name, remark, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [tid, user_id, name, remark, now, now],
    )
    return {"id": tid, "fk_user": user_id, "name": name, "remark": remark, "created_at": now, "updated_at": now, "brokers": []}


def update_terminal(user_id: str, terminal_id: str, name: str, remark: str = "") -> dict | None:
    """更新终端；不存在或 name 为空返回 None。"""
    name = (name or "").strip()
    remark = (remark or "").strip()
    if not name:
        return None
    if USE_MOCK_DATA:
        terminals = _mock_terminals.get(user_id, [])
        for t in terminals:
            if t["id"] == terminal_id:
                t["name"] = name
                t["remark"] = remark
                t["updated_at"] = _now_iso()
                out = t.copy()
                out["brokers"] = [b.copy() for b in _mock_brokers.get(user_id, []) if b["fk_terminal"] == terminal_id]
                return out
        return None
    db = get_biz_db()
    row = db.fetchone("SELECT count(*) FROM biz_terminals WHERE id = ? AND fk_user = ?", [terminal_id, user_id])
    if not row or row[0] == 0:
        return None
    db.execute(
        "UPDATE biz_terminals SET name = ?, remark = ?, updated_at = ? WHERE id = ?",
        [name, remark, _now_iso(), terminal_id],
    )
    return list_terminals(user_id) and next((t for t in list_terminals(user_id) if t["id"] == terminal_id), None)


def delete_terminal(user_id: str, terminal_id: str) -> bool:
    """删除终端及其下全部券商（级联）。不存在返回 False。"""
    if USE_MOCK_DATA:
        terminals = _mock_terminals.get(user_id, [])
        before = len(terminals)
        terminals[:] = [t for t in terminals if t["id"] != terminal_id]
        if len(terminals) < before:
            _mock_brokers[user_id] = [b for b in _mock_brokers.get(user_id, []) if b["fk_terminal"] != terminal_id]
            return True
        return False
    db = get_biz_db()
    row = db.fetchone("SELECT count(*) FROM biz_terminals WHERE id = ? AND fk_user = ?", [terminal_id, user_id])
    if not row or row[0] == 0:
        return False
    db.execute("DELETE FROM biz_brokers WHERE fk_terminal = ?", [terminal_id])
    db.execute("DELETE FROM biz_terminals WHERE id = ?", [terminal_id])
    return True


# ============================================================
# 券商 CRUD（account 为客户端自传主标识）
# ============================================================

def list_brokers(user_id: str, terminal_id: str | None = None) -> list[dict]:
    """列出用户券商；terminal_id 给定时只列该终端下券商，否则全部。"""
    if USE_MOCK_DATA:
        brokers = _mock_brokers.get(user_id, [])
        if terminal_id:
            brokers = [b for b in brokers if b["fk_terminal"] == terminal_id]
        return [b.copy() for b in sorted(brokers, key=lambda x: x.get("created_at") or "")]
    db = get_biz_db()
    if terminal_id:
        rows = db.fetchall(
            "SELECT b.id, b.fk_terminal, b.name, b.account, b.remark, b.created_at, b.updated_at "
            "FROM biz_brokers b JOIN biz_terminals t ON b.fk_terminal = t.id "
            "WHERE t.fk_user = ? AND b.fk_terminal = ? ORDER BY b.created_at",
            [user_id, terminal_id],
        )
    else:
        rows = db.fetchall(
            "SELECT b.id, b.fk_terminal, b.name, b.account, b.remark, b.created_at, b.updated_at "
            "FROM biz_brokers b JOIN biz_terminals t ON b.fk_terminal = t.id "
            "WHERE t.fk_user = ? ORDER BY b.created_at",
            [user_id],
        )
    return [_row_to_broker(r) for r in rows]


def _account_exists(user_id: str, account: str, exclude_id: str | None = None) -> bool:
    """同一用户内 account（主标识）唯一（大小写不敏感）。"""
    acc = account.strip().lower()
    if USE_MOCK_DATA:
        for b in _mock_brokers.get(user_id, []):
            if b["account"].strip().lower() == acc and b["id"] != exclude_id:
                return True
        return False
    db = get_biz_db()
    if exclude_id:
        row = db.fetchone(
            "SELECT count(*) FROM biz_brokers b JOIN biz_terminals t ON b.fk_terminal = t.id "
            "WHERE t.fk_user = ? AND lower(b.account) = ? AND b.id <> ?",
            [user_id, acc, exclude_id],
        )
    else:
        row = db.fetchone(
            "SELECT count(*) FROM biz_brokers b JOIN biz_terminals t ON b.fk_terminal = t.id "
            "WHERE t.fk_user = ? AND lower(b.account) = ?",
            [user_id, acc],
        )
    return bool(row and row[0] > 0)


def create_broker(user_id: str, terminal_id: str, name: str, account: str, remark: str = "") -> dict | None:
    """新增券商；account（客户端自传主标识）同用户已存在时返回 None（路由 409）。

    终端不存在（terminal_id 非法）返回 None（路由 404）。
    """
    name = (name or "").strip()
    account = (account or "").strip()
    remark = (remark or "").strip()
    if not name or not account:
        return None
    if _account_exists(user_id, account):
        return None
    # 校验终端归属
    if USE_MOCK_DATA:
        terminals = _mock_terminals.get(user_id, [])
        if not any(t["id"] == terminal_id for t in terminals):
            return None
    else:
        db = get_biz_db()
        row = db.fetchone("SELECT count(*) FROM biz_terminals WHERE id = ? AND fk_user = ?", [terminal_id, user_id])
        if not row or row[0] == 0:
            return None
    now = _now_iso()
    bid = str(uuid.uuid4())
    if USE_MOCK_DATA:
        item = {"id": bid, "fk_terminal": terminal_id, "name": name, "account": account, "remark": remark, "created_at": now, "updated_at": now}
        _mock_brokers.setdefault(user_id, []).append(item)
        return item.copy()
    db = get_biz_db()
    db.execute(
        "INSERT INTO biz_brokers (id, fk_terminal, name, account, remark, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [bid, terminal_id, name, account, remark, now, now],
    )
    return {"id": bid, "fk_terminal": terminal_id, "name": name, "account": account, "remark": remark, "created_at": now, "updated_at": now}


def update_broker(
    user_id: str,
    broker_id: str,
    terminal_id: str | None = None,
    name: str | None = None,
    account: str | None = None,
    remark: str | None = None,
) -> dict | None:
    """更新券商；不存在返回 None。account / name 为空视为不改（保留原值）。"""
    if USE_MOCK_DATA:
        brokers = _mock_brokers.get(user_id, [])
        for b in brokers:
            if b["id"] == broker_id:
                if terminal_id is not None:
                    b["fk_terminal"] = terminal_id
                if name is not None and name.strip():
                    b["name"] = name.strip()
                if account is not None and account.strip():
                    if _account_exists(user_id, account, exclude_id=broker_id):
                        return None
                    b["account"] = account.strip()
                if remark is not None:
                    b["remark"] = remark.strip()
                b["updated_at"] = _now_iso()
                return b.copy()
        return None
    db = get_biz_db()
    row = db.fetchone(
        "SELECT b.id FROM biz_brokers b JOIN biz_terminals t ON b.fk_terminal = t.id "
        "WHERE b.id = ? AND t.fk_user = ?",
        [broker_id, user_id],
    )
    if not row:
        return None
    # 读取现有值
    cur = db.fetchone(
        "SELECT fk_terminal, name, account, remark FROM biz_brokers WHERE id = ?",
        [broker_id],
    )
    new_terminal = terminal_id if terminal_id is not None else cur[0]
    new_name = name.strip() if (name is not None and name.strip()) else cur[1]
    new_account = account.strip() if (account is not None and account.strip()) else cur[2]
    new_remark = remark.strip() if remark is not None else (cur[3] or "")
    if new_account != cur[2] and _account_exists(user_id, new_account, exclude_id=broker_id):
        return None
    db.execute(
        "UPDATE biz_brokers SET fk_terminal = ?, name = ?, account = ?, remark = ?, updated_at = ? WHERE id = ?",
        [new_terminal, new_name, new_account, new_remark, _now_iso(), broker_id],
    )
    return {"id": broker_id, "fk_terminal": new_terminal, "name": new_name, "account": new_account, "remark": new_remark, "created_at": None, "updated_at": _now_iso()}


def delete_broker(user_id: str, broker_id: str) -> bool:
    """删除券商；不存在返回 False。"""
    if USE_MOCK_DATA:
        brokers = _mock_brokers.get(user_id, [])
        before = len(brokers)
        brokers[:] = [b for b in brokers if b["id"] != broker_id]
        return len(brokers) < before
    db = get_biz_db()
    row = db.fetchone(
        "SELECT b.id FROM biz_brokers b JOIN biz_terminals t ON b.fk_terminal = t.id "
        "WHERE b.id = ? AND t.fk_user = ?",
        [broker_id, user_id],
    )
    if not row:
        return False
    db.execute("DELETE FROM biz_brokers WHERE id = ?", [broker_id])
    return True


# ============================================================
# 上传接口解析
# ============================================================

def get_broker_by_account(user_id: str, account: str) -> dict | None:
    """按 account（客户端自传主标识）查找该用户下的券商；不存在返回 None。

    兼容历史：旧外部上传用 broker_code（BRK-xxxx），迁移时已写入 account，
    故直接以 account 解析即可命中历史数据。
    """
    account = (account or "").strip()
    if not account:
        return None
    if USE_MOCK_DATA:
        for b in _mock_brokers.get(user_id, []):
            if b["account"].strip().lower() == account.lower():
                return b.copy()
        return None
    db = get_biz_db()
    row = db.fetchone(
        "SELECT b.id, b.fk_terminal, b.name, b.account, b.remark, b.created_at, b.updated_at "
        "FROM biz_brokers b JOIN biz_terminals t ON b.fk_terminal = t.id "
        "WHERE t.fk_user = ? AND lower(b.account) = ?",
        [user_id, account.lower()],
    )
    return _row_to_broker(row) if row else None


def resolve_or_create_broker_for_upload(
    user_id: str,
    account: str,
    name: str | None = None,
    remark: str | None = None,
    terminal_id: str | None = None,
) -> dict | None:
    """上传接口券商解析：account 命中则复用（可选回写 name/remark），否则按 account 自动创建。

    - account 为空 → None（上传应整批 failed）；
    - 未指定 terminal_id → 落默认终端（自动保底创建）；
    - 新券商 name 缺省取 account。
    返回券商 dict。
    """
    account = (account or "").strip()
    if not account:
        return None
    existing = get_broker_by_account(user_id, account)
    if existing:
        # 可选回写 name / remark（仅当调用方提供且当前为空/不同）
        upd_name = None
        upd_remark = None
        if name and name.strip() and not existing["name"]:
            upd_name = name.strip()
        if remark is not None and remark.strip() and not existing["remark"]:
            upd_remark = remark.strip()
        if upd_name or upd_remark is not None:
            return update_broker(user_id, existing["id"], name=upd_name, remark=upd_remark)
        return existing
    # 不存在 → 自动创建
    tid = terminal_id or get_or_create_default_terminal(user_id)["id"]
    broker_name = (name or "").strip() or account
    return create_broker(user_id, tid, broker_name, account, remark or "")
