"""Closed-end fund arbitrage analysis — ported from frontend utils/closedFund.ts.

Three dimensions:
1. Liquidity risk — low volume means can't exit
2. Discount convergence path — LOF conversion determines certainty
3. Underlying credit risk — credit rating + asset type
"""

import re
from typing import Any


def parse_remaining_days(term: str | None) -> int:
    """Parse '28 Days' / '1.4 Years' / '312 Days' → number of days."""
    if not term:
        return 365
    match = re.search(r"([\d.]+)\s*(Day|Year)", term, re.IGNORECASE)
    if not match:
        return 365
    val = float(match.group(1))
    unit = match.group(2).lower()
    return round(val * 365) if unit.startswith("year") else round(val)


def _analyze_liquidity(volume: int) -> dict[str, Any]:
    total_shares = 50_000_000
    turnover = round((volume / total_shares) * 10000) / 100

    if volume < 100_000:
        return {"level": "illiquid", "label": "极差", "turnover": turnover}
    elif volume < 300_000:
        return {"level": "moderate", "label": "一般", "turnover": turnover}
    else:
        return {"level": "ample", "label": "充足", "turnover": turnover}


def _analyze_convergence(fund: dict[str, Any]) -> dict[str, Any]:
    is_lof_convertible = fund.get("is_lof_convertible", False)
    remaining_days = parse_remaining_days(fund.get("remaining_term"))
    remaining_years = remaining_days / 365

    is_discount = fund.get("premium_pct", 0) < 0
    discount_pct = abs(fund.get("premium_pct", 0)) if is_discount else 0
    convergence_yield = round(discount_pct / remaining_years, 2) if remaining_years > 0 else discount_pct

    if is_lof_convertible:
        certainty = "certain"
        label = "确定收敛"
    elif remaining_days < 180:
        certainty = "likely"
        label = "大概率收敛"
    else:
        certainty = "uncertain"
        label = "不确定"

    return {
        "certainty": certainty,
        "label": label,
        "is_lof_convertible": is_lof_convertible,
        "remaining_days": remaining_days,
        "convergence_yield": convergence_yield,
    }


def _analyze_credit(rating: str | None, underlying_type: str | None) -> dict[str, str]:
    if not rating or rating == "-":
        return {"level": "risky", "label": "无评级"}
    if rating == "AAA":
        return {"level": "safe", "label": "安全"}
    if rating.startswith("AA"):
        return {"level": "watch", "label": "关注"}
    return {"level": "risky", "label": "风险"}


def _calc_score(convergence_yield: float, certainty: str, liquidity: str, credit_risk: str) -> int:
    yield_score = min(convergence_yield * 3, 40)
    certainty_score = {"certain": 25, "likely": 15, "uncertain": 5}[certainty]
    liquidity_score = {"ample": 20, "moderate": 10, "illiquid": 0}[liquidity]
    credit_score = {"safe": 15, "watch": 8, "risky": 0}[credit_risk]
    return round(yield_score + certainty_score + liquidity_score + credit_score)


def analyze_closed_fund(fund: dict[str, Any]) -> dict[str, Any]:
    liq = _analyze_liquidity(fund.get("volume", 0))
    conv = _analyze_convergence(fund)
    credit = _analyze_credit(fund.get("credit_rating"), fund.get("underlying_type"))

    warnings: list[str] = []
    if liq["level"] == "illiquid":
        warnings.append("成交量极低，大资金无法退出")
    if conv["certainty"] == "uncertain":
        warnings.append("不转LOF且期限较长，折价收敛不确定")
    if credit["level"] == "risky":
        warnings.append("底层持仓信用风险较高")
    if conv["convergence_yield"] < 3:
        warnings.append("年化收敛收益率偏低")

    score = _calc_score(conv["convergence_yield"], conv["certainty"], liq["level"], credit["level"])

    return {
        "code": fund.get("code", ""),
        "liquidity": liq["level"],
        "liquidity_label": liq["label"],
        "convergence": conv["certainty"],
        "convergence_label": conv["label"],
        "convergence_yield": conv["convergence_yield"],
        "credit_risk": credit["level"],
        "credit_label": credit["label"],
        "score": score,
        "warnings": warnings,
    }


CONVERGENCE_ORDER = {"certain": 0, "likely": 1, "uncertain": 2}
