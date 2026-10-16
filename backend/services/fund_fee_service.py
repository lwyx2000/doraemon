"""红利基金「规模 / 费率」后台渐进补全服务。

背景：规模/费率这类字段没有一个源能稳定全量供给，且**同花顺** ``fund_info_ths``
会限流（实测 80 只里 34 只 500）。因此采用「**三源互备 + 后台渐进补全**」：

- 数据源：同花顺 ``fund_info_ths``（现接源，易限流）/ 东方财富 F10 概况页（容器内直连
  CDN，已验证可用）/ 集思录 ETF 列表（经 akshareWebApi 的 jisilu 路由，需 53 侧配 cookie）。
- 互备调度：维护一个有序 source 队列，**成功源移到队首、失败源移到队尾并冷却**，限流源长冷却；
  每次取费按队列顺序尝试，哪个不行自动换下一个，不再卡死。队列顺序持久化在与 DuckDB 同目录的
  JSON 里（容器内即 /data 卷），重启后仍记得「上次谁好用」。
- 渐进补全：每次访问红利页时若仍有缺口就顺手补一批（默认 40 只），结果落 DuckDB 持久化，
  30 天后才重新拉取。页面打开几次后即可填满。

落库表 ``base_fund_fee_info``（IF NOT EXISTS，按需建表，旧库可平滑升级）。
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from services.akshare_client import akshare_request

from database.bulk import bulk_insert

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
    redemption_fee DOUBLE,
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

#: progress() 锁超时分支返回的「上一次快照」（持锁构建，避免无锁读 _FILL 撕裂）
_LAST_PROGRESS: dict | None = None

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
    # ⚠️ 迁移兼容：``redemption_fee`` 是后期迭代新增的列，而 ``base_fund_fee_info``
    # 表可能早已存在（红利费率补全更早创建、当时无此列）。``CREATE TABLE IF NOT EXISTS``
    # 对已有表不会补列，导致 ``_upsert`` / ``get_fee_map`` 都报
    # ``does not have a column with name "redemption_fee"`` → 费率全部写不进、读不出。
    # 这里显式 ALTER 补列；列已存在（或首建表已含该列）时 ALTER 抛错，忽略即可。
    try:
        db.execute(
            "ALTER TABLE base_fund_fee_info ADD COLUMN redemption_fee DOUBLE"
        )
    except Exception:
        pass


def _to_float(s) -> float | None:
    """'0.50%' -> 0.5 ；'1.20' -> 1.2"""
    if s is None:
        return None
    m = _NUM_RE.search(str(s))
    return float(m.group()) if m else None


def _norm_date(s) -> str | None:
    """'2026年06月30日' / '2026-06-30' / '截止至：2026-06-30' → '2026-06-30'。"""
    if not s:
        return None
    m = re.search(r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})", str(s))
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


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
        "redemption_fee": _to_float(kv.get("最高赎回费")),
        "manager": kv.get("基金经理", "") or None,
        "invest_type": kv.get("投资类型", "") or None,
        "benchmark": kv.get("业绩比较基准", "") or None,
    }


# ============================================================
# 多数据源互备（同花顺 / 东方财富 / 集思录）
# ============================================================
# 用户要求：三源互备，哪个不行就换一个；最后一次成功的放队首，失败的丢队尾。
# 队列顺序进程内维护 + 落盘 JSON 持久化（与 DuckDB 同目录，容器内即 /data 卷），
# 重启后仍能记住「上次谁好用」，避免每轮从头试错。
SOURCE_ORDER_DEFAULT = ["ths", "eastmoney", "jisilu"]
_SOURCE_ORDER: list[str] = list(SOURCE_ORDER_DEFAULT)
_SOURCE_COOLDOWN: dict[str, float] = {}      # src -> 冷却到期 unix 秒（到期前不试）
_SOURCE_STATUS: dict[str, str] = {}          # src -> ok / fail / throttled / no_data / unknown
_SRC_LOCK = threading.Lock()

#: 单源失败后的冷却（秒）：普通错误 10min，疑似限流 1h（别反复撞墙）
SRC_FAIL_COOLDOWN = 600
SRC_THROTTLE_COOLDOWN = 3600
_THROTTLE_TOKENS = (
    "429", "403", "500", "502", "503", "504", "timeout", "timed out",
    "too many", "限流", "频繁", "remote disconnected", "connectionerror",
    "connection error", "connecterror", "read timeout", "请求过于频繁",
)

#: 集思录 ETF 列表进程内缓存（避免每只都拉全量列表）
_JISILU_ETF_CACHE: dict = {"data": None, "ts": 0.0, "ttl": 3600}


def _source_state_path() -> Path:
    try:
        from core.config import DB_PATH

        return Path(DB_PATH).parent / "fund_fee_sources.json"
    except Exception:  # noqa: BLE001
        return Path("fund_fee_sources.json")


def _load_source_state() -> None:
    global _SOURCE_ORDER, _SOURCE_COOLDOWN
    try:
        p = _source_state_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            order = data.get("order")
            if isinstance(order, list) and set(order) == set(SOURCE_ORDER_DEFAULT):
                _SOURCE_ORDER = list(order)
            cd = data.get("cooldown") or {}
            _SOURCE_COOLDOWN = {
                k: float(v) for k, v in cd.items() if k in SOURCE_ORDER_DEFAULT
            }
            print(f"[FundFee] 已恢复数据源队列: {_SOURCE_ORDER}")
    except Exception as e:  # noqa: BLE001
        print(f"[FundFee] 数据源队列恢复失败（用默认序）: {e}")


def _save_source_state() -> None:
    try:
        p = _source_state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {"order": _SOURCE_ORDER, "cooldown": _SOURCE_COOLDOWN},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        print(f"[FundFee] 数据源队列持久化失败: {e}")


def _move_to_front(src: str) -> None:
    global _SOURCE_ORDER
    _SOURCE_ORDER = [src] + [s for s in _SOURCE_ORDER if s != src]


def _move_to_back(src: str) -> None:
    global _SOURCE_ORDER
    _SOURCE_ORDER = [s for s in _SOURCE_ORDER if s != src] + [src]


def _any_source_available() -> bool:
    now = time.time()
    with _SRC_LOCK:
        return any(_SOURCE_COOLDOWN.get(s, 0.0) <= now for s in _SOURCE_ORDER)


def _mark_source_ok(src: str) -> None:
    with _SRC_LOCK:
        moved = _SOURCE_ORDER[0] != src
        had_cd = src in _SOURCE_COOLDOWN
        if had_cd:
            _SOURCE_COOLDOWN.pop(src, None)
        _SOURCE_STATUS[src] = "ok"
        if moved:
            _move_to_front(src)
    # 仅当顺序变化或清除了冷却才落盘，避免每成功一只都写 JSON
    if moved or had_cd:
        _save_source_state()


def _mark_source_failed(src: str, exc: Exception | None, throttled: bool | None = None) -> None:
    if throttled is None and exc is not None:
        throttled = any(tok in str(exc).lower() for tok in _THROTTLE_TOKENS)
    cooldown = SRC_THROTTLE_COOLDOWN if throttled else SRC_FAIL_COOLDOWN
    with _SRC_LOCK:
        _SOURCE_COOLDOWN[src] = time.time() + cooldown
        _SOURCE_STATUS[src] = "throttled" if throttled else "fail"
        _move_to_back(src)
    print(
        f"[FundFee] 数据源 {src} 失败（{'限流' if throttled else '错误'}，"
        f"冷却 {cooldown}s），移到队尾"
    )
    _save_source_state()


def _mark_source_no_data(src: str) -> None:
    # 源可达但本 code 无覆盖：不降级，仅记状态
    with _SRC_LOCK:
        _SOURCE_STATUS[src] = "no_data"


def _norm_code(code: str) -> str:
    digits = re.sub(r"\D", "", str(code))
    return digits[-6:] if len(digits) >= 6 else digits


def _pick(row: dict, *keys: str, default=None):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return default


def _safe_float(value, default=None):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# ---------------- 各源抓取器（返回标准 rec 或 None；异常由调度器捕获） ----------------

def _extract_ths(code: str) -> dict | None:
    """同花顺 fund_info_ths（现接源，易限流）。"""
    raw = akshare_request("fund_info_ths", {"symbol": code}, timeout=25, retries=2)
    rec = _parse_fee_rows(raw)
    if not rec or not rec.get("code"):
        return None
    rec["code"] = code
    return rec


def _extract_eastmoney(code: str) -> dict | None:
    """东方财富 F10 基金概况页（容器内直连 CDN，已验证可用）。

    取 份额规模/资产规模、管理费、托管费、最高申购费、业绩比较基准。
    """
    url = f"https://fundf10.eastmoney.com/jbgk_{code}.html"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://fundf10.eastmoney.com/jbgk_{code}.html",
    }
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"eastmoney HTTP {r.status_code}")
    text = re.sub(r"<[^>]+>", " ", r.text)
    text = re.sub(r"\s+", " ", text)
    rec = {
        "code": code, "name": None, "scale": None, "scale_date": None,
        "mgmt_fee": None, "custody_fee": None, "subscribe_fee": None,
        "redemption_fee": None,
        "manager": None, "invest_type": None, "benchmark": None,
    }
    m = re.search(
        r"份额规模\D*?([\d.]+)\s*亿份(?:\s*[（(](?:截止至[:：]\s*)?([\d年-]+月\d+日|\d{4}-\d{2}-\d{2})[)）])?",
        text,
    )
    if not m:
        m = re.search(
            r"资产规模\D*?([\d.]+)\s*亿元(?:\s*[（(](?:截止至[:：]\s*)?([\d年-]+月\d+日|\d{4}-\d{2}-\d{2})[)）])?",
            text,
        )
    if m:
        rec["scale"] = float(m.group(1))
        rec["scale_date"] = _norm_date(m.group(2))
    m = re.search(r"管理费率\D*?([\d.]+)\s*%", text)
    if m:
        rec["mgmt_fee"] = float(m.group(1))
    m = re.search(r"托管费率\D*?([\d.]+)\s*%", text)
    if m:
        rec["custody_fee"] = float(m.group(1))
    m = re.search(r"最高申购费率\D*?([\d.]+)\s*%", text)
    if m:
        rec["subscribe_fee"] = float(m.group(1))
    m = re.search(r"最高赎回费率\D*?([\d.]+)\s*%", text)
    if m:
        rec["redemption_fee"] = float(m.group(1))
    m = re.search(r"业绩比较基准\D*?(.+?)(?:\s+跟踪标的|\s+风险收益特征|\s+基金全称|$)", text)
    if m:
        rec["benchmark"] = m.group(1).strip()[:200]
    m = re.search(r"基金简称\D*?([^\s].*?)(?:\s+基金代码|\s+基金类型|$)", text)
    if m:
        rec["name"] = m.group(1).strip()[:60]
    # 至少要拿到规模或某一费率才算有效，否则视为该源无覆盖
    if rec["scale"] is None and rec["mgmt_fee"] is None and rec["custody_fee"] is None:
        return None
    return rec


def _extract_jisilu(code: str) -> dict | None:
    """集思录 ETF 列表（经 akshareWebApi 的 jisilu 路由；需 53 侧配 cookie）。

    任意失败（未部署/无 cookie/超时）一律抛异常 → 调度器将其丢队尾冷却。
    该 code 不在列表中 → 返回 None（软跳过，不降级）。
    """
    from services.fund_service import _processed_data_request

    now = time.time()
    if (
        _JISILU_ETF_CACHE["data"] is None
        or now - _JISILU_ETF_CACHE["ts"] > _JISILU_ETF_CACHE["ttl"]
    ):
        raw = _processed_data_request("jisilu", {"subtype": "etf"}, retries=1)
        if raw is None:
            raise RuntimeError("jisilu etf 列表不可用")
        _JISILU_ETF_CACHE["data"] = raw
        _JISILU_ETF_CACHE["ts"] = now
    data = _JISILU_ETF_CACHE["data"]
    if not isinstance(data, list):
        raise RuntimeError("jisilu etf 列表格式异常")
    code6 = _norm_code(code)
    for it in data:
        if not isinstance(it, dict):
            continue
        c = _norm_code(_pick(it, "fund_id", "代码", "基金代码", "code"))
        if c and c == code6:
            return {
                "code": code,
                "name": _pick(it, "fund_nm", "名称", "name"),
                "scale": _safe_float(_pick(it, "volume", "规模", "scale", "fund_scale")),
                "scale_date": None,
                "mgmt_fee": _safe_float(_pick(it, "manage_type", "管理费率", "mgmt_fee")),
                "custody_fee": _safe_float(_pick(it, "custodian_type", "托管费率", "custody_fee")),
                "subscribe_fee": None,
                "redemption_fee": None,
                "manager": None,
                "invest_type": None,
                "benchmark": _pick(it, "track", "指数", "benchmark", "跟踪标的"),
            }
    return None


_EXTRACTORS = {
    "ths": _extract_ths,
    "eastmoney": _extract_eastmoney,
    "jisilu": _extract_jisilu,
}


def fetch_fee(code: str) -> dict | None:
    """三源互备调度：按当前队列顺序尝试，成功源置队首、失败源置队尾+冷却。

    返回标准 rec 或 None（所有源都失败/冷却中）。绝不抛给调用方。
    """
    now = time.time()
    with _SRC_LOCK:
        order = list(_SOURCE_ORDER)
        cooled = dict(_SOURCE_COOLDOWN)
    for src in order:
        if cooled.get(src, 0.0) > now:
            continue
        try:
            rec = _EXTRACTORS[src](code)
        except Exception as e:  # noqa: BLE001
            _mark_source_failed(src, e)
            continue
        if rec is None:
            # 软跳过：该源无此 code 覆盖（不降级队列）。
            # 同花顺返回空多为限流/无数据，按失败降级，避免反复空转。
            if src == "ths":
                _mark_source_failed(src, None, throttled=False)
            else:
                _mark_source_no_data(src)
            continue
        _mark_source_ok(src)
        return rec
    return None


def fetch_one(code: str) -> dict | None:
    """兼容旧调用（如有）。"""
    return fetch_fee(code)


# ============================================================
# 读写库
# ============================================================

def _upsert(db, rec: dict) -> None:
    db.execute("DELETE FROM base_fund_fee_info WHERE code = ?", [rec["code"]])
    # 字面量单行 VALUES：参数化 execute ~13.5ms/次（~50ms/基金，P2，
    # 见 docs/性能病理排查报告-2026-10-14.md）；TIMESTAMP 列传 naive CST
    # （墙上时间），与原参数化 aware 路径落库值一致（2026-10-14 实测）。
    bulk_insert(
        db,
        """
        INSERT INTO base_fund_fee_info
            (code, name, scale, scale_date, mgmt_fee, custody_fee, subscribe_fee,
             redemption_fee, manager, invest_type, benchmark, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            [
                rec["code"],
                rec.get("name"),
                rec.get("scale"),
                rec.get("scale_date"),
                rec.get("mgmt_fee"),
                rec.get("custody_fee"),
                rec.get("subscribe_fee"),
                rec.get("redemption_fee"),
                rec.get("manager"),
                rec.get("invest_type"),
                rec.get("benchmark"),
                _now_cst().replace(tzinfo=None),
            ]
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
            "redemption_fee, manager, invest_type, benchmark FROM base_fund_fee_info "
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
                "redemption_fee": r[6],
                "manager": r[7],
                "invest_type": r[8],
                "benchmark": r[9],
            }
    return out


