"""长期视角数据服务——爬取「老钱日日谈 A股看板」5 组数据并落 DuckDB。

背景（用户 2026-10-14 决策）：
    老钱日日谈 A股看板（https://ashare.laoqianriritan.com）是纯静态站，
    页面数据全部来自同域 data/*.json。其中 5 组对 doraemon「长期视角」页
    有参考价值，且本地无等价长历史（base_sw_sector_daily 等只到近月），
    故按用户批准「没有数据支持的从那个网站爬数据，到时注明来源」落地。

本模块职责：
    1. 每周六 17:30（CronTrigger，见 jobs/longterm_job.py）抓取 5 源并落库
    2. 首次部署后手动 POST /api/v1/longterm/collect 立即全量落库
    3. 提供 5 个查询函数 + snapshot_stats 供路由层消费

数据源与表（一一对应）：
    sw_returns.json        申万行业年度涨跌幅热力图   → base_lqr_sw_returns + base_lqr_sw_metrics
    return_decomp.json     指数收益三因子拆解         → base_lqr_return_decomp
    trend_temperature.json 市场趋势温度（双序列）     → base_lqr_trend_temp
    wide_base.json         9 宽基指数全收益净值       → base_lqr_wide_base
    panel_huazheng.json    华证六因子净值             → base_lqr_huazheng
    各源抓取状态（上游时间/我方抓取时间/行数）        → base_lqr_source_meta

口径与边界：
    - 只搬运不加工：所有数值按上游原样落库；页面须注明
      「数据来源：老钱日日谈 A股看板（ashare.laoqianriritan.com），抓取于 {fetchedAt}」
    - 增量策略：日/月频序列（trend_temp / wide_base / huazheng）按 MAX(obs_date)
      只插新行，可重复执行；小表（sw_returns / sw_metrics / return_decomp）
      每次采集全量替换（DELETE + INSERT）
    - 上游停更不清库：页面展示最近一次成功抓取的快照，fetchedAt 即抓取时间
    - 礼貌抓取：UA 带标识、源间 sleep 1s、单源失败不影响其余源
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from database.bulk import bulk_insert

_CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------- 常量
_BASE_URL = "https://ashare.laoqianriritan.com/data"

_SOURCES: dict[str, str] = {
    "sw_returns": f"{_BASE_URL}/sw_returns.json",
    "return_decomp": f"{_BASE_URL}/return_decomp.json",
    "trend_temperature": f"{_BASE_URL}/trend_temperature.json",
    "wide_base": f"{_BASE_URL}/wide_base.json",
    "huazheng": f"{_BASE_URL}/panel_huazheng.json",
}

# 礼貌 UA：浏览器串 + 服务标识 + 来源站（爬取对方公开静态数据，可被溯源）
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
    "doraemon-longterm/1.0 (+https://ashare.laoqianriritan.com)"
)

# sw_returns 表内行类型：年度收益 vs 年内至今（YTD）
_KIND_YEAR = "year"
_KIND_YTD = "ytd"

# trend_temperature 两个序列
_SERIES_STOCK = "stock_ma250"
_SERIES_INDUSTRY = "industry_macd"

_TABLE_READY = False

_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS base_lqr_sw_returns (
        industry_name   VARCHAR,
        industry_code   VARCHAR,
        kind            VARCHAR,
        year            INTEGER,
        ret_pct         DOUBLE,
        fetched_at      TIMESTAMP,
        PRIMARY KEY (industry_name, kind, year)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS base_lqr_sw_metrics (
        industry_name   VARCHAR,
        industry_code   VARCHAR,
        cagr_full       DOUBLE,
        cagr_7y         DOUBLE,
        cagr_5y         DOUBLE,
        cagr_3y         DOUBLE,
        fetched_at      TIMESTAMP,
        PRIMARY KEY (industry_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS base_lqr_return_decomp (
        index_code      VARCHAR,
        index_name      VARCHAR,
        start_date      VARCHAR,
        end_date        VARCHAR,
        total_return_pct DOUBLE,
        dividend_pct    DOUBLE,
        earnings_pct    DOUBLE,
        valuation_pct   DOUBLE,
        pe_start        DOUBLE,
        pe_end          DOUBLE,
        fetched_at      TIMESTAMP,
        PRIMARY KEY (index_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS base_lqr_trend_temp (
        series_type     VARCHAR,
        obs_date        VARCHAR,
        total_cnt       INTEGER,
        pos_cnt         INTEGER,
        pct             DOUBLE,
        fetched_at      TIMESTAMP,
        PRIMARY KEY (series_type, obs_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS base_lqr_wide_base (
        index_code      VARCHAR,
        index_name      VARCHAR,
        note            VARCHAR,
        obs_date        VARCHAR,
        value           DOUBLE,
        fetched_at      TIMESTAMP,
        PRIMARY KEY (index_code, obs_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS base_lqr_huazheng (
        factor_name     VARCHAR,
        obs_date        VARCHAR,
        value           DOUBLE,
        fetched_at      TIMESTAMP,
        PRIMARY KEY (factor_name, obs_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS base_lqr_source_meta (
        source          VARCHAR,
        upstream_updated VARCHAR,
        fetched_at      TIMESTAMP,
        rows_cnt        INTEGER,
        ok              BOOLEAN,
        error           VARCHAR,
        PRIMARY KEY (source)
    )
    """,
]


