"""Convertible bond service — real data from AkShare, with arbitrage & volatility analysis.

数据来源：
- 主源 `bond_zh_cov`（东方财富，全量 ~1000+ 只可转债），覆盖 债现价/转股价值/
  转股溢价率/信用评级/申购日期 等核心字段；
- 兜底 `bond_cb_jsl`（集思录，含 双低/到期收益/剩余年限，但需登录态、封顶 30 条）。

字段补全策略（集思录 CB 接口封顶 30 行，无法全量，故本地推算）：
- 双低：主源已含 债现价 + 转股溢价率，按 价格+|溢价率| 全量近似（即集思录定义）；
- 剩余年限：由 申购日期 + 6 年 − 今天 全量估算（标准 6 年期限）；
- 到期收益率(YTM)：东方财富无此字段，用教科书近似公式
  YTM ≈ [年均票息 + (赎回价−现价)/剩余年限] / [(赎回价+现价)/2]，
  赎回价优先取 bond_cov_comparison 真实值、否则回退 110，结果标记 `ytm_approx=True`。
  近似误差典型 ±0.3~0.8pp，仅用于筛选用途，非精确估值。

取数失败时返回空列表，不使用 mock。
"""

from __future__ import annotations

import datetime
from typing import Any

from services.akshare_client import akshare_request
from utils.convertible_bond import (
    analyze_conversion_arbitrage,
    analyze_volatility,
    CONVERSION_ORDER,
    VOL_SIGNAL_ORDER,
)
from core.config import USE_MOCK_DATA
import mock_data


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _estimate_remaining_years(issue_date: Any) -> float:
    """由发行/申购日期估算剩余年限。

    标准可转债期限为 6 年（少数 5/5.5 年，6 年为市场主流），故以
    `申购日期 + 6 年 - 今天` 近似剩余年限。东方财富 bond_zh_cov 提供申购日期，
    可全量覆盖（集思录 CB 接口封顶 30 行无法全量，故本地估算更实用）。
    无法解析日期时返回 0。
    """
    if issue_date is None:
        return 0.0
    d = None
    if isinstance(issue_date, (datetime.date, datetime.datetime)):
        d = issue_date
    else:
        s = str(issue_date).strip()
        if not s or s in ("-", "None", "nan"):
            return 0.0
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                d = datetime.datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
    if d is None:
        return 0.0
    maturity = d + datetime.timedelta(days=int(365.25 * 6))
    days = (maturity - datetime.date.today()).days
    if days <= 0:
        return 0.0
    return round(days / 365.25, 3)


# 标准可转债票息曲线（逐年，市场主流递增结构），用于近似 YTM 的年均票息估算
_STD_CB_COUPON_CURVE = [0.3, 0.5, 1.0, 1.5, 2.0, 2.5]
# 到期赎回价市场中位（100 + 末年票息），无源时回退
_DEFAULT_REDEMPTION_PRICE = 110.0


def _approx_ytm(
    price: float,
    redemption_price: float,
    remaining_years: float,
    avg_coupon: float | None = None,
) -> float:
    """教科书近似到期收益率：YTM ≈ [C + (F−P)/n] / [(F+P)/2]。

    仅用于筛选用途（典型误差 ±0.3~0.8pp，对比集思录精确 IRR），非精确估值。
    price/剩余年限缺失或非法时返回 0。
    """
    if not price or price <= 0 or not remaining_years or remaining_years <= 0:
        return 0.0
    if avg_coupon is None:
        n = max(1, int(round(remaining_years)))
        seg = (
            _STD_CB_COUPON_CURVE[:n]
            if n <= len(_STD_CB_COUPON_CURVE)
            else _STD_CB_COUPON_CURVE
        )
        avg_coupon = sum(seg) / len(seg)
    f = redemption_price or _DEFAULT_REDEMPTION_PRICE
    numerator = avg_coupon + (f - price) / remaining_years
    denominator = (f + price) / 2.0
    if denominator <= 0:
        return 0.0
    # 返回百分点（与集思录 ytm_rt / _tag_for 中 ytm>2 的口径一致）
    return round(numerator / denominator * 100, 2)


