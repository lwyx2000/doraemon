"""A 股交易日历（共享工具）。

⚠️ 为什么独立成模块（2026-10-08）：
    原本交易日历只存在于 ``jobs/sw_snapshot_job.py`` 的私有函数里，
    但红利页 PE 的**新鲜度判断**也需要它——用自然日判断会在长假
    （如国庆 10-01~10-07）必然误报「数据陈旧」：
    节前最后交易日 09-30 距 10-08 有 8 天 > 阈值，看起来像坏了，其实是最新的。

    抽到这里后``jobs/sw_snapshot_job.py`` 也改为复用（保持原行为不变）。

数据源：新浪 ``tool_trade_date_hist_sina``（含历史与未来交易日）。
取不到时回退到「周一~周五」判断——精度够用，且不会因日历拉取失败而阻塞业务。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

#: 进程内缓存（交易日历全年就一条，没必要反复拉）
_trading_days: set[date] | None = None


def load_trading_days() -> set[date] | None:
    """加载 A 股交易日历（含历史与未来）；失败返回 None（调用方回退到周一~周五）。"""
    global _trading_days
    if _trading_days is not None:
        return _trading_days
    try:
        from services.akshare_client import akshare_request

        rows = akshare_request("tool_trade_date_hist_sina", timeout=30)
        if rows:
            days = {
                datetime.strptime(str(r.get("trade_date"))[:10], "%Y-%m-%d").date()
                for r in rows
                if r.get("trade_date")
            }
            if days:
                _trading_days = days
                print(f"[交易日历] 加载成功：{len(days)} 个交易日")
    except Exception as e:  # pragma: no cover
        print(f"[交易日历] 加载失败（回退到周一~周五判断）: {type(e).__name__}: {e}")
    return _trading_days


def is_trading_day(day: date | None = None) -> bool:
    """是否为 A 股交易日。节假日以日历为准，取不到时回退到周一~周五。"""
    day = day or date.today()
    days = load_trading_days()
    if days:
        return day in days
    return day.weekday() < 5


def latest_trading_day(ref: date | None = None) -> date:
    """返回 ``ref``（默认今天）当天或之前最近的交易日。"""
    ref = ref or date.today()
    if load_trading_days() is None:
        # 回退：最多往前找 15 天，跳过周末
        d = ref
        for _ in range(15):
            if d.weekday() < 5:
                return d
            d -= timedelta(days=1)
        return ref
    # 日历可用：向前回溯（最多 30 天，足以覆盖任何长假）
    d = ref
    for _ in range(30):
        if d in _trading_days:  # type: ignore[operator]
            return d
        d -= timedelta(days=1)
    return ref


def trading_days_between(start: date, end: date) -> int:
    """``start``（含）到 ``end``（含）之间的交易日数量。日历不可用时按自然日折算。"""
    if start >= end:
        return 0
    days = load_trading_days()
    if not days:
        # 回退：一周 5 个交易日
        return max(1, round((end - start).days * 5 / 7))
    n = 0
    d = start
    while d <= end:
        if d in days:
            n += 1
        d += timedelta(days=1)
    return n