# ---------------------------------------------------------------- 基础工具
def _ensure_tables() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    try:
        from database.connection import get_db

        db = get_db()
        for ddl in _DDL:
            db.execute(ddl)
        _TABLE_READY = True
    except Exception as e:
        print(f"[LongTerm] 建表失败: {type(e).__name__}: {e}")


def _now_str() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- 抓取
def _fetch_json(source: str, retries: int = 2) -> tuple[Optional[dict], Optional[str]]:
    """GET 单个 data/*.json，返回 (payload, error)。重试 retries 次后放弃。"""
    import requests

    url = _SOURCES[source]
    last_err: Optional[str] = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
                timeout=(10, 120),
            )
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
            else:
                data = resp.json()
                if isinstance(data, dict):
                    return data, None
                last_err = "响应不是 JSON 对象"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(2.0 * (attempt + 1))
    return None, last_err


# ---------------------------------------------------------------- 落库（ingest）
def _ingest_sw_returns(payload: dict, fetched_at: str) -> int:
    """申万行业年度涨跌幅 + CAGR 指标（两表，全量替换）。"""
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    years = payload.get("years") or []
    data = payload.get("data") or {}
    ytd_year = _to_int(payload.get("ytd_year"))

    db.execute("DELETE FROM base_lqr_sw_returns")
    rows: list[list] = []
    for name, info in data.items():
        code = str(info.get("code") or "")
        rets = info.get("rets") or []
        for i, y in enumerate(years):
            if i >= len(rets):
                break
            fv = _to_float(rets[i])
            if fv is not None:
                rows.append([name, code, _KIND_YEAR, int(y), fv, fetched_at])
        if ytd_year is not None:
            fv = _to_float(info.get(f"ytd{ytd_year}"))
            if fv is not None:
                rows.append([name, code, _KIND_YTD, ytd_year, fv, fetched_at])
    if rows:
        bulk_insert(
            db,
            "INSERT INTO base_lqr_sw_returns "
            "(industry_name, industry_code, kind, year, ret_pct, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            rows,
        )

    db.execute("DELETE FROM base_lqr_sw_metrics")
    mrows: list[list] = []
    for name, info in data.items():
        m = info.get("metrics") or {}
        mrows.append([
            name,
            str(info.get("code") or ""),
            _to_float(m.get("cagr_full")),
            _to_float(m.get("cagr_7y")),
            _to_float(m.get("cagr_5y")),
            _to_float(m.get("cagr_3y")),
            fetched_at,
        ])
    if mrows:
        bulk_insert(
            db,
            "INSERT INTO base_lqr_sw_metrics "
            "(industry_name, industry_code, cagr_full, cagr_7y, cagr_5y, cagr_3y, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            mrows,
        )
    return len(rows) + len(mrows)


