"""指数 PB/PE 历史自建源（替代已失效的 legulegu 接口）。

思路：通过远程网关聚合宽基指数成分股的总市值 / 市净率 / 市盈率(TTM)，
按市值加权还原指数 PB / PE 的月度历史：
    指数PB(t) = Σ mv_i(t) / Σ (mv_i(t) / PB_i(t))
    指数PE(t) = Σ mv_i(t) / Σ (mv_i(t) / PE_i(t))

数据源（全部走远程 AkShare WebAPI 网关，不本地依赖 akshare）：
- index_stock_cons_csindex  → 指数成分股列表（csindex 官方，稳定）
- stock_zh_valuation_baidu  → 个股市净率 / 总市值 / 市盈率(TTM) 全历史（1991→今）

输出与原始 legulegu 接口同构，便于 valuation_service 直接复用：
- PB 行：{"date": "YYYY-MM-DD", "pb": float, "index_value": float|None}
- PE 行：{"date": "YYYY-MM-DD", "pe_ttm": float, "pe_static": float, "index_value": float|None}

缓存：
- 个股历史缓存在 {CACHE_DIR}/stocks/{code}.json（避免重复打网关/上游）
- 指数聚合结果缓存在 {CACHE_DIR}/index_pbpe_{code}.json（API 直接读，毫秒级）
CACHE_DIR 默认 /data/valuation_cache（doraemon_backend 持久卷）。
"""

from __future__ import annotations

import os
import json
import time
import calendar
from datetime import datetime

from services.akshare_client import akshare_request

CACHE_DIR = os.environ.get("VALUATION_CACHE_DIR", "/data/valuation_cache")
STOCK_CACHE_DIR = os.path.join(CACHE_DIR, "stocks")
os.makedirs(STOCK_CACHE_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# 参与回填的宽基指数（csindex 代码）。与 valuation_service.BROAD_INDEX_LIST 保持一致。
BACKFILL_CODES = [
    "000016", "000300", "000009", "399673", "000905",
    "000010", "399324", "399330", "000852", "000015",
    "000903", "000906",
]

# 聚合稳定所需的成分股最小覆盖比例
_MIN_COVERAGE_RATIO = 0.5
_MIN_COVERAGE_ABS = 60
# 历史起点（与原始 legulegu 2005 起对齐）
_HISTORY_START = "2005-01"

# 指数行情日线（用于 index_value 展示，best-effort）
_INDEX_DAILY_PREFIX = lambda code: "sz" if code.startswith("399") else "sh"


def _code_cache_path(code: str) -> str:
    return os.path.join(STOCK_CACHE_DIR, f"{code}.json")


def _index_cache_path(code: str) -> str:
    return os.path.join(CACHE_DIR, f"index_pbpe_{code}.json")


# ---------------------------------------------------------------------------
# 网关取数
# ---------------------------------------------------------------------------

def get_constituents(csindex_code: str) -> list[str]:
    """取指数成分股代码列表（去重，6 位补零）。"""
    rows = akshare_request("index_stock_cons_csindex", {"symbol": csindex_code}, retries=2, timeout=20)
    if not rows:
        return []
    codes: list[str] = []
    seen = set()
    for r in rows:
        c = r.get("成分券代码") or r.get("code") or r.get("成分券代码 ".strip())
        if not c:
            continue
        c = str(c).strip().zfill(6)
        if c and c not in seen:
            seen.add(c)
            codes.append(c)
    return codes


def _fetch_stock_series(code: str, indicator: str, max_age_days: int = 7) -> dict:
    """取个股估值历史 {date: value}，优先用本地缓存。"""
    path = _code_cache_path(code)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            series = cache.get(indicator)
            ts = cache.get("_ts", 0)
            if series is not None and (time.time() - ts) < max_age_days * 86400:
                return series
        except Exception:
            pass

    rows = akshare_request(
        "stock_zh_valuation_baidu",
        {"symbol": code, "indicator": indicator, "period": "全部"},
        retries=2, timeout=20,
    )
    series: dict = {}
    if rows:
        for r in rows:
            d = r.get("date")
            v = r.get("value")
            if d is None or v is None:
                continue
            try:
                series[str(d)] = float(v)
            except (TypeError, ValueError):
                pass

    # 合并写回本地缓存（保留其它 indicator）
    cache: dict = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}
    cache[indicator] = series
    cache["_ts"] = time.time()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass
    return series


def _fetch_index_level(csindex_code: str) -> dict:
    """取指数日线收盘价（用于 index_value 展示），失败返回空。"""
    try:
        rows = akshare_request(
            "stock_zh_index_daily",
            {"symbol": _INDEX_DAILY_PREFIX(csindex_code) + csindex_code},
            retries=2, timeout=20,
        )
        if not rows:
            return {}
        out = {}
        for r in rows:
            d = r.get("日期") or r.get("date")
            c = r.get("收盘") or r.get("close") or r.get("指数")
            if d is None or c is None:
                continue
            try:
                out[str(d)] = float(c)
            except (TypeError, ValueError):
                pass
        return out
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 月度重采样 + 聚合
# ---------------------------------------------------------------------------

