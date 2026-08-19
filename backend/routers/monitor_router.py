"""Monitor router — endpoints for system dashboard and cache configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from models import ApiResponse, MonitorDashboard, CacheConfig
from services.monitor_service import (
    get_monitor_dashboard,
    get_cache_config,
    get_all_cache_config,
    update_cache_config,
)
from core.deps import get_current_user

router = APIRouter(tags=["monitor"])


@router.get("/dashboard", response_model=ApiResponse[MonitorDashboard])
async def get_monitor_dashboard_endpoint(user_id: str = Depends(get_current_user)):
    data = get_monitor_dashboard()
    return ApiResponse(data=data)


@router.get("/config/all", response_model=ApiResponse[CacheConfig])
async def get_all_cache_config_endpoint(user_id: str = Depends(get_current_user)):
    """获取全局缓存配置（不绑定特定 method）。"""
    data = get_all_cache_config()
    return ApiResponse(data=data)


@router.get("/config/{method}", response_model=ApiResponse[CacheConfig])
async def get_cache_config_endpoint(method: str, user_id: str = Depends(get_current_user)):
    data = get_cache_config(method)
    return ApiResponse(data=data)


@router.post("/config", response_model=ApiResponse[CacheConfig])
async def update_cache_config_endpoint(body: CacheConfig, user_id: str = Depends(get_current_user)):
    data = update_cache_config(body.enabled, body.ttl_seconds, body.max_size, body.method)
    return ApiResponse(data=data)
