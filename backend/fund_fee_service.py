"""红利基金「规模 / 费率」后台渐进补全服务。

背景：东财基金 F10 接口在内网不可达，唯一可用源是**同花顺** ``fund_info_ths``，
但它**只能逐只查询**（591 只红利基金全量同步拉取会拖垮接口与请求线程）。
因此采用「后台渐进补全」：每次访问红利页时，若仍有缺口就顺手补一批（默认 80 只），
结果落 DuckDB 持久化，30 天后才重新拉取。页面打开几次后即可填满。

落库表 ``base_fund_fee_info``（IF NOT EXISTS，按需建表，旧库可平滑升级）。
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta, timezone

from services.akshare_client import akshare_request

CST = timezone(timedelta(hours=8))

#: 费率信息缓存有效期（天）：超过则重新拉取
FEE_TTL_DAYS = 30
#: 单轮默认补全只数
DEFAULT_BATCH = 40
#: 每只之间的间隔（秒）。⚠️ 同花顺连续请求会被限流（实测 0.25s 间隔下 80 只里 34 只 500），
#:   必须放慢到 ~1.2s/只；宁慢勿封。
DEFAULT_DELAY = 1.2
#: 被限流中止后的自动续跑退避阶梯（小时）：连续被限流次数越多等越久
BACKOFF_LADDER_HOURS = [2, 4, 8]
#: 单只失败后的额外退避（秒）
FAIL_SLEEP = 3.0
#: 连续失败达到该次数即中止本轮（疑似限流），避免继续硬刷上游
MAX_CONSEC_FAIL = 5
#: 同一只累计失败超过该次数后本轮跳过（下轮/重启后仍会重试）
MAX_FAIL_PER_CODE = 3
#: 自动触发（页面访问顺手补）的最小间隔（秒），防止每次刷新都打上游
AUTO_COOLDOWN = 10 * 60

DDL = """
CREATE TABLE IF NOT EXISTS base_fund_fee_info (
    code          VARCHAR PRIMARY KEY,
    name          VARCHAR,
    scale         DOUBLE,
    scale_date    VARCHAR,
    mgmt_fee      DOUBLE,
    custody_fee   DOUBLE,
    subscribe_fee DOUBLE,
    manager       VARCHAR,
    invest_type   VARCHAR,
    benchmark     VARCHAR,
    updated_at    TIMESTAMP
)
"""

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# ============================================================
# 后台补全状态（进程级，够用；进度本身持久化在表里）
# ============================================================

_FILL: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "ok": 0,
    "fail": 0,
    "rounds": 0,
    "skipped": 0,
    "started_at": None,
    "finished_at": None,
    "last_error": None,
    "last_batch": 0,
    # 上一轮是否因疑似限流而中止（供定时任务决定是否提前续跑）
    "throttled": False,
}
_FILL_LOCK = threading.Lock()

#: 连续被限流中止的次数（一轮正常跑完即清零）
_THROTTLE_STREAK = 0

#: 最近一次见到的红利基金代码全集（由 attach_fees 写入，供手动补全端点复用）
_LAST_CODES: list[str] = []

#: 单只累计失败次数（进程级）：上游确实没有数据的基金（如次新 ETF）不必每轮都占坑
_FAIL_COUNTS: dict[str, int] = {}

#: 上一轮完成时间戳（用于自动补全的冷却判断）
_LAST_FINISH_TS = 0.0


def _now_cst() -> datetime:
    return datetime.now(CST)


def _db():
    from database.connection import get_db

    return get_db()


def _ensure_table(db) -> None:
    try:
        db.execute(DDL)
    except Exception as e:  # pragma: no cover
        print(f"[FundFee] 建表失败: {e}")


def _to_float(s) -> float | None:
    """'0.50%' -> 0.5 ；'1.20' -> 1.2"""
    if s is None:
        return None
    m = _NUM_RE.search(str(s))
    return float(m.group()) if m else None


def _parse_scale(s) -> tuple[float | None, str | None]:
    """'76.54亿份（2026-06-30）' -> (76.54, '2026-06-30')"""
    if not s:
        return None, None
    text = str(s)
    m = _NUM_RE.search(text)
    d = _DATE_RE.search(text)
    return (float(m.group()) if m else None), (d.group(1) if d else None)


def _parse_fee_rows(rows) -> dict | None:
    """``fund_info_ths`` 返回 [{'字段':..,'值':..}] → 结构化费率 dict。"""
    if not isinstance(rows, list) or not rows:
        return None
    kv: dict[str, str] = {}
    for r in rows:
        if isinstance(r, dict):
            k = r.get("字段") or r.get("item")
            v = r.get("值") or r.get("value")
            if k:
                kv[str(k)] = "" if v is None else str(v)
    if not kv:
        return None

    scale, scale_date = _parse_scale(kv.get("份额规模"))
    return {
        "code": kv.get("基金代码", ""),
        "name": kv.get("基金简称", ""),
        "scale": scale,
        "scale_date": scale_date,
        "mgmt_fee": _to_float(kv.get("管理费")),
        "custody_fee": _to_float(kv.get("托管费")),
        "subscribe_fee": _to_float(kv.get("最高申购费")),
        "manager": kv.get("基金经理", "") or None,
        "invest_type": kv.get("投资类型", "") or None,
        "benchmark": kv.get("业绩比较基准", "") or None,
    }


def fetch_one(code: str) -> dict | None:
    """拉取单只基金的费率/规模（同花顺）。失败返回 None，绝不抛给调用方。"""
    try:
        raw = akshare_request("fund_info_ths", {"symbol": code}, timeout=25, retries=2)
    except Exception as e:
        print(f"[FundFee] {code} 拉取异常: {e}")
        return None
    rec = _parse_fee_rows(raw)
    if not rec or not rec.get("code"):
        return None
    rec["code"] = code
    return rec


# ============================================================
# 读写库
# ============================================================

def _upsert(db, rec: dict) -> None:
    db.execute("DELETE FROM base_fund_fee_info WHERE code = ?", [rec["code"]])
    db.execute(
        """
        INSERT INTO base_fund_fee_info
            (code, name, scale, scale_date, mgmt_fee, custody_fee, subscribe_fee,
             manager, invest_type, benchmark, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            rec["code"],
            rec.get("name"),
            rec.get("scale"),
            rec.get("scale_date"),
            rec.get("mgmt_fee"),
            rec.get("custody_fee"),
            rec.get("subscribe_fee"),
            rec.get("manager"),
            rec.get("invest_type"),
            rec.get("benchmark"),
            _now_cst(),
        ],
    )


