"""估值误差自检定时任务（T3）。

挂在 FastAPI lifespan（见 main.py）：

1. **每天 15:30** 落估值快照：此时 ``est_price_date`` 已是当日、``nav_date`` 仍是 T-1，
   正好把「今天赌的净值」连同口径一起存档；
2. **每天 03:00 回填**：基金公司净值一般 20:00~23:00 公布，凌晨回填才拿得到；
   只处理 ``nav_actual IS NULL`` 的行，幂等；
3. **启动补一次回填**（异步）：上次进程可能在回填跑完前就重启了。

⚠️ 两个动作都含上游取数，**必须异步**（daemon 线程）：若在 lifespan 主线程同步调用，
网关慢/挂会令 uvicorn 卡在「Waiting for application startup」→ 整站 502。
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

_scheduler = None

SNAPSHOT_HOUR = 15
SNAPSHOT_MINUTE = 30
BACKFILL_HOUR = 3
BACKFILL_MINUTE = 0


def _job_snapshot() -> dict:
    """落当日估值快照（apscheduler 线程内调用）。"""
    from services import est_nav_history_service as svc
    from services.fund_service import get_funds

    run = record_start("est_nav_snapshot")
    t0 = time.time()
    try:
        # force=True 必须传：get_funds 有 30s 列表缓存，如果恰好在缓存有效期内有人
        # 请求过 /funds、而那时慢腿（日经/港股指数）还没预热完、est_nav 全空，
        # 快照就会把「空」当成结果 —— 那一天的样本白丢，而且事后无法补。
        # 宁可多花几十秒重扫一次，也不能让历史缺一天。
        # 用 all 口径：页面三个 tab 的并集，避免只落 lof 而漏掉 ETF 那几只
        funds, _meta = get_funds("all", force=True)
        res = svc.record_snapshot(funds)
        record_success("est_nav_snapshot", run, (time.time() - t0) * 1000)
        return res
    except Exception as e:
        record_failure("est_nav_snapshot", run, f"{type(e).__name__}: {e}")
        print(f"[EstNavJob] 快照失败: {type(e).__name__}: {e}")
        return {"ok": False, "error": str(e)}


def _job_backfill() -> dict:
    """回填真实净值并算误差（apscheduler 线程内调用）。"""
    from services import est_nav_history_service as svc

    run = record_start("est_nav_backfill")
    t0 = time.time()
    try:
        res = svc.backfill_errors()
        record_success("est_nav_backfill", run, (time.time() - t0) * 1000)
        return res
    except Exception as e:
        record_failure("est_nav_backfill", run, f"{type(e).__name__}: {e}")
        print(f"[EstNavJob] 回填失败: {type(e).__name__}: {e}")
        return {"ok": False, "error": str(e)}


def _maybe_startup_backfill() -> None:
    """启动补一次回填（异步线程内调用，全程 try 保护）。"""
    try:
        from services import est_nav_history_service as svc

        svc.ensure_table()
        res = svc.backfill_errors()
        print(f"[EstNavJob] 启动回填完成: {res}")
    except Exception as e:
        print(f"[EstNavJob] 启动回填失败（忽略，不影响服务启动）: {e}")


def start_est_nav_scheduler() -> None:
    """启动定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[EstNavJob] MOCK 模式，不启动估值误差定时任务")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            _job_snapshot,
            trigger=CronTrigger(
                hour=SNAPSHOT_HOUR, minute=SNAPSHOT_MINUTE, timezone="Asia/Shanghai"
            ),
            id="est_nav_snapshot",
            name="估值快照落库",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            _job_backfill,
            trigger=CronTrigger(
                hour=BACKFILL_HOUR, minute=BACKFILL_MINUTE, timezone="Asia/Shanghai"
            ),
            id="est_nav_backfill",
            name="估值误差回填",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
        _scheduler = scheduler
        print(
            f"[EstNavJob] 定时任务已启动：每天 {SNAPSHOT_HOUR:02d}:{SNAPSHOT_MINUTE:02d} "
            f"落估值快照 / {BACKFILL_HOUR:02d}:{BACKFILL_MINUTE:02d} 回填误差"
        )
    except Exception as e:
        print(f"[EstNavJob] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    # 注册到 jobs 面板（轻量，绝不抛）
    try:
        register_job(
            "est_nav_snapshot",
            "估值快照落库",
            f"每天 {SNAPSHOT_HOUR:02d}:{SNAPSHOT_MINUTE:02d}（Asia/Shanghai）落当日 est_nav",
            job_type="valuation",
            enabled=True,
            triggerable=True,
            fn=_job_snapshot,
        )
        register_job(
            "est_nav_backfill",
            "估值误差回填",
            f"每天 {BACKFILL_HOUR:02d}:{BACKFILL_MINUTE:02d}（Asia/Shanghai）回填真实净值并算误差",
            job_type="valuation",
            enabled=True,
            triggerable=True,
            fn=_job_backfill,
        )
        aps = scheduler.get_job("est_nav_snapshot")
        if aps and aps.next_run_time:
            set_next_run("est_nav_snapshot", aps.next_run_time.strftime("%Y-%m-%d %H:%M:%S"))
        aps = scheduler.get_job("est_nav_backfill")
        if aps and aps.next_run_time:
            set_next_run("est_nav_backfill", aps.next_run_time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        print(f"[EstNavJob] 注册 jobs 面板失败（忽略）: {e}")

    # ⚠️ 启动回填必须异步：fire-and-forget，绝不阻塞 lifespan
    threading.Thread(target=_maybe_startup_backfill, daemon=True).start()


def stop_est_nav_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
