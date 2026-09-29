"""Jobs router — 后台定时/后台任务执行状态监控。

读取 jobs.registry 中已注册任务的实时状态（上次运行、结果、耗时、下次运行、近期历史），
并提供手动触发接口。与 Dashboard 等分区接口一致，暂不强制鉴权（内部工具）。
"""

from __future__ import annotations

from fastapi import APIRouter

from models import ApiResponse
from jobs.registry import get_all_jobs, trigger_job

router = APIRouter(tags=["jobs"])


@router.get("", response_model=ApiResponse[list[dict]])
def list_jobs() -> ApiResponse[list[dict]]:
    """列出全部已注册后台任务及其最近执行状态。"""
    return ApiResponse(data=get_all_jobs())


@router.post("/{job_id}/run", response_model=ApiResponse[dict])
def run_job(job_id: str) -> ApiResponse[dict]:
    """手动触发一个支持触发的任务（如行业快照 / 历史回填）。"""
    ok, msg = trigger_job(job_id)
    return ApiResponse(data={"job_id": job_id, "ok": ok, "message": msg})
