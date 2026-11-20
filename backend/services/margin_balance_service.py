"""融资盘余额曲线（沪深合计 / 沪市 / 深市，单位亿元）。

数据源与口径（2026-11-20 调研后确定，不用不可靠近似值）：

1. ``macro_china_market_margin_sh`` / ``macro_china_market_margin_sz``
   - 金十数据沪深融资融券报告，2010-03-31 起，单次返回全史，约 0.5s。
   - 字段「融资余额」单位为**元**，出口统一换算成亿元并保留 2 位小数。
   - 与交易所官方口径对拍过：2026-11-05 沪市 1180797811849 元，
     与 ``stock_margin_sse`` 完全一致；深市 / 1e8 = 10901.799 亿，
     与 ``stock_margin_szse`` 的 10901.79 亿一致。
   - ⚠️ 深市源在 2017~2025 有零散缺口（最长 2024-10-18 → 2025-06-19），
     这些日期用交易所官方单日接口补齐后固化为 ``backend/data/margin_balance_gap.json``。

2. ``stock_margin_sse``（上交所官方汇总）
   - 单次全史请求最多返回 2000 行，但指定单日/短区间可精确补数。
   - 用于覆盖金十源滞后的最新交易日；字段「融资余额」单位为**元**。

3. ``stock_margin_szse(date)``（深交所官方汇总）
   - 只能按单日查，字段「融资余额」单位已经是**亿元**。
   - 用于补齐金十源之后的尾部交易日；当日未发布时跳过，不伪造。

缓存：
   - 30 分钟进程内缓存，缓存完整沪深 map，按需切片，避免 Dashboard 反复打网关。
   - 网关失败但有缓存时返回陈旧值并在 ``meta.note`` 标明；全失败返回空数据 + mock meta。
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_CST = timezone(timedelta(hours=8))
_TTL = 1800  # 30 min
_MAX_DAYS = 2500  # ≈10 年交易日
_TAIL_DAYS = 45  # 历史源滞后时，最多向前补多少个自然日
_GAP_PATH = Path(__file__).resolve().parent.parent / "data" / "margin_balance_gap.json"

_CACHE: dict[str, Any] = {"data": None, "ts": 0.0, "note": None}
_LOCK = threading.Lock()
_BUILD_LOCK = threading.Lock()
_GAP: dict[str, dict[str, float]] | None = None

_SOURCE = "AkShare macro_* + stock_margin_sse/szse（沪深合计/分市，亿元）"


def _meta(is_mock: bool, data_source: str, note: str | None = None) -> dict[str, Any]:
    from services.market_service import _build_meta

    m = _build_meta(is_mock, data_source)
    if note:
        m["note"] = note
    return m


def _norm_date(value: Any) -> str | None:
    if not value:
        return None
    s = str(value)[:10]
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (ValueError, TypeError):
        return None
    return v if v > 0 else None


def _load_gap() -> dict[str, dict[str, float]]:
    """加载固化的历史缺口（深市 194 日 + 沪市 2 日），只在首次调用时读盘。"""
    global _GAP
    if _GAP is not None:
        return _GAP
    empty: dict[str, dict[str, float]] = {"sh": {}, "sz": {}}
    try:
        raw = json.loads(_GAP_PATH.read_text(encoding="utf-8"))
        sz = raw.get("sz") or raw.get("values") or {}
        empty = {
            "sh": {k: float(v) for k, v in (raw.get("sh") or {}).items()},
            "sz": {k: float(v) for k, v in sz.items()},
        }
    except Exception as e:
        print(f"[Margin Balance] 缺口数据加载失败: {e}")
    _GAP = empty
    return empty


def _fetch_macro(market: str) -> tuple[dict[str, float], str | None]:
    """金十沪深融资融券全史；返回 {日期: 亿元} 与最新日期。"""
    from services.market_service import _akshare_request

    method = f"macro_china_market_margin_{market}"
    rows = _akshare_request(method, retries=2, timeout=15)
    if not isinstance(rows, list):
        return {}, None
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _norm_date(row.get("日期") or row.get("信用交易日期"))
        v = _positive_float(row.get("融资余额"))
        if d and v is not None:
            out[d] = round(v / 1e8, 2)  # 金十字段单位：元
    return out, max(out) if out else None


def _fetch_sse_range(start: str, end: str) -> dict[str, float]:
    """上交所官方汇总补最新尾部；字段单位元。"""
    from services.market_service import _akshare_request

    rows = _akshare_request(
        "stock_margin_sse",
        {"start_date": start.replace("-", ""), "end_date": end.replace("-", "")},
        retries=2,
        timeout=25,
    )
    if not isinstance(rows, list):
        return {}
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _norm_date(row.get("信用交易日期") or row.get("date"))
        v = _positive_float(row.get("融资余额") or row.get("融资余额(元)"))
        if d and v is not None:
            out[d] = round(v / 1e8, 2)
    return out


def _fetch_szse_day(day: str) -> float | None:
    """深交所官方单日汇总；字段单位已经是亿元。"""
    from services.market_service import _akshare_request

    rows = _akshare_request(
        "stock_margin_szse", {"date": day.replace("-", "")}, retries=1, timeout=12
    )
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        v = _positive_float(rows[0].get("融资余额"))
        return round(v, 2) if v is not None else None
    return None


def _build_full() -> tuple[dict[str, dict[str, float]] | None, str | None]:
    """拉取完整沪深序列；返回 (maps, note)。失败不造假，只在 note 里说明。"""
    gap = _load_gap()
    sh, sh_last = _fetch_macro("sh")
    sz, sz_last = _fetch_macro("sz")

    notes: list[str] = []
    if not sh:
        notes.append("沪市历史源失败")
    if not sz:
        notes.append("深市历史源失败")

    # 固化缺口作为底座，线上数据源覆盖其上（同日以线上为准）
    merged_sh: dict[str, float] = dict(gap["sh"])
    merged_sh.update(sh)
    merged_sz: dict[str, float] = dict(gap["sz"])
    merged_sz.update(sz)

    if not merged_sh and not merged_sz:
        return None, "；".join(notes) or "沪深融资余额数据源均无数据"

    today = datetime.now(_CST).date()
    last_dates = [d for d in (sh_last, sz_last) if d]
    tail_start = min(last_dates) if last_dates else today.isoformat()
    tail_end = min(today, date.fromisoformat(tail_start) + timedelta(days=_TAIL_DAYS))

    # 沪市：短区间一次性补齐（官方源可精确指定日期）
    try:
        sse_rows = _fetch_sse_range(tail_start, tail_end.isoformat())
        if sse_rows:
            merged_sh.update(sse_rows)
        else:
            notes.append("沪市近期接口无数据")
    except Exception as e:
        print(f"[Margin Balance] 沪市近期补数失败: {e}")
        notes.append("沪市近期补数失败")

    # 深市：官方接口只有单日，逐日补；未发布的当天会失败，跳过即可
    cursor = date.fromisoformat(tail_start) + timedelta(days=1)
    ok = 0
    failed = 0
    while cursor <= tail_end:
        d = cursor.isoformat()
        if d > (sz_last or ""):
            try:
                bal = _fetch_szse_day(d)
            except Exception as e:
                print(f"[Margin Balance] 深市 {d} 补数异常: {e}")
                bal = None
            if bal is None:
                failed += 1
            else:
                merged_sz[d] = bal
                ok += 1
        cursor += timedelta(days=1)
    if failed:
        notes.append(f"深市近期 {failed} 日未发布")

    note = "；".join(notes) if notes else None
    return {"sh": merged_sh, "sz": merged_sz}, note


def _slice(maps: dict[str, dict[str, float]], days: int) -> dict[str, list[dict]]:
    """按同一日期窗口切片；任一侧缺数值用 null 表示，绝不补造。"""
    all_dates = sorted(set(maps["sh"]) | set(maps["sz"]))[-days:]
    sh = maps["sh"]
    sz = maps["sz"]
    return {
        "total": [
            {
                "date": d,
                "balance": round(sh[d] + sz[d], 2) if d in sh and d in sz else None,
            }
            for d in all_dates
        ],
        "sh": [{"date": d, "balance": sh.get(d)} for d in all_dates],
        "sz": [{"date": d, "balance": sz.get(d)} for d in all_dates],
    }


def get_margin_balance(days: int = 2500) -> tuple[dict[str, list[dict]], dict[str, Any]]:
    """返回 (沪深合计/沪市/深市序列, meta)。失败时优先返回缓存陈旧值。"""
    days = max(5, min(int(days), _MAX_DAYS))
    now = datetime.now(_CST).timestamp()

    with _LOCK:
        cached = _CACHE["data"]
        cache_ts = _CACHE["ts"]
        cached_note = _CACHE["note"]

    fresh = cached is not None and (now - cache_ts) < _TTL
    if not fresh:
        with _BUILD_LOCK:
            with _LOCK:
                cached = _CACHE["data"]
                cache_ts = _CACHE["ts"]
                cached_note = _CACHE["note"]
                fresh = cached is not None and (datetime.now(_CST).timestamp() - cache_ts) < _TTL
            if not fresh:
                maps, build_note = _build_full()
                if maps:
                    with _LOCK:
                        _CACHE["data"] = maps
                        _CACHE["ts"] = datetime.now(_CST).timestamp()
                        _CACHE["note"] = build_note
                    cached = maps
                    cached_note = build_note
                    fresh = True
                # 拉新失败但旧缓存可用：保留旧缓存，由下方统一追加「显示 N 分钟前缓存」

    if not cached:
        return (
            {"total": [], "sh": [], "sz": []},
            _meta(True, "无数据（网关调用失败）", note="融资余额数据获取失败，请稍后刷新"),
        )

    notes = [cached_note] if cached_note else []
    if not fresh:
        stale_min = int((now - cache_ts) / 60)
        notes.append(f"网关暂不可用，显示 {stale_min} 分钟前缓存")
    note = "；".join(notes) or None
    return _slice(cached, days), _meta(False, _SOURCE, note=note)
