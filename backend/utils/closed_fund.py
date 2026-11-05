"""Closed-end fund arbitrage analysis (single source of truth).

The frontend ``utils/closedFund.ts`` is now only an adapter over the fields
produced here — it no longer recomputes liquidity / convergence / credit /
score independently. Keeping two copies of the same heuristic used to let
them drift and produced contradictory numbers.

Data honesty rules (2026-11-05 audit):
* ``premium_pct`` is a signed premium/discount rate: negative = discount.
  Only negative values count as "折价"; positive ones are 溢价 and must never
  be folded into discount statistics via abs().
* A row without a valid exchange price (price <= 0) is flagged
  ``quote_missing`` and its 0 premium is NOT data. Downstream must render
  "无报价" and exclude it from every statistic.
* Missing ``remaining_term`` is back-filled from ``maturity`` (calendar days).
  When neither exists, ``term_days`` is None — we never silently assume 365
  days, which used to inflate/deflate annualised convergence yield.
* ``iopv`` / ``net_arbitrage_yield`` have no upstream source for closed funds;
  they are None, not 0 and not a copy of premium_pct.
* ``volume`` is turnover in **yuan** (成交额, 元), never 手. The ``volume_wan``
  helper exposes 万元 for display; turnover rate is not derivable without
  shares outstanding, so it is not computed at all.
* ``credit_rating`` / ``is_lof_convertible`` are absent in the current source.
  "未披露" is a neutral state, NOT a risk verdict.
* Annualising a discount over < 30 remaining days is meaningless, so
  ``convergence_yield`` is None with ``yield_capped=True`` in that case.
"""

import re
from datetime import date
from typing import Any


def parse_remaining_days(term: str | None) -> int | None:
    """Parse '28 Days' / '1.4 Years' → days. Missing/invalid → None.

    Previously returned 365 as a fallback, which fabricated a one-year term
    for funds whose real maturity was 3 years away.
    """
    if not term:
        return None
    match = re.search(r"([\d.]+)\s*(Day|Year)", str(term), re.IGNORECASE)
    if not match:
        return None
    val = float(match.group(1))
    if val <= 0:
        return None
    unit = match.group(2).lower()
    days = round(val * 365) if unit.startswith("year") else round(val)
    return days if days > 0 else None


def _maturity_days(maturity: Any) -> int | None:
    """'2028-11-12' → calendar days from today; expired/unparsable → None."""
    if not maturity:
        return None
    try:
        end = date.fromisoformat(str(maturity).strip()[:10])
    except (ValueError, TypeError):
        return None
    days = (end - date.today()).days
    return days if days > 0 else None


def resolve_remaining_days(fund: dict[str, Any]) -> tuple[int | None, str | None]:
    """Return (days, source). remaining_term wins; maturity back-fills."""
    days = parse_remaining_days(fund.get("remaining_term"))
    if days is not None:
        return days, "remaining_term"
    days = _maturity_days(fund.get("maturity"))
    if days is not None:
        return days, "maturity"
    return None, None


def _analyze_liquidity(volume: Any) -> dict[str, Any]:
    """Thresholds are in YUAN of daily turnover (10万 / 30万 元)."""
    v = float(volume or 0)
    if v < 100_000:
        level, label = "illiquid", "极差"
    elif v < 300_000:
        level, label = "moderate", "一般"
    else:
        level, label = "ample", "充足"
    return {"level": level, "label": label, "volume_wan": round(v / 10000, 2)}


def _analyze_convergence(
    premium_pct: Any,
    quote_missing: bool,
    days: int | None,
    lof_convertible: Any,
) -> dict[str, Any]:
    premium = float(premium_pct or 0)
    is_discount = (not quote_missing) and premium < 0
    discount_pct = round(abs(premium), 2) if is_discount else None

    conv_yield: float | None = None
    yield_capped = False
    if is_discount and days:
        if days < 30:
            yield_capped = True
        else:
            conv_yield = round(discount_pct / (days / 365), 2)

    if quote_missing:
        certainty, label = "unknown", "无报价"
    elif lof_convertible is True:
        certainty, label = "certain", "确定收敛"
    elif lof_convertible is False:
        certainty = "likely" if days and days < 180 else "uncertain"
        label = "清算临近·大概率收敛" if certainty == "likely" else "不转LOF·收敛不确定"
    elif days and days < 90:
        certainty, label = "likely", "临近到期·大概率收敛"
    else:
        # 数据源未披露是否转 LOF：这是「信息缺失」，不是「已确认不转」
        certainty, label = "uncertain", "路径未披露"

    return {
        "certainty": certainty,
        "label": label,
        "is_lof_convertible": lof_convertible,
        "discount_pct": discount_pct,
        "convergence_yield": conv_yield,
        "yield_capped": yield_capped,
    }


