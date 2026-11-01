"""Import log router — 外部上传调用留痕查询（持仓页「上传记录」展示）。

JWT 鉴权：仅返回当前登录用户自己的上传日志。
"""

from fastapi import APIRouter, Depends, Query

from models import ApiResponse
from services.import_log_service import list_import_logs
from core.deps import get_current_user

router = APIRouter(prefix="/import-logs", tags=["import-logs"])


@router.get("", response_model=ApiResponse[list[dict]])
def get_import_logs(
    limit: int = Query(100, ge=1, le=500),
    user_id: str = Depends(get_current_user),
):
    """当前用户的上传调用留痕（持仓/成交外部接口），按时间倒序。"""
    return ApiResponse(data=list_import_logs(user_id, limit=limit))
