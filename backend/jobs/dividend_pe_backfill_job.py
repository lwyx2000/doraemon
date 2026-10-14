"""红利指数「PE 历史序列」的定时回填（后台线程，不阻塞启动）。

配套 ``services/dividend_service`` 里的 PE 序列本地累积：
把中证官网 ``stock_zh_index_hist_csindex`` 的滚动市盈率抓下来落进
``base_dividend_index_pe``，之后分位 / 区间都在本地算。

为什么需要这个任务：
    PE 分位依赖**全量历史**（window_days 实测 2613 天），而中证官网
    **长期限流**（10-06曾报错 2300+ 次，封禁约 3 小时），一次性 44指数
    并发拉全量极易触发封禁并被反封数小时。因此改成：
      · 每天只推进一小批（默认 6 个），温和小步走
      · 并发固定 2（不可调高，见 PE_BACKFILL_CONCURRENCY）
      · 断点续传：已回填的指数自动跳过，中断/失败无需人工干预
      · 全部回填完（或剩下的都是中证不覆盖的）后自动停掉，不空转

保留手动端点 ``POST /api/v1/dividend/fill-index-pe`` 供排查时立刻补一批。
"""

from __future__ import annotations

import threading
from datetime import datetime

from jobs.registry import (
    record_failure,
    record_start,
    record_success,
    register_job,
    set_next_run,
)

JOB_NAME = "dividend_pe_backfill"

#: 每日推进的指数只数（中证限流敏感，宁慢勿快）
DAILY_LIMIT = 6
#: 每天的执行时间（排在费率 04:30、指数识别 06:15 之后，错开上游请求）
FILL_HOUR = 7
FILL_MINUTE = 20

_scheduler = None
_startup_done = threading.Event()


def _run_fill(job_name: str, limit: int) -> None:
    """在后台线程里跑一轮回填（DuckDB 独占锁 → 必须跑在 backend 进程内）。"""
    from services import dividend_service as ds

    run = record_start(job_name)
    try:
        # ===== 股息率刷新（2026-10-08 新增）=====
        # ⚠️ 与 PE 同类的隐患：overview 日常访问走本地基线后，股息率只从内存
        #   `_DY_LAST` 读、**不抓上游**，而 `_DY_LAST` 只靠 force=1 的路径更新
        #   → 不点刷新股息率就**永久冻结**。这里每天补一次。
        #   放在 PE 回填**之前**：若 PE 待办已清零（调度器已自停），
        #   也要保证股息率每天仍被刷新。
        try:
            st = ds.dy_refresh_batch()
            print(
                f"[{job_name}] 股息率刷新：成功 {st['ok']} / 失败 {st['failed']}"
                f"（共 {st['total']} 个）"
            )
        except Exception as e:  # noqa: BLE001
            print(f"[{job_name}] 股息率刷新异常（忽略）: {type(e).__name__}: {e}")

        # 启动即回填一批（温和：并发 2、自动跳过已完成的）
        r = ds.pe_backfill_start(None, limit=limit)
        if not r.get("started"):
            reason = r.get("reason") or ("已完成" if r.get("done") else "未知")
            print(f"[{job_name}] 本轮跳过：{reason}")
            record_success(job_name, run, 0.0)
            return

        # 等后台线程跑完（pe_backfill_start 内已做并发/异常兜底）
        for _ in range(2400):  # 上限 40 分钟
            s = ds.pe_backfill_status()
            if not s.get("running") and s.get("done"):
                break
            threading.Event().wait(0.5)

        s = ds.pe_backfill_status()
        # 停止条件：**所有剩余待办都已被判定为「中证不覆盖」**。
        # ⚠️ 不能用「rows_added==0」当条件（2026-10-08 修正）：
        #   中证限流是**间歇性**的，连续几轮撞上限流窗口很正常，但那不代表
        #   「已经没东西可补」——贸然停止会导致数据永远停在旧日期。
        #   故只看 `pending_count == 0`：待办清零 = 真的补完了（要么成功、要么确认不覆盖）。
        pending = s.get("pending_count")
        if pending is None:  # 老版本无此字段 → 退回旧判据
            pending = (s.get("index_count", 0) - s.get("done_count", 0))
        if pending == 0:
            print(
                f"[{job_name}] PE 待办已清零（已回填 {s.get('done_count')}/{s.get('index_count')}，"
                f"其中不覆盖 {s.get('unsupported_count', 0)} 个）→ 停掉 PE 回填定时器，"
                f"但**股息率仍需每日刷新**，故本 job 保留、只跳过 PE 部分"
            )
            _stop_scheduler(keep_job=True)
        else:
            print(
                f"[{job_name}] 本轮新增 {s.get('rows_added', 0)} 行，"
                f"仍有 {pending} 个待补（下轮继续）"
            )
        record_success(job_name, run, 0.0)
    except Exception as e:  # noqa: BLE001
        print(f"[{job_name}] 回填失败：{type(e).__name__}: {e}")
        try:
            record_failure(job_name, run, e)
        except Exception:  # pragma: no cover
            pass


