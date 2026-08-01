"""Portfolio service — user portfolios and portfolio items (mock or DuckDB)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from database.connection import get_db
from core.config import USE_MOCK_DATA

# In-memory storage for mock mode.
# user_id -> list of portfolio records.
_mock_portfolios: dict[str, list[dict]] = {}
# portfolio_id -> list of portfolio item records.
_mock_portfolio_items: dict[str, list[dict]] = {}


def get_portfolios(user_id: str) -> list[dict]:
    """Return all portfolios belonging to ``user_id``."""
    if USE_MOCK_DATA:
        return _mock_portfolios.get(user_id, [])

    db = get_db()
    rows = db.fetchall(
        "SELECT id, user_id, name, created_at "
        "FROM biz_portfolios WHERE user_id = ? ORDER BY created_at DESC",
        [user_id],
    )
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "name": row[2],
            "created_at": row[3],
        }
        for row in rows
    ]


def add_portfolio_item(
    user_id: str,
    portfolio_id: str,
    code: str,
    name: str,
    type: str,
    quantity: float,
    cost_price: float,
) -> dict:
    """Add an item to a portfolio, creating the portfolio in mock mode if needed."""
    item = {
        "id": str(uuid.uuid4()),
        "portfolio_id": portfolio_id,
        "user_id": user_id,
        "code": code,
        "name": name,
        "type": type,
        "quantity": quantity,
        "cost_price": cost_price,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if USE_MOCK_DATA:
        portfolios = _mock_portfolios.setdefault(user_id, [])
        if not any(p.get("id") == portfolio_id for p in portfolios):
            portfolios.append(
                {
                    "id": portfolio_id,
                    "user_id": user_id,
                    "name": f"Portfolio {portfolio_id[:8]}",
                    "created_at": item["created_at"],
                }
            )
        _mock_portfolio_items.setdefault(portfolio_id, []).append(item)
        return item

    db = get_db()
    db.execute(
        "INSERT INTO biz_portfolio_items "
        "(id, portfolio_id, user_id, code, name, type, quantity, cost_price, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            item["id"],
            portfolio_id,
            user_id,
            code,
            name,
            type,
            quantity,
            cost_price,
            item["created_at"],
        ],
    )
    return item
