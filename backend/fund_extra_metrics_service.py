"""红利 / 现金流基金三类补充指标：跟踪误差 / 分红频率 / 行业集中度。

背景：这三项原先在红利/现金流名录里只预留了列位（tracking_error / payout_freq /
sector_concentration 恒为 None，前端显示「—」）。现补齐真实数据源，沿用
``fund_fee_service`` 的「后台渐进补全 + 落 DuckDB + 进度可轮询」同构模式，做到
「越用越全、不阻塞页面、不撞上游限流」。

三个指标的数据源与口径：
- 跟踪误差（tracking_error，年化 %）：基金日净值增长率（东财 ``fund_open_fund_info_em``
  的「日增长率」）对齐其跟踪指数的日收益（``_fetch_index_hist`` 的收盘日变动），
  纯本地算 residual std 后 ×√252 年化。**无跟踪指数代码的基金跳过**（值留 None）。
- 分红频率（payout_freq，枚举：0 不定期/无、1 年度、2 半年、4 季度、12 月度）：
  天天基金 F10「分红配送」页（fhsp_{code}.html）解析历次分红登记日，取近 4 年、
  按相邻分红的中位间隔反推频率。F10 限流比同花顺宽松。
- 行业集中度（sector_concentration，Top3 行业占净值比 %；另存 sector_count 行业数）：
  复用 ``fund_holdings_service`` 已抓的季报 top 持仓（base_fund_stock_holdings），
  逐只映射到申万一级行业。映射表 base_stock_sw_industry 由「申万一级成分股」构建：
  sw_index_first_info() 列 31 个申万一级、index_component_sw(symbol) 取成分股，建
  「股票 → 申万一级」字典并落库（进程内存 + 库表双缓存）。⚠️ akshare 1.18.97 无
  stock_industry_category（上游 :8000 报 500），故绕开它改用上述两个真实存在的函数。
  聚合算前 3 行业权重占比。**无持仓的基金跳过**。

⚠️ 与费率补全同一条铁律：DuckDB 单写锁，后台线程串行逐只「取数+落库」，绝不并发写、
绝不攒批写、绝不持锁做阻塞查询（progress() 锁超时 1s 防死锁）。
"""

from __future__ import annotations

import re
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from services.akshare_client import akshare_request

CST = timezone(timedelta(hours=8))

#: 指标缓存有效期（天）：超过则重新计算
EXTRA_TTL_DAYS = 30
#: 单轮默认补全只数
DEFAULT_BATCH = 40
#: 每只之间的间隔（秒）。同花顺/东财连续请求会被限流，必须放慢；宁慢勿封。
DEFAULT_DELAY = 1.2
#: 被限流中止后的自动续跑退避阶梯（小时）
BACKOFF_LADDER_HOURS = [2, 4, 8]
#: 连续失败达到该次数即中止本轮（疑似限流）
MAX_CONSEC_FAIL = 5
#: 同一只累计失败超过该次数后本轮跳过（下轮/重启后仍会重试）
MAX_FAIL_PER_CODE = 3
#: 自动触发（页面访问顺手补）的最小间隔（秒）
AUTO_COOLDOWN = 10 * 60
#: 跟踪误差最少需要的重叠样本天数（不足则样本不足，留 None）
TE_MIN_SAMPLES = 20

DDL = """
CREATE TABLE IF NOT EXISTS fund_extra_metrics (
    code              VARCHAR PRIMARY KEY,
    tracking_error    DOUBLE,
    tracking_error_n  INTEGER,
    tracking_error_at TIMESTAMP,
    payout_freq       INTEGER,
    payout_freq_at    TIMESTAMP,
    sector_top3       DOUBLE,
    sector_count      INTEGER,
    sector_at         TIMESTAMP,
    updated_at        TIMESTAMP
)
"""

#: 股票 → 申万一级行业 缓存表（行业集中度子任务复用，避免每只基金重复请求同一只股票）
DDL_STOCK = """
CREATE TABLE IF NOT EXISTS base_stock_sw_industry (
    stock_code VARCHAR PRIMARY KEY,
    industry    VARCHAR,
    fetched_at  TIMESTAMP
)
"""