def _ingest_return_decomp(payload: dict, fetched_at: str) -> int:
    """指数收益三因子拆解（全量替换）。"""
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    db.execute("DELETE FROM base_lqr_return_decomp")
    rows: list[list] = []
    for idx in payload.get("indexes") or []:
        if not isinstance(idx, dict):
            continue
        rows.append([
            str(idx.get("code") or ""),
            str(idx.get("name") or ""),
            str(idx.get("start") or ""),
            str(idx.get("end") or ""),
            _to_float(idx.get("totalReturnPct")),
            _to_float(idx.get("dividendPct")),
            _to_float(idx.get("earningsPct")),
            _to_float(idx.get("valuationPct")),
            _to_float(idx.get("peStart")),
            _to_float(idx.get("peEnd")),
            fetched_at,
        ])
    if rows:
        bulk_insert(
            db,
            "INSERT INTO base_lqr_return_decomp "
            "(index_code, index_name, start_date, end_date, total_return_pct, "
            "dividend_pct, earnings_pct, valuation_pct, pe_start, pe_end, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            rows,
        )
    return len(rows)


def _ingest_trend_temp(payload: dict, fetched_at: str) -> int:
    """趋势温度双序列（按 MAX(obs_date) 增量）。

    obs_date 存 VARCHAR：日频为 YYYY-MM-DD、月频为 YYYY-MM，字符串字典序即时间序。
    两个 series_type 各自独立取 max，互不干扰。
    """
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    total = 0
    specs = (
        (_SERIES_STOCK, "stock_ma250", "above_ma250", "pct_above"),
        (_SERIES_INDUSTRY, "industry_macd", "positive_count", "pct_positive"),
    )
    for series_type, key, pos_key, pct_key in specs:
        items = payload.get(key) or []
        if not items:
            continue
        row = db.fetchone(
            "SELECT max(obs_date) FROM base_lqr_trend_temp WHERE series_type = ?",
            [series_type],
        )
        max_date = str(row[0]) if row and row[0] else ""
        rows: list[list] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            d = str(it.get("date") or "")
            if not d or d <= max_date:
                continue
            pct = _to_float(it.get(pct_key))
            if pct is None:
                pct = _to_float(it.get("pct"))
            rows.append([
                series_type,
                d,
                _to_int(it.get("total")),
                _to_int(it.get(pos_key)),
                pct,
                fetched_at,
            ])
        if rows:
            bulk_insert(
                db,
                "INSERT INTO base_lqr_trend_temp "
                "(series_type, obs_date, total_cnt, pos_cnt, pct, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                rows,
            )
            total += len(rows)
    return total


def _ingest_wide_base(payload: dict, fetched_at: str) -> int:
    """9 宽基指数全收益净值（按指数分别取 MAX(obs_date) 增量）。"""
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    total = 0
    for code, s in (payload.get("series") or {}).items():
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "")
        note = str(s.get("note") or "")
        dates = s.get("dates") or []
        values = s.get("values") or []
        row = db.fetchone(
            "SELECT max(obs_date) FROM base_lqr_wide_base WHERE index_code = ?",
            [code],
        )
        max_date = str(row[0]) if row and row[0] else ""
        rows: list[list] = []
        for d, v in zip(dates, values):
            ds = str(d)
            if ds <= max_date:
                continue
            fv = _to_float(v)
            if fv is None:
                continue
            rows.append([code, name, note, ds, fv, fetched_at])
        if rows:
            bulk_insert(
                db,
                "INSERT INTO base_lqr_wide_base "
                "(index_code, index_name, note, obs_date, value, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                rows,
            )
            total += len(rows)
    return total


def _ingest_huazheng(payload: dict, fetched_at: str) -> int:
    """华证六因子净值（按因子分别取 MAX(obs_date) 增量）。"""
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    total = 0
    for fname, f in (payload.get("factors") or {}).items():
        if not isinstance(f, dict):
            continue
        dates = f.get("dates") or []
        nav = f.get("nav") or []
        row = db.fetchone(
            "SELECT max(obs_date) FROM base_lqr_huazheng WHERE factor_name = ?",
            [fname],
        )
        max_date = str(row[0]) if row and row[0] else ""
        rows: list[list] = []
        for d, v in zip(dates, nav):
            ds = str(d)
            if ds <= max_date:
                continue
            fv = _to_float(v)
            if fv is None:
                continue
            rows.append([fname, ds, fv, fetched_at])
        if rows:
            bulk_insert(
                db,
                "INSERT INTO base_lqr_huazheng "
                "(factor_name, obs_date, value, fetched_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                rows,
            )
            total += len(rows)
    return total