def missing_codes(codes: list[str]) -> list[str]:
    """返回「库里没有」「已过期（> FEE_TTL_DAYS）」或「缺 redemption_fee 新列」的基金代码。

    返回顺序：缺 redemption_fee 的已存在行排在最前（优先回补），其余按缺失/过期顺序。
    这样 ``start_fill`` 每轮会先把「有 3 项费率但缺赎回费率」的旧行补上，而不是一直追
    全新缺口，避免赎回费率列长期留空（2026-10-10：迁移新增 redemption_fee 列，早期已写入
    的 ~266 只 ETF 行该列为 NULL，须回补）。
    """
    if not codes:
        return []
    # code -> (updated_at, redemption_fee)
    have: dict[str, tuple] = {}
    try:
        db = _db()
        _ensure_table(db)
        for i in range(0, len(codes), 400):
            chunk = codes[i : i + 400]
            marks = ",".join("?" for _ in chunk)
            rows = db.fetchall(
                f"SELECT code, updated_at, redemption_fee FROM base_fund_fee_info WHERE code IN ({marks})",
                list(chunk),
            )
            for r in rows:
                have[str(r[0])] = (r[1], r[2])
    except Exception as e:
        print(f"[FundFee] 缺口计算失败: {e}")
        return list(codes)

    deadline = _now_cst().replace(tzinfo=None) - timedelta(days=FEE_TTL_DAYS)
    null_rf: list[str] = []   # 已存在但缺 redemption_fee（优先回补）
    other: list[str] = []     # 完全缺失或已过期
    for c in codes:
        if _FAIL_COUNTS.get(c, 0) >= MAX_FAIL_PER_CODE:
            continue
        h = have.get(c)
        if h is None:
            other.append(c)
            continue
        ts, rf = h
        # ⚠️ DuckDB TIMESTAMP 取出为 naive，deadlines 也必须是 naive，
        #    否则 tz-aware vs naive 比较抛 TypeError，会把「已补全」误判成缺口。
        if rf is None:
            null_rf.append(c)
        elif _naive(ts) is None or _naive(ts) < deadline:
            other.append(c)
    return null_rf + other


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
        # 三源互备队列：当前顺序（队首=最近成功）与每源状态/冷却
        "source_order": p.get("source_order"),
        "sources": p.get("sources"),
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
    # 数据源队列快照（持 _FILL_LOCK 期间顺带用 _SRC_LOCK 取一份，避免并发改写列表）
    with _SRC_LOCK:
        sources = {
            s: {
                "status": _SOURCE_STATUS.get(s, "unknown"),
                "cooldown_until": _SOURCE_COOLDOWN.get(s, 0.0),
                "available": _SOURCE_COOLDOWN.get(s, 0.0) <= time.time(),
            }
            for s in _SOURCE_ORDER
        }
        source_order = list(_SOURCE_ORDER)
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
        # 三源互备队列：当前顺序（队首=最近成功）与每源状态
        "source_order": source_order,
        "sources": sources,
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
    global _LAST_PROGRESS
    if not _FILL_LOCK.acquire(timeout=1):
        # 超时：绝不无锁读 _FILL（复合快照可能撕裂），返回上一次持锁构建的快照副本
        if _LAST_PROGRESS is not None:
            return dict(_LAST_PROGRESS)
        # 冷启动即撞锁的极端情况：返回静态空骨架（_FILL 初值），同样不碰共享字典
        return {
            "running": False,
            "total": 0,
            "done": 0,
            "ok": 0,
            "fail": 0,
            "rounds": 0,
            "last_batch": 0,
            "started_at": None,
            "finished_at": None,
            "last_error": None,
            "skipped": 0,
            "throttled": False,
            "throttle_streak": _THROTTLE_STREAK,
            "retry_in_hours": 0,
            "source_order": [],
            "sources": {},
        }
    try:
        snap = _progress_locked()
        _LAST_PROGRESS = dict(snap)
        return snap
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
            rec = fetch_fee(code)
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
                r["redemption_fee"] = f.get("redemption_fee")
                r["scale_date"] = f.get("scale_date")
                r["manager"] = f.get("manager")

    prog = progress()
    # 「越用越全」的顺手补：两种情况下不出手——①正在跑；②上一轮是被限流打断的，
    # 且还在退避期、且当前没有任何数据源冷却结束（否则每次刷新页面都去撞墙，
    # 退避阶梯会被架空）。只要还有任一源冷却结束可用，就立刻恢复补全（快恢复）。
    # ⚠️ 用户手动点「补一批」走的 start_fill(auto=False)，不受此限。
    if prog["running"]:
        return codes, prog
    if _THROTTLE_STREAK > 0 and not (_any_source_available() or due_for_retry()):
        return codes, prog
    if missing_codes(codes):
        start_fill(codes, auto=True)
        prog = progress()
    return codes, prog


# 模块加载即恢复数据源队列（重启后记住上次谁好用）
_load_source_state()