# ============================================================
# 后台补全状态
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
    "throttled": False,
}
_FILL_LOCK = threading.Lock()
_THROTTLE_STREAK = 0
_LAST_CODES: list[str] = []
_FAIL_COUNTS: dict[str, int] = {}
_LAST_FINISH_TS = 0.0


def _now_cst() -> datetime:
    return datetime.now(CST)


def _today() -> str:
    return datetime.now(CST).strftime("%Y%m%d")


def _db():
    from database.connection import get_db

    return get_db()


def _ensure_table(db) -> None:
    try:
        db.execute(DDL)
        db.execute(DDL_STOCK)
    except Exception as e:  # pragma: no cover
        print(f"[ExtraMetrics] 建表失败: {e}")


def _naive(dt):
    """把 DuckDB 取出的 TIMESTAMP 统一成 naive（DuckDB 只存 naive）。"""
    if dt is None:
        return None
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        return dt.astimezone(CST).replace(tzinfo=None)
    return dt


def _safe(fn, *args, default=None):
    """子计算防御：任何异常都返回 default，绝不把异常抛给 _run。"""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001
        print(f"[ExtraMetrics] {fn.__name__} 异常: {e}")
        return default


# ============================================================
# 三个指标的具体计算
# ============================================================

def _compute_tracking_error(code: str, index_code: str | None) -> tuple[float | None, int | None]:
    """年化跟踪误差（%）。返回 (te_annual_pct, 样本天数)；无指数或样本不足返 (None, n)。"""
    if not index_code:
        return None, None
    # ⚠️ 懒导入：避免与 dividend_service 顶层互相 import 造成循环依赖（启动即崩）
    from services.dividend_service import _fetch_index_hist
    try:
        start = (datetime.now(CST) - timedelta(days=730)).strftime("%Y%m%d")
        fund_rows = akshare_request(
            "fund_open_fund_info_em",
            {"symbol": code, "indicator": "单位净值", "start_date": start, "end_date": _today()},
            timeout=30,
            retries=2,
        )
        if not isinstance(fund_rows, list) or not fund_rows:
            return None, None
        fund_ret: dict[str, float] = {}
        for r in fund_rows:
            d = str(r.get("净值日期") or "")[:10]
            g = r.get("日增长率")
            if not d or g is None:
                continue
            try:
                fund_ret[d] = float(g) / 100.0
            except (TypeError, ValueError):
                pass
        if len(fund_ret) < TE_MIN_SAMPLES:
            return None, len(fund_ret)

        idx_rows = _fetch_index_hist(index_code)
        idx_close: dict[str, float] = {}
        for r in idx_rows:
            d = str(r.get("日期") or "")[:10]
            c = r.get("收盘")
            if not d or c is None:
                continue
            try:
                idx_close[d] = float(c)
            except (TypeError, ValueError):
                pass
        idx_dates = sorted(idx_close.keys())
        idx_ret: dict[str, float] = {}
        for i in range(1, len(idx_dates)):
            p, c = idx_close[idx_dates[i - 1]], idx_close[idx_dates[i]]
            if p:
                idx_ret[idx_dates[i]] = (c - p) / p

        diffs = [fund_ret[d] - idx_ret[d] for d in fund_ret if d in idx_ret]
        n = len(diffs)
        if n < TE_MIN_SAMPLES:
            return None, n
        mean = sum(diffs) / n
        var = sum((x - mean) ** 2 for x in diffs) / (n - 1)
        te_daily = var ** 0.5
        te_annual = te_daily * (252 ** 0.5)
        return round(te_annual * 100, 2), n
    except Exception as e:  # noqa: BLE001
        print(f"[ExtraMetrics] {code} 跟踪误差计算异常: {e}")
        return None, None