def _resample_month_end(series: dict) -> dict:
    """取每个自然月的最后一个可用交易日的值 -> {YYYY-MM: value}。"""
    by_month: dict = {}
    for d, v in series.items():
        ym = str(d)[:7]
        if ym not in by_month or str(d) > by_month[ym][0]:
            by_month[ym] = (str(d), v)
    return {ym: v for ym, (_, v) in by_month.items()}


def _month_end_date(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    last = calendar.monthrange(y, m)[1]
    return f"{ym}-{last:02d}"


def aggregate_index(csindex_code: str) -> tuple[list, list]:
    """计算单指数 PB / PE 月度历史，返回 (pb_rows, pe_rows)。"""
    constituents = get_constituents(csindex_code)
    if not constituents:
        return [], []

    mv_me, pb_me, pe_me = {}, {}, {}
    for i, code in enumerate(constituents):
        mv_me[code] = _resample_month_end(_fetch_stock_series(code, "总市值"))
        pb_me[code] = _resample_month_end(_fetch_stock_series(code, "市净率"))
        pe_me[code] = _resample_month_end(_fetch_stock_series(code, "市盈率(TTM)"))
        if (i + 1) % 25 == 0:
            time.sleep(0.15)  # 轻量节流，避免上游/网关限流

    level_me = _resample_month_end(_fetch_index_level(csindex_code))

    months = set()
    for m in (mv_me, pb_me, pe_me):
        for mm in m.values():
            months.update(mm.keys())
    months = sorted(x for x in months if x >= _HISTORY_START)

    threshold = max(_MIN_COVERAGE_ABS, int(_MIN_COVERAGE_RATIO * len(constituents)))

    pb_rows: list = []
    pe_rows: list = []
    for ym in months:
        mv_sum = 0.0
        pb_w = 0.0
        pe_w = 0.0
        cnt = 0
        last_day = ""
        for code in constituents:
            mv = mv_me[code].get(ym)
            pb = pb_me[code].get(ym)
            pe = pe_me[code].get(ym)
            if mv is None or pb is None or pe is None or pb <= 0 or pe <= 0:
                continue
            mv_sum += mv
            pb_w += mv / pb
            pe_w += mv / pe
            cnt += 1
            if ym in mv_me[code] and mv_me[code][ym] is not None:
                pass
        if cnt < threshold or pb_w <= 0 or pe_w <= 0:
            continue
        idx_pb = mv_sum / pb_w
        idx_pe = mv_sum / pe_w
        md = _month_end_date(ym)
        lvl = level_me.get(ym)
        pb_rows.append({"date": md, "pb": round(idx_pb, 4), "index_value": lvl})
        pe_rows.append({"date": md, "pe_ttm": round(idx_pe, 2), "pe_static": round(idx_pe, 2), "index_value": lvl})

    return pb_rows, pe_rows


# ---------------------------------------------------------------------------
# 缓存读写
# ---------------------------------------------------------------------------

def compute_index_pb_pe(csindex_code: str, max_age_days: int = 1) -> tuple[list, list]:
    """读聚合缓存；缺失或过期则重算（重算走网关，较慢，由 backfill 预先跑好）。"""
    path = _index_cache_path(csindex_code)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                rec = json.load(f)
            if (time.time() - rec.get("_ts", 0)) < max_age_days * 86400:
                return rec.get("pb", []), rec.get("pe", [])
        except Exception:
            pass
    pb_rows, pe_rows = aggregate_index(csindex_code)
    if not pb_rows:
        return [], []
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"_ts": time.time(), "pb": pb_rows, "pe": pe_rows}, f)
    except Exception:
        pass
    return pb_rows, pe_rows


def get_index_pb_pe(csindex_code: str) -> tuple[list, list]:
    """对外主入口：返回 (pb_rows, pe_rows)。优先缓存。

    缓存有效期设为 30 天：正常请求路径绝不触发在线重算（重算走网关很慢），
    由独立的回填任务（akshare-backend 内原生计算）定期刷新 /data/valuation_cache。
    """
    return compute_index_pb_pe(csindex_code, max_age_days=30)


def backfill_all(codes: list[str] | None = None) -> dict:
    codes = codes or BACKFILL_CODES
    summary = {}
    for code in codes:
        t0 = time.time()
        pb, pe = compute_index_pb_pe(code, max_age_days=0)  # 强制重算
        summary[code] = {"months": len(pb), "elapsed_s": round(time.time() - t0, 1)}
        print(f"[backfill] {code}: {len(pb)} months, {round(time.time()-t0,1)}s")
    return summary


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "backfill"
    if arg == "backfill":
        codes = sys.argv[2].split(",") if len(sys.argv) > 2 else None
        print(json.dumps(backfill_all(codes), ensure_ascii=False, indent=2))
    elif arg == "one":
        code = sys.argv[2]
        pb, pe = compute_index_pb_pe(code, max_age_days=0)
        print(f"{code}: pb_months={len(pb)} pe_months={len(pe)}")
        print("latest pb:", pb[-1] if pb else None)
        print("latest pe:", pe[-1] if pe else None)