def get_fee_map(codes: list[str]) -> dict[str, dict]:
    """批量读取已落库的费率/规模。库不可用时退化为 {}（页面显示 —）。"""
    if not codes:
        return {}
    try:
        db = _db()
        _ensure_table(db)
    except Exception as e:  # pragma: no cover
        print(f"[FundFee] 获取 DB 失败: {e}")
        return {}

    out: dict[str, dict] = {}
    for i in range(0, len(codes), 400):
        chunk = codes[i : i + 400]
        marks = ",".join("?" for _ in chunk)
        sql = (
            "SELECT code, scale, scale_date, mgmt_fee, custody_fee, subscribe_fee, "
            "manager, invest_type, benchmark FROM base_fund_fee_info "
            f"WHERE code IN ({marks})"
        )
        try:
            rows = db.fetchall(sql, list(chunk))
        except Exception as e:
            print(f"[FundFee] 查询失败: {e}")
            continue
        for r in rows:
            out[str(r[0])] = {
                "scale": r[1],
                "scale_date": r[2],
                "mgmt_fee": r[3],
                "custody_fee": r[4],
                "subscribe_fee": r[5],
                "manager": r[6],
                "invest_type": r[7],
                "benchmark": r[8],
            }
    return out


def missing_codes(codes: list[str]) -> list[str]:
    """返回「库里没有」或「已过期（> FEE_TTL_DAYS）」的基金代码。"""
    if not codes:
        return []
    have: dict[str, datetime | None] = {}
    try:
        db = _db()
        _ensure_table(db)
        for i in range(0, len(codes), 400):
            chunk = codes[i : i + 400]
            marks = ",".join("?" for _ in chunk)
            rows = db.fetchall(
                f"SELECT code, updated_at FROM base_fund_fee_info WHERE code IN ({marks})",
                list(chunk),
            )
            for r in rows:
                have[str(r[0])] = r[1]
    except Exception as e:
        print(f"[FundFee] 缺口计算失败: {e}")
        return list(codes)

    deadline = _now_cst().replace(tzinfo=None) - timedelta(days=FEE_TTL_DAYS)
    out = []
    for c in codes:
        if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE:
            continue
        ts = _naive(have.get(c))
        # ⚠️ DuckDB TIMESTAMP 取出为 naive， deadlines 也必须是 naive，
        #    否则 tz-aware vs naive 比较抛 TypeError，会把「已补全」误判成缺口。
        if ts is None or ts < deadline:
            out.append(c)
    return out