def _fetch_redemption_prices() -> dict:
    """东方财富比价表(bond_cov_comparison)的到期赎回价(code→价)，用于精确近似 YTM。

    53 上 push2 接口可能受限，失败时返回空 dict，调用方回退到默认赎回价。
    """
    try:
        df = akshare_request("bond_cov_comparison", retries=1, timeout=10)
    except Exception as exc:  # noqa: BLE001
        print(f"[CB] 到期赎回价获取失败，回退默认赎回价: {exc}")
        return {}
    mapping: dict = {}
    if isinstance(df, list):
        for r in df:
            code = str(r.get("转债代码") or r.get("债券代码") or "")
            rp = _safe_float(r.get("到期赎回价"))
            if code and rp:
                mapping[code] = rp
    return mapping


def _fill_approx_ytm(items: list[dict], redemption_map: dict) -> list[dict]:
    """为未携带真实 YTM 的转债补全近似 YTM（集思录兜底的真实值不被覆盖）。"""
    for it in items:
        if it.get("ytm"):
            continue
        rp = redemption_map.get(it.get("code")) or _DEFAULT_REDEMPTION_PRICE
        ytm = _approx_ytm(it.get("price"), rp, it.get("remaining_years"))
        it["ytm"] = ytm
        it["ytm_approx"] = True
    return items


def _tag_for(double_low: float | None, ytm: float, premium_pct: float) -> tuple[str, str]:
    if double_low is not None and double_low < 120:
        return "双低策略", "double_low"
    if ytm > 2:
        return "稳健收息", "stable_yield"
    if premium_pct > 30:
        return "高溢价", "high_risk"
    return "", ""


def _norm_row(row: dict[str, Any]) -> dict[str, Any]:
    """将任一数据源的行归一化为统一中间结构。"""
    # 优先按东方财富列名读取
    code = str(row.get("债券代码") or row.get("代码") or "")
    name = str(row.get("债券简称") or row.get("转债名称") or "")
    price = _safe_float(row.get("债现价") or row.get("现价"))
    conv_value = _safe_float(row.get("转股价值"))
    premium_pct = _safe_float(row.get("转股溢价率"))
    rating = str(row.get("信用评级") or row.get("债券评级") or "")
    ytm = _safe_float(row.get("到期税前收益"))
    remaining_years = _safe_float(row.get("剩余年限"))
    # 源未提供剩余年限时（东方财富 bond_zh_cov 无此列），由申购日期估算全量覆盖
    if not remaining_years:
        remaining_years = _estimate_remaining_years(
            row.get("申购日期") or row.get("上市时间") or row.get("发行日期")
        )
    double_low = _safe_float(row.get("双低"), None) if row.get("双低") not in (None, "") else None
    stock_code = str(row.get("正股代码") or "")
    stock_name = str(row.get("正股简称") or row.get("正股名称") or "")
    stock_price = _safe_float(row.get("正股价"))
    stock_change = _safe_float(row.get("正股涨跌"))
    # 集思录无双低时，按 转债价格+转股溢价率 近似（集思录双低定义）
    if double_low is None:
        double_low = round(price + abs(premium_pct), 2) if price else None
    return {
        "code": code,
        "name": name,
        "price": price,
        "conv_value": conv_value,
        "premium_pct": premium_pct,
        "rating": rating,
        "ytm": ytm,
        "remaining_years": remaining_years,
        "double_low_score": double_low,
        "stock_code": stock_code or None,
        "stock_name": stock_name or None,
        "stock_price": stock_price or None,
        "stock_change_pct": stock_change or None,
    }


