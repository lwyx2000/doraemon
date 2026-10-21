"""LLM 多渠道配置服务 — OpenAI 兼容协议统一多渠道。

设计要点：
- 支持 deepseek / openai / qwen / moonshot / kimi / doubao / zhipu / custom 等
  OpenAI 兼容 provider（均提供 /chat/completions）。
- 渠道配置持久化到 /data/llm_channels.json（仿 fund_fee_service 的 JSON 文件模式），
  避免写 DuckDB（单写锁）与内存态重启丢失。
- api_key 在 API 读出时脱敏（只回 ****last4）；写入时若传入空串/None 表示不修改。
- 调用用 requests（项目唯一 HTTP 依赖），流式为同步生成器，
  由 FastAPI StreamingResponse 放线程池迭代，不阻塞事件循环。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import requests

# ============================================================
# Provider 预设（endpoint / model 缺省值，用户可改）
# ============================================================

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek",
        "endpoint": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "openai": {
        "label": "OpenAI",
        "endpoint": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "qwen": {
        "label": "通义千问",
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "moonshot": {
        "label": "Moonshot",
        "endpoint": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "kimi": {
        "label": "Kimi",
        "endpoint": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "doubao": {
        "label": "豆包",
        "endpoint": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-pro-32k",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "endpoint": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    "custom": {
        "label": "自定义（OpenAI 兼容）",
        "endpoint": "",
        "model": "",
    },
}

_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 2048
_HTTP_TIMEOUT = (10, 120)


class LlmError(Exception):
    """LLM 调用失败（网络/鉴权/上游错误）。"""


class LlmNotConfigured(LlmError):
    """未配置任何可用渠道（无渠道 / 无 api_key）。"""


# ============================================================
# 持久化（/data/llm_channels.json）
# ============================================================

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"active_id": None, "channels": []}


def _config_path() -> Path:
    try:
        from core.config import DB_PATH

        return Path(DB_PATH).parent / "llm_channels.json"
    except Exception:  # noqa: BLE001
        return Path("llm_channels.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> None:
    """启动时恢复配置（失败静默用空配置）。"""
    global _STATE
    try:
        p = _config_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            channels = data.get("channels")
            if isinstance(channels, list):
                _STATE = {
                    "active_id": data.get("active_id"),
                    "channels": [c for c in channels if isinstance(c, dict) and c.get("id")],
                }
                print(f"[LLM] 已恢复 {len(_STATE['channels'])} 个渠道配置")
    except Exception as e:  # noqa: BLE001
        print(f"[LLM] 渠道配置恢复失败（用空配置）: {e}")


def _save() -> None:
    """持久化到 /data/llm_channels.json（原子写：tmp + os.replace）。

    失败必须抛 LlmError（路由层转 400）—— 早期版本只 print，/data 卷
    只读/满盘时渠道静默丢失（用户以为保存成功，重启后全没），不可接受。
    注意：调用方均已先改内存态，此处抛错意味着「内存生效但落盘失败」，
    错误信息里明确说明，便于用户排查卷问题。
    """
    try:
        p = _config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(_STATE, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:  # noqa: BLE001
        raise LlmError(f"渠道配置写入磁盘失败（内存已生效，重启后将丢失）: {e}") from e


_load()


# ============================================================
# 渠道 CRUD
# ============================================================

def _mask_key(key: str | None) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return "****" + key[-4:]


def _public(ch: dict) -> dict:
    """读出用：脱敏 api_key。"""
    out = dict(ch)
    out["api_key"] = _mask_key(ch.get("api_key"))
    out["has_key"] = bool(ch.get("api_key"))
    return out


def _preset_for(provider: str) -> dict[str, str]:
    return PROVIDER_PRESETS.get(provider) or PROVIDER_PRESETS["custom"]


def list_channels() -> dict:
    """返回全部渠道（脱敏）+ 激活 id + provider 预设。"""
    with _LOCK:
        return {
            "active_id": _STATE.get("active_id"),
            "channels": [_public(c) for c in _STATE.get("channels", [])],
            "presets": PROVIDER_PRESETS,
        }


def create_channel(
    name: str,
    provider: str,
    api_key: str,
    endpoint: str | None = None,
    model: str | None = None,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> dict:
    provider = provider if provider in PROVIDER_PRESETS else "custom"
    preset = _preset_for(provider)
    ch = {
        "id": "ch_" + uuid.uuid4().hex[:12],
        "name": name or preset["label"],
        "provider": provider,
        "api_key": api_key or "",
        "endpoint": endpoint or preset["endpoint"],
        "model": model or preset["model"],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    with _LOCK:
        _STATE.setdefault("channels", []).append(ch)
        # 首个渠道自动激活
        if not _STATE.get("active_id"):
            _STATE["active_id"] = ch["id"]
        _save()
        return _public(ch)


def update_channel(channel_id: str, **fields: Any) -> dict:
    with _LOCK:
        for ch in _STATE.get("channels", []):
            if ch.get("id") == channel_id:
                # api_key 空串/None = 不修改
                key = fields.pop("api_key", None)
                if key:
                    ch["api_key"] = key
                # 先记下原 provider：白名单循环会立刻把 ch["provider"] 覆写成新值，
                # 若在循环后拿 ch.get("provider") 做比较，永远等于新值 → 预设跟随
                # 逻辑成为死代码（2026-10-14 审计 P1-2 修复）。
                old_provider = ch.get("provider")
                for k in ("name", "provider", "endpoint", "model"):
                    if fields.get(k) is not None:
                        ch[k] = fields[k]
                if fields.get("temperature") is not None:
                    ch["temperature"] = float(fields["temperature"])
                if fields.get("max_tokens") is not None:
                    ch["max_tokens"] = int(fields["max_tokens"])
                # provider 变更且未显式给 endpoint/model → 跟随预设
                new_provider = ch.get("provider")
                if new_provider and new_provider != old_provider:
                    if fields.get("endpoint") is None:
                        ch["endpoint"] = _preset_for(new_provider)["endpoint"]
                    if fields.get("model") is None:
                        ch["model"] = _preset_for(new_provider)["model"]
                ch["updated_at"] = _now_iso()
                _save()
                return _public(ch)
    raise LlmError(f"渠道不存在: {channel_id}")


def delete_channel(channel_id: str) -> bool:
    global _STATE
    with _LOCK:
        channels = [c for c in _STATE.get("channels", []) if c.get("id") != channel_id]
        if len(channels) == len(_STATE.get("channels", [])):
            return False
        _STATE["channels"] = channels
        if _STATE.get("active_id") == channel_id:
            _STATE["active_id"] = channels[0]["id"] if channels else None
        _save()
        return True


def set_active(channel_id: str) -> dict:
    with _LOCK:
        ids = [c.get("id") for c in _STATE.get("channels", [])]
        if channel_id not in ids:
            raise LlmError(f"渠道不存在: {channel_id}")
        _STATE["active_id"] = channel_id
        _save()
        return {"active_id": channel_id}


def get_channel(channel_id: str) -> dict | None:
    with _LOCK:
        for ch in _STATE.get("channels", []):
            if ch.get("id") == channel_id:
                return dict(ch)
    return None


def get_active_channel() -> dict | None:
    """返回激活渠道原文（含 api_key）；无可用配置返回 None。"""
    with _LOCK:
        active_id = _STATE.get("active_id")
        channels = _STATE.get("channels", [])
        for ch in channels:
            if ch.get("id") == active_id and ch.get("api_key"):
                return dict(ch)
        # 激活渠道失效时兜底第一个有 key 的
        for ch in channels:
            if ch.get("api_key"):
                return dict(ch)
    return None


# ============================================================
# OpenAI 兼容调用
# ============================================================

def _chat_url(ch: dict) -> str:
    endpoint = (ch.get("endpoint") or _preset_for(ch.get("provider", ""))["endpoint"]).rstrip("/")
    if not endpoint:
        raise LlmError(f"渠道 {ch.get('name')} 未配置 endpoint")
    return endpoint + "/chat/completions"


def _headers(ch: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {ch.get('api_key', '')}",
        "Content-Type": "application/json",
    }


def _payload(ch: dict, messages: list[dict], stream: bool, max_tokens: int | None) -> dict:
    return {
        "model": ch.get("model") or _preset_for(ch.get("provider", ""))["model"],
        "messages": messages,
        "temperature": float(ch.get("temperature", _DEFAULT_TEMPERATURE)),
        "max_tokens": int(max_tokens or ch.get("max_tokens") or _DEFAULT_MAX_TOKENS),
        "stream": stream,
    }


def chat_complete(
    messages: list[dict],
    channel: dict | None = None,
    max_tokens: int | None = None,
) -> tuple[str, dict]:
    """非流式对话，返回 (文本, usage)。无可用渠道抛 LlmNotConfigured。"""
    ch = channel or get_active_channel()
    if not ch:
        raise LlmNotConfigured("尚未配置可用的 LLM 渠道，请先在 AI 决策中心添加渠道")
    url = _chat_url(ch)
    try:
        resp = requests.post(
            url,
            headers=_headers(ch),
            json=_payload(ch, messages, stream=False, max_tokens=max_tokens),
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as e:
        raise LlmError(f"LLM 请求失败: {e}") from e
    # 上游 LLM（OpenAI 兼容渠道）的响应普遍不带 charset，requests 对
    # text/event-stream 会回退 ISO-8859-1，中文 delta 被 Latin-1 解码成
    # mojibake（2026-10-21「AI 解读」整页乱码根因）。显式锁定 UTF-8。
    resp.encoding = "utf-8"
    if resp.status_code != 200:
        raise LlmError(f"LLM 返回 {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
        text = data["choices"][0]["message"]["content"] or ""
        return text, data.get("usage") or {}
    except Exception as e:  # noqa: BLE001
        raise LlmError(f"LLM 响应解析失败: {e}") from e


def chat_stream(
    messages: list[dict],
    channel: dict | None = None,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """流式对话：yield 文本增量 delta。

    同步生成器——由 StreamingResponse 在线程池迭代。
    在 yield 第一个 delta 前完成鉴权检查，无渠道时**立即**抛 LlmNotConfigured
    （路由层捕获后转成 SSE 引导帧，不 500）。
    """
    ch = channel or get_active_channel()
    if not ch:
        raise LlmNotConfigured("尚未配置可用的 LLM 渠道，请先在 AI 决策中心添加渠道")
    url = _chat_url(ch)
    try:
        resp = requests.post(
            url,
            headers=_headers(ch),
            json=_payload(ch, messages, stream=True, max_tokens=max_tokens),
            stream=True,
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as e:
        raise LlmError(f"LLM 请求失败: {e}") from e
    # 同 chat_complete：上游 SSE 不带 charset 时 requests 默认 ISO-8859-1，
    # 必须显式锁定 UTF-8，否则流式中文字段全乱（iter_lines(decode_unicode=True)
    # 按 resp.encoding 解码）。
    resp.encoding = "utf-8"
    if resp.status_code != 200:
        body = resp.text[:300]
        resp.close()
        raise LlmError(f"LLM 返回 {resp.status_code}: {body}")
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
                delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    yield piece
            except Exception:  # noqa: BLE001 — 单行解析失败跳过，不中断流
                continue
    finally:
        resp.close()


def test_channel(channel_id: str) -> dict:
    """连通性测试：发一条最小对话，返回延迟与模型首响。"""
    ch = get_channel(channel_id)
    if not ch:
        raise LlmError(f"渠道不存在: {channel_id}")
    if not ch.get("api_key"):
        raise LlmError(f"渠道 {ch.get('name')} 未填写 api_key")
    started = time.perf_counter()
    text, _usage = chat_complete(
        messages=[
            {"role": "system", "content": "你是一个连通性测试助手，只回复两个字：正常"},
            {"role": "user", "content": "ping"},
        ],
        channel=ch,
        max_tokens=16,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {"ok": True, "latency_ms": latency_ms, "reply": text[:50], "model": ch.get("model")}
