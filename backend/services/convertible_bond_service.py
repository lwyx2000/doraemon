"""Convertible bond service — 集思录全量存续转债为主源。

数据来源（2026-11-06 更正，见工作日志）：
- 主源 `/api/processed_data?category=jisilu&subtype=cb`：登录态集思录全量
  存续转债（约 315 行 / 23 字段），含真实 到期税前收益(YTM)、双低、剩余年限、
  涨跌幅、正股涨跌/PB、成交额、换手率、评级、强赎/回售触发价。
  ⚠️ 不要改用 `/api/ak?method=bond_cb_jsl` —— 那是游客态，恒 30 行。
- 条款补充 `/api/ak?method=bond_cb_redeem_jsl`（约 317 行）：转股起始日、
  强赎状态、强赎天计数、最后交易日、到期日、剩余规模。
- 降级 `/api/ak?method=bond_zh_cov`（东财发行一览 1066 行）+
  `bond_zh_hs_cov_spot`（新浪全量行情）：主源失败时按「转股价值>0 且
  上市时间非空」过滤出存续债，避免把 747 行历史退市/面值占位行当行情。

口径原则：不再使用近似 YTM / 估算剩余年限 / 写死的条款进度；
无上游源的字段一律返回 None，由前端显示「— / 未接入」，不把数据缺失伪装成结论。

取数全部失败时返回空列表 + gateway_no_data_meta，不使用 mock。
"""

from __future__ import annotations

import datetime
import re
import threading
import time
from typing import Any

from core.config import USE_MOCK_DATA, AKSHARE_API_BASE
from services.akshare_client import akshare_request, processed_data_request
from services.meta_utils import gateway_no_data_meta, real_meta_base, mock_meta
from utils.convertible_bond import analyze_conversion_arbitrage, analyze_volatility
import mock_data


# 集思录 YTM 也偶有极端脏值（实测 min -1135%），超出该区间视为无效值
_YTM_SANE_MIN = -50.0
_YTM_SANE_MAX = 50.0


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    if value is None or value == "" or value == "-":
        return default
    try:
        v = float(value)
    except (ValueError, TypeError):
        return default
    # NaN / Inf 不应进入响应（JSON 序列化会炸）
    if v != v or v in (float("inf"), float("-inf")):
        return default
    return v


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s and s not in ("-", "None", "nan") else None


def _sane_ytm(value: Any) -> float | None:
    """集思录真实 YTM，超出合理区间返回 None（不伪造也不放极端值进统计）。"""
    v = _safe_float(value, None)
    if v is None or not (_YTM_SANE_MIN <= v <= _YTM_SANE_MAX):
        return None
    return round(v, 2)


# ============================================================
# 上游取数
# ============================================================

def _fetch_jisilu_cb() -> list[dict] | None:
    """主源：登录态集思录全量存续转债（约 315 行 / 23 字段）。

    复用 fund_service 同一套 processed_data 重试逻辑（网关多副本 404 换连接），
    避免可转债链路单独写一份不抗抖动的实现。
    """
    data = processed_data_request("jisilu", {"subtype": "cb"}, retries=3, timeout=30)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data
    print("[CB] jisilu/cb 主源不可用，准备降级")
    return None


def _fetch_redeem_terms() -> dict[str, dict]:
    """条款补充源：转股起始日 / 强赎状态 / 天计数 / 最后交易日 / 剩余规模。"""
    rows = akshare_request("bond_cb_redeem_jsl", retries=3, timeout=15)
    if not isinstance(rows, list) or not rows:
        return {}
    return {str(r.get("代码") or ""): r for r in rows if r.get("代码")}


def _fetch_sina_spot() -> dict[str, dict]:
    """新浪全量行情，用于降级源补涨跌幅与成交额。"""
    rows = akshare_request("bond_zh_hs_cov_spot", retries=3, timeout=15)
    if not isinstance(rows, list) or not rows:
        return {}
    return {str(r.get("code") or ""): r for r in rows if r.get("code")}


