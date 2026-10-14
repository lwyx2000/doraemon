"""红利基金「持仓股」后台补全服务。

数据源：东财 ``fund_portfolio_hold_em``（单基金季报持仓），经 aksharewebapi ``/api/ak`` 代理。

⚠️ 口径（务必与前端一致，避免误读）：
- 这是**季报披露持仓**（T-1 季度），不是实时持仓；返回的 ``quarter`` 字段必须展示给用户。
- 深度不均：**ETF / 指数基金**返回全量持仓（实测 40~115 条），**主动基金**只有十大重仓（10 条）。
- 少数基金（如次新联接基金 007760）无季报 → 上游返回空数组，前端显示「—」，**不 mock**。

落库表 ``base_fund_stock_holdings``（IF NOT EXISTS，按需建表，旧库平滑升级）。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from services.akshare_client import akshare_request

CST = timezone(timedelta(hours=8))

#: 持仓缓存有效期（天）。
#: ⚠️ 季报一年四更（4/30/9/12 月末披露），但披露后上游东财不一定马上就能查到最新报告期，
#: 30 天偏激进 → 刚抓完没多久又整只重刷；60 天约等于「两个季报窗口」，
#: 既能跟上新季报又不至于天天重刷（实测 464 只有数据的里 127 只本就无季报，重刷纯属浪费请求）。
HOLDINGS_TTL_DAYS = 60
#: 单轮默认补全只数
DEFAULT_BATCH = 120
#: 并发抓取路数。⚠️ 必须压低：5 路并发时上游（aksharewebapi → 东财）会在百来只内开始
#: 超时/限流，实测整轮 ok=0、fail=116（同花顺 fund_info_ths 当年也是这个坑）。3 路稳。
DEFAULT_CONCURRENCY = 3
#: 每只之间的间隔（秒）
DEFAULT_DELAY = 0.3
#: 整轮失败率达到该比例即中止本轮（疑似限流），避免继续硬刷上游
FAIL_ABORT_RATIO = 0.3
#: 连续失败达到该只数即中止（放宽到 12：并发下个别抖动不应直接判定限流）
MAX_CONSEC_FAIL = 25
# 连续「上游返回空」上限（次新 / 联接 / 货币基金本来就无季报，会扎堆连续空，
# 不能按失败处理，否则一轮跑 25 只空数据就白白中止）。真限流会返回错误 / 超时，走 fail 计数。
MAX_CONSEC_EMPTY = 80
#: 同一只累计失败超过该次数后跳过（下轮/重启后仍会重试）
MAX_FAIL_PER_CODE = 3

DDL = """
CREATE TABLE IF NOT EXISTS base_fund_stock_holdings (
    fund_code     VARCHAR,
    stock_code    VARCHAR,
    stock_name    VARCHAR,
    pct           DOUBLE,
    shares        DOUBLE,
    mv            DOUBLE,
    quarter       VARCHAR,
    seq           INTEGER,
    source        VARCHAR,
    fetched_at    TIMESTAMP,
    PRIMARY KEY (fund_code, stock_code, quarter)
)
"""

# 单位说明（前端 tooltip 直接用，避免用户误读数量级）
#: 「持股数」原始单位为万份（东财口径）
UNIT_SHARES = "万份"
#: 「持仓市值」原始单位为万元（东财口径）
UNIT_MV = "万元"

#: 「无季报」哨兵占位股票代码。
#: 次新 / 联接 / 债券 / 货币基金（实测 127 只）上游永远返回空数组，抓不到任何持仓。
#: 不落哨兵的话 ``missing_codes`` 每轮都会把它们当缺口重新捡回来（死循环空跑），
#: 而且 ``counts()`` 永远差这 127 只、进度条卡在 80% 下不来。落哨兵后
#: ``max(fetched_at)`` 有值 → 在 TTL 内被正确跳过；读路径已用 ``stock_code <> 哨兵`` 过滤，
#: 不会漏到前端。
NO_REPORT_CODE = "__NO_REPORT__"

# ============================================================
# 后台补全状态（进程级；进度本身持久化在表里）
# ============================================================

_FILL: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "ok": 0,
    "fail": 0,
    "empty": 0,
    "rounds": 0,
    "skipped": 0,
    "last_batch": 0,
    "started_at": None,
    "finished_at": None,
    "last_error": None,
    "throttled": False,
}
_FILL_LOCK = threading.Lock()

#: 连续被限流中止的次数（一轮正常跑完即清零）
_THROTTLE_STREAK = 0

#: 单只累计失败次数（进程级）
_FAIL_COUNTS: dict[str, int] = {}

#: 上一轮完成时间戳，供自动补全冷却判断
_LAST_FINISH_TS = 0.0

#: 最近一次算出的「轮开始前已补全只数」（由 start_fill 写入，供 snapshot 免查库复用）
_LAST_COUNTS: dict = {"loaded": 0}

#: 最近一次见到的红利基金代码全集
_LAST_CODES: list[str] = []


def _now_cst() -> datetime:
    return datetime.now(CST)


def _db():
    from database.connection import get_db

    return get_db()


def _ensure_table(db) -> None:
    """建表（IF NOT EXISTS）。

    历史遗留：初版列名叫 ``stock_count``（实际存的是东财「序号」，命名有误），
    后改为 ``seq``。旧表若没有 ``seq`` 列就整表重建——数据量小（单只基金最多百来条），
    重建代价可忽略，比写一堆 ALTER 划算。
    """
    try:
        cols = {r[0] for r in db.fetchall("DESCRIBE base_fund_stock_holdings")}
        if cols and "seq" not in cols:
            print("[FundHold] 检测到旧版 base_fund_stock_holdings（无 seq 列），重建表")
            db.execute("DROP TABLE base_fund_stock_holdings")
    except Exception:
        pass  # 表还不存在，正常走建表
    try:
        db.execute(DDL)
    except Exception as e:  # pragma: no cover
        print(f"[FundHold] 建表失败: {e}", flush=True)


# ============================================================
# 取数
# ============================================================

def all_fund_codes() -> list[str]:
    """后台补全目标代码全集：红利名录 + 现金流场内 ETF（优先用缓存，避免重复拉 5MB 名录）。

    2026-10-07 起目标扩到现金流 33 只场内 ETF（用户拍板「最好都扩」）；
    红利在前、现金流在后，保证主业不被挤到队尾。
    """
    global _LAST_CODES
    if _LAST_CODES:
        return list(_LAST_CODES)
    try:
        from services.dividend_service import get_backend_fund_codes

        codes = get_backend_fund_codes()
        if codes:
            _LAST_CODES = list(codes)
            return list(codes)
    except Exception as e:
        print(f"[FundHold] 取基金名录失败: {e}", flush=True)
    return []


def _fetch_rows(code: str) -> list[dict]:
    """拉一只基金的季报持仓明细（东财 fund_portfolio_hold_em）。

    上游 accept 的 ``date`` 是形如 ``20261231`` 的报告期日期；取当前年 12-31
    即可拿到最新季报（部分基金会回落到上一季度）。
    """
    data = akshare_request(
        "fund_portfolio_hold_em",
        {"symbol": code, "date": f"{datetime.now(CST).year}1231"},
        timeout=25,
        retries=1,
    )
    if not data:
        return []
    return [r for r in data if r.get("股票代码")]


def _row_to_record(fund_code: str, r: dict) -> tuple:
    return (
        fund_code,
        str(r.get("股票代码") or "").zfill(6),
        r.get("股票名称") or "",
        float(r.get("占净值比例") or 0) or None,
        float(r.get("持股数") or 0) or None,
        float(r.get("持仓市值") or 0) or None,
        r.get("季度") or "",
        int(r.get("序号") or 0) or None,
        "东财fund_portfolio_hold_em",
    )


def _dedupe(rows: list[dict]) -> list[dict]:
    """按 (股票代码, 季度) 去重。

    ⚠️ 东财 ``fund_portfolio_hold_em`` 对部分基金（尤其 ETF）会在同一季度里
    返回同一只股票的**重复行**（例如 股票代码/名称 与 占净值比例 重复出现），
    直接写会撞 ``PRIMARY KEY (fund_code, stock_code, quarter)`` 报
    ``Constraint Error: Duplicate key``。这里保留「占净值比例」最大的一条。
    """
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("股票代码"), r.get("季度"))
        prev = best.get(key)
        if prev is None or (r.get("占净值比例") or 0) > (prev.get("占净值比例") or 0):
            best[key] = r
    return list(best.values())


def _persist(db, fund_code: str, rows: list[dict]) -> int:
    """批量落一只基金的持仓（按 季度 分区写）。返回写入条数（0 表示空持仓）。"""
    if not rows:
        return 0
    rows = _dedupe(rows)
    quarters = {r.get("季度") for r in rows}
    now = _now_cst()
    payload = []
    for q in quarters:
        db.execute(
            "DELETE FROM base_fund_stock_holdings WHERE fund_code = ? AND quarter = ?",
            [fund_code, q],
        )
        for r in rows:
            if r.get("季度") != q:
                continue
            payload.append(_row_to_record(fund_code, r) + (now,))
    db.executemany(
        "INSERT INTO base_fund_stock_holdings "
        "(fund_code, stock_code, stock_name, pct, shares, mv, quarter, "
        " seq, source, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        payload,
    )
    return len(payload)


def _mark_no_report(db, fund_code: str) -> None:
    """给「确认无季报」的基金落一条哨兵行，让它在 TTL 内不再被当缺口。

    ⚠️ 只写哨兵，**不写任何 fake 持仓**：``stock_name`` 就是「无季报」，
    且读路径会过滤掉 ``stock_code = NO_REPORT_CODE`` 的行，前端永远看不到它。
    """
    now = _now_cst()
    db.execute(
        "DELETE FROM base_fund_stock_holdings WHERE fund_code = ? AND stock_code = ?",
        [fund_code, NO_REPORT_CODE],
    )
    db.execute(
        "INSERT INTO base_fund_stock_holdings "
        "(fund_code, stock_code, stock_name, pct, shares, mv, quarter, "
        " seq, source, fetched_at) "
        "VALUES (?, ?, ?, NULL, NULL, NULL, 'NO_REPORT', 0, '东财无季报', ?)",
        [fund_code, NO_REPORT_CODE, "无季报", now],
    )


# ============================================================
# 缺口计算 / 进度
# ============================================================

def missing_codes(codes: list[str]) -> list[str]:
    """剔除「已抓过且未过期」「累计失败超限」的基金，返回本轮待抓清单。"""
    try:
        db = _db()
        rows = db.fetchall(
            "SELECT fund_code, max(fetched_at) AS t FROM base_fund_stock_holdings "
            "GROUP BY fund_code"
        )
        have = {r[0]: r[1] for r in rows}
    except Exception as e:
        print(f"[FundHold] 缺口计算失败: {e}", flush=True)
        return list(codes)

    deadline = _now_cst().replace(tzinfo=None) - timedelta(days=HOLDINGS_TTL_DAYS)
    out = []
    for c in codes:
        if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE:
            continue
        ts = have.get(c)
        # ⚠️ DuckDB TIMESTAMP 取出为 naive，deadline 也必须是 naive，否则比较抛 TypeError
        if ts is None or ts < deadline:
            out.append(c)
    return out


def counts(codes: list[str]) -> tuple[int, int]:
    """(已**真正**落库的只数, 总只数)。

    ⚠️ 永久失败（累计失败 >= MAX_FAIL_PER_CODE）的基金不计入「已补全」——
    它们被 missing_codes 排除、不再重试，若算进 filled 会虚高进度（审查 L1）。
    """
    miss = missing_codes(codes)
    failed = sum(1 for c in codes if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE)
    return len(codes) - len(miss) - failed, len(codes)


def progress() -> dict:
    """当前补全进度快照。

    ⚠️ **绝不能无限等 ``_FILL_LOCK``**（2026-10-06 事故现场）：``_FILL_LOCK``
    曾被 ``start_fill`` 一直持有去调 ``missing_codes`` 查 DuckDB，而 DuckDB 写锁
    一被别的后台任务占住，这个等待就是几十秒起步、甚至永远；``holdings-progress``
    走的正是 ``progress()`` → 接口整片 HTTP=000（实测 curl 40s 都不回），而同时
    ``/api/v1/jobs`` 还 2ms 就回，极具迷惑性。

    这里改成**最多等 1 秒**，拿不到就返回上一次的快照——前端轮询本来就「差不多
    就行」，宁可旧一点也绝不能把请求线程拖死。
    """
    if not _FILL_LOCK.acquire(timeout=1):
        return dict(_FILL)
    try:
        return dict(_FILL)
    finally:
        _FILL_LOCK.release()


def snapshot(codes: list[str] | None = None) -> dict:
    """供接口返回的一次性进度快照。

    ⚠️ 刻意**不查库**：后台补全跑起来时 DuckDB 写锁被占用，任何来自请求线程的
    查询都会一直阻塞（实测整站 HTTP=000 无响应）。「已补全只数」用
    ``start_fill`` 时算好的 ``_LAST_COUNTS["loaded"]`` 加本轮增量，误差仅在本轮
    中途，够前端轮询用。
    """
    _t0 = time.time()
    codes = codes or all_fund_codes()
    _dt = time.time() - _t0
    if _dt > 3:
        # 名录缓存正常情况下是 0s；慢在这里说明 _LAST_COUNTS 空了、又去全量拉了一次
        print(f"[FundHold] snapshot 取红利名录耗时 {_dt:.1f}s", flush=True)
    p = progress()
    total = len(codes)
    base = _LAST_COUNTS["loaded"]
    filled = base + p["ok"] if p["running"] else min(base, total)
    return {
        # ⚠️ 两组口径别混用：
        # - ``filled`` / ``total``：**全量视角**（轮开始前已补全只数 + 本轮成功只数 / 名录总只数），
        #   这才是进度条该用的分母。
        # - ``round_done`` / ``round_total``：**本轮视角**（本轮已遍历只数 / 本轮计划只数）。
        #   ``round_done`` **含「无季报」**（empty），所以本轮跑满时它等于 round_total 属正常，
        #   绝不能拿它当「已补全」去看——那边请一律用 ``filled`` 和 ``ok``。
        "filled": filled,
        "total": total,
        "running": p["running"],
        "round_done": p["done"],
        "round_total": p["total"],
        "ok": p["ok"],
        "fail": p["fail"],
        "empty": p["empty"],
        "skipped": p["skipped"],
        "perm_failed": sum(1 for c in codes if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE),
        "rounds": p["rounds"],
        "started_at": p["started_at"],
        "finished_at": p["finished_at"],
        "last_error": p["last_error"],
        "throttled": p["throttled"],
        "throttle_streak": _THROTTLE_STREAK,
    }


# ============================================================
# 后台渐进补全（线程池并发）
# ============================================================

def _one(code: str) -> tuple[str, list[dict], str | None]:
    try:
        rows = _fetch_rows(code)
        return code, rows, None
    except Exception as e:  # noqa: BLE001
        return code, [], str(e)[:120]


#: 会被本任务避让的 DuckDB 写任务（占位说明用，实际以 ``jobs.registry`` 实时状态为准）
_AVOID_JOB_HINTS = (
    "sw_sector",          # 申万板块快照 / 回填
    "turnover",           # 成交额快照
    "dividend_fee",       # 基金费率补全
    "dividend_index_map",  # 跟踪指数识别
)


def _busy_job_names() -> list[str]:
    """当前正在跑、且很可能占用 DuckDB 写锁的任务名（只看 jobs.registry 的实时状态）。"""
    busy = []
    try:
        from jobs.registry import get_all_jobs

        for j in get_all_jobs():
            if j.get("last_status") == "running" and j.get("job_id") != "dividend_holdings_daily_fill":
                busy.append(j.get("job_id") or j.get("name") or "?")
    except Exception:  # noqa: BLE001
        pass
    # 费率服务自报running（它未必注册进 registry，历史版本只认它）
    try:
        from services import fund_fee_service

        if fund_fee_service.progress().get("running"):
            busy.append("fund_fee_service")
    except Exception:  # noqa: BLE001
        pass
    # 指数识别服务同样自报状态（没进 registry 时靠这里兜）
    try:
        from services import fund_index_map_service

        if fund_index_map_service.progress().get("running"):
            busy.append("fund_index_map_service")
    except Exception:  # noqa: BLE001
        pass
    return busy


def _wait_for_db_quiet(max_wait: int = 20, interval: int = 30) -> None:
    """其他会写 DuckDB 的后台任务在跑时，本轮先干等，不要去抢同一个连接。

    ⚠️ 两个后台线程共用同一个 duckdb 连接会**死锁**（一个持 GIL 等锁、一个持锁等 GIL），
    实测表现为整站 HTTP=000。这里主动避让，最多等 ``max_wait * interval`` 秒。

    ⚠️ 覆盖面必须包含**所有**写 DuckDB 的任务（申万快照、成交额快照、费率、
    指数识别），早期版本只等 ``fund_fee_service`` —— 别的任务在跑时本轮照样会撞锁，
    只是当时没踩上而已。
    """
    waited = 0
    while True:
        busy = _busy_job_names()
        if not busy:
            return
        if waited >= max_wait:
            print(
                f"[FundHold] {','.join(busy)} 已占用 DuckDB {waited}s，"
                f"本轮先不抢（下次再补）",
                flush=True,
            )
            return
        print(f"[FundHold] {','.join(busy)} 正在写 DuckDB，本轮避让 {interval}s…", flush=True)
        time.sleep(interval)
        waited += interval


def _run(codes: list[str], delay: float, concurrency: int) -> None:
    """串行逐只「取数 + 落库」。

    ⚠️ 三条硬约束，全是踩坑换来的：
    1. **不能并发取数写库**：DuckDB 单写锁 + 连接非线程安全，线程池里共用写连接会大量
       抛「写入失败」（实测 591 只整轮 ok=0 / fail=138，一条都没落进去）。
    2. **不能攒一批再落库**：攒批写会长时间占着写锁（期间还持 GIL），把费率补全的后台
       任务和 HTTP 请求线程一起饿死（实测整站 HTTP=000）。逐只写，锁持有仅几十毫秒。
    3. **不能和其他后台写库任务同时写**：见 ``_wait_for_db_quiet``（费率 / 申万快照 /
       成交额快照 / 指数识别全都要避）。
    """
    del concurrency, delay  # 保留签名，本轮不使用并发
    consec_fail = 0
    consec_empty = 0
    print(f"[FundHold] _run 启动：本轮 {len(codes)} 只", flush=True)
    # 避让：别的后台任务此刻可能正在写同一个 DuckDB，先干等它们落停再动写锁
    _wait_for_db_quiet(max_wait=6, interval=15)
    print("[FundHold] 费率避让结束，准备拿 DB 句柄", flush=True)
    try:
        db = _db()
        print("[FundHold] DB 句柄已获取", flush=True)
        _ensure_table(db)
        print("[FundHold] base_fund_stock_holdings 表结构就绪", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[FundHold] DB 不可用: {e}", flush=True)
        with _FILL_LOCK:
            _FILL["running"] = False
            _FILL["last_error"] = f"DB 不可用: {e}"
            _FILL["finished_at"] = _now_cst().strftime("%Y-%m-%d %H:%M:%S")
        return

    for code in codes:
        try:
            code, rows, err = _one(code)
        except Exception as e:  # noqa: BLE001
            code, rows, err = code, [], str(e)[:160]
        try:
            if rows:
                n = _persist(db, code, rows)
                _FAIL_COUNTS.pop(code, None)
                consec_fail = 0
                consec_empty = 0
                with _FILL_LOCK:
                    _FILL["ok"] += 1
                    _FILL["last_error"] = None
                print(f"[FundHold] {code} 落库 {n} 条持仓", flush=True)
            elif err:
                # 真异常（取数报错 / 上游 5xx / 超时）→计入 fail，用于限流判定
                _FAIL_COUNTS[code] = _FAIL_COUNTS.get(code, 0) + 1
                consec_fail += 1
                consec_empty = 0
                with _FILL_LOCK:
                    _FILL["fail"] += 1
                    _FILL["last_error"] = f"{code} 取数异常: {err}"
                print(f"[FundHold] {code} 取数异常({consec_fail}) err={err}", flush=True)
            else:
                # 上游 200 但空数组 = 这只基金真没有季报（次新 / 联接 / 货币等），
                # 落一条哨兵行，让它在 TTL 内不再被视为缺口，避免每天白跑上百次请求。
                try:
                    _mark_no_report(db, code)
                except Exception as e:  # noqa: BLE001
                    print(f"[FundHold] {code} 落无季报哨兵失败: {type(e).__name__} {str(e)[:120]}", flush=True)
                consec_empty += 1
                with _FILL_LOCK:
                    _FILL["empty"] += 1
                    # ⚠️ 空季报≠失败：次新 / 联接 / 货币基金本来就没有季报持仓，
                    # 计入 fail 会让整轮在 30% 空数据处误判「限流」而提前中止。
                    _FILL["throttle_suspect"] = False
                    _FILL["last_error"] = None
                if consec_empty <= 6:
                    print(f"[FundHold] {code} 无季报({consec_empty})", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[FundHold] {code} 落库异常: {type(e).__name__} {str(e)[:160]}", flush=True)
            with _FILL_LOCK:
                _FILL["fail"] += 1
                _FILL["last_error"] = str(e)[:200]

        with _FILL_LOCK:
            _FILL["done"] += 1
            done = _FILL["done"]
            n_fail = _FILL["fail"]
        ratio = n_fail / done if done else 0.0
        if consec_fail >= MAX_CONSEC_FAIL or (done >= 30 and ratio > FAIL_ABORT_RATIO):
            with _FILL_LOCK:
                _FILL["last_error"] = (
                    f"疑似东财限流：已处理 {done} 只、失败 {n_fail} 只"
                    f"（连续失败 {consec_fail}，异常失败率 {ratio:.0%}），本轮中止"
                )
            print("[FundHold] 疑似限流，本轮中止（下轮自动续）", flush=True)
            break
        time.sleep(0.05)  # 让出 GIL，别把 HTTP 线程饿死

    with _FILL_LOCK:
        _FILL["running"] = False
        _FILL["throttled"] = consec_fail >= MAX_CONSEC_FAIL
        _FILL["finished_at"] = _now_cst().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"[FundHold] 本轮结束 ok={_FILL['ok']} fail={_FILL['fail']} "
        f"empty={_FILL['empty']} done={_FILL['done']}"
    )


def start_fill(
    codes: list[str] | None = None,
    limit: int = DEFAULT_BATCH,
    delay: float = DEFAULT_DELAY,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict:
    """启动一轮后台补全（非阻塞）。已在跑则直接返回当前进度。"""
    global _LAST_COUNTS
    codes = codes or all_fund_codes()
    # ⚠️ 缺失清单（查 DuckDB）**必须在锁外算**：DuckDB 写锁被别的后台任务占住时，
    # 这一步会阻塞几十秒甚至更久；把它放在 _FILL_LOCK 里等于把 progress() 一起陪葬
    # → /dividend/holdings-progress 整片超时（2026-10-06 实测）。
    miss = missing_codes(codes)
    failed = sum(1 for c in codes if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE)
    _LAST_COUNTS["loaded"] = max(0, len(codes) - len(miss) - failed)
    todo = miss[: max(1, limit)]
    with _FILL_LOCK:
        if _FILL["running"]:
            return dict(_FILL)
        if not todo:
            _FILL["last_error"] = None
            return dict(_FILL)
        _FILL.update({
            "running": True,
            "total": len(todo),
            "done": 0,
            "ok": 0,
            "fail": 0,
            "empty": 0,
            "skipped": sum(1 for c in codes if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE),
            "last_batch": len(todo),
            "started_at": _now_cst().strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": None,
            "last_error": None,
        })
        _FILL["rounds"] += 1
        target = todo

    threading.Thread(
        target=_run, args=(target, delay, concurrency), daemon=True
    ).start()
    return progress()


# ============================================================
# 读取（供接口 / 前端）
# ============================================================

def get_holdings(fund_code: str, limit: int = 200) -> dict:
    """某只红利基金的持仓明细。

    返回：
    - ``quarter``：季报所属季度（如「2026年3季度股票投资明细」），前端必须展示；
    - ``rows``：持仓明细（``seq`` 为东财原表序号，``pct`` 占净值比例、``shares`` 持股数(万份)、
      ``mv`` 持仓市值(万元)，按占净值比例降序）；
    - ``source`` / ``stale``：口径与新鲜度标注。
    无数据时返回空 ``rows``（**不 mock**）。
    """
    fund_code = str(fund_code or "").strip()
    empty = {
        "code": fund_code,
        "quarter": None,
        "source": None,
        "stock_count": 0,
        "row_count": 0,
        "fetched_at": None,
        "stale": False,
        "rows": [],
    }
    if not fund_code:
        return empty

    try:
        db = _db()
        rows = db.fetchall(
            "SELECT stock_code, stock_name, pct, shares, mv, quarter, seq, "
            "       fetched_at, source "
            "FROM base_fund_stock_holdings "
            "WHERE fund_code = ? AND stock_code <> ? "  # 过滤「无季报」哨兵行
            "ORDER BY pct DESC NULLS LAST",
            [fund_code, NO_REPORT_CODE],
        )
    except Exception as e:
        print(f"[FundHold] {fund_code} 读持仓失败: {e}", flush=True)
        return empty
    if not rows:
        return empty

    quarters = {r[5] for r in rows if r[5]}
    fetched = max([r[7] for r in rows if r[7]] or [None])
    stale = bool(fetched and (datetime.now(CST).replace(tzinfo=None) - fetched).days > HOLDINGS_TTL_DAYS)
    data = [
        {
            "stock_code": r[0],
            "stock_name": r[1],
            "pct": r[2],
            "shares": r[3],
            "mv": r[4],
            "quarter": r[5],
            "seq": r[6],
        }
        for r in rows
    ]
    return {
        "code": fund_code,
        "quarter": max(quarters) if quarters else None,
        "source": rows[0][8] if rows and rows[0][8] else "东财季报持仓",
        "stock_count": max([r[6] or 0 for r in rows] or [0]),
        "row_count": len(data),
        "fetched_at": str(fetched) if fetched else None,
        "stale": stale,
        "rows": data[:limit],
    }


def last_finish_ts() -> float:
    return _LAST_FINISH_TS


def due_for_retry(now: float | None = None) -> bool:
    """上一轮被限流中止后是否已到续跑时间（退避阶梯：2 / 4 / 8 小时）。"""
    ladder = [2, 4, 8]
    idx = min(max(_THROTTLE_STREAK, 1), len(ladder)) - 1
    if _THROTTLE_STREAK <= 0 or _LAST_FINISH_TS <= 0:
        return False
    return (now or time.time()) - _LAST_FINISH_TS >= ladder[idx] * 3600


def attach_codes(codes: list[str]) -> None:
    """由页面入口顺手写入基金全集，避免每次都重拉 5MB 名录。"""
    global _LAST_CODES
    if codes and codes != _LAST_CODES:
        _LAST_CODES = list(codes)
