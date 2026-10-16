"""AI router — endpoints for AI report generation and configuration."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse

from models import ApiResponse, PaginatedData, AiReport, AiConfig, AiChannel, AiChannelsView
from services.ai_service import (
    get_ai_reports,
    generate_ai_report,
    get_ai_config,
    update_ai_config,
    build_interpret,
    build_chat,
)
from services import llm_service
from services import knowledge_service
from services.llm_service import LlmError, LlmNotConfigured
from core.deps import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/reports", response_model=ApiResponse[PaginatedData[AiReport]])
def list_ai_reports(
    date: str | None = Query(None),
    page: int = Query(1, ge=1),
    user_id: str = Depends(get_current_user),
):
    data = get_ai_reports(user_id, date, page)
    return ApiResponse(data=data)


@router.post("/reports/generate", response_model=ApiResponse[AiReport])
def generate_ai_report_endpoint(user_id: str = Depends(get_current_user)):
    data = generate_ai_report(user_id)
    return ApiResponse(data=data)


@router.get("/config", response_model=ApiResponse[AiConfig])
def get_ai_config_endpoint(user_id: str = Depends(get_current_user)):
    data = get_ai_config(user_id)
    return ApiResponse(data=data)


@router.put("/config", response_model=ApiResponse[AiConfig])
def update_ai_config_endpoint(body: AiConfig, user_id: str = Depends(get_current_user)):
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


# ============================================================
# LLM 多渠道管理（OpenAI 兼容）
# ============================================================

@router.get("/channels", response_model=ApiResponse[AiChannelsView])
def list_channels(user_id: str = Depends(get_current_user)):
    return ApiResponse(data=llm_service.list_channels())


@router.post("/channels", response_model=ApiResponse[AiChannel])
def create_channel(body: dict = Body(...), user_id: str = Depends(get_current_user)):
    try:
        data = llm_service.create_channel(
            name=body.get("name") or "",
            provider=body.get("provider") or "custom",
            api_key=body.get("api_key") or "",
            endpoint=body.get("endpoint"),
            model=body.get("model"),
            temperature=float(body.get("temperature") or 0.3),
            max_tokens=int(body.get("max_tokens") or 2048),
        )
    except (LlmError, TypeError, ValueError) as e:
        # temperature="hot" 等非法值：float/int 抛 ValueError；**body 撞名抛
        # TypeError —— 统一转 400，不 500（2026-10-14 审计 P2-1 修复）。
        return ApiResponse(code=400, message=f"参数不合法: {e}")
    return ApiResponse(data=data)


@router.put("/channels/{channel_id}", response_model=ApiResponse[AiChannel])
def update_channel(channel_id: str, body: dict = Body(...), user_id: str = Depends(get_current_user)):
    try:
        data = llm_service.update_channel(channel_id, **body)
    except (LlmError, TypeError, ValueError) as e:
        return ApiResponse(code=400, message=f"参数不合法: {e}")
    return ApiResponse(data=data)


@router.delete("/channels/{channel_id}", response_model=ApiResponse[dict])
def delete_channel(channel_id: str, user_id: str = Depends(get_current_user)):
    try:
        ok = llm_service.delete_channel(channel_id)
    except LlmError as e:
        # _save() 落盘失败会抛 LlmError（P2-4），删除同样要可见化
        return ApiResponse(code=400, message=str(e))
    return ApiResponse(data={"deleted": ok})


@router.post("/channels/{channel_id}/test", response_model=ApiResponse[dict])
def test_channel(channel_id: str, user_id: str = Depends(get_current_user)):
    try:
        data = llm_service.test_channel(channel_id)
    except LlmError as e:
        return ApiResponse(code=400, message=str(e))
    return ApiResponse(data=data)


@router.post("/channels/active", response_model=ApiResponse[dict])
def set_active_channel(body: dict = Body(...), user_id: str = Depends(get_current_user)):
    try:
        data = llm_service.set_active(body.get("id") or "")
    except LlmError as e:
        return ApiResponse(code=400, message=str(e))
    return ApiResponse(data=data)


# ============================================================
# 知识库（单一真源在 backend/knowledge/，前端与 AI 共用）
# ============================================================

@router.get("/knowledge", response_model=ApiResponse[dict])
def list_knowledge(user_id: str = Depends(get_current_user)):
    return ApiResponse(data=knowledge_service.list_docs())


@router.get("/knowledge/{doc_id}", response_model=ApiResponse[dict])
def get_knowledge_doc(doc_id: str, user_id: str = Depends(get_current_user)):
    doc = knowledge_service.get_doc(doc_id)
    if not doc:
        return ApiResponse(code=404, message="文档不存在")
    return ApiResponse(data=doc)


# ============================================================
# AI 解读 / 问答（SSE 流式）
# ============================================================

def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _sse_stream(pack_builder):
    """统一 SSE 骨架：meta → delta* → done；异常转 error 帧，不 500。"""

    def gen():
        try:
            pack = pack_builder()
        except Exception as e:  # noqa: BLE001
            yield _sse({"type": "error", "code": "bad_request", "message": str(e)})
            yield _sse({"type": "done"})
            return
        yield _sse({
            "type": "meta",
            "context_type": pack.get("context_type"),
            "context": pack.get("context"),
            "docs": pack.get("docs"),
        })
        try:
            for delta in llm_service.chat_stream(pack["messages"]):
                yield _sse({"type": "delta", "text": delta})
        except LlmNotConfigured as e:
            yield _sse({"type": "error", "code": "not_configured", "message": str(e)})
        except LlmError as e:
            yield _sse({"type": "error", "code": "llm_error", "message": str(e)})
        yield _sse({"type": "done"})

    return gen()


@router.post("/interpret")
def interpret_endpoint(body: dict = Body(...), user_id: str = Depends(get_current_user)):
    context_type = body.get("context_type") or ""
    return StreamingResponse(
        _sse_stream(lambda: {**build_interpret(context_type), "context_type": context_type}),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat")
def chat_endpoint(body: dict = Body(...), user_id: str = Depends(get_current_user)):
    message = body.get("message") or ""
    context_type = body.get("context_type")
    history = body.get("history") if isinstance(body.get("history"), list) else None
    return StreamingResponse(
        _sse_stream(lambda: build_chat(message, context_type, history)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
