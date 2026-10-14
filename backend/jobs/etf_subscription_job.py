"""ETF 每日申赎快照定时任务。

挂在 FastAPI lifespan（见 main.py）：
1. 每天 19:00（Asia/Shanghai）快照当日 ETF 份额/规模/净值（麦蕊 fund_rank etf）；
2. 启动时若还没有快照（首次部署 / 表空）补一次，让页面当天就有「日净申赎」列。

为何 19:00：麦蕊 fund_rank 的「净值日期」通常滞后一个交易日，19:00 后当日收盘数据
已基本稳定，快照能拿到最新一日的 (code, 净值日期, 份额, 规模)。

⚠️ 启动快照**必须异步**（daemon 线程）：`_snapshot_daily` 含一次上游网络取数，
若在 lifespan 主线程同步调用，上游慢/挂会令 uvicorn 永远卡在
「Waiting for application startup」——整站 /api 全 502。因此启动快照 fire-and-forget。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone, timedelta

from jobs.registry import (
    register_job,
    record_failure,
    record_start,
    record_success,
    set_next_run,
)

CST = timezone(timedelta(hours=8))

# 每日快照时间（盘后，避开白天请求高峰）
SNAPSHOT_HOUR = 19
SNAPSHOT_MINUTE = 0

_scheduler = None


def _job_snapshot() -> dict:
    """快照当日 ETF 份额/规模/净值（apscheduler 线程内调用，非阻塞主进程）。"""
    from services import etf_subscription_service

    run = record_start("etf_subscription_daily")
    t0 = time.time()
    try:
        res = etf_subscription_service._snapshot_daily()
        record_success("etf_subscription_daily", run, (time.time() - t0) * 1000)
        return res
    except Exception as e:
        record_failure("etf_subscription_daily", run, f"{type(e).__name__}: {e}")
        print(f"[ETFSub Job] 快照失败: {type(e).__name__}: {e}")
        return {"ok": False, "error": str(e)}


def _maybe_startup_snapshot() -> None:
    """启动时若从没快照 / 最新快照超过 1 天，补一次（异步线程内调用，全程 try 保护）。"""
    try:
        from database.connection import get_db
        from services import etf_subscription_service

        db = get_db()
        etf_subscription_service._ensure_table(db)
        row = db.fetchone("SELECT MAX(trade_date) FROM base_etf_subscription_daily")
        latest = row[0] if row else None
        need = True
        if latest:
            try:
                latest_dt = datetime.strptime(str(latest), "%Y-%m-%d").date()
                need = (datetime.now(CST).date() - latest_dt).days > 1
            except Exception:
                need = True
        if need:
            etf_subscription_service._snapshot_daily()
            print(f"[ETFSub Job] 启动补快照完成（latest={latest}）")
    except Exception as e:
        print(f"[ETFSub Job] 启动快照失败（忽略，不影响服务启动）: {e}")


def start_etf_subscription_scheduler() -> None:
    """启动定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[ETFSub Job] MOCK 模式，不启动快照定时任务")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            _job_snapshot,
            trigger=CronTrigger(
                hour=SNAPSHOT_HOUR,
                minute=SNAPSHOT_MINUTE,
                timezone="Asia/Shanghai",
            ),
            id="etf_subscription_daily",
            name="ETF每日申赎快照",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
        _scheduler = scheduler
        print(
            f"[ETFSub Job] 定时任务已启动：每天 {SNAPSHOT_HOUR:02d}:{SNAPSHOT_MINUTE:02d} "
            f"快照 ETF 份额/规模/净值"
        )
    except Exception as e:
        print(f"[ETFSub Job] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    # 注册到 jobs 面板（轻量，绝不抛）
    try:
        register_job(
            "etf_subscription_daily",
            "ETF每日申赎快照",
            f"每天 {SNAPSHOT_HOUR:02d}:{SNAPSHOT_MINUTE:02d}（Asia/Shanghai）快照 ETF 份额/规模/净值",
            job_type="scheduled",
            enabled=True,
            triggerable=True,
            fn=_job_snapshot,
        )
        aps_job = scheduler.get_job("etf_subscription_daily")
        if aps_job and aps_job.next_run_time:
            set_next_run("etf_subscription_daily", aps_job.next_run_time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        print(f"[ETFSub Job] 注册 jobs 面板失败（忽略）: {e}")

    # ⚠️ 启动快照必须异步：fire-and-forget 线程，绝不阻塞 lifespan（否则整站 502）。
    threading.Thread(target=_maybe_startup_snapshot, daemon=True).start()


def stop_etf_subscription_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