def _analyze_credit(rating: str | None, underlying_type: str | None) -> dict[str, str]:
    if not rating or str(rating).strip() in ("", "-"):
        return {"level": "unknown", "label": "未披露"}
    r = str(rating).strip().upper()
    if r == "AAA":
        return {"level": "safe", "label": "安全"}
    if r.startswith("AA"):
        return {"level": "watch", "label": "关注"}
    return {"level": "risky", "label": "风险"}


def _calc_score(
    convergence_yield: float | None,
    certainty: str,
    liquidity: str,
    credit_risk: str,
) -> int:
    yield_score = min((convergence_yield or 0) * 3, 40)
    certainty_score = {"certain": 25, "likely": 15, "uncertain": 5, "unknown": 5}[certainty]
    liquidity_score = {"ample": 20, "moderate": 10, "illiquid": 0}[liquidity]
    # 未披露 = 中性，不因缺数据直接判 0 分（旧逻辑让 36/36 全被扣分）
    credit_score = {"safe": 15, "watch": 8, "risky": 0, "unknown": 8}[credit_risk]
    return round(yield_score + certainty_score + liquidity_score + credit_score)


def analyze_closed_fund(fund: dict[str, Any]) -> dict[str, Any]:
    price = float(fund.get("price") or 0)
    quote_missing = price <= 0
    days, term_source = resolve_remaining_days(fund)

    liq = _analyze_liquidity(fund.get("volume", 0))
    conv = _analyze_convergence(
        fund.get("premium_pct"),
        quote_missing,
        days,
        fund.get("is_lof_convertible"),
    )
    credit = _analyze_credit(fund.get("credit_rating"), fund.get("underlying_type"))

    warnings: list[str] = []
    if quote_missing:
        warnings.append("无有效场内报价，溢折价率未计算")
    if liq["level"] == "illiquid":
        warnings.append("日成交额不足10万元，大资金进出困难")
    if conv["certainty"] == "uncertain":
        warnings.append("到期是否转LOF未披露，折价收敛路径待确认")
    if credit["level"] == "risky":
        warnings.append("底层持仓信用评级偏低")
    if conv["yield_capped"]:
        warnings.append("剩余期限不足30天，年化收敛收益率不具参考性")
    elif conv["convergence_yield"] is not None and conv["convergence_yield"] < 3:
        warnings.append("年化收敛收益率偏低")

    score = _calc_score(
        conv["convergence_yield"], conv["certainty"], liq["level"], credit["level"]
    )

    return {
        **fund,  # 保留原始基金字段，供前端表格直接展示
        "code": fund.get("code", ""),
        # ---- 数据质量标记 ----
        "quote_missing": quote_missing,
        "term_days": days,
        "term_source": term_source,
        # ---- 无源字段：显式置空，不再伪装成 0 ----
        "iopv": None,
        "net_arbitrage_yield": None,
        # ---- 分析结论（前端只做展示适配）----
        "volume_wan": liq["volume_wan"],
        "liquidity": liq["level"],
        "liquidity_label": liq["label"],
        "convergence": conv["certainty"],
        "convergence_label": conv["label"],
        "is_lof_convertible": conv["is_lof_convertible"],
        "discount_pct": conv["discount_pct"],
        "convergence_yield": conv["convergence_yield"],
        "yield_capped": conv["yield_capped"],
        "credit_risk": credit["level"],
        "credit_label": credit["label"],
        "score": score,
        "warnings": warnings,
    }


CONVERGENCE_ORDER = {"certain": 0, "likely": 1, "uncertain": 2, "unknown": 3}
