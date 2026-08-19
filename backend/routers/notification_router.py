"""Notification router — endpoints for notification channel configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from models import ApiResponse, NotificationConfig
from services.notification_service import (
    get_notification_config,
    update_notification_config,
)
from core.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/config", response_model=ApiResponse[NotificationConfig])
async def get_notification_config_endpoint(user_id: str = Depends(get_current_user)):
    """获取通知渠道配置。"""
    data = get_notification_config()
    return ApiResponse(data=data)


@router.put("/config", response_model=ApiResponse[NotificationConfig])
async def update_notification_config_endpoint(
    body: NotificationConfig,
    user_id: str = Depends(get_current_user),
):
    """更新通知渠道配置。"""
    data = update_notification_config(
        wecom_webhook_url=body.wecom_webhook_url,
        dingtalk_webhook_url=body.dingtalk_webhook_url,
        email_smtp_host=body.email_smtp_host,
        email_smtp_port=body.email_smtp_port,
        email_username=body.email_username,
        email_password=body.email_password,
        email_from=body.email_from,
        email_to=body.email_to,
    )
    return ApiResponse(data=data)


@router.post("/test", response_model=ApiResponse[dict])
async def test_notification_endpoint(
    body: dict,
    user_id: str = Depends(get_current_user),
):
    """发送一条测试通知消息。

    请求体: {"channel": "wechat"} 或 {"channel": "dingtalk"}
    """
    from services.notification_service import send_wecom_message, send_dingtalk_message
    from services.notification_service import get_notification_config

    channel = body.get("channel", "wechat")
    cfg = get_notification_config()
    title = "【量化终端】通知测试"
    content = "这是一条来自 QuantTerminal Pro 的测试通知消息，用于验证通知渠道配置是否正确。"

    if channel == "wechat":
        ok = send_wecom_message(cfg["wecom_webhook_url"], title, content)
    elif channel == "dingtalk":
        ok = send_dingtalk_message(cfg["dingtalk_webhook_url"], title, content)
    else:
        return ApiResponse(code=400, message=f"未知渠道: {channel}", data=None)

    return ApiResponse(data={"channel": channel, "sent": ok})