def _compute_payout_freq(code: str) -> int:
    """分红频率枚举：0 不定期/无、1 年度、2 半年、4 季度、12 月度。解析失败返 0。"""
    try:
        r = requests.get(
            f"https://fundf10.eastmoney.com/fhsp_{code}.html",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124"},
            timeout=15,
        )
    except Exception:  # noqa: BLE001
        return 0
    if r.status_code != 200:
        return 0
    html = r.text
    # 优先 ISO 日期；拿不到再试「YYYY年MM月DD日」
    dates = re.findall(r"(\d{4}-\d{2}-\d{2})", html)
    if not dates:
        alt = re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", html)
        dates = [f"{y}-{m.zfill(2)}-{d.zfill(2)}" for y, m, d in alt]
    if not dates:
        return 0
    today = datetime.now(CST).date()
    cutoff = today - timedelta(days=4 * 365)
    ds = []
    for d in dates:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
        except Exception:  # noqa: BLE001
            continue
        if dt >= cutoff:
            ds.append(dt)
    if len(ds) < 2:
        return 0
    ds.sort()
    gaps = [max(1, (ds[i] - ds[i - 1]).days) for i in range(1, len(ds))]
    med = statistics.median(gaps)
    if med <= 45:
        return 12
    if med <= 130:
        return 4
    if med <= 240:
        return 2
    if med <= 500:
        return 1
    return 0


# ============================================================
# 申万一级行业映射（股票 → 申万一级名）
# 数据来源：sw_index_first_info() 列 31 个申万一级；index_component_sw(symbol) 取成分股。
# ⚠️ akshare 1.18.97 无 stock_industry_category（上游 :8000 报 500），故绕开它，
#    改用上述两个真实存在的函数自建映射，落 base_stock_sw_industry（双缓存：进程内存 + 库表）。
# ============================================================
SW_MAP_TTL_DAYS = 30
_SW_MAP: dict[str, str] = {}
_SW_MAP_AT: datetime | None = None
_SW_MAP_LOCK = threading.Lock()


def _build_sw_industry_map(db) -> None:
    """遍历申万一级，调 index_component_sw 拼全市场『股票 → 申万一级』映射，落库。"""
    try:
        first = akshare_request("sw_index_first_info", {}, timeout=30, retries=2)
    except Exception as e:  # noqa: BLE001
        print(f"[ExtraMetrics] sw_index_first_info 失败: {e}")
        return
    if not isinstance(first, list) or not first:
        return
    levels: list[tuple[str, str]] = []  # (申万一级6位代码, 行业名)
    for row in first:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("行业代码") or row.get("index_code") or row.get("code") or "")
        name = str(row.get("行业名称") or row.get("index_name") or row.get("name") or "")
        m = re.match(r"(\d{6})", raw)
        if m and name:
            levels.append((m.group(1), name))
    if not levels:
        return
    now = _now_cst().replace(tzinfo=None)
    pairs: list[tuple[str, str]] = []
    for sw_code, name in levels:
        try:
            comp = akshare_request("index_component_sw", {"symbol": sw_code}, timeout=30, retries=2)
        except Exception as e:  # noqa: BLE001
            print(f"[ExtraMetrics] index_component_sw {sw_code} 失败: {e}")
            continue
        if isinstance(comp, list):
            for c in comp:
                if not isinstance(c, dict):
                    continue
                sc = str(c.get("证券代码") or c.get("stock_code") or c.get("代码") or "").strip()
                if sc:
                    pairs.append((sc, name))
        time.sleep(0.2)  # 节流，避免打爆上游
    if not pairs:
        return
    try:
        for sc, nm in pairs:
            db.execute("DELETE FROM base_stock_sw_industry WHERE stock_code = ?", [sc])
            db.execute(
                "INSERT INTO base_stock_sw_industry (stock_code, industry, fetched_at) VALUES (?, ?, ?)",
                [sc, nm, now],
            )
        _SW_MAP.clear()
        for sc, nm in pairs:
            _SW_MAP[sc] = nm
        global _SW_MAP_AT
        _SW_MAP_AT = now
    except Exception as e:  # noqa: BLE001
        print(f"[ExtraMetrics] 申万行业映射落库失败: {e}")


