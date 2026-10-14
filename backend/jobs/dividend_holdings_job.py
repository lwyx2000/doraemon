"""红利基金「季报持仓」的定时补全（后台线程，不阻塞启动）。

配套 ``services/fund_holdings_service``：把每只红利基金的季报持仓明细抓回
``base_fund_stock_holdings``（ETF / 指数基金全量 40~115 条，主动基金十大重仓 10 条）。

为什么要单独一个任务：
    持仓取自东财 ``fund_portfolio_hold_em``（``date`` 用当年 12-31 拿最新报告期），
    上游还有一层 ``/api/ak`` 代理，**0.3s/只**，全量 591 只要跑几分钟；新发的红利基金
    也不会自动落持仓，所以需要每天夜里往前推一批。

保留手动端点 ``POST /api/v1/dividend/fill-holdings?limit=`` 供排查时立刻补一批。

⚠️ 与费率 / 指数识别任务的差异：那两个服务自己是「同步跑到完」的，这里
``fund_holdings_service.start_fill`` 会再开一层线程，所以要主动等它跑完才能上报
任务状态，否则任务一启动就显示「成功」。
"""

from __future__ import annotations

import threading
import time

from jobs.registry import (
    record_failure,
    record_start,
    record_success,
    register_job,
    set_next_run,
)

# 每日补全时间：费率 04:30、指数识别 06:15 之后，避开申万/成交额 15:30 的收盘快照
FILL_HOUR = 6
FILL_MINUTE = 45
# 每轮只数（0.3s/只 + 落库，120 只约 1 分钟出头）
DAILY_LIMIT = 120
# 启动时先补的一小批
STARTUP_LIMIT = 60
# 单个后台补全的最长等待（秒）：进度轮询兜底，避免任务状态永远卡在 running
MAX_FILL_WAIT = 900
# 轮询间隔（秒）
POLL_INTERVAL = 10

JOB_ID = "dividend_holdings_daily_fill"

_scheduler = None
_startup_done = threading.Event()


def _run_fill(job_name: str, limit: int) -> None:
    """在**后台线程**里跑一轮补全（start_fill 内部还会再开线程，这里只负责等它收尾）。"""
    from services import fund_holdings_service
    from services.dividend_service import get_backend_fund_codes

    # 红利名录 + 现金流场内 ETF（2026-10-07 用户拍板「最好都扩」）
    codes = get_backend_fund_codes() or fund_holdings_service.all_fund_codes()
    if not codes:
        print(f"[{job_name}] 基金代码为空，跳过本轮")
        return

    run = record_start(job_name)
    t0 = time.time()
    try:
        prog = fund_holdings_service.start_fill(codes, limit=limit)
        if not prog.get("running"):
            # 已是满载 / 无缺口 / 上轮还在跑：直接算一次「无事可做」的成功
            if run is not None:
                record_success(job_name, run, (time.time() - t0) * 1000)
            print(f"[{job_name}] 无需补跑（running={prog.get('running')}），本轮跳过")
            return
        _wait_for_fill(timeout=MAX_FILL_WAIT)
        record_success(job_name, run, (time.time() - t0) * 1000)
        snap = fund_holdings_service.snapshot(codes)
        print(
            f"[{job_name}] 本轮结束 遍历={snap['round_done']}/{snap['round_total']} "
            f"成功={snap['ok']} 无季报={snap['empty']} 异常={snap['fail']} "
            f"全量已补全={snap['filled']}/{snap['total']}"
        )
    except Exception as e:  # noqa: BLE001
        record_failure(job_name, run, f"{type(e).__name__}: {e}")
        print(f"[{job_name}] 补全失败: {type(e).__name__}: {e}")


def _wait_for_fill(timeout: int) -> dict:
    """轮询 ``fund_holdings_service.progress()`` 直到跑完（或超时）。"""
    from services import fund_holdings_service

    waited = 0
    prog = fund_holdings_service.progress()
    while prog.get("running") and waited < timeout:
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
        prog = fund_holdings_service.progress()
    if prog.get("running"):
        print(f"[DividendHoldings Job] 后台补全超过 {timeout}s 仍在跑，本轮任务先收尾")
    return prog


def _job_daily_fill() -> None:
    threading.Thread(
        target=_run_fill, args=(JOB_ID, DAILY_LIMIT), daemon=True
    ).start()


def _startup_fill() -> None:
    threading.Thread(
        target=_run_fill, args=("dividend_holdings_startup", STARTUP_LIMIT), daemon=True
    ).start()


_extra_runs = {"n": 0}


def _job_watchdog() -> None:
    """启动补跑后的几次兜底：首轮若仍有缺口，隔 10 分钟再补一轮就收手。

    收敛条件比「跑空」更宽松（start_fill 内部自带 TTL 缺口判断，跑空说明真没了），
    避免每 10 分钟无脑重试去撞上游。
    """
    if _startup_done.is_set() or _extra_runs["n"] >= 2:
        return
    if not _wait_for_quiet_enough():
        return
    threading.Thread(
        target=_run_fill, args=("dividend_holdings_watchdog", STARTUP_LIMIT), daemon=True
    ).start()
    _extra_runs["n"] += 1


def _wait_for_quiet_enough() -> bool:
    """看门狗前再确认一次没有别的任务在写 DuckDB（避免两个写任务撞锁）。"""
    try:
        from services import fund_holdings_service

        busy = fund_holdings_service._busy_job_names()
        if busy:
            print(f"[DividendHoldings Job] {','.join(busy)} 正在写 DuckDB，看门狗本轮让路")
            return False
    except Exception:  # noqa: BLE001
        return True
    return True


def _trigger_desc() -> str:
    return f"每天 {FILL_HOUR:02d}:{FILL_MINUTE:02d}（Asia/Shanghai，{DAILY_LIMIT} 只/轮）"


def start_dividend_holdings_scheduler() -> None:
    """启动持仓补全定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[DividendHoldings Job] MOCK 模式，不启动持仓补全定时任务")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            _job_daily_fill,
            trigger=CronTrigger(hour=FILL_HOUR, minute=FILL_MINUTE, timezone="Asia/Shanghai"),
            id=JOB_ID,
            name="红利基金季报持仓·每日补全",
            replace_existing=True,
            misfire_grace_time=7200,
        )
        scheduler.add_job(
            _job_watchdog,
            trigger=IntervalTrigger(minutes=10),
            id="dividend_holdings_startup_retry",
            name="红利基金季报持仓·启动补跑看门狗",
            replace_existing=True,
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        _scheduler = scheduler
        print(
            f"[DividendHoldings Job] 定时任务已启动：{_trigger_desc()}；"
            f"启动补跑 {STARTUP_LIMIT} 只，未跑完则每 10 分钟重试"
        )
    except Exception as e:  # noqa: BLE001
        print(f"[DividendHoldings Job] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    register_job(
        JOB_ID,
        "红利基金季报持仓·每日补全",
        _trigger_desc(),
        job_type="scheduled",
        enabled=True,
        triggerable=True,
        fn=lambda: _run_fill(JOB_ID, DAILY_LIMIT),
    )

    aps_job = scheduler.get_job(JOB_ID)
    if aps_job and aps_job.next_run_time:
        set_next_run(JOB_ID, aps_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"))

    _startup_fill()
    threading.Timer(300, _startup_done.set).start()  # 启动后 5 分钟不再看门狗兜底


def stop_dividend_holdings_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        _scheduler = None