def _date_iso(value: Any) -> str | None:
    """把上游日期归一化为 YYYY-MM-DD（兼容 datetime / YYYY/MM/DD / 带时分秒）。"""
    s = _safe_str(value)
    if not s:
        return None
    s = s.replace("/", "-")[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None


def _fetch_eastmoney_valid() -> list[dict] | None:
    """降级源：东财发行一览，只保留真实存续行。

    `bond_zh_cov` 覆盖 2007 年至今全部发行记录（1066 行），其中 747 行是
    「债现价=100 面值占位 + 转股价值=0」的历史退市债。过滤条件：
    转股价值>0 且 上市时间有效且已上市 —— 实测约 315 行存续债。
    """
    rows = akshare_request("bond_zh_cov", retries=3, timeout=15)
    if not isinstance(rows, list) or not rows:
        return None
    today = datetime.date.today().isoformat()
    valid: list[dict] = []
    for r in rows:
        conv = _safe_float(r.get("转股价值")) or 0
        listed = _date_iso(r.get("上市时间"))
        price = _safe_float(r.get("债现价")) or 0
        if conv <= 0 or not listed or price <= 0:
            continue
        # 上市时间晚于今天 = 待上市，其价格 100 是面值占位
        if listed > today:
            continue
        valid.append(r)
    print(f"[CB] 东财降级源：{len(rows)} 行发行记录 → {len(valid)} 行存续债")
    return valid or None


# ============================================================
# 归一化
# ============================================================

_REDEEM_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def _norm_from_jisilu(row: dict, terms: dict, spot: dict) -> dict | None:
    """主源（集思录 23 字段）→ 统一中间结构。"""
    code = _safe_str(row.get("代码"))
    if not code:
        return None
    price = _safe_float(row.get("现价"))
    if not price or price <= 0:
        return None
    volume = _safe_float(row.get("成交额")) or 0
    term = terms.get(code, {})
    sp = spot.get(code, {})
    # 游客态 30 行里部分债的集思录成交额为 0，用新浪成交额/非面值价兜底，
    # 避免把正常交易债误标成「无成交」而排除出统计
    spot_amount = _safe_float(sp.get("amount")) or 0
    has_trade = volume > 0 or spot_amount > 0 or abs(price - 100.0) > 1e-6

    # 强赎天计数是 HTML 片段，只有明确出现 "n/m" 才解析为进度；否则留空
    days = total = None
    counter = _safe_str(term.get("强赎天计数"))
    if counter:
        m = _REDEEM_PROGRESS_RE.search(re.sub(r"<[^>]+>", " ", counter))
        if m:
            days, total = int(m.group(1)), int(m.group(2))

    conv_start = _date_iso(term.get("转股起始日"))
    today = datetime.date.today().isoformat()
    return {
        "code": code,
        "name": _safe_str(row.get("转债名称")) or "",
        "price": price,
        "change_pct": _safe_float(row.get("涨跌幅"), None),
        "conv_value": _safe_float(row.get("转股价值")) or 0,
        "premium_pct": _safe_float(row.get("转股溢价率")) or 0,
        "ytm": _sane_ytm(row.get("到期税前收益")),
        "remaining_years": _safe_float(row.get("剩余年限"), None),
        "rating": _safe_str(row.get("债券评级")) or "",
        "double_low_score": _safe_float(row.get("双低"), None),
        "stock_name": _safe_str(row.get("正股名称")),
        "stock_code": _safe_str(row.get("正股代码")),
        "stock_price": _safe_float(row.get("正股价"), None),
        "stock_change_pct": _safe_float(row.get("正股涨跌"), None),
        "stock_pb": _safe_float(row.get("正股PB"), None),
        "remaining_size": _safe_float(row.get("剩余规模"), None),
        "turnover_rate": _safe_float(row.get("换手率"), None),
        "volume_raw": volume or spot_amount,
        "has_trade": has_trade,
        "maturity_date": _date_iso(row.get("到期时间")) or _date_iso(term.get("到期日")),
        "last_trade_date": _date_iso(term.get("最后交易日")),
        "conversion_start_date": conv_start,
        "redemption_trigger_price": _safe_float(row.get("强赎触发价"), None),
        "putback_trigger_price": _safe_float(row.get("回售触发价"), None),
        "redemption_status": _safe_str(term.get("强赎状态")),
        "redemption_days": days,
        "total_redemption_days": total,
        "is_in_conversion_period": (conv_start <= today if conv_start else None),
        "data_source": "jisilu/cb",
    }


def _norm_from_eastmoney(row: dict, terms: dict, spot: dict) -> dict | None:
    """降级源（东财 + 新浪行情）→ 统一中间结构；无源字段一律 None。"""
    code = _safe_str(row.get("债券代码"))
    if not code:
        return None
    price = _safe_float(row.get("债现价"))
    if not price or price <= 0:
        return None
    sp = spot.get(code, {})
    term = terms.get(code, {})
    change = _safe_float(sp.get("changepercent"), None)
    amount = _safe_float(sp.get("amount")) or 0
    conv_start = _date_iso(term.get("转股起始日"))
    today = datetime.date.today().isoformat()
    # 东财已按存续性过滤，价格非面值占位即视作可交易；
    # 新浪成交额缺失不应把整批降级数据排除出统计
    has_trade = amount > 0 or abs(price - 100.0) > 1e-6

    premium = _safe_float(row.get("转股溢价率")) or 0
    conv_value = _safe_float(row.get("转股价值")) or 0
    return {
        "code": code,
        "name": _safe_str(row.get("债券简称")) or "",
        "price": price,
        "change_pct": change,
        "conv_value": conv_value,
        "premium_pct": premium,
        # 降级源没有真实 YTM / 剩余年限，绝不重算近似值。
        # 双低是「价格 + 转股溢价率」的精确定义（集思录同口径），可由已有字段
        # 精确得出，但必须用带符号的溢价率，绝不能取 abs（负溢价会被算成正数）。
        "ytm": None,
        "remaining_years": None,
        "rating": _safe_str(row.get("信用评级")) or "",
        "double_low_score": round(price + premium, 2),
        "stock_name": _safe_str(term.get("正股名称")),
        "stock_code": _safe_str(term.get("正股代码")),
        "stock_price": _safe_float(term.get("正股价"), None),
        "stock_change_pct": None,
        "stock_pb": None,
        "remaining_size": _safe_float(term.get("剩余规模"), None),
        "turnover_rate": None,
        "volume_raw": amount,
        "has_trade": has_trade,
        "maturity_date": _date_iso(term.get("到期日")),
        "last_trade_date": _date_iso(term.get("最后交易日")),
        "conversion_start_date": conv_start,
        "redemption_trigger_price": _safe_float(term.get("强赎触发价"), None),
        "putback_trigger_price": None,
        "redemption_status": _safe_str(term.get("强赎状态")),
        "redemption_days": None,
        "total_redemption_days": None,
        "is_in_conversion_period": (conv_start <= today if conv_start else None),
        "data_source": "eastmoney+sina",
    }


# ============================================================
# 标签 / 分析 / 自检
# ============================================================

def _tag_for(norm: dict) -> tuple[str, str]:
    """只对有真实成交的存续债打标签；无成交/无源数据不打「双低」。"""
    if not norm.get("has_trade"):
        return "", ""
    dl = norm.get("double_low_score")
    ytm = norm.get("ytm")
    premium = norm.get("premium_pct") or 0
    if dl is not None and dl < 120:
        return "双低策略", "double_low"
    if ytm is not None and ytm > 2:
        return "稳健收息", "stable_yield"
    if premium > 30:
        return "高溢价", "high_risk"
    return "", ""


def _build_bond(norm: dict) -> dict:
    tag, tag_type = _tag_for(norm)
    item: dict[str, Any] = {
        **norm,
        "ytm_approx": False,  # 不再使用近似 YTM；保留字段兼容旧前端
        "tag": tag,
        "tag_type": tag_type,
        # 无上游源的字段：统一 None（不写 0 / false / 假天数）
        "putback_days": None,
        "total_putback_days": None,
        "revision_days": None,
        "total_revision_days": None,
        "altman_z_score": None,
        "pledge_rate": None,
        "is_st_risk": None,
        "iv": None,
        "hv": None,
        "stock_limit_up": None,
        "stock_suspended": None,
    }
    item["conversion_analysis"] = analyze_conversion_arbitrage(item)
    item["volatility_analysis"] = analyze_volatility(item)
    return item


def _self_check(items: list[dict]) -> None:
    """口径自检：把数据质量问题打进日志，避免静默回归到 1066 行占位数据。"""
    if not items:
        print("[CB][self-check] 无数据")
        return
    n = len(items)
    traded = sum(1 for x in items if x.get("has_trade"))
    bad_premium = 0
    for x in items:
        cv, p, prem = x.get("conv_value") or 0, x.get("price") or 0, x.get("premium_pct") or 0
        if cv > 0 and p > 0:
            calc = (p - cv) / cv * 100
            if abs(calc - prem) > 1.0:
                bad_premium += 1
    sources = sorted({str(x.get("data_source")) for x in items})
    print(
        f"[CB][self-check] 存续债 {n} 只 | 有成交 {traded} | "
        f"YTM有效 {sum(1 for x in items if x.get('ytm') is not None)} | "
        f"转股期已披露 {sum(1 for x in items if x.get('is_in_conversion_period') is not None)} | "
        f"溢折价自洽偏差>1pct {bad_premium} | 源 {sources}"
    )
    if n > 400:
        print(f"[CB][self-check][WARN] 行数 {n} 异常偏多，疑似退化到发行一览未过滤版本")


# ============================================================
# 对外接口
# ============================================================

_CB_LIST_TTL = 30
_CB_LIST_MAX_KEYS = 64
_CB_LIST_CACHE: dict[tuple, tuple[float, tuple[list[dict], dict]]] = {}
_CB_LIST_LOCK = threading.Lock()
# 未过滤全量快照：详情接口与告警引擎复用，避免为了一行重拉三个上游
_CB_ALL_CACHE: tuple[float, list[dict], str | None] | None = None


def _load_all(use_cache: bool = True) -> tuple[list[dict], str | None]:
    """取数 + 归一化 + 分析，返回 (bonds, note)。全部失败返回 ([], None)。"""
    global _CB_ALL_CACHE
    if use_cache and _CB_ALL_CACHE and (time.time() - _CB_ALL_CACHE[0]) < _CB_LIST_TTL:
        return _CB_ALL_CACHE[1], _CB_ALL_CACHE[2]

    # 四源始终全取：集思录登录态会退化（cookie 失效时只返回游客态 30 行），
    # 单靠它会让页面从 315 只突然变成 30 只。以东财存续性过滤后的 315 行为
    # universe 骨架，按代码合并其余三源，富字段有多少标多少、缺的一律 null。
    jisilu = _fetch_jisilu_cb() or []
    eastmoney = _fetch_eastmoney_valid() or []
    if not jisilu and not eastmoney:
        return [], None

    terms = _fetch_redeem_terms()
    spot = _fetch_sina_spot()

    jmap = {str(r.get("代码") or ""): r for r in jisilu if r.get("代码")}
    cmap = {str(r.get("债券代码") or ""): r for r in eastmoney if r.get("债券代码")}
    # 东财骨架优先（保证全量存续），再补集思录独有的可交换债(EB)等
    codes = list(dict.fromkeys([*cmap.keys(), *jmap.keys()]))

    items: list[dict] = []
    for code in codes:
        j, c = jmap.get(code), cmap.get(code)
        if j:
            norm = _norm_from_jisilu(j, terms, spot)
            if norm and c and not norm.get("rating"):
                norm["rating"] = _safe_str(c.get("信用评级")) or ""
        elif c:
            norm = _norm_from_eastmoney(c, terms, spot)
        else:
            continue
        if norm:
            items.append(_build_bond(norm))

    n_j = len(jisilu)
    if n_j >= 100:
        note = "集思录全量存续转债（登录态）+ 东财存续性校验 + 强赎条款 + 新浪行情交叉"
    else:
        note = (
            f"集思录登录态失效，仅 {n_j} 只有 YTM/双低等富字段；"
            "其余存续债由东财发行一览(存续性过滤) + 新浪行情 + 强赎条款合并，"
            "无源字段显示 —（网关恢复登录后自动补齐）"
        )
    print(f"[CB] 四源合并：集思录 {n_j} / 东财存续 {len(eastmoney)} → 输出 {len(items)} 只")

    # 成交额降序：流动性优先，战术扫描取前 N 只时不再全是次新债
    items.sort(key=lambda x: (x.get("volume_raw") or 0), reverse=True)
    _self_check(items)
    _CB_ALL_CACHE = (time.time(), items, note)
    return items, note


def get_convertible_bonds(
    price_min: float | None = None,
    price_max: float | None = None,
    premium_max: float | None = None,
    rating: str | None = None,
    ytm_min: float | None = None,
    double_low_max: float | None = None,
    feasibility: str | None = None,
    vol_signal: str | None = None,
    force: bool = False,
) -> tuple[list[dict], dict]:
    """Return (real listed convertible bonds, meta) filtered by criteria."""
    if USE_MOCK_DATA:
        return [dict(b) for b in mock_data.MOCK_CONVERTIBLE_BONDS], mock_meta()

    cache_key = (price_min, price_max, premium_max, rating, ytm_min, double_low_max, feasibility, vol_signal)
    if not force:
        with _CB_LIST_LOCK:
            hit = _CB_LIST_CACHE.get(cache_key)
            if hit and (time.time() - hit[0]) < _CB_LIST_TTL:
                return hit[1]

    items, note = _load_all(use_cache=not force)
    if not items:
        return [], gateway_no_data_meta()

    filtered: list[dict] = []
    for it in items:
        if price_min is not None and it["price"] < price_min:
            continue
        if price_max is not None and it["price"] > price_max:
            continue
        if premium_max is not None and (it["premium_pct"] or 0) > premium_max:
            continue
        if rating is not None and it.get("rating") != rating:
            continue
        # 无源字段不参与「≥/≤」筛选：缺值时直接排除，不能用 0 冒充满足条件
        if ytm_min is not None and (it.get("ytm") is None or it["ytm"] < ytm_min):
            continue
        if double_low_max is not None and (
            it.get("double_low_score") is None or it["double_low_score"] > double_low_max
        ):
            continue
        if feasibility is not None and (it.get("conversion_analysis") or {}).get("feasibility") != feasibility:
            continue
        if vol_signal is not None and (it.get("volatility_analysis") or {}).get("signal") != vol_signal:
            continue
        filtered.append(it)

    out = (filtered, real_meta_base(AKSHARE_API_BASE, note or ""))
    with _CB_LIST_LOCK:
        _CB_LIST_CACHE[cache_key] = (time.time(), out)
        if len(_CB_LIST_CACHE) > _CB_LIST_MAX_KEYS:
            oldest = sorted(_CB_LIST_CACHE, key=lambda k: _CB_LIST_CACHE[k][0])
            for k in oldest[: len(_CB_LIST_CACHE) - _CB_LIST_MAX_KEYS]:
                _CB_LIST_CACHE.pop(k, None)
    return out


def get_convertible_bond_detail(code: str) -> dict | None:
    items, _ = _load_all()
    return next((x for x in items if x.get("code") == code), None)