def _ensure_sw_map(db) -> None:
    """确保 _SW_MAP 已建（进程内存缓存，30 天 TTL）。表里有则直接载入，否则重建。"""
    global _SW_MAP_AT
    with _SW_MAP_LOCK:
        if _SW_MAP and _SW_MAP_AT is not None:
            if _now_cst().replace(tzinfo=None) - _SW_MAP_AT < timedelta(days=SW_MAP_TTL_DAYS):
                return
        # 先尝试从本地表载入（容器重启后免打网络）
        try:
            rows = db.fetchall("SELECT stock_code, industry FROM base_stock_sw_industry")
            if rows:
                _SW_MAP.clear()
                for sc, ind in rows:
                    if sc and ind:
                        _SW_MAP[str(sc)] = str(ind)
                if _SW_MAP:
                    _SW_MAP_AT = _now_cst().replace(tzinfo=None)
                    return
        except Exception:  # noqa: BLE001
            pass
        # 表空 → 重建（打 31 次上游，带节流）
        _build_sw_industry_map(db)


def _stock_industry(db, stock_code: str) -> str | None:
    """股票 → 申万一级行业（进程内存映射 + 本地表双缓存，绕开上游坏方法）。"""
    _ensure_sw_map(db)
    return _SW_MAP.get(stock_code)


def _compute_sector(db, code: str) -> tuple[float | None, int | None]:
    """行业集中度：Top3 行业占净值比(%) + 行业数。无持仓返 (None, None)。"""
    try:
        rows = db.fetchall(
            "SELECT stock_code, pct FROM base_fund_stock_holdings "
            "WHERE fund_code = ? AND stock_code <> ? AND quarter = ("
            "  SELECT MAX(quarter) FROM base_fund_stock_holdings "
            "  WHERE fund_code = ? AND stock_code <> ?)",
            [code, "__NO_REPORT__", code, "__NO_REPORT__"],
        )
        if not rows:
            return None, None
        by_ind: dict[str, float] = {}
        for stock_code, pct in rows:
            ind = _stock_industry(db, str(stock_code))
            if not ind:
                continue
            by_ind[ind] = by_ind.get(ind, 0.0) + (float(pct or 0) or 0.0)
        if not by_ind:
            return None, None
        total = sum(by_ind.values())
        if total <= 0:
            return None, None
        top3 = sum(sorted(by_ind.values(), reverse=True)[:3])
        return round(top3 / total * 100, 1), len(by_ind)
    except Exception as e:  # noqa: BLE001
        print(f"[ExtraMetrics] {code} 行业集中度异常: {e}")
        return None, None


def compute_one(db, code: str, index_code: str | None) -> dict:
    """算一只基金的三项指标，返回待落库记录（子计算全防御，本函数绝不抛）。"""
    te, te_n = _safe(_compute_tracking_error, code, index_code, default=(None, None))
    pf = _safe(_compute_payout_freq, code, default=0)
    top3, cnt = _safe(_compute_sector, db, code, default=(None, None))
    return {
        "code": code,
        "tracking_error": te,
        "tracking_error_n": te_n,
        "payout_freq": pf,
        "sector_top3": top3,
        "sector_count": cnt,
    }


# ============================================================
# 读写库
# ============================================================