_INGESTORS: dict[str, Callable[[dict, str], int]] = {
    "sw_returns": _ingest_sw_returns,
    "return_decomp": _ingest_return_decomp,
    "trend_temperature": _ingest_trend_temp,
    "wide_base": _ingest_wide_base,
    "huazheng": _ingest_huazheng,
}


# ---------------------------------------------------------------- 源 meta
def _upsert_source_meta(
    source: str, upstream: str, fetched_at: str, rows_cnt: int, ok: bool, error: str
) -> None:
    from database.connection import get_db

    db = get_db()
    db.execute(
        "INSERT INTO base_lqr_source_meta "
        "(source, upstream_updated, fetched_at, rows_cnt, ok, error) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (source) DO UPDATE SET "
        "upstream_updated = excluded.upstream_updated, fetched_at = excluded.fetched_at, "
        "rows_cnt = excluded.rows_cnt, ok = excluded.ok, error = excluded.error",
        [source, upstream or "", fetched_at, int(rows_cnt), bool(ok), error or ""],
    )


def _get_source_meta(source: str) -> dict:
    """单源抓取状态（供查询函数附带回源信息）。"""
    try:
        from database.connection import get_db

        db = get_db()
        row = db.fetchone(
            "SELECT upstream_updated, fetched_at, rows_cnt, ok, error "
            "FROM base_lqr_source_meta WHERE source = ?",
            [source],
        )
    except Exception:
        row = None
    if not row:
        return {"fetchedAt": None, "upstreamUpdated": None, "rows": 0, "ok": False, "error": None}
    return {
        "fetchedAt": str(row[1]) if row[1] else None,
        "upstreamUpdated": str(row[0]) if row[0] else None,
        "rows": int(row[2]) if row[2] is not None else 0,
        "ok": bool(row[3]),
        "error": str(row[4]) if row[4] else None,
    }


# 各源对应的落库表（meta rows_cnt 记这些表的存量总行数）
_SOURCE_TABLES: dict[str, list[str]] = {
    "sw_returns": ["base_lqr_sw_returns", "base_lqr_sw_metrics"],
    "return_decomp": ["base_lqr_return_decomp"],
    "trend_temperature": ["base_lqr_trend_temp"],
    "wide_base": ["base_lqr_wide_base"],
    "huazheng": ["base_lqr_huazheng"],
}


def _source_row_count(source: str) -> int:
    """该源落库后的表内总行数。

    meta rows_cnt 语义为「存量」而非「本次增量」：周任务无新数据时增量恒 0，
    记增量会让页面来源标注误导（显示 0 行）；本次新增数另在 collect 响应里返回。
    """
    try:
        from database.connection import get_db

        db = get_db()
        total = 0
        for table in _SOURCE_TABLES.get(source, []):
            row = db.fetchone(f"SELECT count(*) FROM {table}")
            total += int(row[0]) if row else 0
        return total
    except Exception:
        return 0


# ---------------------------------------------------------------- 对外主流程
def collect_all(progress_cb: Optional[Callable[[str, dict], None]] = None) -> dict:
    """采集全部 5 源并落库（幂等；定时任务每周六 17:30 与手动 POST 均走此函数）。

    单源失败不影响其余源；返回每源 ok/rows/upstreamUpdated/error。
    """
    _ensure_tables()
    fetched_at = _now_str()
    results: dict[str, dict] = {}
    for source, ingestor in _INGESTORS.items():
        payload, err = _fetch_json(source)
        if err:
            results[source] = {"ok": False, "error": err, "fetchedAt": fetched_at}
            _upsert_source_meta(source, "", fetched_at, 0, False, err)
        else:
            try:
                n = ingestor(payload, fetched_at)
                upstream = str(payload.get("generated") or payload.get("updated") or "")
                _upsert_source_meta(source, upstream, fetched_at, _source_row_count(source), True, "")
                results[source] = {
                    "ok": True,
                    "rows": n,
                    "upstreamUpdated": upstream,
                    "fetchedAt": fetched_at,
                }
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
                results[source] = {"ok": False, "error": err, "fetchedAt": fetched_at}
                _upsert_source_meta(source, "", fetched_at, 0, False, err)
        if progress_cb:
            try:
                progress_cb(source, results[source])
            except Exception:
                pass
        time.sleep(1.0)  # 源间礼貌间隔
    ok_count = sum(1 for r in results.values() if r.get("ok"))
    return {
        "ok": ok_count == len(results),
        "okCount": ok_count,
        "totalCount": len(results),
        "fetchedAt": fetched_at,
        "sources": results,
    }