def _map_bond(norm: dict[str, Any]) -> dict[str, Any]:
    price = norm["price"]
    premium_pct = norm["premium_pct"]
    ytm = norm["ytm"]
    double_low = norm["double_low_score"]
    tag, tag_type = _tag_for(double_low, ytm, premium_pct)
    return {
        "name": norm["name"],
        "code": norm["code"],
        "price": price,
        "change_pct": 0,  # 东方财富/集思录源未直接提供转债涨跌幅
        "conv_value": norm["conv_value"],
        "premium_pct": premium_pct,
        "ytm": ytm,
        "remaining_years": norm["remaining_years"],
        "rating": norm["rating"],
        "redemption_days": 0,
        "total_redemption_days": 15,
        "tag": tag,
        "tag_type": tag_type,
        "double_low_score": double_low,
        "ytm_approx": False,
        "stock_name": norm["stock_name"],
        "stock_code": norm["stock_code"],
        "stock_price": norm["stock_price"],
        "stock_change_pct": norm["stock_change_pct"],
    }


def _attach_analyses(bond: dict[str, Any]) -> dict[str, Any]:
    item = dict(bond)
    item["conversion_analysis"] = analyze_conversion_arbitrage(bond)
    item["volatility_analysis"] = analyze_volatility(bond)
    return item


def _fetch_raw() -> list[dict] | None:
    """拉取原始可转债数据：先东方财富全量，失败再集思录。"""
    raw = akshare_request("bond_zh_cov", retries=1, timeout=10)
    if raw and isinstance(raw, list) and len(raw):
        return raw
    raw = akshare_request("bond_cb_jsl", retries=1, timeout=10)
    if raw and isinstance(raw, list) and len(raw):
        return raw
    return None


def get_convertible_bonds(
    price_min: float | None = None,
    price_max: float | None = None,
    premium_max: float | None = None,
    rating: str | None = None,
    ytm_min: float | None = None,
    double_low_max: float | None = None,
    feasibility: str | None = None,
    vol_signal: str | None = None,
) -> list[dict]:
    """Return real convertible bonds filtered by the given criteria."""
    if USE_MOCK_DATA:
        return [_attach_analyses(dict(b)) for b in mock_data.MOCK_CONVERTIBLE_BONDS]
    raw = _fetch_raw()
    if not raw:
        print("[CB Service] 取数失败，返回空列表")
        return []

    results = [_attach_analyses(_map_bond(_norm_row(row))) for row in raw]
    # 补全近似 YTM（东方财富主源无此字段；集思录兜底的真实值已在 _norm_row 中保留）
    redemption_map = _fetch_redemption_prices()
    results = _fill_approx_ytm(results, redemption_map)

    filtered: list[dict] = []
    for item in results:
        if price_min is not None and item.get("price", 0) < price_min:
            continue
        if price_max is not None and item.get("price", 0) > price_max:
            continue
        if premium_max is not None and item.get("premium_pct", 0) > premium_max:
            continue
        if rating is not None and item.get("rating", "") != rating:
            continue
        if ytm_min is not None and item.get("ytm", 0) < ytm_min:
            continue
        if double_low_max is not None:
            double_low_score = item.get("double_low_score")
            if double_low_score is not None and double_low_score > double_low_max:
                continue
        if feasibility is not None:
            conv = item.get("conversion_analysis") or {}
            if conv.get("feasibility") != feasibility:
                continue
        if vol_signal is not None:
            vol = item.get("volatility_analysis") or {}
            if vol.get("signal") != vol_signal:
                continue
        filtered.append(item)

    return filtered


def get_convertible_bond_detail(code: str) -> dict | None:
    raw = _fetch_raw()
    if not raw:
        return None
    for row in raw:
        if str(row.get("债券代码") or row.get("代码") or "") == code:
            item = _attach_analyses(_map_bond(_norm_row(row)))
            _fill_approx_ytm([item], _fetch_redemption_prices())
            return item
    return None
