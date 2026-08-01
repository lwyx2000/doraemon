"""Monitor router — endpoints for system dashboard and cache configuration."""

from __future__ import annotations

from fastapi import APIRouter

from models import ApiResponse, MonitorDashboard, CacheConfig
from services.monitor_service import (
    get_monitor_dashboard,
    get_cache_config,
    update_cache_config,
)

router = APIRouter(tags=["monitor"])


@router.get("/monitor/dashboard", response_model=ApiResponse[MonitorDashboard])
async def get_monitor_dashboard_endpoint():
    data = get_monitor_dashboard()
    return ApiResponse(data=data)


@router.get("/config/{method}", response_model=ApiResponse[CacheConfig])
async def get_cache_config_endpoint(method: str):
    data = get_cache_config(method)
    return ApiResponse(data=data)


@router.post("/config", response_model=ApiResponse[CacheConfig])
async def update_cache_config_endpoint(body: CacheConfig):
    data = update_cache_config(body.enabled, body.ttl_seconds, body.max_size, body.method)
    return ApiResponse(data=data)