# ---------------------------------------------------------------- 查询
def get_sw_returns() -> dict:
    """申万行业年度涨跌幅（热力图）：years + industries[{name,code,rets,ytd,ytdYear,metrics}]。"""
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    meta = _get_source_meta("sw_returns")
    rows = db.fetchall(
        "SELECT industry_name, industry_code, kind, year, ret_pct "
        "FROM base_lqr_sw_returns ORDER BY industry_name, year"
    )
    if not rows:
        return {**meta, "years": [], "industries": []}
    yearly: dict[str, dict[int, Optional[float]]] = {}
    ytd: dict[str, tuple[Optional[float], Optional[int]]] = {}
    codes: dict[str, str] = {}
    years_set: set[int] = set()
    for name, code, kind, year, ret in rows:
        codes[name] = code
        if kind == _KIND_YEAR:
            yearly.setdefault(name, {})[int(year)] = _to_float(ret)
            years_set.add(int(year))
        else:
            ytd[name] = (_to_float(ret), _to_int(year))
    years = sorted(years_set)
    mrows = db.fetchall(
        "SELECT industry_name, cagr_full, cagr_7y, cagr_5y, cagr_3y FROM base_lqr_sw_metrics"
    )
    metrics = {
        r[0]: {
            "cagrFull": _to_float(r[1]),
            "cagr7y": _to_float(r[2]),
            "cagr5y": _to_float(r[3]),
            "cagr3y": _to_float(r[4]),
        }
        for r in mrows
    }
    industries = []
    for name in sorted(set(yearly.keys()) | set(ytd.keys())):
        yv, yy = ytd.get(name, (None, None))
        industries.append({
            "name": name,
            "code": codes.get(name, ""),
            "rets": [yearly.get(name, {}).get(y) for y in years],
            "ytd": yv,
            "ytdYear": yy,
            "metrics": metrics.get(name),
        })
    return {**meta, "years": years, "industries": industries}


def get_return_decomp() -> dict:
    """指数收益三因子拆解：indexes[{code,name,start,end,totalReturnPct,dividendPct,earningsPct,valuationPct,peStart,peEnd}]。"""
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    meta = _get_source_meta("return_decomp")
    rows = db.fetchall(
        "SELECT index_code, index_name, start_date, end_date, total_return_pct, "
        "dividend_pct, earnings_pct, valuation_pct, pe_start, pe_end "
        "FROM base_lqr_return_decomp ORDER BY index_code"
    )
    indexes = [
        {
            "code": r[0],
            "name": r[1],
            "start": r[2],
            "end": r[3],
            "totalReturnPct": _to_float(r[4]),
            "dividendPct": _to_float(r[5]),
            "earningsPct": _to_float(r[6]),
            "valuationPct": _to_float(r[7]),
            "peStart": _to_float(r[8]),
            "peEnd": _to_float(r[9]),
        }
        for r in rows
    ]
    return {**meta, "indexes": indexes}


