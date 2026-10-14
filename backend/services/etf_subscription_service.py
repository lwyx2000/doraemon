"""ETF 每日申赎快照服务。

数据源：53 /api/processed_data?category=fund_rank&subtype=etf（麦蕊 ETF 排行），
含 代码/名称/净值/最新价/溢价率/涨跌幅/净值日期/规模/份额 等。

单位实测（前轮已坐实）：
- ``份额`` = 原始「份」（如 510300=1.89e10 份 ≈ 189 亿份）→ 展示层 /1e8 得「亿份」；
- ``规模`` = 「万元」（如 510300=3.3e6 万 ≈ 329 亿）→ 展示层 /1e4 得「亿元」；
- 日净申赎额 = 份额 delta(份) × 净值(元) / 1e8（亿元），份额与净值同口径，单位自洽。

落库表 ``base_etf_subscription_daily``（按交易日快照，主键 (code, trade_date)）。
展示层换算（/1e8、/1e4）留给 API/前端，库里存原始值，避免二次换算误差。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

from services.fund_service import _processed_data_request, _pick, _safe_float

CST = timezone(timedelta(hours=8))

DDL = """
CREATE TABLE IF NOT EXISTS base_etf_subscription_daily (
    code       VARCHAR,
    trade_date VARCHAR,
    share      DOUBLE,
    scale      DOUBLE,
    nav        DOUBLE,
    PRIMARY KEY (code, trade_date)
)
"""


def _db():
    from database.connection import get_db

    return get_db()


_TABLE_READY = False


def _ensure_table(db) -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    try:
        db.execute(DDL)
        _TABLE_READY = True
    except Exception as e:  # pragma: no cover
        print(f"[ETFSub] 建表失败: {e}")


def _norm_date(s) -> str | None:
    """'2026年06月30日' / '2026-06-30' / '2026/06/30' / '2026.06.30' / '截止至：2026-06-30' → '2026-06-30'。"""
    if not s:
        return None
    m = re.search(r"(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})", str(s))
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _snapshot_daily() -> dict:
    """全量 upsert 当日 (code, 净值日期, 份额, 规模, 净值)。份额/规模原值入库。

    返回 {snapshotted, ok}。网络异常时安全返回（绝不抛出，避免拖死调用方）。
    """
    try:
        raw = _processed_data_request("fund_rank", {"subtype": "etf"}, retries=2)
    except Exception as e:  # 网络/上游异常：安全降级，不阻塞上层
        print(f"[ETFSub] fund_rank(etf) 取数异常（跳过快照）: {e}")
        return {"snapshotted": 0, "ok": False}
    if not (raw and isinstance(raw, list) and raw):
        print("[ETFSub] fund_rank(etf) 取数失败，跳过快照")
        return {"snapshotted": 0, "ok": False}
    try:
        db = _db()
        _ensure_table(db)
    except Exception as e:  # pragma: no cover
        print(f"[ETFSub] DB 不可用: {e}")
        return {"snapshotted": 0, "ok": False}

    n = 0
    for item in raw:
        code = str(_pick(item, "代码", "基金代码", default=""))
        if not code:
            continue
        nav_date = _norm_date(_pick(item, "净值日期"))
        if not nav_date:
            continue
        share = _safe_float(_pick(item, "份额"))
        scale = _safe_float(_pick(item, "规模"))
        nav = _safe_float(_pick(item, "净值"))
        if share is None and scale is None and nav is None:
            continue
        try:
            db.execute(
                "DELETE FROM base_etf_subscription_daily WHERE code = ? AND trade_date = ?",
                [code, nav_date],
            )
            db.execute(
                "INSERT INTO base_etf_subscription_daily (code, trade_date, share, scale, nav) "
                "VALUES (?, ?, ?, ?, ?)",
                [code, nav_date, share, scale, nav],
            )
            n += 1
        except Exception as e:
            print(f"[ETFSub] {code} 写入失败: {e}")
    print(f"[ETFSub] 当日快照完成：{n} 只（trade_date=净值日期）")
    return {"snapshotted": n, "ok": True}


def compute_net_subscription(codes: list[str]) -> dict[str, dict]:
    """对每只取最新两日快照，算 净申赎份额(亿份)/净申赎额(亿元)/截止日期。

    净申赎额 = (最新份额 − 前一日份额) × 最新净值 / 1e8（亿元），与份额同口径。
    单查询批量取，避免逐只打库（ETF 全量 ~3660 只）。
    """
    if not codes:
        return {}
    try:
        db = _db()
        _ensure_table(db)
    except Exception as e:  # pragma: no cover
        print(f"[ETFSub] DB 不可用: {e}")
        return {}

    out: dict[str, dict] = {}
    for i in range(0, len(codes), 400):
        chunk = codes[i : i + 400]
        marks = ",".join("?" for _ in chunk)
        try:
            rows = db.fetchall(
                f"SELECT code, trade_date, share, nav FROM base_etf_subscription_daily "
                f"WHERE code IN ({marks}) ORDER BY code, trade_date DESC",
                list(chunk),
            )
        except Exception as e:
            print(f"[ETFSub] 批量查询失败: {e}")
            continue
        by_code: dict[str, list] = {}
        for r in rows:
            by_code.setdefault(str(r[0]), []).append(r)
        for code, rs in by_code.items():
            if len(rs) < 2:
                continue
            # 已按 trade_date DESC，取前两条
            latest, prev = rs[0], rs[1]
            if latest[2] is None or prev[2] is None:
                continue
            net_share = (latest[2] - prev[2]) / 1e8  # 亿份
            nav_for_amt = latest[3] if latest[3] is not None else prev[3]
            net_amount = net_share * nav_for_amt if nav_for_amt is not None else None  # 亿元
            out[code] = {
                "net_subscribe_share": net_share,
                "net_subscribe_amount": net_amount,
                "net_subscribe_date": str(latest[1]),
            }
    return out


def attach_subscription(etfs: list[dict]) -> None:
    """写回 share(=最新份额/1e8)、scale(=最新规模/1e4)、nav_date、net_subscribe_*。

    原地修改传入的 dict 列表（与 get_etfs 返回同一对象）。
    """
    if not etfs:
        return
    codes = [str(e.get("code")) for e in etfs if e.get("code")]
    if not codes:
        return

    try:
        db = _db()
        _ensure_table(db)
        latest: dict[str, dict] = {}
        for i in range(0, len(codes), 400):
            chunk = codes[i : i + 400]
            marks = ",".join("?" for _ in chunk)
            rows = db.fetchall(
                f"SELECT code, trade_date, share, scale, nav FROM base_etf_subscription_daily "
                f"WHERE code IN ({marks})",
                list(chunk),
            )
            for r in rows:
                c = str(r[0])
                cur = latest.get(c)
                if cur is None or (r[1] or "") > (cur.get("trade_date") or ""):
                    latest[c] = {"trade_date": r[1], "share": r[2], "scale": r[3], "nav": r[4]}
    except Exception as e:  # pragma: no cover
        print(f"[ETFSub] 最新份额查询失败: {e}")
        latest = {}

    net = compute_net_subscription(codes)
    by_code = {str(e.get("code")): e for e in etfs if e.get("code")}
    for code, e in by_code.items():
        lat = latest.get(code)
        if lat:
            e["share"] = (lat["share"] / 1e8) if lat["share"] is not None else None
            e["scale"] = (lat["scale"] / 1e4) if lat["scale"] is not None else None
            e["nav_date"] = lat["trade_date"]
        ns = net.get(code)
        if ns:
            e["net_subscribe_share"] = ns["net_subscribe_share"]
            e["net_subscribe_amount"] = ns["net_subscribe_amount"]
            e["net_subscribe_date"] = ns["net_subscribe_date"]
