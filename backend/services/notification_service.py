"""Notification service — 企业微信群机器人 / 钉钉机器人消息推送。

支持的通知渠道：
  - wechat   : 企业微信群机器人 Webhook
  - dingtalk : 钉钉群机器人 Webhook
  - email    : 邮件（预留接口，暂未实现）
  - popup    : 系统内弹窗（前端 WebSocket / 轮询，本服务仅记录日志）

配置来源：
  1. 环境变量 WECOM_WEBHOOK_URL / DINGTALK_WEBHOOK_URL（core/config.py）
  2. 运行时通过 notification_config 内存态动态修改（系统设置页面）
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import requests

from core.config import WECOM_WEBHOOK_URL, DINGTALK_WEBHOOK_URL


# ============================================================
# 运行时可覆盖的通知渠道配置（内存态）
# ============================================================

_notification_config: dict[str, Any] = {
    "wecom_webhook_url": WECOM_WEBHOOK_URL,
    "dingtalk_webhook_url": DINGTALK_WEBHOOK_URL,
    "email_smtp_host": "",
    "email_smtp_port": 465,
    "email_username": "",
    "email_password": "",
    "email_from": "",
    "email_to": "",
}


def get_notification_config() -> dict[str, Any]:
    """获取当前通知渠道配置。"""
    return dict(_notification_config)


def update_notification_config(
    wecom_webhook_url: str | None = None,
    dingtalk_webhook_url: str | None = None,
    email_smtp_host: str | None = None,
    email_smtp_port: int | None = None,
    email_username: str | None = None,
    email_password: str | None = None,
    email_from: str | None = None,
    email_to: str | None = None,
) -> dict[str, Any]:
    """更新通知渠道配置（仅传入非 None 的字段）。"""
    if wecom_webhook_url is not None:
        _notification_config["wecom_webhook_url"] = wecom_webhook_url
    if dingtalk_webhook_url is not None:
        _notification_config["dingtalk_webhook_url"] = dingtalk_webhook_url
    if email_smtp_host is not None:
        _notification_config["email_smtp_host"] = email_smtp_host
    if email_smtp_port is not None:
        _notification_config["email_smtp_port"] = email_smtp_port
    if email_username is not None:
        _notification_config["email_username"] = email_username
    if email_password is not None:
        _notification_config["email_password"] = email_password
    if email_from is not None:
        _notification_config["email_from"] = email_from
    if email_to is not None:
        _notification_config["email_to"] = email_to
    return dict(_notification_config)


# ============================================================
# 消息格式化
# ============================================================

def _format_alert_message(
    rule_name: str,
    target: str,
    condition: str,
    value: float,
    actual_value: float,
    message: str | None = None,
) -> dict[str, str]:
    """将预警信息格式化为标题+正文。"""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    condition_label = {"above": "高于", "below": "低于", "crosses": "穿越"}.get(condition, condition)
    title = f"【量化终端预警】{rule_name}"
    content = (
        f"预警规则: {rule_name}\n"
        f"监控标的: {target}\n"
        f"触发条件: {condition_label} {value}\n"
        f"实际数值: {actual_value}\n"
    )
    if message:
        content += f"详细信息: {message}\n"
    content += f"触发时间: {now_str}"
    return {"title": title, "content": content}


# ============================================================
# 企业微信群机器人
# ============================================================

def send_wecom_message(webhook_url: str, title: str, content: str) -> bool:
    """发送企业微信群机器人消息。

    企业微信群机器人 Webhook 接口文档:
    https://developer.work.weixin.qq.com/document/path/91770

    消息格式:
    {
        "msgtype": "markdown",
        "markdown": {
            "content": "标题\\n正文"
        }
    }
    """
    if not webhook_url:
        print("[Notification] 企业微信 Webhook URL 未配置，跳过发送")
        return False

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": f"## {title}\n{content}"
        }
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("errcode") == 0:
            print(f"[Notification] 企业微信消息发送成功: {title}")
            return True
        else:
            print(f"[Notification] 企业微信消息发送失败: {result}")
            return False
    except Exception as e:
        print(f"[Notification] 企业微信消息发送异常: {e}")
        return False


# ============================================================
# 钉钉群机器人
# ============================================================

def send_dingtalk_message(webhook_url: str, title: str, content: str) -> bool:
    """发送钉钉群机器人消息。

    钉钉机器人 Webhook 接口文档:
    https://open.dingtalk.com/document/robots/custom-robot-access

    消息格式:
    {
        "msgtype": "markdown",
        "markdown": {
            "title": "标题",
            "text": "正文"
        }
    }
    """
    if not webhook_url:
        print("[Notification] 钉钉 Webhook URL 未配置，跳过发送")
        return False

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"## {title}\n{content}"
        }
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("errcode") == 0:
            print(f"[Notification] 钉钉消息发送成功: {title}")
            return True
        else:
            print(f"[Notification] 钉钉消息发送失败: {result}")
            return False
    except Exception as e:
        print(f"[Notification] 钉钉消息发送异常: {e}")
        return False


# ============================================================
# 邮件（预留）
# ============================================================

def send_email_message(
    smtp_host: str, smtp_port: int, username: str, password: str,
    from_addr: str, to_addr: str, subject: str, body: str,
) -> bool:
    """发送邮件通知（预留实现）。"""
    print(f"[Notification] 邮件通知暂未实现: {subject} -> {to_addr}")
    return False


# ============================================================
# 统一发送入口
# ============================================================

def send_notification(
    channels: list[str],
    rule_name: str,
    target: str,
    condition: str,
    value: float,
    actual_value: float,
    message: str | None = None,
) -> dict[str, bool]:
    """根据规则配置的渠道列表发送通知。

    Args:
        channels: 通知渠道列表，如 ['popup', 'wechat', 'dingtalk', 'email']
        rule_name: 规则名称
        target: 监控标的
        condition: 触发条件 (above/below/crosses)
        value: 规则阈值
        actual_value: 实际数值
        message: 额外描述信息

    Returns:
        各渠道发送结果，如 {'wechat': True, 'popup': True}
    """
    formatted = _format_alert_message(rule_name, target, condition, value, actual_value, message)
    title = formatted["title"]
    content = formatted["content"]

    results: dict[str, bool] = {}
    cfg = get_notification_config()

    for ch in channels:
        if ch == "popup":
            # 系统弹窗：后端不直接推送，由前端拉取 events 时展示
            print(f"[Notification] 弹窗通知: {title}")
            results["popup"] = True

        elif ch == "wechat":
            results["wechat"] = send_wecom_message(
                cfg["wecom_webhook_url"], title, content
            )

        elif ch == "dingtalk":
            results["dingtalk"] = send_dingtalk_message(
                cfg["dingtalk_webhook_url"], title, content
            )

        elif ch == "email":
            results["email"] = send_email_message(
                cfg["email_smtp_host"], cfg["email_smtp_port"],
                cfg["email_username"], cfg["email_password"],
                cfg["email_from"], cfg["email_to"],
                title, content,
            )

        else:
            print(f"[Notification] 未知渠道: {ch}")
            results[ch] = False

    return results
