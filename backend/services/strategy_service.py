"""Strategy service — CRUD and execution for quantitative screening strategies.

In the mock-data mode all state is held in an in-memory list so the API is
fully functional without a database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from mock_data import (
    MOCK_STRATEGIES,
    MOCK_FUNDS,
    MOCK_CONVERTIBLE_BONDS,
    MOCK_REITS,
    MOCK_ETF_FUNDS,
)

# ============================================================
# In-memory state (copy so we can mutate freely)
# ============================================================

_mock_strategies: list[dict] = [dict(s) for s in MOCK_STRATEGIES]


# ============================================================
# Field mapping (Chinese rule field -> dataset dict key)
# ============================================================

FIELD_MAP: dict[str, str] = {
    # Convertible bond fields
    "价格": "price",
    "转股溢价率": "premium_pct",
    "到期收益率": "ytm",
    "信用评级": "rating",
    "剩余年限": "remaining_years",
    "双低值": "double_low_score",
    "波动率": "iv",
    # Fund / ETF fields
    "实时折溢价率": "premium_pct",
    "折溢价率": "premium_pct",
    "净套利收益率": "net_arbitrage_yield",
    "成交量": "volume",
    # REITs fields
    "分红率": "dividend_rate",
    "出租率": "occupancy_rate",
    "irr": "irr",
    "IRR": "irr",
}

# target_asset -> mock dataset
DATASET_MAP: dict[str, list[dict]] = {
    "cb": MOCK_CONVERTIBLE_BONDS,
    "lof": MOCK_FUNDS,
    "fund": MOCK_FUNDS,
    "etf": MOCK_ETF_FUNDS,
    "reit": MOCK_REITS,
    "reits": MOCK_REITS,
}


# ============================================================
# Rule evaluation helpers
# ============================================================

def _match_rule(item: dict, rule: dict) -> bool:
    """Return True if *item* satisfies *rule*.

    Unsupported operators or missing fields are treated as a match (skipped)
    so that partial rules still return results.
    """
    field: str = rule.get("field", "")
    operator: str = rule.get("operator", "")
    value: Any = rule.get("value", "")

    key = FIELD_MAP.get(field, field)
    if key not in item:
        return True  # field not on the dict — skip rule

    item_value = item[key]

    # "属于" (belongs to) — comma-separated membership check
    if operator == "属于":
        allowed = [v.strip() for v in str(value).split(",") if v.strip()]
        return str(item_value) in allowed

    # Numeric comparison operators
    try:
        iv = float(item_value)
        rv = float(value)
    except (ValueError, TypeError):
        return True  # cannot convert — skip rule

    if operator == "<":
        return iv < rv
    if operator == ">":
        return iv > rv
    if operator == "<=":
        return iv <= rv
    if operator == ">=":
        return iv >= rv
    if operator == "==":
        return iv == rv

    return True  # unsupported operator — skip rule


def _matches_all_rules(item: dict, rules: list[dict]) -> bool:
    return all(_match_rule(item, rule) for rule in rules)


# ============================================================
# Public API
# ============================================================

def get_strategies(user_id: str) -> list[dict]:
    """Return all strategies."""
    return list(_mock_strategies)


def create_strategy(user_id: str, name: str, target_asset: str, rules: list[dict]) -> dict:
    """Create a new strategy and add it to the mock list."""
    strategy = {
        "id": str(uuid.uuid4()),
        "name": name,
        "target_asset": target_asset,
        "rules": rules,
        "active": True,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    _mock_strategies.append(strategy)
    return strategy


def update_strategy(user_id: str, strategy_id: str, name: str | None, active: bool | None) -> dict | None:
    """Find and update a strategy in the mock list; return updated or None."""
    for s in _mock_strategies:
        if s["id"] == strategy_id:
            if name is not None:
                s["name"] = name
            if active is not None:
                s["active"] = active
            return s
    return None


def delete_strategy(user_id: str, strategy_id: str) -> bool:
    """Remove a strategy from the mock list; return True/False."""
    for i, s in enumerate(_mock_strategies):
        if s["id"] == strategy_id:
            _mock_strategies.pop(i)
            return True
    return False


def execute_strategy(user_id: str, strategy_id: str, date: str | None) -> list[dict]:
    """Run a strategy's rules against the appropriate mock dataset.

    Returns the list of matching items.
    """
    strategy: dict | None = None
    for s in _mock_strategies:
        if s["id"] == strategy_id:
            strategy = s
            break

    if strategy is None:
        return []

    dataset = DATASET_MAP.get(strategy.get("target_asset", ""), [])
    rules = strategy.get("rules", [])

    return [item for item in dataset if _matches_all_rules(item, rules)]
