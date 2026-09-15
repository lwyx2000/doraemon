"""申万一级行业快照定时任务 + 历史回填。

挂在 FastAPI lifespan 上（见 main.py）：

1. 每交易日 15:30 落一次当日行业快照 —— 收盘后自动写入，不再依赖"有人打开热力图"顺带落库；
2. 启动时若 base_sw_sector_daily 数据不足（交易日数 < 5），后台线程自动回填近一年日线。

之所以需要它：历史走势 / 相对强度两张图读的是 base_sw_sector_daily 的历史序列，
而快照只在请求热力图时顺带写一天，靠"攒"永远攒不出曲线。
"""

from __future__ import annotations

import threading
from datetime import date, datetime

# 每交易日收盘后落快照的时间（A 股 15:00 收盘，留 30 分钟等数据源稳定）
SNAPSHOT_HOUR = 15
SNAPSHOT_MINUTE = 30

# 启动自动回填的阈值：已有交易日数少于该值才回填
AUTO_BACKFILL_MIN_DAYS = 5
AUTO_BACKFILL_DAYS = 250  # ≈ 一年

_scheduler = None
_backfill_lock = threading.Lock()
_backfill_running = False
_trading_days: set[date] | None = None


def _load_trading_days() -> set[date] | None:
    """加载 A 股交易日历（含历史与未来），失败返回 None（调用方回退到周一~周五判断）。"""
    global _trading_days
    if _trading_days is not None:
        return _trading_days
    try:
        from services.akshare_client import akshare_request

        df = akshare_request("tool_trade_date_hist_sina", timeout=30)
        if df:
            days = {datetime.strptime(str(v.get("trade_date"))[:10], "%Y-%m-%d").date() for v in df}
            if days:
                _trading_days = days
                print(f"[SW Job] 交易日历加载成功：{len(days)} 个交易日（网关）")
    except Exception as e:
        print(f"[SW Job] 交易日历加载失败（回退到周一~周五判断）: {type(e).__name__}: {e}")
    return _trading_days


def _is_trading_day(day: date | None = None) -> bool:
    """是否为 A 股交易日。节假日以交易日历为准，取不到时回退到周一~周五。"""
    day = day or date.today()
    days = _load_trading_days()
    if days:
        return day in days
    return day.weekday() < 5


def _job_daily_snapshot() -> None:
    """定时任务主体：交易日收盘后写一次行业快照。"""
    if not _is_trading_day():
        print(f"[SW Job] 非交易日，跳过快照（{date.today()}）")
        return
    try:
        from services.market_service import get_sw_sectors

        sectors, _meta = get_sw_sectors()  # 内部已调用 _save_sw_sector_snapshot 落库
        print(f"[SW Job] 收盘快照完成：{len(sectors)} 个行业")
    except Exception as e:
        print(f"[SW Job] 收盘快照失败: {type(e).__name__}: {e}")


def run_backfill_async(days: int = AUTO_BACKFILL_DAYS) -> bool:
    """后台线程触发历史回填（不阻塞启动；已在跑则忽略）。

    Returns:
        是否成功启动新线程。
    """
    global _backfill_running

    def _worker() -> None:
        global _backfill_running
        try:
            from services.market_service import backfill_sw_sector_history

            print(f"[SW Job] 开始回填申万行业历史（近 {days} 个交易日）...")
            result = backfill_sw_sector_history(days=days)
            print(f"[SW Job] 回填结果: {result}")
        except Exception as e:
            print(f"[SW Job] 回填异常: {type(e).__name__}: {e}")
        finally:
            with _backfill_lock:
                _backfill_running = False

    with _backfill_lock:
        if _backfill_running:
            return False
        _backfill_running = True

    threading.Thread(target=_worker, name="sw-backfill", daemon=True).start()
    return True


def _maybe_auto_backfill() -> None:
    """启动时按数据充分度决定是否回填。"""
    try:
        from services.market_service import get_sw_sector_snapshot_stats

        stats = get_sw_sector_snapshot_stats()
        print(f"[SW Job] base_sw_sector_daily 现状: {stats}")
        if (stats.get("tradeDays") or 0) < AUTO_BACKFILL_MIN_DAYS:
            run_backfill_async(AUTO_BACKFILL_DAYS)
        else:
            print("[SW Job] 历史数据已充分，跳过回填")
    except Exception as e:
        print(f"[SW Job] 检查快照表失败: {type(e).__name__}: {e}")


def start_sw_snapshot_scheduler() -> None:
    """启动定时任务（幂等）。mock 模式下不启动。"""
    global _scheduler
    if _scheduler is not None:
        return

    from core.config import USE_MOCK_DATA

    if USE_MOCK_DATA:
        print("[SW Job] MOCK 模式，不启动快照定时任务")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            _job_daily_snapshot,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=SNAPSHOT_HOUR,
                minute=SNAPSHOT_MINUTE,
                timezone="Asia/Shanghai",
            ),
            id="sw_sector_daily_snapshot",
            name="申万一级行业每日收盘快照",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
        _scheduler = scheduler
        print(f"[SW Job] 定时任务已启动：每交易日 {SNAPSHOT_HOUR:02d}:{SNAPSHOT_MINUTE:02d} 落快照")
    except Exception as e:
        print(f"[SW Job] 定时任务启动失败: {type(e).__name__}: {e}")
        return

    _maybe_auto_backfill()


def stop_sw_snapshot_scheduler() -> None:
    """停止定时任务（shutdown 时调用）。"""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            print("[SW Job] 定时任务已停止")
        except Exception as e:
            print(f"[SW Job] 定时任务停止异常: {e}")
        finally:
            _scheduler = None


def scheduler_status() -> dict:
    """定时任务运行状态（供运维查看）。"""
    return {
        "running": _scheduler is not None and _scheduler.running,
        "snapshotTime": f"{SNAPSHOT_HOUR:02d}:{SNAPSHOT_MINUTE:02d}",
        "backfillRunning": _backfill_running,
        "tradingCalendarLoaded": _trading_days is not None,
    }
