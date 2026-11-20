"""融资盘余额曲线（沪市融资余额，单位亿元）。

数据源与口径：
    - AkShare ``stock_margin_sse``（上交所融资融券历史），字段「融资余额」单位元，
      出口统一换算成**亿元**并保留 2 位小数。
    - ⚠️ 必须显式传 start_date/end_date（YYYYMMDD）：不带日期参数时网关只返回
      止于约 2023 年的陈旧默认窗口（见 fear_greed_service._fetch_margin_series 注释）。
    - 深市 stock_margin_szse 只有最新一日、无历史序列，无法画曲线，故仅取沪市。
      （贪婪恐惧指数的「融资余额 20 日变化」也用同一口径。）

缓存：
    - 30 分钟进程内缓存，避免 Dashboard 每次刷新都打网关（该接口单次约 20s）。
    - 网关失败但缓存有值时返回陈旧值，并在 meta.note 标出，绝不静默造假。
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

_CST = timezone(timedelta(hours=8))
_TTL = 1800  # 30 min

_CACHE: dict[str, Any] = {"data": None, "ts": 0.0, "days": None}
_LOCK = threading.Lock()


def _meta(is_mock: bool, data_source: str, note: str | None = None) -> dict[str, Any]:
    from services.market_service import _build_meta

    m = _build_meta(is_mock, data_source)
    if note:
        m["note"] = note
    return m


def _fetch(days: int) -> list[dict]:
    """向网关拉序列；返回升序 [{date, balance}]（balance 单位亿元）。"""
    from services.market_service import _akshare_request

    today = datetime.now(_CST)
    start = (today - timedelta(days=max(days, 1) * 2 + 30)).strftime("%Y%m%d")
    rows = _akshare_request(
        "stock_margin_sse",
        {"start_date": start, "end_date": today.strftime("%Y%m%d")},
        retries=2,
        timeout=20,
    )
    if not rows or not isinstance(rows, list):
        return []

    out: list[dict] = []
    for row in rows:
        d = row.get("信用交易日期") or row.get("date")
        bal = row.get("融资余额")
        if bal is None:
            bal = row.get("融资余额(元)")
        if not d or bal is None:
            continue
        s = str(d)[:10]
        if len(s) == 8 and s.isdigit():  # YYYYMMDD -> YYYY-MM-DD
            s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
        try:
            amount = float(bal)
        except (ValueError, TypeError):
            continue
        out.append({"date": s, "balance": round(amount / 1e8, 2)})

    out.sort(key=lambda r: r["date"])
    # 双倍的日历日窗口足以覆盖 N 个交易日；极端节假日稀疏时再按实际尾部截取
    return out[-days:] if len(out) > days else out


def get_margin_balance(days: int = 120) -> tuple[list[dict], dict[str, Any]]:
    """返回 (升序余额序列, meta)。失败时优先返回缓存陈旧值并在 meta 标明。"""
    days = max(5, min(int(days), 500))
    now = datetime.now(_CST).timestamp()

    with _LOCK:
        cached = _CACHE["data"]
        cache_ts = _CACHE["ts"]
        cached_days = _CACHE["days"]

    fresh = cached is not None and (now - cache_ts) < _TTL and cached_days == days
    if fresh:
        return list(cached), _meta(False, "AkShare stock_margin_sse（沪市，亿元）")

    rows = _fetch(days)
    if rows:
        with _LOCK:
            _CACHE["data"] = rows
            _CACHE["ts"] = datetime.now(_CST).timestamp()
            _CACHE["days"] = days
        return rows, _meta(False, "AkShare stock_margin_sse（沪市，亿元）")

    if cached:
        stale_min = int((now - cache_ts) / 60)
        note = f"网关暂不可用，显示 {stale_min} 分钟前缓存"
        return list(cached), _meta(False, "AkShare stock_margin_sse（沪市，亿元）", note=note)

    return [], _meta(True, "无数据（网关调用失败）", note="融资余额数据获取失败，请稍后刷新")
