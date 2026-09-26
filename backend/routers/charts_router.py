"""图表路由 — 公众号「每周市场复盘」11 图。

端点
----
- ``GET /``                      图表清单（元数据）
- ``GET /all``                   一次性返回全部 11 图（未命中缓存时后台刷新，本次先返回已有数据）
- ``GET /{chart_id}``            单个图表数据（?force=1 强制刷新）
- ``GET /{chart_id}/meta``       单图元数据（备用）

所有数据经 AkShare WebAPI 网关获取；路由为同步 ``def``（内部取数为阻塞 I/O，由 AnyIO 线程池卸载）。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from models import ApiResponse
from services.market_charts_service import list_charts, get_all_charts, get_chart

router = APIRouter(tags=["charts"])


@router.get("", response_model=ApiResponse[list[dict]])
def chart_list() -> ApiResponse[list[dict]]:
    """图表清单（id / 标题 / 简介）。"""
    return ApiResponse(data=list_charts())


@router.get("/all", response_model=ApiResponse[list[dict]])
def weekly_review(force: bool = Query(False, description="是否强制刷新缓存")) -> ApiResponse[list[dict]]:
    """每周市场复盘 — 全部 11 图。

    未命中缓存时触发后台刷新，本次先返回当前已有（可能部分为空）数据；
    前端可间隔轮询或点击刷新补齐。
    """
    data = get_all_charts(force=force)
    ok = any(c.get("primary", {}).get("dates") for c in data)
    return ApiResponse(
        data=data,
        meta={"isMock": False, "dataSource": "AkShare WebAPI", "updateTime": None,
              "note": None if ok else "首次加载，数据后台刷新中，请稍后刷新页面"},
    )


@router.get("/{chart_id}", response_model=ApiResponse[dict])
def single_chart(
    chart_id: str,
    force: bool = Query(False, description="强制刷新该图缓存"),
) -> ApiResponse[dict]:
    """单个图表数据。"""
    data = get_chart(chart_id, force=force)
    if data is None:
        return ApiResponse(code=404, message=f"未找到图表: {chart_id}", data=None)
    return ApiResponse(data=data)