#: 启动兜底的**跨重启防抖间隔**（小时）。
#: ⚠️ 为什么要（2026-10-09）：`_startup_done` 只是**进程内** Event，容器一重建就重置
#   ——运维/发版时反复重建 backend，会**每重启一次就触发一轮**回填 + 44 个股息率刷新。
#:   实测一晚重建 7 次 → 上游 `csindex` 1 小时内报 **506 次限流**，
#:   启动兜底本身成了加剧限流的帮凶。距上次回填不足该间隔时直接跳过，
#:   把配额留给真正需要推进的定时轮次。
STARTUP_DEBOUNCE_HOURS = 6


def _last_backfill_at():
    """最近一次成功回填落库的时间（来自完成记录表，**跨重启可见**）。"""
    try:
        from database.connection import get_db
        from services.dividend_service import PE_BACKFILL_LOG_DDL

        db = get_db()
        db.execute(PE_BACKFILL_LOG_DDL)
        rows = db.fetchall("SELECT MAX(done_at) FROM base_dividend_index_pe_backfill")
        if rows and rows[0] and rows[0][0]:
            return rows[0][0]
    except Exception as e:  # pragma: no cover — 读不到就当没回填过
        print(f"[{JOB_NAME}] 读取上次回填时间失败（按「无记录」处理）: {type(e).__name__}")
    return None


def _startup_backfill() -> None:
    """启动兜底：先补一小批，之后交给定时任务。

    带**跨重启防抖**：若完成记录表显示不久前刚回填过（本job 间隔内的上一轮
    已经在推进），则跳过本次启动兜底 —— 避免「每次重建容器就打一轮上游」。
    """
    if _startup_done.is_set():
        return
    last = _last_backfill_at()
    if last:
        try:
            from datetime import datetime as _dt

            # ⚠️ **时区语义（2026-10-09 实测校准，别想当然）**：
            #   `_pe_mark_backfilled` 写入的是 `datetime.now(CST)`（东八区墙上时间），
            #   但列类型是 `TIMESTAMP`，**DuckDB 会把它转成 UTC 存储**
            #   —— 实测写入 `00:40 CST`、读出来是 `16:40 UTC`（差8 小时）。
            #   所以读回来的 `done_at` 是 **UTC naive**，
            #   必须与同为 UTC 的 `datetime.now()`（容器时区=UTC）相减。
            #   ⚠️ 曾误以为是 CST 而改用 `now(CST)` → 结果差8 小时、防抖完全失效。
            last_dt = last if isinstance(last, _dt) else _dt.fromisoformat(str(last)[:19])
            if last_dt.tzinfo is not None:
                last_dt = last_dt.astimezone(_dt.now().astimezone().tzinfo).replace(tzinfo=None)
            hours = (_dt.now() - last_dt).total_seconds() / 3600
            if hours < STARTUP_DEBOUNCE_HOURS:
                print(
                    f"[{JOB_NAME}] 启动兜底跳过：距上次回填仅 {hours:.1f} 小时"
                    f"（< {STARTUP_DEBOUNCE_HOURS}h），留给定时轮次推进"
                )
                return
        except Exception as e:  # noqa: BLE001
            print(f"[{JOB_NAME}] 防抖判断失败（继续兜底）: {type(e).__name__}")
    _startup_done.set()
    print(f"[{JOB_NAME}] 启动兜底：先回填 {DAILY_LIMIT} 个指数")
    threading.Thread(
        target=_run_fill, args=(JOB_NAME, DAILY_LIMIT), name="pe-backfill-startup", daemon=True
    ).start()


