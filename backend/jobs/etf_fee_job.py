"""ETF 费率后台渐进补全定时任务（复用 fund_fee_service.start_fill）。

挂在 lifespan（见 main.py）：
1. 每天 05:00（Asia/Shanghai）自动补一批 ETF 费率（默认 200 只，1.2s/只 ≈ 5 分钟）；
2. 被限流中止后自动续跑：看门狗每 15 分钟检查，按 2h/4h/8h 指数退避续跑；
3. 启动时若有缺口，先温和补一批（40 只）。

为何复用 fund_fee_service：规模/费率三源互备（同花顺/东财F10/集思录）已在该服务实现，
ETF 费率与红利基金费率落同一张 ``base_fund_fee_info`` 表，共用同一套补全/限流/冷却逻辑。
注意：不调用 ``attach_fees``（那会把 ETF 全量代码写进红利补全队列 _LAST_CODES 造成污染），
而是直接 ``start_fill(etf_codes)``，该队列是 ETF 专属。
"""

from __future__ import annotations

import threading
import time

from jobs.registry import (
    register_job,
    record_failure,
    record_start,
    record_success,
    set_next_run,
)

# 每日补全时间（凌晨，避开白天请求高峰与上游限流）
FILL_HOUR = 5
FILL_MINUTE = 0
# 每轮补全只数（1.2s/只 → 约 5 分钟）
DAILY_LIMIT = 200
# 启动时先补的一小批（温和，避免启动瞬间打上游）
STARTUP_LIMIT = 40
# 看门狗轮巡间隔（分钟）：只做判断，真正取数仍在后台线程
WATCHDOG_INTERVAL_MIN = 15
# 续跑轮次的只数上限（比日常轮小，避免刚被限流又一次性灌太多）
RETRY_LIMIT = 80

_scheduler = None


def _job_fill(limit: int = DAILY_LIMIT) -> dict:
    """补一批 ETF 费率（非阻塞：start_fill 内部起线程）。"""
    from services import fund_fee_service
    from services.etf_service import get_all_etf_codes

    codes = get_all_etf_codes()
    if not codes:
        print("[ETFFee Job] ETF 代码为空，跳过本轮")
        return {"filled": 0, "total": 0}

    filled_before, total = fund_fee_service.counts(codes)
    prog = fund_fee_service.start_fill(codes, limit=limit)
    msg = (
        f"[ETFFee Job] 本轮提交 {prog['total']} 只（已有 {filled_before}/{total}），"
        f"running={prog['running']}"
    )
    print(msg)
    return {"filled": filled_before, "total": total, "running": prog["running"]}


def _job_daily_fill() -> None:
    run = record_start("etf_fee_daily_fill")
    t0 = time.time()
    try:
        _job_fill(DAILY_LIMIT)
        record_success("etf_fee_daily_fill", run, (time.time() - t0) * 1000)
    except Exception as e:
        record_failure("etf_fee_daily_fill", run, f"{type(e).__name__}: {e}")
        print(f"[ETFFee Job] 补全失败: {type(e).__name__}: {e}")


def _maybe_startup_fill() -> None:
    """启动时若有缺口，先温和补一批（异步线程内调用，全程 try 保护）。

    ⚠️ 内含一次上游网络取数（get_all_etf_codes → fund_rank etf），绝不可在 lifespan
       主线程同步调用，否则会像 ETF 快照那样卡死整站启动。
    """
    try:
        from services import fund_fee_service
        from services.etf_service import get_all_etf_codes

        codes = get_all_etf_codes()
        if not codes:
            return
        missing = fund_fee_service.missing_codes(codes)
        print(f"[ETFFee Job] 现状：{len(codes) - len(missing)}/{len(codes)} 已补全")
        if missing:
            fund_fee_service.start_fill(codes, limit=STARTUP_LIMIT, auto=True)
    except Exception as e:
        print(f"[ETFFee Job] 启动补全检查失败（忽略，不影响服务启动）: {type(e).__name__}: {e}")


def _job_watchdog() -> None:
    """看门狗：上一轮若被限流中止，达到退避时间后自动续跑一轮。"""
    try:
        from services import fund_fee_service
        from services.etf_service import get_all_etf_codes

        if fund_fee_service.progress()["running"]:
            return
        if not fund_fee_service.due_for_retry():
            return

        codes = get_all_etf_codes()
        if not codes or not fund_fee_service.missing_codes(codes):
            return

        filled, total = fund_fee_service.counts(codes)
        prog = fund_fee_service.start_fill(codes, limit=RETRY_LIMIT)
        print(
            f"[ETFFee Job] 限流退避结束，自动续跑一轮：已有 {filled}/{total}，"
            f"本轮提交 {prog['total']} 只"
        )
    except Exception as e:
        print(f"[ETFFee Job] 看门狗异常: {type(e).__name__}: {e}")


def start_etf_fee_scheduler() -> None:
    """启动定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[ETFFee Job] MOCK 模式，不启动补全定时任务")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            _job_daily_fill,
            trigger=CronTrigger(
                hour=FILL_HOUR,
                minute=FILL_MINUTE,
                timezone="Asia/Shanghai",
            ),
            id="etf_fee_daily_fill",
            name="ETF费率每日补全",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            _job_watchdog,
            trigger=IntervalTrigger(minutes=WATCHDOG_INTERVAL_MIN),
            id="etf_fee_retry_watchdog",
            name="ETF费率补全·限流后续跑",
            replace_existing=True,
            misfire_grace_time=300,
        )
        scheduler.start()
        _scheduler = scheduler
        print(
            f"[ETFFee Job] 定时任务已启动：每天 {FILL_HOUR:02d}:{FILL_MINUTE:02d} 补 {DAILY_LIMIT} 只；"
            f"看门狗每 {WATCHDOG_INTERVAL_MIN} 分钟巡检，被限流则按 2h/4h/8h 退避自动续跑"
        )
    except Exception as e:
        print(f"[ETFFee Job] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    # 注册到 jobs 面板（轻量，绝不抛）
    try:
        register_job(
            "etf_fee_daily_fill",
            "ETF费率每日补全",
            f"每天 {FILL_HOUR:02d}:{FILL_MINUTE:02d}（Asia/Shanghai，{DAILY_LIMIT} 只/轮）；"
            f"被限流则 2h/4h/8h 退避自动续跑",
            job_type="scheduled",
            enabled=True,
            triggerable=True,
            fn=lambda: _job_fill(DAILY_LIMIT),
        )
        aps_job = scheduler.get_job("etf_fee_daily_fill")
        if aps_job and aps_job.next_run_time:
            set_next_run("etf_fee_daily_fill", aps_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        print(f"[ETFFee Job] 注册 jobs 面板失败（忽略）: {e}")

    # ⚠️ 启动补全必须异步：内含上游网络取数，fire-and-forget 线程，绝不阻塞 lifespan。
    threading.Thread(target=_maybe_startup_fill, daemon=True).start()


def stop_etf_fee_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
