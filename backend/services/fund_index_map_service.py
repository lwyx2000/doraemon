"""红利基金 → 红利指数的**文本反查**识别（业绩比较基准 / 基金全称）。

背景：原匹配只按基金简称里的别名（如「国企红利」）做区域隔离匹配，301/591 只
基金识别不出来，因为基金简称的口径和指数官方全称口径不一致
（例：510720「红利国泰」的业绩比较基准是「上证国有企业红利指数收益率」，
而指数简称表写的是「国企红利」）。

数据源（全部真实、无 mock）：
1. 同花顺 ``fund_info_ths``（经 aksharewebapi ``/api/ak`` 代理）返回的
   ``业绩比较基准`` 与 ``基金全称`` —— 指数基金必填，是最准的口径；
   结果同时已被 ``fund_fee_service`` 落在 ``base_fund_fee_info.benchmark``，
   **已抓过的基金可以离线识别，不再重复请求**。
2. 只在库里没有基准文本时才逐只请求同花顺，并沿用其限流策略
   （间隔 ``DEFAULT_DELAY`` 秒、连续失败 ``MAX_CONSEC_FAIL`` 只即中止）。

识别结果落 ``base_fund_index_map``，供 ``dividend_service`` 回填到基金名录的
``index_code`` / ``index_name``，从而提升「指数映射率」。
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import requests

from database.connection import get_db
from database.bulk import bulk_insert
from services import fund_fee_service, index_compilation_service
from services.akshare_client import akshare_request
from services.akshare_client import get_session

CST = timezone(timedelta(hours=8))

#: 同花顺请求间隔（秒）
DEFAULT_DELAY = 1.2
#: 本地 / 天天基金 F10 请求间隔（秒，F10 也限流，别抽太猛）
LOCAL_DELAY = 1.1
#: 连续失败上限，超过即中止本轮（避免把上游限流拖成死循环）
MAX_CONSEC_FAIL = 5
#: 取值失败后的退避（小时）
BACKOFF_HOURS = [2, 4, 8]
#: 已确认匹配不上的基金代码（多轮都拿不到 26 个红利指数里的跟踪标的，通常是
#: 跟踪了标普/恒生/中证智选这类**池外**指数的产品）。不再每晚重复请求，
#: 免得定时任务空烧；超过 DEAD_MAX 整体清空，给数据源变化留个口子。
DEAD_MAX = 600
_dead_codes: set[str] = set()


def mark_dead(code: str) -> None:
    """把一只「多轮都没匹配上」的基金移出候选池。"""
    _dead_codes.add(str(code))
    if len(_dead_codes) > DEAD_MAX:
        _dead_codes.clear()


DDL = """
CREATE TABLE IF NOT EXISTS base_fund_index_map (
    fund_code   VARCHAR PRIMARY KEY,
    index_code  VARCHAR,
    index_name  VARCHAR,
    source      VARCHAR,
    matched_at  TIMESTAMP
)
"""

#: 识别不上的基金，把它的「跟踪标的 / 业绩比较基准」原文存这里，
#: 页面据此说明「该基金跟踪的是 XXX 指数（不在当前 26 个红利指数池内）」。
DDL_TRACKING = """
CREATE TABLE IF NOT EXISTS base_fund_tracking_text (
    fund_code     VARCHAR PRIMARY KEY,
    tracking_text VARCHAR,
    source        VARCHAR,
    checked_at    TIMESTAMP
)
"""

_VENDOR_FAIL_AT: float | None = None
_throttle_streak = 0
_next_retry_at: float = 0.0

_map_loaded = False


def _now_cst() -> datetime:
    return datetime.now(CST)


def _next_retry_in_hours() -> float:
    return BACKOFF_HOURS[min(_throttle_streak, len(BACKOFF_HOURS) - 1)]


def due_for_retry() -> bool:
    if _throttle_streak == 0:
        return True
    return time.time() >= _next_retry_at


# ============================================================
# 文本 → 指数
# ============================================================

def _region_of(text: str) -> str:
    """从文本（基金全称 / 业绩比较基准）判定所属区域：A / HK / SHS。"""
    if "沪港深" in text:
        return "SHS"
    if any(k in text for k in ("港股", "恒生", "香港")):
        return "HK"
    return "A"


def match_from_text(text: str | None) -> tuple[str | None, str | None]:
    """把「业绩比较基准 / 基金全称」文本反查到红利指数。

    规范化后做**最长别名子串匹配**，且要求区域一致；区域判不出来时
    （文本无港股关键词）只允许匹配 A 股指数，避免港股产品被错配。
    """
    if not text:
        return None, None
    norm = index_compilation_service._norm(text)
    if len(norm) < 6:
        return None, None
    region = _region_of(text)
    best: tuple[int, str | None, str | None] = (0, None, None)
    for alias, code, name, idx_region in _vocabulary():
        if len(alias) > best[0] and alias in norm and idx_region == region:
            best = (len(alias), code, name)
    if best[0]:
        return best[1], best[2]

    # 文本里带港股/沪港深关键词却没匹配上（常见：基准写「恒生……」而指数简称不同）
    if region != "A":
        for alias, code, name, idx_region in _vocabulary():
            if len(alias) > best[0] and alias in norm:
                best = (len(alias), code, name)
    return best[1], best[2]


_vocab_cache: list[tuple[str, str, str, str]] | None = None


def _vocabulary() -> list[tuple[str, str, str, str]]:
    global _vocab_cache
    if _vocab_cache is None:
        try:
            _vocab_cache = index_compilation_service.build_vocabulary()
        except Exception as e:  # noqa: BLE001
            print(f"[FundIdxMap] 别名词表构建失败（忽略）: {e}")
            _vocab_cache = []
    return _vocab_cache


# ============================================================
# 库读写
# ============================================================

def _ensure_table() -> None:
    db = get_db()
    db.execute(DDL)
    try:
        db.execute(DDL_TRACKING)
    except Exception:  # noqa: BLE001
        pass


def get_map_from_db() -> dict[str, tuple[str, str]]:
    """全量读取已识别映射（code -> (index_code, index_name)）。"""
    global _map_loaded
    try:
        _ensure_table()
        rows = get_db().fetchall("SELECT fund_code, index_code, index_name FROM base_fund_index_map")
    except Exception as e:  # noqa: BLE001
        print(f"[FundIdxMap] 映射读库失败（忽略）: {e}")
        return {}
    _map_loaded = True
    out = {}
    for code, idx_code, idx_name in rows:
        out[str(code)] = (str(idx_code), str(idx_name) if idx_name else None)
    return out


def _save(code: str, idx_code: str, idx_name: str | None, source: str) -> None:
    try:
        _ensure_table()
        db = get_db()
        db.execute("DELETE FROM base_fund_index_map WHERE fund_code = ?", [code])
        # 字面量单行 VALUES：参数化 execute ~13.5ms/次（~50ms/基金，P2，
        # 见 docs/性能病理排查报告-2026-10-14.md）；TIMESTAMP 列传 naive CST
        # （墙上时间），与原参数化 aware 路径落库值一致（2026-10-14 实测）。
        bulk_insert(
            db,
            "INSERT INTO base_fund_index_map (fund_code, index_code, index_name, source, matched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [[code, idx_code, idx_name, source, _now_cst().replace(tzinfo=None)]],
        )
    except Exception as e:  # noqa: BLE001
        print(f"[FundIdxMap] {code} 映射落库失败（忽略）: {e}")


def _benchmarks_in_db(codes: list[str]) -> dict[str, str]:
    """从 fund_fee_service 的落库表读已有基准文本（离线识别用）。"""
    if not codes:
        return {}
    try:
        db = get_db()
        out: dict[str, str] = {}
        for i in range(0, len(codes), 300):
            chunk = codes[i: i + 300]
            marks = ",".join("?" for _ in chunk)
            for row in db.fetchall(
                f"SELECT code, benchmark FROM base_fund_fee_info WHERE code IN ({marks})",
                chunk,
            ):
                if row[1]:
                    out[str(row[0])] = str(row[1])
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[FundIdxMap] 基准文本读库失败（忽略）: {e}")
        return {}


def _save_tracking(code: str, text: str, source: str) -> None:
    """存下识别不上的基金其「跟踪标的」原文（页面用来解释为什么留空）。"""
    if not text:
        return
    try:
        _ensure_table()
        get_db().execute(
            "DELETE FROM base_fund_tracking_text WHERE fund_code = ?", [code]
        )
        get_db().execute(
            "INSERT INTO base_fund_tracking_text (fund_code, tracking_text, source, checked_at) "
            "VALUES (?, ?, ?, ?)",
            [code, text[:200], source, _now_cst()],
        )
    except Exception:  # noqa: BLE001
        pass


def attach_tracking_texts(funds: dict[str, list[dict]]) -> int:
    """把「跟踪标的」原文回填到尚未识别的基金上（供前端说明留空原因）。

    纯读库，不新增任何请求；库不可用时静默返回 0。
    """
    if not funds:
        return 0
    codes = [str(f.get("code")) for rows in funds.values() for f in rows if not f.get("index_code")]
    if not codes:
        return 0
    out: dict[str, str] = {}
    try:
        _ensure_table()
        db = get_db()
        for i in range(0, len(codes), 300):
            chunk = codes[i: i + 300]
            marks = ",".join("?" for _ in chunk)
            for row in db.fetchall(
                f"SELECT fund_code, tracking_text FROM base_fund_tracking_text "
                f"WHERE fund_code IN ({marks})",
                chunk,
            ):
                if row[1]:
                    out[str(row[0])] = str(row[1])
    except Exception:  # noqa: BLE001
        return 0
    if not out:
        return 0
    filled = 0
    for rows in funds.values():
        for f in rows:
            if f.get("index_code") or f.get("tracking_text"):
                continue
            t = out.get(str(f.get("code")))
            if not t:
                continue
            f["tracking_text"] = t
            filled += 1
    if filled:
        print(f"[FundIdxMap] 池外跟踪标的说明回填 {filled} 只红利基金")
    return filled


def augment_funds(funds: dict[str, list[dict]]) -> int:
    """把库里已识别的映射回填进基金名录（仅补 ``index_code`` 为空的）。

    返回本次补上的条数。库不可用时静默返回 0，页面照常显示 —。
    """
    if not funds:
        return 0
    _map = get_map_from_db()
    if not _map:
        return 0
    filled = 0
    for rows in funds.values():
        for f in rows:
            if f.get("index_code"):
                continue
            hit = _map.get(str(f.get("code")))
            if not hit or not hit[0]:
                continue
            f["index_code"] = hit[0]
            f["index_name"] = hit[1]
            filled += 1
    if filled:
        print(f"[FundIdxMap] 库内映射回填 {filled} 只红利基金")
    return filled


# ============================================================
# 后台渐进补全
# ============================================================

def pending_codes(all_codes: list[str], limit: int | None = None) -> list[str]:
    """待识别的基金代码，**已落库基准的排前面（离线识别，零请求）**。

    - 离线：``base_fund_fee_info.benchmark`` 已有 → 直接文本反查，不发请求；
    - 在线：库里没基准 → 需要逐只请求同花顺（慢，且会限流）。
    """
    _map = get_map_from_db()
    have_bench = _benchmarks_in_db(all_codes)
    offline: list[str] = []
    online: list[str] = []
    for c in all_codes:
        if str(c) in _map:
            continue
        (offline if str(c) in have_bench else online).append(str(c))
    out = offline + online
    return out[:limit] if limit else out


def _em_text(code: str, label: str) -> str | None:
    """从天天基金 F10「基金概况」页取单个字段文本。

    F10 同时给出 ``跟踪标的``（最准，直接是指数全称，如「上证国有企业红利指数」）
    和 ``业绩比较基准``（指数名 + 收益率），且限流比同花顺宽松，优先用。
    """
    try:
        r = get_session().get(
            f"https://fundf10.eastmoney.com/jbgk_{code}.html",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124"},
            timeout=15,
        )
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200:
        return None
    try:
        html = r.text
        i = html.find(label)
        if i < 0:
            return None
        seg = html[i:i + 400]
        seg = seg.split("</div>")[0]
        txt = re.sub(r"<[^>]+>", " ", seg)
        txt = re.sub(r"\s+", " ", txt).strip(" :：")
        # 「该基金无跟踪标的」这类占位值不算有效信号
        if not txt or txt.startswith("该基金无") or len(txt) > 120:
            return None
        return txt
    except Exception:  # noqa: BLE001
        return None


def _kv_from_em(code: str) -> dict[str, str]:
    """天天基金 F10：一次性取 ``跟踪标的`` 与 ``业绩比较基准``。"""
    return {
        "tracking": _em_text(code, "跟踪标的"),
        "benchmark": _em_text(code, "业绩比较基准"),
    }


def _kv_from_ths(code: str) -> dict[str, str]:
    """拉同花顺基金信息，返回 {字段: 值} 字典（只取需要的两个字段，失败返回 {}）。"""
    try:
        raw = akshare_request("fund_info_ths", {"symbol": str(code)}, timeout=25, retries=2)
    except Exception:  # noqa: BLE001
        return {}
    kv: dict[str, str] = {}
    if isinstance(raw, list):
        for r in raw:
            if isinstance(r, dict):
                k = r.get("字段") or r.get("item")
                v = r.get("值") or r.get("value")
                if k and v:
                    kv[str(k)] = str(v)
    return kv


def identify_one(code: str) -> tuple[str | None, str | None, str]:
    """识别单只基金，返回 (index_code, index_name, source)。

    四级信号，逐级兜底（命中即停）：
    1. ``base_fund_fee_info.benchmark``（已落库 → 零请求）
    2. 天天基金 F10 ``跟踪标的`` / ``业绩比较基准``（限流宽松，最通用）
    3. 同花顺 ``业绩比较基准`` / ``基金全称``（兜底，易限流）
    4. 都拿不到 → 返回 None，等下一轮
    """
    # 各源文本全部收集并逐级兜底：库里那个旧基准若没命中，绝不能当成终点，
    # 后面还有天天基金 F10 / 同花顺可以用（原来「有基准就不再拉 F10」堵死了
    # 一整批基金，如 159581「红利ETF万家」其实跟踪的是中证红利指数）。
    pairs: list[tuple[str, str]] = []  # (文本, 来源)

    try:
        rows = get_db().fetchall(
            "SELECT benchmark FROM base_fund_fee_info WHERE code = ?", [str(code)],
        )
        if rows and rows[0][0]:
            pairs.append((str(rows[0][0]), "benchmark"))
    except Exception:  # noqa: BLE001
        pass

    em = _kv_from_em(str(code)) or {}
    if em.get("tracking"):
        pairs.append((em["tracking"], "em_tracking"))
    if em.get("benchmark"):
        pairs.append((em["benchmark"], "em_benchmark"))

    kv = _kv_from_ths(code) or {}
    if kv.get("业绩比较基准"):
        pairs.append((kv["业绩比较基准"], "benchmark"))
    if kv.get("基金全称"):
        pairs.append((kv["基金全称"], "full_name"))

    seen: set[str] = set()
    for text, source in pairs:
        if text in seen:
            continue
        seen.add(text)
        idx_code, idx_name = match_from_text(text)
        if idx_code:
            _save(str(code), idx_code, idx_name, source)
            return idx_code, idx_name, source
    # 全都没命中：把「跟踪标的 / 基准」原文留下，供页面说明「它其实跟踪了 XXX 指数，
    # 只是不在我们 26 个红利指数池里」，而不是干瘪一个 —
    if pairs:
        _save_tracking(str(code), pairs[0][0], pairs[0][1])
    return None, None, (pairs[0][1] if pairs else "none")


def _offline_candidates(all_codes: list[str], limit: int | None = None) -> list[str]:
    """退避期仍可处理的队列。

    一级源（库里已落库的 ``benchmark``）和二级源（天天基金 F10）都不消耗
    同花顺配额，所以退避期内照样能把未识别的基金往前推；只有完全走不通的
    才会退到同花顺去撞限流。
    """
    try:
        _map = get_map_from_db()
        have = _benchmarks_in_db(all_codes)
    except Exception:  # noqa: BLE001
        return []
    local: list[str] = []
    rest: list[str] = []
    for c in all_codes:
        if str(c) in _map or str(c) in _dead_codes:
            continue
        (local if str(c) in have else rest).append(str(c))
    out = local + rest
    return out[:limit] if limit else out


def map_batch(all_codes: list[str], limit: int = 50) -> dict:
    """本轮识别（默认 50 只）。

    退避期内不空转：优先消化「库里已有基准」的**离线队列**（不发任何请求，
    不会触碰同花顺限流）。只有离线队列也空了，才按退避时间返回。
    """
    global _throttle_streak, _next_retry_at

    # 优先级：本地 / 天天基金 F10 队列（不消耗同花顺配额）先抽干，
    # 抽完且退避到期了才轮到同花顺。
    codes = _offline_candidates(all_codes, limit) if limit else _offline_candidates(all_codes)
    local_mode = bool(codes)
    if local_mode:
        # 本地队列没跑完前把退避往前推，避免本轮又被同花顺限流打断
        _next_retry_at = time.time() + 0.5 * 3600
    else:
        if not due_for_retry():
            return progress(0)
        codes = pending_codes(all_codes, limit) if limit else [
            c for c in all_codes if str(c) not in get_map_from_db()
        ]
        if not codes:
            return progress(0)

    # 退避阈值分档：本地/天天基金源不撞限流，宽松；同花顺仍严格
    consec_limit = 25 if local_mode else MAX_CONSEC_FAIL
    print(f"[FundIdxMap] 本轮 {len(codes)} 只（{'本地/EM 源' if local_mode else '同花顺源'}）")

    done = matched = 0
    for code in codes:
        try:
            idx_code, idx_name, source = identify_one(code)
        except Exception as e:  # noqa: BLE001
            print(f"[FundIdxMap] {code} 识别异常: {e}")
            _throttle_streak += 1
            continue

        if idx_code:
            matched += 1
            _throttle_streak = 0
        else:
            if local_mode:
                # 本地/天天基金源没匹配上 = 这只基金跟踪的是池外指数，拉黑不再重试
                mark_dead(str(code))
            else:
                # 同花顺源：只触发网络限流退避，不做拉黑
                _throttle_streak += 1
                if _throttle_streak >= consec_limit:
                    _next_retry_at = time.time() + _next_retry_in_hours() * 3600
                    print(f"[FundIdxMap] 连续失败，{_next_retry_in_hours()} 小时后再试")
                    break
        done += 1
        time.sleep(LOCAL_DELAY if local_mode else DEFAULT_DELAY)

    return progress(done)


def progress(done_this_round: int = 0) -> dict:
    """识别进度 / 退避状态（供前端展示）。"""
    _map = get_map_from_db()
    total = len(_map)
    throttled = _throttle_streak > 0
    retry_hours = _next_retry_in_hours() if throttled else 0
    return {
        "ok": True,
        "matched": total,
        "this_round": done_this_round,
        "throttled": throttled,
        "retry_in_hours": retry_hours,
    }