def _stop_scheduler(keep_job: bool = False) -> None:
    """停掉定时器。

    ``keep_job=True`` 时只**移除 PE 回填这条job**、保留调度器本身——
    因为本 job 还兼着**股息率每日刷新**（2026-10-08）：PE 待办清零后
    股息率仍必须每天刷新，否则会冻结在最后一次 force=1 的值。
    """
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(JOB_NAME)
        if keep_job:
            print(
                f"[{JOB_NAME}] PE 回填定时器已移除（待办清零），"
                f"但保留调度器以继续每日刷新股息率"
            )
            return
        _scheduler.shutdown(wait=False)
        print(f"[{JOB_NAME}] 定时器已停止（回填完成且无需再刷股息率）")
    except Exception as e:  # pragma: no cover  # noqa: BLE001
        print(f"[{JOB_NAME}] 停止定时器失败（忽略）：{e}")
    _scheduler = None


def start_dividend_pe_backfill_scheduler() -> None:
    """注册并启动定时回填（每天 07:20 一小批）。"""
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception as e:  # pragma: no cover  # noqa: BLE001
        print(f"[{JOB_NAME}] APScheduler 不可用，跳过定时回填：{e}")
        _startup_backfill()
        return

    try:
        register_job(
            JOB_NAME,
            JOB_NAME,
            f"每天 {FILL_HOUR:02d}:{FILL_MINUTE:02d}",
            job_type="scheduler",
            enabled=True,
            triggerable=True,
        )
        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        _scheduler.add_job(
            _run_fill,
            trigger=CronTrigger(hour=FILL_HOUR, minute=FILL_MINUTE, timezone="Asia/Shanghai"),
            args=(JOB_NAME, DAILY_LIMIT),
            id=JOB_NAME,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        set_next_run(JOB_NAME, _next_run_text())
        print(f"[{JOB_NAME}] 已启动：每天 {FILL_HOUR:02d}:{FILL_MINUTE:02d} 回填 {DAILY_LIMIT} 个指数")
    except Exception as e:  # pragma: no cover  # noqa: BLE001
        print(f"[{JOB_NAME}] 定时器启动失败（忽略）：{e}")

    _startup_backfill()


def stop_dividend_pe_backfill_scheduler() -> None:
    """停止定时回填（应用 shutdown 时调用，与 start_* 对称）。

    ⚠️ 与内部 ``_stop_scheduler(keep_job=True)`` 语义不同：后者只用于
    「PE 待办清零、但股息率仍需每日刷新」的运行中自停场景；
    shutdown 场景下 PE 回填与股息率刷新都应完全停止，故此处 keep_job=False。
    """
    _stop_scheduler(keep_job=False)


def _next_run_text() -> str:
    from datetime import datetime as _dt, timedelta as _td

    now = _dt.now()
    target = now.replace(hour=FILL_HOUR, minute=FILL_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += _td(days=1)
    return target.strftime("%Y-%m-%d %H:%M:%S")


# 便于测试：直接跑一轮
if __name__ == "__main__":  # pragma: no cover
    print(f"[{JOB_NAME}] 手动跑一轮，limit={DAILY_LIMIT}")
    _run_fill(JOB_NAME, DAILY_LIMIT)
    print("完成时间：", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))