def _naive(dt):
    """把 DuckDB 取出的 TIMESTAMP 统一成 naive（DuckDB 只存 naive）。"""
    if dt is None:
        return None
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        return dt.astimezone(CST).replace(tzinfo=None)
    return dt


def snapshot(codes: list[str] | None = None) -> dict:
    """供接口返回的一次性进度快照（字段命名对外稳定）。"""
    codes = codes or all_known_codes()
    filled, total = counts(codes)
    p = progress()
    return {
        "filled": filled,
        "total": total,
        "running": p["running"],
        "round_done": p["done"],
        "round_total": p["total"],
        "ok": p["ok"],
        "fail": p["fail"],
        "skipped": p["skipped"],
        "perm_failed": sum(1 for c in codes if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE),
        "rounds": p["rounds"],
        "started_at": p["started_at"],
        "finished_at": p["finished_at"],
        "last_error": p["last_error"],
        "throttled": p["throttled"],
        "throttle_streak": p["throttle_streak"],
        "retry_in_hours": p["retry_in_hours"],
    }


def counts(codes: list[str]) -> tuple[int, int]:
    """(已**真正**补全的只数, 总只数)。

    ⚠️ 永久失败（累计失败 >= MAX_FAIL_PER_CODE）的基金不计入「已补全」——
    它们被 missing_codes 排除、不再重试，若算进 filled 会虚高进度（审查 L1）。
    """
    miss = missing_codes(codes)
    failed = sum(1 for c in codes if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE)
    return len(codes) - len(miss) - failed, len(codes)


# ============================================================
# 后台渐进补全
# ============================================================

def next_retry_in_hours() -> int:
    """下一次「自动续跑」需要等待的小时数（指数退避，连续被限流越多次等越久）。"""
    idx = min(max(_THROTTLE_STREAK, 1), len(BACKOFF_LADDER_HOURS)) - 1
    return BACKOFF_LADDER_HOURS[idx]


def last_finish_ts() -> float:
    """上一轮完成的 time.time()（供定时任务做间隔判断）。"""
    return _LAST_FINISH_TS


def due_for_retry(now: float | None = None) -> bool:
    """上一轮被限流中止后，是否已到自动续跑时间。"""
    if _THROTTLE_STREAK <= 0 or _LAST_FINISH_TS <= 0:
        return False
    return (now or time.time()) - _LAST_FINISH_TS >= next_retry_in_hours() * 3600


