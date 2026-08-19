"""Alert router — endpoints for alert rules and alert events."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from models import ApiResponse, PaginatedData, AlertRule, AlertRuleCreate, AlertRuleUpdate, AlertEvent, AlertScanResult
from services.alert_service import (
    get_alert_rules,
    create_alert_rule,
    update_alert_rule,
    delete_alert_rule,
    get_alert_events,
    mark_event_read,
)
from services.alert_engine import run_alert_scan
from core.deps import get_current_user

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ============================================================
# Alert rules
# ============================================================

@router.get("/rules", response_model=ApiResponse[list[AlertRule]])
async def list_alert_rules(user_id: str = Depends(get_current_user)):
    data = get_alert_rules(user_id)
    return ApiResponse(data=data)


@router.post("/rules", response_model=ApiResponse[AlertRule])
async def create_alert_rule_endpoint(body: AlertRuleCreate, user_id: str = Depends(get_current_user)):
    data = create_alert_rule(user_id, body.name, body.type, body.target, body.condition, body.value, body.channels)
    return ApiResponse(data=data)


@router.put("/rules/{rule_id}", response_model=ApiResponse[AlertRule])
async def update_alert_rule_endpoint(rule_id: str, body: AlertRuleUpdate, user_id: str = Depends(get_current_user)):
    data = update_alert_rule(
        user_id, rule_id,
        name=body.name,
        active=body.active,
        type=body.type,
        target=body.target,
        condition=body.condition,
        value=body.value,
        channels=body.channels,
    )
    if data is None:
        return ApiResponse(code=404, message="Not found", data=None)
    return ApiResponse(data=data)


@router.delete("/rules/{rule_id}", response_model=ApiResponse[dict])
async def delete_alert_rule_endpoint(rule_id: str, user_id: str = Depends(get_current_user)):
    deleted = delete_alert_rule(user_id, rule_id)
    if not deleted:
        return ApiResponse(code=404, message="Not found", data=None)
    return ApiResponse(data={"deleted": True})


# ============================================================
# Alert events
# ============================================================

@router.get("/events", response_model=ApiResponse[PaginatedData[AlertEvent]])
async def list_alert_events(
    is_read: bool | None = Query(None),
    since: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
):
    data = get_alert_events(user_id, is_read, since, page, page_size)
    return ApiResponse(data=data)


@router.put("/events/{event_id}/read", response_model=ApiResponse[dict])
async def mark_event_read_endpoint(event_id: int, user_id: str = Depends(get_current_user)):
    marked = mark_event_read(user_id, event_id)
    if not marked:
        return ApiResponse(code=404, message="Not found", data=None)
    return ApiResponse(data={"read": True})


# ============================================================
# 预警扫描（手动触发）
# ============================================================

@router.post("/scan", response_model=ApiResponse[AlertScanResult])
async def scan_alerts_endpoint(user_id: str = Depends(get_current_user)):
    """手动触发一次预警扫描，检查所有活跃规则。"""
    result = run_alert_scan(user_id)
    return ApiResponse(data=result)
