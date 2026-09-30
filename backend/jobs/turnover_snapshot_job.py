"""全市场成交额收盘快照定时任务。

挂在 FastAPI lifespan 上（见 main.py），每交易日收盘后把**全天**成交额落库到
`base_market_turnover_daily`，供宏观看板「上一日成交额」读取。

为什么需要它：
`get_market_stats_real` 只在有人打开看板时才顺带 upsert 当天成交额，存的是
**盘中部分值**（例如 10:00 打开就只存到 10:00 的量）。若某天没人打开看板，
那天根本没有记录。用它当「上一交易日成交额」会既缺失又失真。

本任务在收盘后（15:35）固定跑一次，用 upsert 覆盖当天记录，
保证库里每个交易日留下的是**全天成交额**，而非某个盘中时刻的快照。
"""

from __future__ import annotations

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

# 收盘后落库时间：A 股 15:00 收盘，15:30 已有行业快照在跑，这里顺延到 15:35 错开
SNAPSHOT_HOUR = 15
SNAPSHOT_MINUTE = 35

_scheduler = None


def _job_daily_turnover_snapshot() -> None:
    """定时任务主体：交易日收盘后写一次全天成交额。"""
    if not _is_trading_day():
        print(f"[Turnover Job] 非交易日，跳过收盘成交额落库（{date.today()}）")
        return

    run = record_start("market_turnover_daily_snapshot")
    t0 = time.time()
    try:
        from services.market_service import get_market_stats_real

        # 内部已调用 _save_today_turnover 做 upsert，收盘后即为全天值
        stats = get_market_stats_real()
        if not stats:
            raise RuntimeError("market_stats 返回为空，未落库")
        record_success(
            "market_turnover_daily_snapshot",
            run,
            (time.time() - t0) * 1000,
        )
        print(
            f"[Turnover Job] 收盘成交额已落库：{stats.get('totalTurnover')}亿"
            f"（{stats.get('date')}）"
        )
    except Exception as e:
        record_failure("market_turnover_daily_snapshot", run, f"{type(e).__name__}: {e}")
        print(f"[Turnover Job] 收盘成交额落库失败: {type(e).__name__}: {e}")


def start_turnover_snapshot_scheduler() -> None:
    """启动成交额收盘快照定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[Turnover Job] MOCK 模式，不启动成交额快照定时任务")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            _job_daily_turnover_snapshot,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=SNAPSHOT_HOUR,
                minute=SNAPSHOT_MINUTE,
                timezone="Asia/Shanghai",
            ),
            id="market_turnover_daily_snapshot",
            name="全市场成交额每日收盘快照",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
        _scheduler = scheduler
        print(
            f"[Turnover Job] 定时任务已启动：每交易日 "
            f"{SNAPSHOT_HOUR:02d}:{SNAPSHOT_MINUTE:02d} 落全天成交额"
        )
    except Exception as e:
        print(f"[Turnover Job] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    # 注册到任务监控注册表（供「任务监控」页展示执行状态、支持手动触发）
    register_job(
        "market_turnover_daily_snapshot",
        "全市场成交额每日收盘快照",
        f"每交易日 {SNAPSHOT_HOUR:02d}:{SNAPSHOT_MINUTE:02d}（Asia/Shanghai）",
        job_type="scheduled",
        enabled=True,
        triggerable=True,
        fn=_job_daily_turnover_snapshot,
    )
    aps_job = scheduler.get_job("market_turnover_daily_snapshot")
    if aps_job and aps_job.next_run_time:
        set_next_run(
            "market_turnover_daily_snapshot",
            aps_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"),
        )


def stop_turnover_snapshot_scheduler() -> None:
    """停止定时任务（shutdown 时调用）。"""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            print("[Turnover Job] 定时任务已停止")
        except Exception as e:
            print(f"[Turnover Job] 定时任务停止异常: {e}")
        finally:
            _scheduler = None


def scheduler_status() -> dict:
    """定时任务运行状态（供运维查看）。"""
    return {
        "running": _scheduler is not None and _scheduler.running,
        "snapshotTime": f"{SNAPSHOT_HOUR:02d}:{SNAPSHOT_MINUTE:02d}",
    }
