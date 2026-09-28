"""Datasource router — 网关数据源自描述信息代理。

代理网关 /api/project/info，把「数据接口情况说明」透传给前端「数据来源」页，
实时渲染网关能力、各源健康度、容灾降级链与接口目录。

该信息描述的是「网关本身的状态」，与本项目是否运行在 USE_MOCK_DATA 模式无关，
因此始终尝试拉取；网关未部署/不可达时优雅降级（data=None + gatewayEmpty meta），
前端据此显示横幅而非白屏。
"""

from fastapi import APIRouter

from models import ApiResponse
from core.config import AKSHARE_API_BASE
from services.akshare_client import akshare_api_get
from services.meta_utils import real_meta_base, gateway_no_data_meta

router = APIRouter(tags=["datasources"])


@router.get("/project-info", response_model=ApiResponse[dict])
def project_info() -> ApiResponse[dict]:
    """代理网关 /api/project/info，返回其数据源能力自描述信息（含运行时真实健康状态）。"""
    info = akshare_api_get("/api/project/info", timeout=20)
    if info is None:
        return ApiResponse(data=None, meta=gateway_no_data_meta("网关未部署或不可达"))
    return ApiResponse(data=info, meta=real_meta_base(AKSHARE_API_BASE))
