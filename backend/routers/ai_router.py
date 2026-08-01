"""AI router — endpoints for AI report generation and configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from models import ApiResponse, PaginatedData, AiReport, AiConfig
from services.ai_service import (
    get_ai_reports,
    generate_ai_report,
    get_ai_config,
    update_ai_config,
)
from core.deps import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/reports", response_model=ApiResponse[PaginatedData[AiReport]])
async def list_ai_reports(
    date: str | None = Query(None),
    page: int = Query(1, ge=1),
    user_id: str = Depends(get_current_user),
):
    data = get_ai_reports(user_id, date, page)
    return ApiResponse(data=data)


@router.post("/reports/generate", response_model=ApiResponse[AiReport])
async def generate_ai_report_endpoint(user_id: str = Depends(get_current_user)):
    data = generate_ai_report(user_id)
    return ApiResponse(data=data)


@router.get("/config", response_model=ApiResponse[AiConfig])
async def get_ai_config_endpoint(user_id: str = Depends(get_current_user)):
    data = get_ai_config(user_id)
    return ApiResponse(data=data)


@router.put("/config", response_model=ApiResponse[AiConfig])
async def update_ai_config_endpoint(body: AiConfig, user_id: str = Depends(get_current_user)):
    data = update_ai_config(
        user_id,
        body.provider,
        body.api_key,
        body.endpoint,
        body.temperature,
        body.cron_expression,
        body.enabled,
    )
    return ApiResponse(data=data)
