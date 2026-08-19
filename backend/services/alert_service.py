"""Alert service — CRUD for alert rules and event management.

In-memory mock implementation; no database required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from mock_data import MOCK_ALERT_RULES

# ============================================================
# In-memory state
# ============================================================

_mock_rules: list[dict] = [dict(r) for r in MOCK_ALERT_RULES]
_mock_events: list[dict] = []


# ============================================================
# Internal helpers
# ============================================================

def _ensure_events() -> None:
    """Generate a few mock events derived from the alert rules if empty."""
    if _mock_events:
        return

    now = datetime.now(timezone.utc)
    idx = 0
    for rule in _mock_rules:
        if not rule.get("active"):
            continue
        idx += 1
        triggered_at = now - timedelta(hours=idx * 3)
        _mock_events.append({
            "id": idx,
            "rule_id": rule["id"],
            "triggered_at": triggered_at.isoformat(),
            "target_code": f"DEMO{idx:03d}",
            "target_name": rule.get("target", ""),
            "actual_value": rule.get("value"),
            "message": (
                f"预警触发: {rule.get('name', '')} — "
                f"{rule.get('target', '')} {rule.get('condition', '')} "
                f"{rule.get('value', '')}"
            ),
            "is_read": False,
        })


# ============================================================
# Alert rules
# ============================================================

def get_alert_rules(user_id: str) -> list[dict]:
    """Return all alert rules."""
    return list(_mock_rules)


def create_alert_rule(
    user_id: str,
    name: str,
    type: str,
    target: str,
    condition: str,
    value: float,
    channels: list[str],
) -> dict:
    """Create a new alert rule."""
    rule = {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": type,
        "target": target,
        "condition": condition,
        "value": value,
        "channels": channels,
        "active": True,
    }
    _mock_rules.append(rule)
    return rule


def update_alert_rule(
    user_id: str,
    rule_id: str,
    name: str | None = None,
    active: bool | None = None,
    type: str | None = None,
    target: str | None = None,
    condition: str | None = None,
    value: float | None = None,
    channels: list[str] | None = None,
) -> dict | None:
    """Update an alert rule; supports updating all fields.

    Only non-None fields are updated.
    """
    for r in _mock_rules:
        if r["id"] == rule_id:
            if name is not None:
                r["name"] = name
            if active is not None:
                r["active"] = active
            if type is not None:
                r["type"] = type
            if target is not None:
                r["target"] = target
            if condition is not None:
                r["condition"] = condition
            if value is not None:
                r["value"] = value
            if channels is not None:
                r["channels"] = channels
            return r
    return None


def delete_alert_rule(user_id: str, rule_id: str) -> bool:
    """Delete an alert rule; return True/False."""
    for i, r in enumerate(_mock_rules):
        if r["id"] == rule_id:
            _mock_rules.pop(i)
            return True
    return False


# ============================================================
# Alert events
# ============================================================

def get_alert_events(
    user_id: str,
    is_read: bool | None,
    since: str | None,
    page: int,
    page_size: int,
) -> dict:
    """Return paginated alert events.

    Generates mock events derived from the alert rules when the list is empty.
    """
    _ensure_events()

    events = list(_mock_events)

    if is_read is not None:
        events = [e for e in events if e["is_read"] == is_read]
    if since:
        events = [e for e in events if e["triggered_at"] >= since]

    # Most recent first
    events.sort(key=lambda e: e["triggered_at"], reverse=True)

    total = len(events)
    start = (page - 1) * page_size
    end = start + page_size
    items = events[start:end]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def mark_event_read(user_id: str, event_id: int) -> bool:
    """Mark an alert event as read; return True/False."""
    for ev in _mock_events:
        if ev["id"] == event_id:
            ev["is_read"] = True
            return True
    return False
