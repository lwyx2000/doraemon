"""估值误差自检：把「自算净值到底准不准」变成可观测数字。

背景（迁移自 lofarb ``valuation_error``）
------------------------------------------
``est_nav`` 是个黑盒：没有历史比对，就没人知道 0.2% 的残差是真的，还是某天权重把
旧值 ``bfill`` 过来造成的 39% 高估。lofarb 的真实事故就是靠「误差突然变大」发现的。

所以这里做三件事：
1. **落快照**：每日盘后把当时算出的 ``est_nav`` 连同口径（method/position/base_date/
   price_date）落库；
2. **次日回填**：等基金公司公布真实净值后，算出 ``valuation_error = est_nav/nav - 1``；
3. **透出**：列表带上最近一次误差 + 样本数 + 平均绝对误差，前端据此标色。

关键口径决策：``date`` 取 **est_price_date**（估值实际赌的那一天的净值日），
不是「运行日」。因为 10-30 盘后算出的估值，赌的是 **10-30 的净值**（基准是 10-29），
回填时要拿 ``base_fund_nav`` 里 10-30 的净值去比 —— 用运行日会整体错一天。

数据源
------
真实净值走网关 ``fund_open_fund_info_em``（1.0~1.7s/只，含全历史）。不复用
``fund_extra_metrics_service`` 的 ``pingzhongdata`` 腿 —— 那条是直连，本模块不引入直连。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

CST = timezone(timedelta(hours=8))

DDL = """
CREATE TABLE IF NOT EXISTS fund_est_nav_history (
    date             VARCHAR NOT NULL,
    fund_code        VARCHAR NOT NULL,
    est_nav          DOUBLE,
    method           VARCHAR,
    position         DOUBLE,
    base_date        VARCHAR,
    price_date       VARCHAR,
    nav_actual       DOUBLE,
    valuation_error  DOUBLE,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, fund_code)
)
"""

#: 回填最多回溯多少天（更早的不再补：那些日子的估值我们从没落过库，补也补不出来）
BACKFILL_LOOKBACK_DAYS = 30
#: 单轮回填最多处理多少只基金（防止一次打爆网关）
BACKFILL_MAX_CODES = 80
#: 误差汇总缓存 TTL（秒）：/funds 每个请求都读，不能每次扫表
SUMMARY_TTL = 120
#: 汇总回看窗口（天）：算 mae / max 用
SUMMARY_WINDOW_DAYS = 20

_summary_cache: dict = {"ts": 0.0, "data": {}}
_summary_lock = threading.Lock()


def _db():
    from database.connection import get_db

    return get_db()


def _today() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _round(v) -> float | None:
    x = _f(v)
    return round(x, 4) if x is not None else None


def ensure_table(db=None) -> None:
    try:
        (db or _db()).execute(DDL)
    except Exception as e:  # pragma: no cover
        print(f"[EstNavHistory] 建表失败: {e}")


# ============================================================
# 1. 落快照
# ============================================================

def record_snapshot(funds: Iterable[dict], run_date: str | None = None) -> dict:
    """把当日算出的 est_* 落库。

    ``date`` 优先取 ``est_price_date``（估值赌的那一天），缺失才退回 run_date。
    已经回填过误差的行**不覆盖** —— 那一天的估值结论已经定了，同一天重复运行
    不该改历史（盘后可能因网关重试算出略有差别的数）。

    已存在的行也直接跳过，不靠 ``ON CONFLICT DO NOTHING`` 兜底计数：DuckDB 的
    ``executemany`` 不返回影响行数，若按待写行数报 written，日志会写「落库 3 行」
    而实际插入 0 行 —— 排查「为什么今天没数据」时最容易被这种假日志带偏。
    DO NOTHING 仍保留，用于两个线程同时跑快照时的兜底。
    """
    db = _db()
    ensure_table(db)
    run_date = run_date or _today()
    funds = list(funds)
    if not funds:
        return {"ok": True, "written": 0, "skipped_filled": 0, "skipped_existing": 0}

    # 已存在 / 已回填的 (date, code)：前者跳过避免重复写，后者跳过避免改历史结论
    existing: set[tuple[str, str]] = set()
    locked: set[tuple[str, str]] = set()
    try:
        for d, c, nav_actual in db.fetchall(
            "SELECT date, fund_code, nav_actual FROM fund_est_nav_history"
        ):
            key = (str(d), str(c))
            existing.add(key)
            if nav_actual is not None:
                locked.add(key)
    except Exception as e:
        print(f"[EstNavHistory] 读取已有行集合失败（继续，靠 ON CONFLICT 兜底）: {e}")

    rows: list[list] = []
    skipped_filled = 0
    skipped_existing = 0
    for f in funds:
        est = _f(f.get("est_nav"))
        if not est or est <= 0:
            continue
        code = str(f.get("code") or "").strip()
        if not code:
            continue
        # 估值赌的那一天 = 行情日；没有行情日就无法回填，退化为运行日
        date = str(f.get("est_price_date") or "")[:10] or run_date
        if (date, code) in locked:
            skipped_filled += 1
            continue
        if (date, code) in existing:
            skipped_existing += 1
            continue
        rows.append([
            date,
            code,
            round(est, 4),
            str(f.get("est_method") or ""),
            _round(f.get("est_position")),
            str(f.get("est_base_date") or "")[:10],
            str(f.get("est_price_date") or "")[:10],
        ])

    if rows:
        try:
            db.executemany(
                "INSERT INTO fund_est_nav_history "
                "(date, fund_code, est_nav, method, position, base_date, price_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (date, fund_code) DO NOTHING",
                rows,
            )
        except Exception as e:
            print(f"[EstNavHistory] 落库失败: {type(e).__name__}: {e}")
            return {
                "ok": False,
                "error": str(e),
                "written": 0,
                "skipped_filled": skipped_filled,
                "skipped_existing": skipped_existing,
            }

    # 新落库会让误差汇总缓存变脏
    with _summary_lock:
        _summary_cache["ts"] = 0.0
    print(
        f"[EstNavHistory] 快照写入 {len(rows)} 行"
        f"（跳过已回填 {skipped_filled} / 已存在 {skipped_existing}）"
    )
    return {
        "ok": True,
        "written": len(rows),
        "skipped_filled": skipped_filled,
        "skipped_existing": skipped_existing,
    }


# ============================================================
# 2. 次日回填真实净值 + 算误差
# ============================================================

def _fetch_nav_map(code: str) -> dict[str, float]:
    """网关取该基金全部历史单位净值 → {YYYY-MM-DD: nav}。失败返回空。"""
    from services.akshare_client import akshare_request

    try:
        data = akshare_request(
            "fund_open_fund_info_em",
            {"symbol": code, "indicator": "单位净值走势"},
            retries=1,
            timeout=25,
        )
    except Exception as e:
        print(f"[EstNavHistory] {code} 净值取数失败: {type(e).__name__}: {e}")
        return {}
    if not isinstance(data, list):
        return {}
    out: dict[str, float] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        d = str(row.get("净值日期") or "")[:10]
        nav = _f(row.get("单位净值"))
        if len(d) == 10 and nav and nav > 0:
            out[d] = nav
    return out


def backfill_errors(days: int = BACKFILL_LOOKBACK_DAYS) -> dict:
    """把已公布真实净值的估值行回填 nav_actual / valuation_error。

    只处理 ``nav_actual IS NULL`` 的行 —— 幂等，可反复调用。
    净值按 code 聚合，一只基金只打一次网关（全历史一次到手）。

    日期边界取 ``date <= today`` 而不是 ``< today``：能不能回填只取决于
    nav_map 里**有没有那一天的真实净值**，这个判断已经做了（取不到就 continue）。
    多卡一道日期只会让「当天净値已提前公布」的情况空等一夜。
    定时任务 03:00 跑时，当天不可能有快照行（快照固定 15:30 落，此刻还没到），
    所以放宽这一步几乎不增加网关请求。
    """
    db = _db()
    ensure_table(db)
    today = _today()
    since = (datetime.now(CST) - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        pending = db.fetchall(
            "SELECT date, fund_code, est_nav FROM fund_est_nav_history "
            "WHERE nav_actual IS NULL AND date <= ? AND date >= ? "
            "ORDER BY date DESC",
            [today, since],
        )
    except Exception as e:
        print(f"[EstNavHistory] 读取待回填失败: {type(e).__name__}: {e}")
        return {"ok": False, "error": str(e), "filled": 0}

    if not pending:
        print("[EstNavHistory] 无需回填")
        return {"ok": True, "filled": 0, "codes": 0}

    by_code: dict[str, list[tuple[str, float]]] = {}
    for d, code, est in pending:
        est_f = _f(est)
        if est_f and est_f > 0:
            by_code.setdefault(str(code), []).append((str(d), est_f))

    codes = list(by_code)[:BACKFILL_MAX_CODES]
    filled = 0
    no_nav = 0
    for code in codes:
        nav_map = _fetch_nav_map(code)
        if not nav_map:
            no_nav += 1
            continue
        updates: list[list] = []
        for date, est in by_code[code]:
            nav = nav_map.get(date)
            if not nav:
                # 净值还没公布（或该日非交易日），留到下次
                continue
            # 浮点一律 round(4)：否则 ULP 差异会让同一行反复 UPDATE（lofarb 踩过）
            err = round((est / nav - 1.0) * 100.0, 4)
            updates.append([round(nav, 4), err, date, code])
        if not updates:
            continue
        try:
            db.executemany(
                "UPDATE fund_est_nav_history SET nav_actual = ?, valuation_error = ? "
                "WHERE date = ? AND fund_code = ? AND nav_actual IS NULL",
                updates,
            )
            filled += len(updates)
        except Exception as e:
            print(f"[EstNavHistory] {code} 回填失败: {type(e).__name__}: {e}")

    with _summary_lock:
        _summary_cache["ts"] = 0.0
    print(
        f"[EstNavHistory] 回填完成：{filled} 行 / {len(codes)} 只"
        f"（无净值 {no_nav} 只）"
    )
    return {"ok": True, "filled": filled, "codes": len(codes), "no_nav": no_nav}


# ============================================================
# 3. 汇总 + 挂到列表
# ============================================================

def _load_summary() -> dict[str, dict]:
    """{code: {valuation_error, valuation_error_date, valuation_error_n, mae, max}}"""
    db = _db()
    since = (datetime.now(CST) - timedelta(days=SUMMARY_WINDOW_DAYS)).strftime("%Y-%m-%d")
    try:
        rows = db.fetchall(
            "SELECT fund_code, date, valuation_error FROM fund_est_nav_history "
            "WHERE valuation_error IS NOT NULL AND date >= ? ORDER BY date DESC",
            [since],
        )
    except Exception as e:
        print(f"[EstNavHistory] 汇总读取失败: {type(e).__name__}: {e}")
        return {}

    agg: dict[str, dict] = {}
    for code, date, err in rows:
        e = _f(err)
        if e is None:
            continue
        rec = agg.setdefault(
            str(code), {"n": 0, "sum_abs": 0.0, "max_abs": 0.0, "last": None, "last_date": ""}
        )
        rec["n"] += 1
        rec["sum_abs"] += abs(e)
        rec["max_abs"] = max(rec["max_abs"], abs(e))
        # rows 已按 date DESC，第一条即最近
        if rec["last"] is None:
            rec["last"] = e
            rec["last_date"] = str(date)

    return {
        code: {
            "valuation_error": rec["last"],
            "valuation_error_date": rec["last_date"],
            "valuation_error_n": rec["n"],
            "valuation_error_mae": round(rec["sum_abs"] / rec["n"], 4) if rec["n"] else None,
            "valuation_error_max": round(rec["max_abs"], 4) if rec["n"] else None,
        }
        for code, rec in agg.items()
    }


def get_error_summary(force: bool = False) -> dict[str, dict]:
    """带 TTL 缓存的误差汇总。空字典 = 还没有任何回填样本（上线第一天很正常）。"""
    with _summary_lock:
        fresh = (time.time() - float(_summary_cache["ts"] or 0)) < SUMMARY_TTL
        if fresh and not force:
            return _summary_cache["data"]
    data = _load_summary()
    with _summary_lock:
        _summary_cache["ts"] = time.time()
        _summary_cache["data"] = data
    return data


def attach_valuation_errors(funds: Iterable[dict]) -> None:
    """给 /funds 每一行挂 valuation_error* 字段（只读缓存，不发网络请求）。

    没有样本的基金**不写字段**（前端显示 '-'），而不是写 0 —— 0 会被误读成「零误差」。
    """
    try:
        summary = get_error_summary()
    except Exception as e:
        print(f"[EstNavHistory] 挂载失败（忽略）: {type(e).__name__}: {e}")
        return
    if not summary:
        return
    funds = list(funds)
    hit = 0
    for f in funds:
        rec = summary.get(str(f.get("code") or ""))
        if not rec:
            continue
        f.update(rec)
        hit += 1
    if hit:
        print(f"[EstNavHistory] 估值误差命中 {hit}/{len(funds)} 只")
