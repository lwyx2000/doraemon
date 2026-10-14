"""红利基金「跟踪指数识别」的定时补全（后台线程，不阻塞启动）。

配套 ``services/fund_index_map_service``：把基金的「跟踪标的 / 业绩比较基准」
文本反查到 26 个红利指数上，结果落 ``base_fund_index_map``。

为什么要单独一个任务：
    识别的主数据源是天天基金 F10（``jbgk_<code>.html`` 的「跟踪标的」），
    1.1s/只，属于**逐只请求**，不能一次性跑完；新发的红利基金也不会自动
    带映射，所以需要每天夜里温和小批量往前推。

保留手动端点 ``POST /api/v1/dividend/fill-index-map`` 供排查时立刻补一批。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from jobs.registry import (
    record_failure,
    record_start,
    record_success,
    register_job,
    set_next_run,
)

# 每日补全时间（排在费率补全 04:30 之后，错开上游请求）
FILL_HOUR = 6
FILL_MINUTE = 15
# 每轮只数（LOCAL_DELAY=1.1s/只 → 60 只约 1 分钟）
DAILY_LIMIT = 60
# 启动时先补的一小批（温和，避免启动瞬间打上游）
STARTUP_LIMIT = 40

_scheduler = None
_startup_done = threading.Event()


def _run_fill(job_name: str, limit: int) -> None:
    """在**后台线程**里跑一轮识别（map_batch 内部有 sleep，不能占着启动流程）。"""
    from services import fund_index_map_service
    from services.dividend_service import get_dividend_fund_codes

    codes = get_dividend_fund_codes()
    if not codes:
        print(f"[{job_name}] 基金代码为空，跳过本轮")
        return

    run = record_start(job_name)
    t0 = time.time()
    try:
        prog = fund_index_map_service.map_batch(codes, limit=limit)
        record_success(job_name, run, (time.time() - t0) * 1000)
        print(
            f"[{job_name}] 本轮扫描 {prog.get('this_round', 0)} 只，"
            f"累计已识别 {prog.get('matched', 0)} 只"
        )
    except Exception as e:  # noqa: BLE001
        record_failure(job_name, run, f"{type(e).__name__}: {e}")
        print(f"[{job_name}] 补全失败: {type(e).__name__}: {e}")


def _job_daily_fill() -> None:
    threading.Thread(
        target=_run_fill, args=("dividend_index_map_daily_fill", DAILY_LIMIT), daemon=True
    ).start()


_extra_runs = {"n": 0}


def _job_watchdog() -> None:
    """启动补跑后的 1~2 次兜底：首轮若还有未识别的，隔 10 分钟再补一轮就收手。

    收敛条件比「跑空」更宽松，避免每 10 分钟无脑重试去撞天天基金限流。
    """
    if _startup_done.is_set() or _extra_runs["n"] >= 2:
        return
    from services import fund_index_map_service
    from services.dividend_service import get_dividend_fund_codes

    codes = get_dividend_fund_codes()
    prog = fund_index_map_service.map_batch(codes, limit=STARTUP_LIMIT)
    _extra_runs["n"] += 1
    print(
        f"[DividendIdxMap Job] 启动兜底第 {_extra_runs['n']} 轮：扫描 "
        f"{prog.get('this_round', 0)} 只，累计已识别 {prog.get('matched', 0)} 只"
    )


def _startup_fill() -> None:
    threading.Thread(
        target=_run_fill, args=("dividend_index_map_startup", STARTUP_LIMIT), daemon=True
    ).start()


def _trigger_desc() -> str:
    return f"每天 {FILL_HOUR:02d}:{FILL_MINUTE:02d}（Asia/Shanghai，{DAILY_LIMIT} 只/轮）"


def start_dividend_index_map_scheduler() -> None:
    """启动识别定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[DividendIdxMap Job] MOCK 模式，不启动识别定时任务")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            _job_daily_fill,
            trigger=CronTrigger(hour=FILL_HOUR, minute=FILL_MINUTE, timezone="Asia/Shanghai"),
            id="dividend_index_map_daily_fill",
            name="红利基金跟踪指数识别·每日补全",
            replace_existing=True,
            misfire_grace_time=7200,
        )
        scheduler.add_job(
            _job_watchdog,
            trigger=IntervalTrigger(minutes=10),
            id="dividend_index_map_startup_retry",
            name="红利基金跟踪指数识别·启动补跑看门狗",
            replace_existing=True,
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        _scheduler = scheduler
        print(
            f"[DividendIdxMap Job] 定时任务已启动：{_trigger_desc()}；"
            f"启动补跑 {STARTUP_LIMIT} 只，未跑完则每 10 分钟重试"
        )
    except Exception as e:  # noqa: BLE001
        print(f"[DividendIdxMap Job] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    register_job(
        "dividend_index_map_daily_fill",
        "红利基金跟踪指数识别·每日补全",
        _trigger_desc(),
        job_type="scheduled",
        enabled=True,
        triggerable=True,
        fn=lambda: _run_fill("dividend_index_map_daily_fill", DAILY_LIMIT),
    )

    aps_job = scheduler.get_job("dividend_index_map_daily_fill")
    if aps_job and aps_job.next_run_time:
        set_next_run("dividend_index_map_daily_fill", aps_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"))

    _startup_fill()


def stop_dividend_index_map_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        _scheduler = None
        _startup_done.clear()
