"""中证指数官方信息（编制说明 / 简称全称）获取与落库。

数据源：中证指数公司官网（csindex.com.cn）与前端同源接口::

    GET https://www.csindex.com.cn/csindex-home/indexInfo/index-basic-info/{indexCode}

返回体关键字段：
- ``indexCnDesc``     官方编制说明（「…选取 N 只…作为指数样本，以反映…」）
- ``indexShortNameCn``/``indexFullNameCn`` 中证官方简称/全称
- ``adjFreqCn``       调样频率（每年 / 每半年 …）
- ``weightingType``   加权方式、``indexCompliance`` 指数合规声明

⚠️ 中证对高频 / 并发请求会 403 或返回非 JSON（本项目此前已被封过 IP）：
- 串行请求，固定间隔 ``REQUEST_GAP`` 秒；
- 结果落 DuckDB ``base_index_compilation``，命中库就不再请求；
- 取数失败返回 None，**绝不 mock**，前端显示「编制说明暂不可得」。

另外本模块顺带产出**指数别名词表**（``alias_vocabulary``），供
``fund_index_map_service`` 把「业绩比较基准」文本反查到指数：中证官方全称
（如「上证国有企业红利指数」）比基金简称口径（「国企红利」）更长，两者剪掉
「指数/收益率」后做规范化子串匹配即可对齐。
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import requests

from services.akshare_client import get_session

CST = timezone(timedelta(hours=8))

#: 中证接口基址（与官网前端同源）
CSI_BASE = "https://www.csindex.com.cn/csindex-home"

#: 串行请求间隔（秒）。压到 0.8s 时连拉 26 个指数实测可全部成功。
REQUEST_GAP = 0.8

#: 内存缓存 TTL（秒）；已落库的前提下几乎不会重复请求
CACHE_TTL = 12 * 3600

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://www.csindex.com.cn/",
    "Accept": "application/json, text/plain, */*",
}

#: ⚠️ 列名为 ``description`` 而非 ``desc``：**desc 是 DuckDB 保留字**（ORDER BY 的
#: DESC），实测裸写 ``desc VARCHAR`` 会 ``Parser Error: syntax error at or near
#: "desc"`` 直接建表失败 → 整张 base_index_compilation 建不出来 → 编制说明
#: 一条都存不进去（表根本不存在）。加反引号也没用：这版 DuckDB 对
#: ``desc`` 反引号同样报 ``syntax error at or near "`"``。故直接改名。
DDL = """
CREATE TABLE IF NOT EXISTS base_index_compilation (
    code           VARCHAR PRIMARY KEY,
    name           VARCHAR,
    full_name      VARCHAR,
    description    VARCHAR,
    adj_freq       VARCHAR,
    weighting      VARCHAR,
    compliance     VARCHAR,
    fetched_at     TIMESTAMP
)
"""

#: code -> dict，来自中证 / 库
_compile_cache: dict[str, dict] = {}
_cache_ts: float = 0.0
_cache_loaded = False


def _now_cst() -> datetime:
    return datetime.now(CST)


def _fetch(code: str, retries: int = 2) -> dict | None:
    """拉取单个指数的中证官方信息。失败返回 None。"""
    url = f"{CSI_BASE}/indexInfo/index-basic-info/{code}"
    last: str | None = None
    for attempt in range(retries):
        try:
            r = get_session().get(url, headers=_HEADERS, timeout=12)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                data = r.json().get("data")
                if isinstance(data, dict) and data.get("indexCode"):
                    return data
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = str(e)[:80]
        time.sleep(1.0 * (attempt + 1))
    print(f"[IdxCompile] {code} 中证信息取数失败: {last}")
    return None


def _load_cache_from_db() -> None:
    """首次使用时把库里已抓到的编制说明灌进内存。"""
    global _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(DDL)
        for row in db.fetchall("SELECT code, name, full_name, description, adj_freq, weighting, "
                               "compliance, fetched_at FROM base_index_compilation"):
            _compile_cache[str(row[0])] = _row_to_dict(row)
    except Exception as e:  # noqa: BLE001
        print(f"[IdxCompile] 编制说明读库失败（忽略）: {e}")


def _row_to_dict(row) -> dict:
    return {
        "code": row[0],
        "name": row[1],
        "full_name": row[2],
        "desc": row[3],
        "adj_freq": row[4],
        "weighting": row[5],
        "compliance": row[6],
        "fetched_at": str(row[7]) if row[7] else None,
    }


def save_compilation(data: dict) -> None:
    """把一条中证官方信息落库。库不可用则只留内存缓存。"""
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(DDL)
        # 中证原始响应用的是 indexCode，记录体用的是 code；两处都兼容，避免落 NULL
        code = data.get("indexCode") or data.get("code")
        db.execute("DELETE FROM base_index_compilation WHERE code = ?", [code])
        db.execute(
            "INSERT INTO base_index_compilation "
            "(code, name, full_name, description, adj_freq, weighting, compliance, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                code,
                data.get("indexShortNameCn"),
                data.get("indexFullNameCn"),
                data.get("indexCnDesc"),
                data.get("adjFreqCn"),
                data.get("weightingType"),
                data.get("indexCompliance"),
                _now_cst(),
            ],
        )
    except Exception as e:  # noqa: BLE001
        # 中证原始响应用的是 indexCode，记录体用的是 code；打日志时兼容两种键，
        # 否则这里永远显示 None，看不出到底是哪只指数没存进去
        print(f"[IdxCompile] {data.get('indexCode') or data.get('code')} "
              f"编制说明落库失败（忽略）: {e}")


def get_compilation(code: str) -> dict | None:
    """取单个指数的编制说明（内存 → 库 → 请求）。

    中证不可用时返回 None，由调用方决定兜底文案（**不 mock**）。
    """
    _load_cache_from_db()
    hit = _compile_cache.get(str(code))
    if hit:
        return hit

    data = _fetch(str(code))
    if not data:
        return None
    record = {
        "code": data.get("indexCode"),
        "name": data.get("indexShortNameCn"),
        "full_name": data.get("indexFullNameCn"),
        "desc": data.get("indexCnDesc"),
        "adj_freq": data.get("adjFreqCn"),
        "weighting": data.get("weightingType"),
        "compliance": data.get("indexCompliance"),
        "fetched_at": _now_cst().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _compile_cache[str(code)] = record
    save_compilation(data)
    return record


def fill_compilations(codes: list[str], force: bool = False) -> dict:
    """批量补齐指数编制说明（串行 + 间隔）。返回进度。"""
    global _cache_ts
    _load_cache_from_db()

    done, failed = 0, 0
    for idx, code in enumerate(codes):
        if (not force) and str(code) in _compile_cache:
            continue
        if idx and time.time() - _cache_ts < REQUEST_GAP:
            time.sleep(REQUEST_GAP - (time.time() - _cache_ts))
        data = _fetch(str(code))
        if data:
            record = {
                "code": data.get("indexCode"),
                "name": data.get("indexShortNameCn"),
                "full_name": data.get("indexFullNameCn"),
                "desc": data.get("indexCnDesc"),
                "adj_freq": data.get("adjFreqCn"),
                "weighting": data.get("weightingType"),
                "compliance": data.get("indexCompliance"),
                "fetched_at": _now_cst().strftime("%Y-%m-%d %H:%M:%S"),
            }
            _compile_cache[str(code)] = record
            save_compilation(data)
            done += 1
        else:
            failed += 1
        _cache_ts = time.time()

    return {
        "ok": True,
        "filled": done,
        "failed": failed,
        "total": len(codes),
        "cached": len(_compile_cache),
    }


# ============================================================
# 别名词表（供基金 → 指数反查）
# ============================================================

#: 别名里需要掐掉的「指数/_收益率」等噪音，做规范化时统一去掉
_NOISE_CHARS = re.compile(r"[指数收益率同期加权]")
#: 前置交易所 / 编制方前缀，掐掉后得到更口语的别名（国企红利 ← 上证国有企业红利）
_PREFIXES = ("中证", "上证", "深证", "国证", "中华", "恒生", "沪市", "深市")


def _norm(s: str) -> str:
    """规范化：去空格与「指数/收益率/同期/加权」噪音，便于子串比对。"""
    return _NOISE_CHARS.sub("", str(s).replace(" ", "").replace("　", ""))


def _strip_prefix(s: str) -> str:
    for p in _PREFIXES:
        if s.startswith(p) and len(s) > len(p) + 2:
            return s[len(p):]
    return s


def build_vocabulary() -> list[tuple[str, str, str, str]]:
    """指数别名词表 → [(规范化别名, 指数代码, 指数简称, 区域)]，长别名优先。

    别名 = 静态 ``DIVIDEND_INDICES`` 里的人工别名 + 中证官方简称/全称
    （含掐掉「指数」与掐掉交易所前缀的变体）。
    """
    from services.dividend_service import DIVIDEND_INDICES  # 延迟导入，避免循环引用

    pairs: dict[str, tuple[str, str, str, str]] = {}
    for code, name, region, aliases in DIVIDEND_INDICES:
        variants: list[str] = []
        for a in (name, *aliases, *_aliases_of(code)):
            variants.append(a)
            if str(a).endswith("指数"):
                variants.append(str(a)[:-2])
        for v in list(variants):
            s = _strip_prefix(v)
            if s and s not in variants:
                variants.append(s)
        for v in variants:
            n = _norm(v)
            if len(n) >= 3:
                pairs.setdefault(n, (n, code, name, region))

    out = list(pairs.values())
    out.sort(key=lambda p: len(p[0]), reverse=True)
    return out


def _aliases_of(code: str) -> list[str]:
    """取该指数在中证官方口径下的简称 / 全称（取不到就返回空）。"""
    rec = _compile_cache.get(str(code))
    if rec and rec.get("name"):
        return [rec["name"], rec.get("full_name") or rec["name"]]
    rec = get_compilation(str(code))
    return [rec["name"], rec.get("full_name") or rec["name"]] if rec else []
