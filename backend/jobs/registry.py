"""后台任务注册表 —— 集中记录定时/后台任务的执行状态，供「任务监控」页展示。

持久化改造（2026-10-08）：原实现为纯进程内存态，backend 容器重启后 last_status / run_count
等清零，导致「任务监控」页长期显示「从未运行」。现改为以 SQLite（biz 库 job_registry 表）
为权威存储：record_* 实时落库，register_job 用 INSERT OR IGNORE 保留历史；重启后从 SQLite
恢复状态。静态元数据（name / schedule / triggerable / fn）仍留在内存（随注册重建），
recent_runs 为当前进程内的近期执行（重启后清空，符合「本进程观测」语义）。
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Callable, Optional

from database.sqlite_connection import get_biz_db


MAX_RECENT_RUNS = 20

_STATUS_LABELS = {
    "never": "从未运行",
    "running": "运行中",
    "success": "成功",
    "failed": "失败",
}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _Run:
    """单次运行的轻量句柄（仅供 record_success / record_failure 使用）。"""

    def __init__(self) -> None:
        self.started_at = datetime.now()
        self.finished_at: Optional[datetime] = None
        self.status = "running"
        self.duration_ms: Optional[float] = None
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": self.finished_at.strftime("%Y-%m-%d %H:%M:%S") if self.finished_at else None,
            "status": self.status,
            "duration_ms": round(self.duration_ms) if self.duration_ms is not None else None,
            "error": self.error,
        }


_LOCK = threading.RLock()
_JOBS: dict[str, dict] = {}


class _Expr:
    """标记一个 SQL 表达式值（在 _persist_upsert 中作为内联 SQL，而非绑定参数）。"""

    def __init__(self, sql: str) -> None:
        self.sql = sql


def _expr(sql: str) -> _Expr:
    return _Expr(sql)


def _persist_upsert(job_id: str, name: str, schedule: str, update_cols: Optional[list] = None, **fields) -> None:
    """UPSERT 任务行：保证行存在，并写入字段。

    fields 的值为普通 Python 值时作为绑定参数；为 _Expr 时作为内联 SQL 表达式
    （如 run_count+1），用于自增计数。
    update_cols: 仅这些列参与 ON CONFLICT(DO UPDATE) 的 SET；其余列只在 INSERT 时写入，
    冲突时保留原值。register_job 必须把 last_status/run_count/fail_count 排除出 update_cols，
    否则容器重启会把持久化的状态清零 —— 这正是「任务监控」长期显示「从未运行」的根因。
    """
    db = get_biz_db()
    normal: dict[str, Any] = {}
    exprs: dict[str, str] = {}
    for k, v in fields.items():
        if isinstance(v, _Expr):
            exprs[k] = v.sql
        else:
            normal[k] = v
    if update_cols is None:
        update_cols = list(normal.keys()) + list(exprs.keys())
    always_insert = ["name", "schedule"]
    insert_cols = ["job_id", "name", "schedule"] + list(normal.keys()) + list(exprs.keys())
    # INSERT 阶段无法引用「表已有的行」（该行此刻尚不存在），所以 _Expr 列一律填中性占位 0，
    # 自增只发生在 DO UPDATE 分支 —— 那里 c 解析为表列，c = c + 1 取的是旧值。
    insert_vals = ["?", "?", "?"] + ["?"] * len(normal) + ["0"] * len(exprs)
    set_parts = [
        f"{c}=excluded.{c}"
        for c in update_cols
        if c in normal or c in always_insert
    ] + [
        f"{c}={exprs[c]}"
        for c in update_cols
        if c in exprs
    ]
    sql = (
        f"INSERT INTO job_registry ({', '.join(insert_cols)}, updated_at) "
        f"VALUES ({', '.join(insert_vals)}, ?) "
        f"ON CONFLICT(job_id) DO UPDATE SET {', '.join(set_parts)}, updated_at=excluded.updated_at"
    )
    params = [job_id, name, schedule] + list(normal.values()) + [_now_str()]
    db.execute(sql, params)


def register_job(
    job_id: str,
    name: str,
    schedule: str,
    *,
    job_type: str = "unknown",
    enabled: bool = True,
    triggerable: bool = False,
    fn: Optional[Callable[[], Any]] = None,
) -> dict:
    """注册（或幂等更新）一个任务。重复注册只刷新静态信息。同时保证 SQLite 行存在。"""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            job = {
                "job_id": job_id,
                "name": name,
                "schedule": schedule,
                "job_type": job_type,
                "enabled": enabled,
                "triggerable": triggerable,
                "fn": fn,
                "recent_runs": [],
            }
            _JOBS[job_id] = job
        else:
            job["name"] = name
            job["schedule"] = schedule
            job["job_type"] = job_type
            job["enabled"] = enabled
            job["triggerable"] = triggerable
            if fn is not None:
                job["fn"] = fn
    try:
        _persist_upsert(
            job_id, name, schedule,
            update_cols=["name", "schedule", "job_type", "enabled", "triggerable"],
            job_type=job_type,
            enabled=1 if enabled else 0,
            triggerable=1 if triggerable else 0,
            last_status="never",
            run_count=0,
            fail_count=0,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[registry] register_job persist failed for {job_id}: {e}")
    return job


def record_start(job_id: str) -> Optional[_Run]:
    """标记一次运行开始，返回本次运行的句柄。同时落库（run_count+1, last_status=running）。"""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        run = _Run()
        job["recent_runs"].append(run)
        if len(job["recent_runs"]) > MAX_RECENT_RUNS:
            job["recent_runs"] = job["recent_runs"][-MAX_RECENT_RUNS:]
    try:
        _persist_upsert(
            job_id, job["name"], job["schedule"],
            update_cols=["last_status", "last_run_at", "run_count"],
            last_status="running",
            last_run_at=_now_str(),
            run_count=_expr("run_count + 1"),
        )
    except Exception as e:  # noqa: BLE001
        print(f"[registry] record_start persist failed for {job_id}: {e}")
    return run


def record_success(job_id: str, run: Optional[_Run], duration_ms: Optional[float] = None) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or run is None:
            return
        run.finished_at = datetime.now()
        run.status = "success"
        run.duration_ms = duration_ms if duration_ms is not None else (run.finished_at - run.started_at).total_seconds() * 1000
        job["recent_runs"][-1] = run
    try:
        dm = round(run.duration_ms) if run.duration_ms is not None else None
        _persist_upsert(
            job_id, job["name"], job["schedule"],
            update_cols=["last_status", "last_duration_ms", "last_error"],
            last_status="success",
            last_duration_ms=dm,
            last_error=None,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[registry] record_success persist failed for {job_id}: {e}")


def record_failure(job_id: str, run: Optional[_Run], error: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or run is None:
            return
        run.finished_at = datetime.now()
        run.status = "failed"
        run.duration_ms = (run.finished_at - run.started_at).total_seconds() * 1000
        run.error = str(error)
        job["recent_runs"][-1] = run
    try:
        _persist_upsert(
            job_id, job["name"], job["schedule"],
            update_cols=["last_status", "last_error", "last_duration_ms", "fail_count"],
            last_status="failed",
            last_error=str(error)[:500],
            last_duration_ms=round(run.duration_ms),
            fail_count=_expr("fail_count + 1"),
        )
    except Exception as e:  # noqa: BLE001
        print(f"[registry] record_failure persist failed for {job_id}: {e}")


def set_next_run(job_id: str, next_run_at: Optional[str]) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job["next_run_at"] = next_run_at
            sched = job.get("schedule", "")
        else:
            sched = ""
    try:
        _persist_upsert(job_id, _JOB_NAME(job_id), sched, update_cols=["next_run_at"], next_run_at=next_run_at)
    except Exception as e:  # noqa: BLE001
        print(f"[registry] set_next_run persist failed for {job_id}: {e}")


def _JOB_NAME(job_id: str) -> str:
    with _LOCK:
        return _JOBS.get(job_id, {}).get("name", job_id)


def get_all_jobs() -> list[dict]:
    """返回全部任务（合并内存静态信息 + SQLite 持久化状态）。"""
    db = get_biz_db()
    try:
        rows = db.fetchall(
            "SELECT job_id, name, schedule, job_type, enabled, triggerable, "
            "last_status, last_run_at, last_duration_ms, last_error, next_run_at, "
            "run_count, fail_count FROM job_registry ORDER BY job_id"
        )
    except Exception:  # noqa: BLE001
        rows = []
    with _LOCK:
        memory = {jid: j for jid, j in _JOBS.items()}
    result = []
    for r in rows:
        jid = r[0]
        mem = memory.get(jid, {})
        recent = [rr.to_dict() for rr in mem.get("recent_runs", [])]
        enabled = bool(r[4]) if r[4] is not None else mem.get("enabled", True)
        triggerable = bool(r[5]) if r[5] is not None else mem.get("triggerable", False)
        last_status = r[6] or "never"
        result.append({
            "job_id": jid,
            "name": mem.get("name") or r[1],
            "schedule": mem.get("schedule") or r[2] or "",
            "job_type": mem.get("job_type") or r[3] or "unknown",
            "enabled": enabled,
            "triggerable": triggerable,
            "last_run_at": r[7],
            "last_status": last_status,
            "last_status_label": _STATUS_LABELS.get(last_status, last_status),
            "last_duration_ms": round(r[8]) if r[8] is not None else None,
            "last_error": r[9],
            "next_run_at": r[10],
            "run_count": r[11] or 0,
            "fail_count": r[12] or 0,
            "recent_runs": recent,
        })
    return result


def get_job(job_id: str) -> Optional[dict]:
    with _LOCK:
        return _JOBS.get(job_id)


def trigger_job(job_id: str) -> tuple[bool, str]:
    """手动触发一个 triggerable 任务；返回 (ok, message)。"""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return False, "任务不存在"
        if not job.get("triggerable") or job.get("fn") is None:
            return False, "该任务不支持手动触发"
        fn = job["fn"]
    try:
        fn()
        return True, "已触发"
    except Exception as e:  # noqa: BLE001
        return False, f"触发失败: {type(e).__name__}: {e}"