def _upsert(db, rec: dict) -> None:
    db.execute("DELETE FROM fund_extra_metrics WHERE code = ?", [rec["code"]])
    db.execute(
        """
        INSERT INTO fund_extra_metrics
            (code, tracking_error, tracking_error_n, tracking_error_at,
             payout_freq, payout_freq_at, sector_top3, sector_count, sector_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            rec["code"],
            rec.get("tracking_error"),
            rec.get("tracking_error_n"),
            _now_cst(),
            rec.get("payout_freq"),
            _now_cst(),
            rec.get("sector_top3"),
            rec.get("sector_count"),
            _now_cst(),
            _now_cst(),
        ],
    )


def get_map(codes: list[str]) -> dict[str, dict]:
    """批量读取已落库的三项指标。库不可用时退化为 {}（页面显示 —）。"""
    if not codes:
        return {}
    try:
        db = _db()
        _ensure_table(db)
    except Exception as e:  # pragma: no cover
        print(f"[ExtraMetrics] 获取 DB 失败: {e}")
        return {}
    out: dict[str, dict] = {}
    for i in range(0, len(codes), 400):
        chunk = codes[i : i + 400]
        marks = ",".join("?" for _ in chunk)
        sql = (
            "SELECT code, tracking_error, tracking_error_n, payout_freq, sector_top3, sector_count "
            f"FROM fund_extra_metrics WHERE code IN ({marks})"
        )
        try:
            rows = db.fetchall(sql, list(chunk))
        except Exception as e:  # pragma: no cover
            print(f"[ExtraMetrics] 查询失败: {e}")
            continue
        for r in rows:
            out[str(r[0])] = {
                "tracking_error": r[1],
                "tracking_error_n": r[2],
                "payout_freq": r[3],
                "sector_top3": r[4],
                "sector_count": r[5],
            }
    return out


def missing_codes(codes: list[str]) -> list[str]:
    """返回「库里没有」或「已过期（> EXTRA_TTL_DAYS）」的基金代码。

    三项指标用**各自独立的时间戳**判断：只要有一项缺失/过期就视为缺口（重算时三项一起补）。
    计算成功的基金会把三项时间戳全部写齐（值可为 None），因此每只基金只在 TTL 内被补一次。
    """
    if not codes:
        return []
    have: dict[str, tuple] = {}
    try:
        db = _db()
        _ensure_table(db)
        for i in range(0, len(codes), 400):
            chunk = codes[i : i + 400]
            marks = ",".join("?" for _ in chunk)
            rows = db.fetchall(
                f"SELECT code, tracking_error_at, payout_freq_at, sector_at, sector_top3 "
                f"FROM fund_extra_metrics WHERE code IN ({marks})",
                list(chunk),
            )
            for r in rows:
                have[str(r[0])] = (r[1], r[2], r[3], r[4])
    except Exception as e:  # pragma: no cover
        print(f"[ExtraMetrics] 缺口计算失败: {e}")
        return list(codes)

    deadline = _now_cst().replace(tzinfo=None) - timedelta(days=EXTRA_TTL_DAYS)
    # 行业列曾因上游 stock_industry_category 500 而留空的历史遗留：给一次重算宽限（>1 天）
    sector_grace = timedelta(days=1)
    out = []
    for c in codes:
        if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE:
            continue
        t = have.get(c)
        if not t:
            out.append(c)
            continue
        te_at, pf_at, sec_at, sec_val = t
        fresh = (
            _naive(te_at) is not None and _naive(te_at) >= deadline
            and _naive(pf_at) is not None and _naive(pf_at) >= deadline
            and _naive(sec_at) is not None and _naive(sec_at) >= deadline
        )
        if not fresh:
            out.append(c)
            continue
        # 三项时间戳都新鲜，但行业显式为空（旧 500 遗留）→ 宽限后重补，让新数据源填真实值
        if sec_val is None and _naive(sec_at) is not None and (
            _now_cst().replace(tzinfo=None) - _naive(sec_at) >= sector_grace
        ):
            out.append(c)
    return out


def snapshot(codes: list[str] | None = None) -> dict:
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
    idx = min(max(_THROTTLE_STREAK, 1), len(BACKOFF_LADDER_HOURS)) - 1
    return BACKOFF_LADDER_HOURS[idx]


def last_finish_ts() -> float:
    return _LAST_FINISH_TS


def due_for_retry(now: float | None = None) -> bool:
    if _THROTTLE_STREAK <= 0 or _LAST_FINISH_TS <= 0:
        return False
    return (now or time.time()) - _LAST_FINISH_TS >= next_retry_in_hours() * 3600


def _progress_locked() -> dict:
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
    """当前补全进度快照（供轮询）。⚠️ 锁超时 1s，绝不无限等 _FILL_LOCK（防 HTTP=000）。"""
    if not _FILL_LOCK.acquire(timeout=1):
        return _progress_locked()
    try:
        return _progress_locked()
    finally:
        _FILL_LOCK.release()


def _run(codes: list[str], delay: float) -> None:
    global _LAST_FINISH_TS, _THROTTLE_STREAK
    try:
        db = _db()
        _ensure_table(db)
        _ensure_sw_map(db)  # 启动即构建申万一级映射（进程内存缓存，仅首轮/过期打网络）
    except Exception as e:  # pragma: no cover
        with _FILL_LOCK:
            _FILL["running"] = False
            _FILL["last_error"] = f"DB 不可用: {e}"
            _FILL["finished_at"] = _now_cst().strftime("%Y-%m-%d %H:%M:%S")
        return

    from services.fund_index_map_service import get_map_from_db

    index_map = get_map_from_db()

    consec_fail = 0
    throttled = False
    for code in codes:
        try:
            rec = compute_one(db, code, index_map.get(code))
        except Exception as e:  # noqa: BLE001
            rec = None
            print(f"[ExtraMetrics] {code} 计算异常: {e}")

        if rec:
            try:
                _upsert(db, rec)
                _FAIL_COUNTS.pop(code, None)
                consec_fail = 0
                with _FILL_LOCK:
                    _FILL["ok"] += 1
            except Exception as e:  # noqa: BLE001
                print(f"[ExtraMetrics] {code} 写入失败: {e}")
                with _FILL_LOCK:
                    _FILL["fail"] += 1
                    _FILL["last_error"] = str(e)[:200]
        else:
            _FAIL_COUNTS[code] = _FAIL_COUNTS.get(code, 0) + 1
            consec_fail += 1
            with _FILL_LOCK:
                _FILL["fail"] += 1
                _FILL["last_error"] = f"{code} 计算失败"
            if consec_fail >= MAX_CONSEC_FAIL:
                throttled = True
                with _FILL_LOCK:
                    _FILL["last_error"] = f"连续 {consec_fail} 只失败，疑似上游限流，本轮中止，稍后自动继续"
                break
            time.sleep(3.0)

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
            f"[ExtraMetrics] 本轮疑似被限流中止（连续中止 {_THROTTLE_STREAK} 次），"
            f"{next_retry_in_hours()} 小时后由定时任务续跑"
        )


def start_fill(
    codes: list[str],
    limit: int = DEFAULT_BATCH,
    delay: float = DEFAULT_DELAY,
    auto: bool = False,
) -> dict:
    """启动一轮后台补全（非阻塞）。已在跑则直接返回当前进度。"""
    if auto and time.time() - _LAST_FINISH_TS < AUTO_COOLDOWN:
        return progress()
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
    """后台补全目标代码全集：红利名录 + 现金流场内 ETF。"""
    global _LAST_CODES
    if _LAST_CODES:
        return list(_LAST_CODES)
    try:
        from services.dividend_service import get_backend_fund_codes

        codes = get_backend_fund_codes()
        if codes:
            _LAST_CODES = codes
    except Exception as e:  # pragma: no cover
        print(f"[ExtraMetrics] 代码全集构建失败: {e}")
    return list(_LAST_CODES)


def attach_extra_metrics(funds: dict[str, list[dict]]) -> tuple[list[str], dict]:
    """把已落库的三项指标写回基金条目，返回 (全部代码, 进度)。同时顺手触发后台补全。"""
    global _LAST_CODES
    codes: list[str] = []
    for rows in funds.values():
        for r in rows:
            codes.append(str(r.get("code")))
    if codes:
        _seen = set(_LAST_CODES)
        _LAST_CODES = list(_LAST_CODES) + [c for c in codes if c not in _seen]
    if not codes:
        return [], progress()

    m = get_map(codes)
    for rows in funds.values():
        for r in rows:
            rec = m.get(str(r.get("code")))
            if not rec:
                continue
            r["tracking_error"] = rec.get("tracking_error")
            r["tracking_error_n"] = rec.get("tracking_error_n")
            r["payout_freq"] = rec.get("payout_freq")
            r["sector_concentration"] = rec.get("sector_top3")
            r["sector_count"] = rec.get("sector_count")

    prog = progress()
    if prog["running"] or (_THROTTLE_STREAK > 0 and not due_for_retry()):
        return codes, prog
    if missing_codes(codes):
        start_fill(codes, auto=True)
        prog = progress()
    return codes, prog