def _progress_locked() -> dict:
    """拼进度字典（**调用方必须已经持有 ``_FILL_LOCK``**）。"""
    return {
        "running": _FILL["running"],
        "total": _FILL["total"],
        "done": _FILL["done"],
        "ok": _FILL["ok"],
        "fail": _FILL["fail"],
        "rounds": _FILL["rounds"],
        "last_batch": _FILL["last_batch"],
        "started_at": _FILL["started_at"],
        "finished_at": _FILL["finished_at"],
        "last_error": _FILL["last_error"],
        "skipped": _FILL.get("skipped", 0),
        "throttled": _FILL.get("throttled", False),
        "throttle_streak": _THROTTLE_STREAK,
        "retry_in_hours": next_retry_in_hours() if _THROTTLE_STREAK > 0 else 0,
    }


def progress() -> dict:
    """当前补全进度快照（供 ``/dividend/fee-progress`` 轮询）。

    ⚠️ 和 holdings 侧同一条铁律：**绝不能无限等 ``_FILL_LOCK``**。
    ``start_fill`` 曾经把 ``missing_codes``（查 DuckDB）放在持锁期间，DuckDB 写锁
    一被别的后台任务占住，这把锁就被无限持有，``/dividend/fee-progress`` 跟着整片
    HTTP=000（实测 curl 40s 不回，而同进程的 ``/api/v1/jobs`` 还 2ms 就回）。
    这里最多等 1 秒，拿不到就返回上一次的快照——轮询宁可旧一点，也绝不能把
    请求线程拖死。
    """
    if not _FILL_LOCK.acquire(timeout=1):
        return _progress_locked()
    try:
        return _progress_locked()
    finally:
        _FILL_LOCK.release()


def _run(codes: list[str], delay: float) -> None:
    global _LAST_FINISH_TS
    try:
        db = _db()
        _ensure_table(db)
    except Exception as e:
        with _FILL_LOCK:
            _FILL["running"] = False
            _FILL["last_error"] = f"DB 不可用: {e}"
            _FILL["finished_at"] = _now_cst().strftime("%Y-%m-%d %H:%M:%S")
        return

    global _THROTTLE_STREAK
    consec_fail = 0
    throttled = False
    for code in codes:
        try:
            rec = fetch_one(code)
        except Exception as e:
            rec = None
            print(f"[FundFee] {code} 拉取异常: {e}")

        if rec:
            try:
                _upsert(db, rec)
                _FAIL_COUNTS.pop(code, None)
                consec_fail = 0
                with _FILL_LOCK:
                    _FILL["ok"] += 1
            except Exception as e:
                print(f"[FundFee] {code} 写入失败: {e}")
                with _FILL_LOCK:
                    _FILL["fail"] += 1
                    _FILL["last_error"] = str(e)[:200]
        else:
            _FAIL_COUNTS[code] = _FAIL_COUNTS.get(code, 0) + 1
            consec_fail += 1
            with _FILL_LOCK:
                _FILL["fail"] += 1
                _FILL["last_error"] = f"{code} 上游无数据/限流"
            if consec_fail >= MAX_CONSEC_FAIL:
                throttled = True
                with _FILL_LOCK:
                    _FILL["last_error"] = (
                        f"连续 {consec_fail} 只失败，疑似同花顺限流，本轮中止，稍后自动继续"
                    )
                break
            time.sleep(FAIL_SLEEP)

        with _FILL_LOCK:
            _FILL["done"] += 1
        time.sleep(delay)

    _THROTTLE_STREAK = _THROTTLE_STREAK + 1 if throttled else 0

    with _FILL_LOCK:
        _FILL["running"] = False
        _FILL["throttled"] = throttled
        _FILL["finished_at"] = _now_cst().strftime("%Y-%m-%d %H:%M:%S")
        _LAST_FINISH_TS = time.time()

    if throttled:
        print(
            f"[FundFee] 本轮疑似被限流中止（连续中止 {_THROTTLE_STREAK} 次），"
            f"{next_retry_in_hours()} 小时后由定时任务续跑"
        )


