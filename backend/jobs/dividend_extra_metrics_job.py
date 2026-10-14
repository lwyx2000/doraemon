"""红利/现金流基金「三类补充指标」后台渐进补全定时任务。

挂在 FastAPI lifespan 上（见 main.py）：

1. 每天 05:00（Asia/Shanghai）自动补一批（默认 200 只，1.2s/只 ≈ 5 分钟）；
2. **被限流中止后自动续跑**：看门狗每 15 分钟检查一次，若上一轮是被上游限流打断的，
   按 2h → 4h → 8h 指数退避自动再起一轮；
3. 启动时若有缺口，先温和补一批（40 只）。

三项指标（跟踪误差 / 分红频率 / 行业集中度）分别走不同数据源，计算全防御，
落 DuckDB 后页面随名录自动带出。数据源：东财 fund_open_fund_info_em（跟踪误差）、
天天基金 F10 fhsp（分红频率）、东财 fund_portfolio_hold_em 持仓 + akshare 申万行业
（行业集中度）。
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
FILL_HOUR = 5
FILL_MINUTE = 0
# 每轮补全只数（1.2s/只 → 约 5 分钟）
DAILY_LIMIT = 200
# 启动时先补的一小批（温和，避免启动瞬间打上游）
STARTUP_LIMIT = 40
# 看门狗轮巡间隔（分钟）
WATCHDOG_INTERVAL_MIN = 15
# 续跑轮次的只数上限（比日常轮小，避免刚被限流又一次性灌太多）
RETRY_LIMIT = 80

_scheduler = None


def _job_fill(limit: int = DAILY_LIMIT) -> dict:
    """补一批三类指标（非阻塞：start_fill 内部起线程）。"""
    from services import fund_extra_metrics_service
    from services.dividend_service import get_backend_fund_codes

    codes = get_backend_fund_codes()
    if not codes:
        print("[ExtraMetrics Job] 基金代码为空，跳过本轮")
        return {"filled": 0, "total": 0}

    filled_before, total = fund_extra_metrics_service.counts(codes)
    prog = fund_extra_metrics_service.start_fill(codes, limit=limit)
    msg = (
        f"[ExtraMetrics Job] 本轮提交 {prog['total']} 只（已有 {filled_before}/{total}），"
        f"running={prog['running']}"
    )
    print(msg)
    return {"filled": filled_before, "total": total, "running": prog["running"]}


def _job_daily_fill() -> None:
    run = record_start("dividend_extra_metrics_daily_fill")
    t0 = time.time()
    try:
        _job_fill(DAILY_LIMIT)
        record_success("dividend_extra_metrics_daily_fill", run, (time.time() - t0) * 1000)
    except Exception as e:
        record_failure("dividend_extra_metrics_daily_fill", run, f"{type(e).__name__}: {e}")
        print(f"[ExtraMetrics Job] 补全失败: {type(e).__name__}: {e}")


def _maybe_startup_fill() -> None:
    """启动时若有缺口，先温和补一批。"""
    try:
        from services import fund_extra_metrics_service
        from services.dividend_service import get_backend_fund_codes

        codes = get_backend_fund_codes()
        if not codes:
            return
        missing = fund_extra_metrics_service.missing_codes(codes)
        print(f"[ExtraMetrics Job] 现状：{len(codes) - len(missing)}/{len(codes)} 已补全")
        if missing:
            fund_extra_metrics_service.start_fill(codes, limit=STARTUP_LIMIT, auto=True)
    except Exception as e:
        print(f"[ExtraMetrics Job] 启动补全检查失败: {type(e).__name__}: {e}")


def _job_watchdog() -> None:
    """看门狗：上一轮若被限流中止，达到退避时间后自动续跑一轮。"""
    try:
        from services import fund_extra_metrics_service
        from services.dividend_service import get_backend_fund_codes

        if fund_extra_metrics_service.progress()["running"]:
            return
        if not fund_extra_metrics_service.due_for_retry():
            return

        codes = get_backend_fund_codes()
        if not codes or not fund_extra_metrics_service.missing_codes(codes):
            return

        filled, total = fund_extra_metrics_service.counts(codes)
        prog = fund_extra_metrics_service.start_fill(codes, limit=RETRY_LIMIT)
        print(
            f"[ExtraMetrics Job] 限流退避结束，自动续跑一轮：已有 {filled}/{total}，"
            f"本轮提交 {prog['total']} 只"
        )
    except Exception as e:
        print(f"[ExtraMetrics Job] 看门狗异常: {type(e).__name__}: {e}")


def _backoff_ladder() -> list[int]:
    try:
        from services import fund_extra_metrics_service

        return list(fund_extra_metrics_service.BACKOFF_LADDER_HOURS)
    except Exception:
        return [2, 4, 8]


def start_dividend_extra_metrics_scheduler() -> None:
    """启动定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[ExtraMetrics Job] MOCK 模式，不启动补全定时任务")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            _job_daily_fill,
            trigger=CronTrigger(hour=FILL_HOUR, minute=FILL_MINUTE, timezone="Asia/Shanghai"),
            id="dividend_extra_metrics_daily_fill",
            name="红利/现金流三类指标每日补全",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            _job_watchdog,
            trigger=IntervalTrigger(minutes=WATCHDOG_INTERVAL_MIN),
            id="dividend_extra_metrics_retry_watchdog",
            name="三类指标补全·限流后续跑",
            replace_existing=True,
            misfire_grace_time=300,
        )
        scheduler.start()
        _scheduler = scheduler
        print(
            f"[ExtraMetrics Job] 定时任务已启动：每天 {FILL_HOUR:02d}:{FILL_MINUTE:02d} 补 {DAILY_LIMIT} 只；"
            f"看门狗每 {WATCHDOG_INTERVAL_MIN} 分钟巡检，被限流则按 "
            f"{'/'.join(str(h) + 'h' for h in _backoff_ladder())} 退避自动续跑"
        )
    except Exception as e:
        print(f"[ExtraMetrics Job] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    register_job(
        "dividend_extra_metrics_daily_fill",
        "红利/现金流三类指标每日补全",
        f"每天 {FILL_HOUR:02d}:{FILL_MINUTE:02d}（Asia/Shanghai，{DAILY_LIMIT} 只/轮）；"
        f"被限流则 {'/'.join(str(h) + 'h' for h in _backoff_ladder())} 退避自动续跑",
        job_type="scheduled",
        enabled=True,
        triggerable=True,
        fn=lambda: _job_fill(DAILY_LIMIT),
    )

    aps_job = scheduler.get_job("dividend_extra_metrics_daily_fill")
    if aps_job and aps_job.next_run_time:
        set_next_run("dividend_extra_metrics_daily_fill", aps_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"))

    _maybe_startup_fill()


def stop_dividend_extra_metrics_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
