"""红利基金「规模 / 费率」后台渐进补全定时任务。

挂在 FastAPI lifespan 上（见 main.py）：

1. 每天 04:30（Asia/Shanghai）自动补一批（默认 200 只，1.2s/只 ≈ 5 分钟）；
2. **被限流中止后自动续跑**：看门狗每 15 分钟检查一次，若上一轮是被同花顺限流打断的，
   按 2h → 4h → 8h 指数退避自动再起一轮（一轮顺利跑完即清零），不必干等 24 小时；
3. 启动时若有缺口，先温和补一批（40 只），让后台慢慢填满 591 只。

为什么需要它：``fund_info_ths``（同花顺）**只能逐只查询**，靠用户打开页面顺手补一批
也行，但天数不可控；定时任务让数据在几天内自然补齐，且不占用请求线程。
上游会限流，因此节奏刻意放慢（见 fund_fee_service 的 DEFAULT_DELAY / MAX_CONSEC_FAIL）。
"""

from __future__ import annotations

import time

from jobs.registry import (
    register_job,
    record_failure,
    record_start,
    record_success,
    set_next_run,
)

# 每日补全时间（凌晨，避开白天请求高峰与上游限流）
FILL_HOUR = 4
FILL_MINUTE = 30
# 每轮补全只数（1.2s/只 → 约 5 分钟）
DAILY_LIMIT = 200
# 启动时先补的一小批（温和，避免启动瞬间打上游）
STARTUP_LIMIT = 40
# 看门狗轮巡间隔（分钟）：只做判断，真正取数仍在后台线程
WATCHDOG_INTERVAL_MIN = 15
# 续跑轮次的只数上限（比日常轮小，避免刚被限流又一次性灌太多）
RETRY_LIMIT = 80

_scheduler = None


def _job_fill_fees(limit: int = DAILY_LIMIT) -> dict:
    """补一批规模/费率（非阻塞：start_fill 内部起线程）。"""
    from services import fund_fee_service
    from services.dividend_service import get_backend_fund_codes

    codes = get_backend_fund_codes()
    if not codes:
        print("[DividendFee Job] 基金代码为空，跳过本轮")
        return {"filled": 0, "total": 0}

    filled_before, total = fund_fee_service.counts(codes)
    prog = fund_fee_service.start_fill(codes, limit=limit)
    msg = (
        f"[DividendFee Job] 本轮提交 {prog['total']} 只（已有 {filled_before}/{total}），"
        f"running={prog['running']}"
    )
    print(msg)
    return {"filled": filled_before, "total": total, "running": prog["running"]}


def _job_daily_fill() -> None:
    run = record_start("dividend_fee_daily_fill")
    t0 = time.time()
    try:
        _job_fill_fees(DAILY_LIMIT)
        record_success("dividend_fee_daily_fill", run, (time.time() - t0) * 1000)
    except Exception as e:
        record_failure("dividend_fee_daily_fill", run, f"{type(e).__name__}: {e}")
        print(f"[DividendFee Job] 补全失败: {type(e).__name__}: {e}")


def _maybe_startup_fill() -> None:
    """启动时若有缺口，先温和补一批。"""
    try:
        from services import fund_fee_service
        from services.dividend_service import get_backend_fund_codes

        codes = get_backend_fund_codes()
        if not codes:
            return
        missing = fund_fee_service.missing_codes(codes)
        print(f"[DividendFee Job] 现状：{len(codes) - len(missing)}/{len(codes)} 已补全")
        if missing:
            fund_fee_service.start_fill(codes, limit=STARTUP_LIMIT, auto=True)
    except Exception as e:
        print(f"[DividendFee Job] 启动补全检查失败: {type(e).__name__}: {e}")


def _job_watchdog() -> None:
    """看门狗：上一轮若被限流中止，达到退避时间后自动续跑一轮。

    ⚠️ 只在「上一轮确实是被限流打断」时才动手；正常跑完的轮次交给每日任务，
       避免变成无意义的轮询刷上游。
    """
    try:
        from services import fund_fee_service
        from services.dividend_service import get_backend_fund_codes

        # 还欠 < 1 轮的量就不用催了
        if fund_fee_service.progress()["running"]:
            return
        if not fund_fee_service.due_for_retry():
            return

        codes = get_backend_fund_codes()
        if not codes or not fund_fee_service.missing_codes(codes):
            return

        filled, total = fund_fee_service.counts(codes)
        prog = fund_fee_service.start_fill(codes, limit=RETRY_LIMIT)
        print(
            f"[DividendFee Job] 限流退避结束，自动续跑一轮：已有 {filled}/{total}，"
            f"本轮提交 {prog['total']} 只"
        )
    except Exception as e:
        print(f"[DividendFee Job] 看门狗异常: {type(e).__name__}: {e}")


def _backoff_ladder() -> list[int]:
    """退避阶梯（单一真源在 fund_fee_service）。"""
    try:
        from services import fund_fee_service

        return list(fund_fee_service.BACKOFF_LADDER_HOURS)
    except Exception:
        return [2, 4, 8]


def start_dividend_fee_scheduler() -> None:
    """启动定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[DividendFee Job] MOCK 模式，不启动补全定时任务")
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
            id="dividend_fee_daily_fill",
            name="红利基金规模/费率每日补全",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            _job_watchdog,
            trigger=IntervalTrigger(minutes=WATCHDOG_INTERVAL_MIN),
            id="dividend_fee_retry_watchdog",
            name="红利费率补全·限流后续跑",
            replace_existing=True,
            misfire_grace_time=300,
        )
        scheduler.start()
        _scheduler = scheduler
        print(
            f"[DividendFee Job] 定时任务已启动：每天 {FILL_HOUR:02d}:{FILL_MINUTE:02d} 补 {DAILY_LIMIT} 只；"
            f"看门狗每 {WATCHDOG_INTERVAL_MIN} 分钟巡检，被限流则按 "
            f"{'/'.join(str(h) + 'h' for h in _backoff_ladder())} 退避自动续跑"
        )
    except Exception as e:
        print(f"[DividendFee Job] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    register_job(
        "dividend_fee_daily_fill",
        "红利基金规模/费率每日补全",
        f"每天 {FILL_HOUR:02d}:{FILL_MINUTE:02d}（Asia/Shanghai，{DAILY_LIMIT} 只/轮）；"
        f"被限流则 {'/'.join(str(h) + 'h' for h in _backoff_ladder())} 退避自动续跑",
        job_type="scheduled",
        enabled=True,
        triggerable=True,
        fn=lambda: _job_fill_fees(DAILY_LIMIT),
    )

    aps_job = scheduler.get_job("dividend_fee_daily_fill")
    if aps_job and aps_job.next_run_time:
        set_next_run("dividend_fee_daily_fill", aps_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"))

    _maybe_startup_fill()


def stop_dividend_fee_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