def get_trend_temperature() -> dict:
    """市场趋势温度：stockMa250（日频）+ industryMacd（月频）双序列。"""
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    meta = _get_source_meta("trend_temperature")
    stock = db.fetchall(
        "SELECT obs_date, total_cnt, pos_cnt, pct FROM base_lqr_trend_temp "
        "WHERE series_type = ? ORDER BY obs_date",
        [_SERIES_STOCK],
    )
    industry = db.fetchall(
        "SELECT obs_date, total_cnt, pos_cnt, pct FROM base_lqr_trend_temp "
        "WHERE series_type = ? ORDER BY obs_date",
        [_SERIES_INDUSTRY],
    )
    return {
        **meta,
        "stockMa250": [
            {
                "date": str(r[0]),
                "total": _to_int(r[1]),
                "aboveMa250": _to_int(r[2]),
                "pctAbove": _to_float(r[3]),
            }
            for r in stock
        ],
        "industryMacd": [
            {
                "date": str(r[0]),
                "total": _to_int(r[1]),
                "positiveCount": _to_int(r[2]),
                "pctPositive": _to_float(r[3]),
            }
            for r in industry
        ],
    }


def get_wide_base(days: int = 0) -> dict:
    """宽基指数全收益净值：series[{name,note,dates,values}]（days>0 时每指数截取最近 N 个点）。"""
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    meta = _get_source_meta("wide_base")
    codes = db.fetchall(
        "SELECT DISTINCT index_code, index_name, note FROM base_lqr_wide_base ORDER BY index_code"
    )
    if not codes:
        return {**meta, "series": {}}
    limit = _to_int(days) or 0
    series: dict[str, dict] = {}
    for code, name, note in codes:
        if limit > 0:
            rows = db.fetchall(
                "SELECT obs_date, value FROM base_lqr_wide_base "
                "WHERE index_code = ? ORDER BY obs_date DESC LIMIT ?",
                [code, limit],
            )
            pairs = [(str(r[0]), _to_float(r[1])) for r in rows]
            pairs.reverse()
        else:
            rows = db.fetchall(
                "SELECT obs_date, value FROM base_lqr_wide_base "
                "WHERE index_code = ? ORDER BY obs_date",
                [code],
            )
            pairs = [(str(r[0]), _to_float(r[1])) for r in rows]
        series[code] = {
            "name": name or code,
            "note": note or "",
            "dates": [d for d, _ in pairs],
            "values": [v for _, v in pairs],
        }
    return {**meta, "series": series}


def get_huazheng(days: int = 0) -> dict:
    """华证六因子净值：factors[{name,dates,values}]（days>0 时每因子截取最近 N 个点）。"""
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    meta = _get_source_meta("huazheng")
    names = db.fetchall(
        "SELECT DISTINCT factor_name FROM base_lqr_huazheng ORDER BY factor_name"
    )
    if not names:
        return {**meta, "factors": {}}
    limit = _to_int(days) or 0
    factors: dict[str, dict] = {}
    for (fname,) in names:
        if limit > 0:
            rows = db.fetchall(
                "SELECT obs_date, value FROM base_lqr_huazheng "
                "WHERE factor_name = ? ORDER BY obs_date DESC LIMIT ?",
                [fname, limit],
            )
            pairs = [(str(r[0]), _to_float(r[1])) for r in rows]
            pairs.reverse()
        else:
            rows = db.fetchall(
                "SELECT obs_date, value FROM base_lqr_huazheng "
                "WHERE factor_name = ? ORDER BY obs_date",
                [fname],
            )
            pairs = [(str(r[0]), _to_float(r[1])) for r in rows]
        factors[fname] = {
            "name": fname,
            "dates": [d for d, _ in pairs],
            "values": [v for _, v in pairs],
        }
    return {**meta, "factors": factors}


def snapshot_stats() -> dict:
    """各表行数 + 各源抓取状态（供 /status 端点与运维排查）。"""
    _ensure_tables()
    from database.connection import get_db

    db = get_db()
    tables = {
        "swReturns": "base_lqr_sw_returns",
        "swMetrics": "base_lqr_sw_metrics",
        "returnDecomp": "base_lqr_return_decomp",
        "trendTemp": "base_lqr_trend_temp",
        "wideBase": "base_lqr_wide_base",
        "huazheng": "base_lqr_huazheng",
    }
    stats: dict[str, Any] = {}
    for key, table in tables.items():
        try:
            row = db.fetchone(f"SELECT count(*) FROM {table}")
            stats[key] = int(row[0]) if row else 0
        except Exception:
            stats[key] = 0
    stats["sources"] = {s: _get_source_meta(s) for s in _SOURCES}
    return stats
