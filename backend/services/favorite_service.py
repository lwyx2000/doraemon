"""Favorite service — user watchlist items (mock or DuckDB)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from database.connection import get_db
from core.config import USE_MOCK_DATA

# In-memory storage for mock mode: list of favorite dicts.
_mock_favorites: list[dict] = []


def get_favorites(user_id: str) -> list[dict]:
    """Return all favorites belonging to ``user_id``."""
    if USE_MOCK_DATA:
        return [f for f in _mock_favorites if f.get("user_id") == user_id]

    db = get_db()
    rows = db.fetchall(
        "SELECT pk_favorites AS id, fk_user AS user_id, code, name, type, note, added_at "
        "FROM biz_favorites WHERE fk_user = ? ORDER BY added_at DESC",
        [user_id],
    )
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "code": row[2],
            "name": row[3],
            "type": row[4],
            "note": row[5],
            "added_at": row[6],
        }
        for row in rows
    ]


def add_favorite(
    user_id: str,
    code: str,
    name: str,
    type: str,
    note: str | None = None,
) -> dict:
    """Create a favorite item and persist it (mock list or DB)."""
    favorite = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "code": code,
        "name": name,
        "type": type,
        "note": note,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }

    if USE_MOCK_DATA:
        _mock_favorites.append(favorite)
        return favorite

    db = get_db()
    db.execute(
        "INSERT INTO biz_favorites "
        "(pk_favorites, fk_user, code, name, type, note, added_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            favorite["id"],
            user_id,
            code,
            name,
            type,
            note,
            favorite["added_at"],
        ],
    )
    return favorite


def delete_favorite(user_id: str, favorite_id: str) -> bool:
    """Delete a favorite by id; return True if a row was removed."""
    if USE_MOCK_DATA:
        for index, fav in enumerate(_mock_favorites):
            if fav.get("id") == favorite_id and fav.get("user_id") == user_id:
                _mock_favorites.pop(index)
                return True
        return False

    db = get_db()
    existing = db.fetchone(
        "SELECT pk_favorites FROM biz_favorites WHERE pk_favorites = ? AND fk_user = ?",
        [favorite_id, user_id],
    )
    if existing is None:
        return False
    db.execute(
        "DELETE FROM biz_favorites WHERE pk_favorites = ? AND fk_user = ?",
        [favorite_id, user_id],
    )
    return True
