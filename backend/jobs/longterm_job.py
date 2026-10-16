"""长期视角数据（老钱日日谈 A股看板）每周采集定时任务。

挂在 FastAPI lifespan 上（见 main.py），每周六 17:30（Asia/Shanghai）调用
longterm_service.collect_all()：

    - 5 个数据源全部为第三方静态 JSON（ashare.laoqianriritan.com/data/*.json）
    - 日/月频序列增量落库（MAX(obs_date) 之后才插），周六采集补上本周新数据
    - 小表（行业年度收益/CAGR/收益拆解）每次全量替换
    - 上游周六未更新时为空跑（无新行可插），不影响已有快照

首次部署后用 POST /api/v1/longterm/collect 立即触发一次全量采集
（wide_base / huazheng 首建约 8 万行，同步执行约 10-30 秒，可传 async_mode=true）。
"""

from __future__ import annotations

import threading
import time

from jobs.registry import (
    register_job,
    record_start,
    record_success,
    record_failure,
    set_next_run,
)

# 每周六 17:30 采集一次：长期视角数据非实时行情，周频足够（盘中手动 POST /collect 可立即刷新）
COLLECT_WEEKDAY = "sat"
COLLECT_HOUR = 17
COLLECT_MINUTE = 30

JOB_ID = "longterm_lqr_collect"

_scheduler = None

# 手动采集的后台线程句柄（同时只允许一个，防重入）
_collect_thread: threading.Thread | None = None
_collect_lock = threading.Lock()


def _job_longterm_collect() -> None:
    """定时任务主体：抓取 5 源并落库（单源失败不影响其余源）。"""
    run = record_start(JOB_ID)
    t0 = time.time()
    try:
        from services.longterm_service import collect_all

        result = collect_all()
        if not result.get("ok"):
            record_failure(
                JOB_ID,
                run,
                f"{result.get('okCount')}/{result.get('totalCount')} 源成功",
            )
            print(
                f"[LongTerm Job] 部分源失败 "
                f"({result.get('okCount')}/{result.get('totalCount')}): "
                f"{ {k: v.get('error') for k, v in result.get('sources', {}).items() if not v.get('ok')} }"
            )
            return
        record_success(JOB_ID, run, (time.time() - t0) * 1000)
        rows = {k: v.get("rows") for k, v in result.get("sources", {}).items()}
        print(f"[LongTerm Job] 采集完成 {result.get('fetchedAt')}: 落库行数 {rows}")
    except Exception as e:
        record_failure(JOB_ID, run, f"{type(e).__name__}: {e}")
        print(f"[LongTerm Job] 采集失败: {type(e).__name__}: {e}")


def run_collect_async() -> bool:
    """后台线程执行一次全量采集；返回是否成功启动（已有采集在跑则 False）。"""
    global _collect_thread
    with _collect_lock:
        if _collect_thread is not None and _collect_thread.is_alive():
            return False

        def _worker() -> None:
            try:
                from services.longterm_service import collect_all

                result = collect_all()
                print(
                    f"[LongTerm Job] 手动采集完成: "
                    f"{result.get('okCount')}/{result.get('totalCount')} 源成功"
                )
            except Exception as e:  # noqa: BLE001
                print(f"[LongTerm Job] 手动采集失败: {type(e).__name__}: {e}")

        _collect_thread = threading.Thread(target=_worker, name="longterm-collect", daemon=True)
        _collect_thread.start()
        return True


def collect_status() -> dict:
    """手动采集线程状态（供 /status 接口展示）。"""
    t = _collect_thread
    return {"running": bool(t is not None and t.is_alive())}


def start_longterm_scheduler() -> None:
    """启动长期视角数据每周采集定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[LongTerm Job] MOCK 模式，不启动长期视角数据定时任务")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            _job_longterm_collect,
            trigger=CronTrigger(
                day_of_week=COLLECT_WEEKDAY,
                hour=COLLECT_HOUR,
                minute=COLLECT_MINUTE,
                timezone="Asia/Shanghai",
            ),
            id=JOB_ID,
            name="长期视角数据每周采集（老钱看板）",
            replace_existing=True,
            misfire_grace_time=7200,
        )
        scheduler.start()
        _scheduler = scheduler
        print(
            f"[LongTerm Job] 定时任务已启动：每周{_weekday_cn()} "
            f"{COLLECT_HOUR:02d}:{COLLECT_MINUTE:02d} 采集长期视角数据"
        )
    except Exception as e:
        print(f"[LongTerm Job] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    # 注册到任务监控注册表（供「任务监控」页展示执行状态、支持手动触发）
    register_job(
        JOB_ID,
        "长期视角数据每周采集",
        f"每周{_weekday_cn()} {COLLECT_HOUR:02d}:{COLLECT_MINUTE:02d}（Asia/Shanghai）",
        job_type="scheduled",
        enabled=True,
        triggerable=True,
        fn=_job_longterm_collect,
    )
    aps_job = scheduler.get_job(JOB_ID)
    if aps_job and aps_job.next_run_time:
        set_next_run(
            JOB_ID,
            aps_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"),
        )


def _weekday_cn() -> str:
    return {"sat": "六"}.get(COLLECT_WEEKDAY, COLLECT_WEEKDAY)


def stop_longterm_scheduler() -> None:
    """停止定时任务（shutdown 时调用）。"""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            print("[LongTerm Job] 定时任务已停止")
        except Exception as e:
            print(f"[LongTerm Job] 定时任务停止异常: {e}")
        finally:
            _scheduler = None


def scheduler_status() -> dict:
    """定时任务运行状态（供运维查看）。"""
    return {
        "running": _scheduler is not None and _scheduler.running,
        "collectTime": f"每周{_weekday_cn()} {COLLECT_HOUR:02d}:{COLLECT_MINUTE:02d}",
        "manualCollect": collect_status(),
    }
