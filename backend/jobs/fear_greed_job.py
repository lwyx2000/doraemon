"""贪婪恐惧指数每日采集定时任务。

挂在 FastAPI lifespan 上（见 main.py），每交易日收盘后（15:40，错开 15:30 行业快照 /
15:35 成交额快照）调用 fear_greed_service.collect_today()：

    - 当日快照类（上涨占比、涨停数）走 market_stats + 乐咕，收盘后即为全日值
    - 指数位置 / 量能比 / 波动率走中证官网上证日线，融资余额变化走上证两融历史
    - 落库 base_fear_greed_daily 后按「过去一年窗口」重算 6 分项得分与恐贪总值

历史序列首次部署后用 POST /api/v1/market/fear-greed/backfill 回填
（涨停池仅近数月有历史，上涨占比无历史源，见服务模块 docstring）。
"""

from __future__ import annotations

import threading
import time
from datetime import date

from jobs.registry import (
    register_job,
    record_start,
    record_success,
    record_failure,
    set_next_run,
)
from jobs.sw_snapshot_job import _is_trading_day

# 收盘后采集时间：A 股 15:00 收盘，错开 sw(15:30)/turnover(15:35)，定在 15:40
COLLECT_HOUR = 15
COLLECT_MINUTE = 40

JOB_ID = "fear_greed_daily_collect"

_scheduler = None

# 回填任务的后台线程句柄（同时只允许一个，供 /backfill 接口查询/防重入）
_backfill_thread: threading.Thread | None = None
_backfill_lock = threading.Lock()


def _job_fear_greed_collect() -> None:
    """定时任务主体：交易日收盘后采集当日恐贪指标。"""
    if not _is_trading_day():
        print(f"[FearGreed Job] 非交易日，跳过采集（{date.today()}）")
        return

    run = record_start(JOB_ID)
    t0 = time.time()
    try:
        from services.fear_greed_service import collect_today

        result = collect_today()
        if not result.get("ok"):
            # 非交易日跳过不算失败
            record_success(JOB_ID, run, (time.time() - t0) * 1000)
            print(f"[FearGreed Job] {result.get('message', 'skipped')}")
            return
        record_success(JOB_ID, run, (time.time() - t0) * 1000)
        print(
            f"[FearGreed Job] 采集完成 {result.get('date')}: "
            f"恐贪值 {result.get('totalScore')}（{result.get('label')}）"
        )
        for w in result.get("warnings") or []:
            print(f"[FearGreed Job] 警告: {w}")
    except Exception as e:
        record_failure(JOB_ID, run, f"{type(e).__name__}: {e}")
        print(f"[FearGreed Job] 采集失败: {type(e).__name__}: {e}")


def run_backfill_async(days: int = 120) -> bool:
    """后台线程执行历史回填；返回是否成功启动（已有回填在跑则 False）。"""
    global _backfill_thread
    with _backfill_lock:
        if _backfill_thread is not None and _backfill_thread.is_alive():
            return False

        def _worker() -> None:
            try:
                from services.fear_greed_service import backfill

                result = backfill(days=days)
                print(f"[FearGreed Job] 回填完成: {result}")
            except Exception as e:  # noqa: BLE001
                print(f"[FearGreed Job] 回填失败: {type(e).__name__}: {e}")

        _backfill_thread = threading.Thread(target=_worker, name="fear-greed-backfill", daemon=True)
        _backfill_thread.start()
        return True


def backfill_status() -> dict:
    """回填线程状态（供 /status 接口展示）。"""
    t = _backfill_thread
    return {"running": bool(t is not None and t.is_alive())}


def start_fear_greed_scheduler() -> None:
    """启动贪婪恐惧指数每日采集定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[FearGreed Job] MOCK 模式，不启动恐贪指数定时任务")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            _job_fear_greed_collect,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=COLLECT_HOUR,
                minute=COLLECT_MINUTE,
                timezone="Asia/Shanghai",
            ),
            id=JOB_ID,
            name="贪婪恐惧指数每日采集",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
        _scheduler = scheduler
        print(
            f"[FearGreed Job] 定时任务已启动：每交易日 "
            f"{COLLECT_HOUR:02d}:{COLLECT_MINUTE:02d} 采集恐贪指数"
        )
    except Exception as e:
        print(f"[FearGreed Job] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    # 注册到任务监控注册表（供「任务监控」页展示执行状态、支持手动触发）
    register_job(
        JOB_ID,
        "贪婪恐惧指数每日采集",
        f"每交易日 {COLLECT_HOUR:02d}:{COLLECT_MINUTE:02d}（Asia/Shanghai）",
        job_type="scheduled",
        enabled=True,
        triggerable=True,
        fn=_job_fear_greed_collect,
    )
    aps_job = scheduler.get_job(JOB_ID)
    if aps_job and aps_job.next_run_time:
        set_next_run(
            JOB_ID,
            aps_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"),
        )


def stop_fear_greed_scheduler() -> None:
    """停止定时任务（shutdown 时调用）。"""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            print("[FearGreed Job] 定时任务已停止")
        except Exception as e:
            print(f"[FearGreed Job] 定时任务停止异常: {e}")
        finally:
            _scheduler = None


def scheduler_status() -> dict:
    """定时任务运行状态（供运维查看）。"""
    return {
        "running": _scheduler is not None and _scheduler.running,
        "collectTime": f"{COLLECT_HOUR:02d}:{COLLECT_MINUTE:02d}",
        "backfill": backfill_status(),
    }
