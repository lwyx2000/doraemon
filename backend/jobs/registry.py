"""后台任务注册表 —— 集中记录定时/后台任务的执行状态，供「任务监控」页展示。

设计要点：
- 纯内存（进程级）。进程重启后历史清零，但 last_run / next_run 等关键字段实时反映当前
  状态，足以支撑「定时任务执行情况」的监控诉求。如需跨重启持久化，后续可落 DuckDB。
- 与 APScheduler 解耦：任何后台任务（cron 定时、手动触发、启动期回填）都通过
  register_job + record_* 上报，统一在一个视图里呈现，避免各任务各自打日志难以观测。
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

MAX_RECENT_RUNS = 20

_STATUS_LABELS = {
    "never": "从未运行",
    "running": "运行中",
    "success": "成功",
    "failed": "失败",
}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class JobRun:
    started_at: float
    finished_at: Optional[float] = None
    status: str = "running"  # running | success | failed
    duration_ms: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "started_at": _now_str_from(self.started_at),
            "finished_at": _now_str_from(self.finished_at) if self.finished_at else None,
            "status": self.status,
            "duration_ms": round(self.duration_ms) if self.duration_ms is not None else None,
            "error": self.error,
        }


@dataclass
class JobRecord:
    job_id: str
    name: str
    schedule: str
    job_type: str = "unknown"  # scheduled | manual | startup
    enabled: bool = True
    triggerable: bool = False  # 是否支持「立即运行」按钮
    last_run_at: Optional[str] = None
    last_status: str = "never"  # never | success | failed | running
    last_duration_ms: Optional[float] = None
    last_error: Optional[str] = None
    next_run_at: Optional[str] = None
    run_count: int = 0
    fail_count: int = 0
    recent_runs: list[JobRun] = field(default_factory=list)
    _fn: Optional[Callable[[], Any]] = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "schedule": self.schedule,
            "job_type": self.job_type,
            "enabled": self.enabled,
            "triggerable": self.triggerable,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "last_status_label": _STATUS_LABELS.get(self.last_status, self.last_status),
            "last_duration_ms": round(self.last_duration_ms) if self.last_duration_ms is not None else None,
            "last_error": self.last_error,
            "next_run_at": self.next_run_at,
            "run_count": self.run_count,
            "fail_count": self.fail_count,
            "recent_runs": [r.to_dict() for r in self.recent_runs],
        }


def _now_str_from(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


_LOCK = threading.Lock()
_JOBS: dict[str, JobRecord] = {}


def register_job(
    job_id: str,
    name: str,
    schedule: str,
    *,
    job_type: str = "unknown",
    enabled: bool = True,
    triggerable: bool = False,
    fn: Optional[Callable[[], Any]] = None,
) -> JobRecord:
    """注册（或幂等更新）一个任务。重复注册只刷新静态信息。"""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            job = JobRecord(
                job_id=job_id,
                name=name,
                schedule=schedule,
                job_type=job_type,
                enabled=enabled,
                triggerable=triggerable,
                _fn=fn,
            )
            _JOBS[job_id] = job
        else:
            job.name = name
            job.schedule = schedule
            job.job_type = job_type
            job.enabled = enabled
            job.triggerable = triggerable
            if fn is not None:
                job._fn = fn
    return job


def record_start(job_id: str) -> Optional[JobRun]:
    """标记一次运行开始，返回本次运行的句柄（供 success/failure 使用）。"""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        run = JobRun(started_at=time.time())
        job.recent_runs.append(run)
        if len(job.recent_runs) > MAX_RECENT_RUNS:
            job.recent_runs = job.recent_runs[-MAX_RECENT_RUNS:]
        job.last_status = "running"
        job.last_run_at = _now_str()
        job.run_count += 1
        return run


def record_success(job_id: str, run: Optional[JobRun], duration_ms: Optional[float] = None) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or run is None:
            return
        run.finished_at = time.time()
        run.status = "success"
        run.duration_ms = duration_ms if duration_ms is not None else (run.finished_at - run.started_at) * 1000
        job.last_status = "success"
        job.last_duration_ms = run.duration_ms
        job.last_error = None


def record_failure(job_id: str, run: Optional[JobRun], error: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or run is None:
            return
        run.finished_at = time.time()
        run.status = "failed"
        run.duration_ms = (run.finished_at - run.started_at) * 1000
        run.error = error
        job.last_status = "failed"
        job.last_duration_ms = run.duration_ms
        job.last_error = error
        job.fail_count += 1


def set_next_run(job_id: str, next_run_at: Optional[str]) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.next_run_at = next_run_at


def get_all_jobs() -> list[dict]:
    with _LOCK:
        return [j.to_dict() for j in _JOBS.values()]


def get_job(job_id: str) -> Optional[JobRecord]:
    with _LOCK:
        return _JOBS.get(job_id)


def trigger_job(job_id: str) -> tuple[bool, str]:
    """手动触发一个 triggerable 任务；返回 (ok, message)。"""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return False, "任务不存在"
        if not job.triggerable or job._fn is None:
            return False, "该任务不支持手动触发"
        fn = job._fn
    try:
        fn()
        return True, "已触发"
    except Exception as e:  # noqa: BLE001
        return False, f"触发失败: {type(e).__name__}: {e}"