def start_fill(
    codes: list[str],
    limit: int = DEFAULT_BATCH,
    delay: float = DEFAULT_DELAY,
    auto: bool = False,
) -> dict:
    """启动一轮后台补全（非阻塞）。已在跑则直接返回当前进度。

    ``auto=True``（页面访问顺手补）会受 ``AUTO_COOLDOWN`` 限制，避免刷新一次就打一轮上游。
    """
    if auto and time.time() - _LAST_FINISH_TS < AUTO_COOLDOWN:
        return progress()
    # ⚠️ 缺失清单（查 DuckDB）必须在**锁外**算：DuckDB 写锁被别的后台任务占住时
    # 这一步会阻塞几十秒甚至更久，把它放在 _FILL_LOCK 里等于把 progress() 一起陪葬
    # → /dividend/fee-progress 整片超时（2026-10-06 事故）。
    todo = missing_codes(codes)[: max(1, limit)]
    with _FILL_LOCK:
        if _FILL["running"]:
            return _progress_locked()
        if not todo:
            _FILL["last_error"] = None
            return _progress_locked()
        _FILL.update({
            "running": True,
            "total": len(todo),
            "done": 0,
            "ok": 0,
            "fail": 0,
            "skipped": sum(1 for c in codes if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE),
            "last_batch": len(todo),
            "started_at": _now_cst().strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": None,
            "last_error": None,
        })
        _FILL["rounds"] += 1
        target = todo

    threading.Thread(target=_run, args=(target, delay), daemon=True).start()
    return progress()


def all_known_codes() -> list[str]:
    """后台补全目标代码全集：红利名录 + 现金流场内 ETF（优先用上次缓存，避免重复拉 5MB 名录）。"""
    global _LAST_CODES
    if _LAST_CODES:
        return list(_LAST_CODES)
    try:
        from services.dividend_service import get_backend_fund_codes

        codes = get_backend_fund_codes()
        if codes:
            _LAST_CODES = codes
    except Exception as e:
        print(f"[FundFee] 代码全集构建失败: {e}")
    return list(_LAST_CODES)


def attach_fees(funds: dict[str, list[dict]]) -> tuple[list[str], dict]:
    """把已落库的费率/规模写回基金条目，返回 (全部代码, 进度)。

    同时**顺手触发一轮后台补全**（若有缺口且当前没在跑），做到「越用越全」。
    """
    global _LAST_CODES
    codes: list[str] = []
    for rows in funds.values():
        for r in rows:
            codes.append(str(r.get("code")))
    if codes:
        # ⚠️ 必须是**并集**而不是覆盖：这个函数同时服务红利名录与现金流名录两条线，
        # 任何一条把 _LAST_CODES 覆盖掉都会让另一条从补全队列里消失
        # （2026-10-07：现金流 Tab 一开始调 attach_fees 就曾把红利 361 只挤出去）。
        _seen = set(_LAST_CODES)
        _LAST_CODES = list(_LAST_CODES) + [c for c in codes if c not in _seen]
    if not codes:
        return [], progress()

    fee_map = get_fee_map(codes)
    for rows in funds.values():
        for r in rows:
            f = fee_map.get(str(r.get("code")))
            if f:
                r["scale"] = f.get("scale")
                r["mgmt_fee"] = f.get("mgmt_fee")
                r["custody_fee"] = f.get("custody_fee")
                r["subscribe_fee"] = f.get("subscribe_fee")
                r["scale_date"] = f.get("scale_date")
                r["manager"] = f.get("manager")

    prog = progress()
    # 「越用越全」的顺手补：两种情况下不出手——①正在跑；②上一轮是被限流打断的，
    # 且还在退避期（否则每次刷新页面都去撞墙，退避阶梯会被架空）。
    # ⚠️ 用户手动点「补一批」走的 start_fill(auto=False)，不受此限。
    if prog["running"] or (_THROTTLE_STREAK > 0 and not due_for_retry()):
        return codes, prog
    if missing_codes(codes):
        start_fill(codes, auto=True)
        prog = progress()
    return codes, prog
