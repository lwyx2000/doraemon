"""外部上传接口调用留痕（holdings/import/api、trades/import）。

每次无鉴权外部调用都写一行 biz_import_log：归属用户、接口类型、来源、券商 code、
成败统计（added/updated/deleted/inserted/failed）与失败摘要，供持仓页「上传记录」展示。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from database.sqlite_connection import get_biz_db
from core.config import USE_MOCK_DATA

_TABLES_READY = False

# mock 模式内存存储
_mock_logs: dict[str, list[dict]] = {}


def _ensure_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY or USE_MOCK_DATA:
        return
    db = get_biz_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_import_log (
            id          VARCHAR PRIMARY KEY,
            fk_user BIGINT NOT NULL,
            endpoint    VARCHAR(20) NOT NULL,   -- holdings / trades
            source      VARCHAR(50) DEFAULT '',
            broker_code VARCHAR(20) DEFAULT '',
            broker      VARCHAR(50) DEFAULT '',
            total       INTEGER DEFAULT 0,
            added       INTEGER DEFAULT 0,
            updated     INTEGER DEFAULT 0,
            deleted     INTEGER DEFAULT 0,
            inserted    INTEGER DEFAULT 0,
            failed      INTEGER DEFAULT 0,
            fail_detail VARCHAR,                -- 失败条目摘要(JSON)
            created_at  VARCHAR
        )
        """
    )
    _TABLES_READY = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sum_result(result: dict) -> int:
    return (
        result.get("added", 0)
        + result.get("updated", 0)
        + result.get("inserted", 0)
        + result.get("deleted", 0)
        + len(result.get("failed", []))
    )


def add_import_log(
    user_id: str,
    endpoint: str,
    source: str,
    broker_code: str,
    broker: str,
    result: dict,
    total: int | None = None,
) -> dict:
    """写入一条上传调用留痕。fail_detail 取失败条目前 20 条摘要。"""
    failed = result.get("failed", []) or []
    fail_detail = json.dumps(failed[:20], ensure_ascii=False) if failed else ""
    item = {
        "id": str(uuid.uuid4()),
        "fk_user": user_id,
        "endpoint": endpoint,
        "source": source or "",
        "broker_code": broker_code or "",
        "broker": broker or "",
        "total": total if total is not None else _sum_result(result),
        "added": result.get("added", 0),
        "updated": result.get("updated", 0),
        "deleted": result.get("deleted", 0),
        "inserted": result.get("inserted", 0),
        "failed": len(failed),
        "fail_detail": fail_detail,
        "created_at": _now_iso(),
    }
    if USE_MOCK_DATA:
        _mock_logs.setdefault(user_id, []).append(item)
        return item
    _ensure_tables()
    db = get_biz_db()
    db.execute(
        "INSERT INTO biz_import_log "
        "(id, fk_user, endpoint, source, broker_code, broker, total, added, updated, "
        "deleted, inserted, failed, fail_detail, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            item["id"], user_id, item["endpoint"], item["source"], item["broker_code"],
            item["broker"], item["total"], item["added"], item["updated"],
            item["deleted"], item["inserted"], item["failed"], item["fail_detail"],
            item["created_at"],
        ],
    )
    return item


def list_import_logs(user_id: str, limit: int = 100) -> list[dict]:
    if USE_MOCK_DATA:
        return sorted(_mock_logs.get(user_id, []), key=lambda x: x["created_at"], reverse=True)[:limit]
    _ensure_tables()
    db = get_biz_db()
    rows = db.fetchall(
        "SELECT id, fk_user, endpoint, source, broker_code, broker, total, added, "
        "updated, deleted, inserted, failed, fail_detail, created_at "
        "FROM biz_import_log WHERE fk_user = ? ORDER BY created_at DESC LIMIT ?",
        [user_id, limit],
    )
    cols = [
        "id", "fk_user", "endpoint", "source", "broker_code", "broker", "total",
        "added", "updated", "deleted", "inserted", "failed", "fail_detail", "created_at",
    ]
    return [dict(zip(cols, r)) for r in rows]
