"""Arbitrage feasibility analysis — ported from frontend utils/arbitrage.ts.

Core problem solved:
1. Subscription-limited products yield zeroed — QDII/cross-border ETF FX quota restrictions
2. T+N exposure quantification — cross-border ETF T+2 settlement, NAV volatility risk
"""

import math
import re
from typing import Any, Optional

# ============================================================
# Trading Cost Model
# ============================================================

TRADING_COSTS = {
    "subscription_fee_rate": 0.15,
    "sell_commission_rate": 0.03,
    "impact_cost": 0.05,
}


def calc_net_yield_after_costs(gross_yield: float) -> float:
    total = TRADING_COSTS["subscription_fee_rate"] + TRADING_COSTS["sell_commission_rate"] + TRADING_COSTS["impact_cost"]
    return round(gross_yield - total, 2)


# ============================================================
# Core Functions
# ============================================================

def parse_subscribe_limit(limit: Optional[str]) -> float:
    """Parse subscription limit string → amount in yuan.

    '限购 100 元' → 100
    '暂停申购' → -1 (suspended, cannot subscribe)
    '无限制' / None → float('inf')
    """
    if not limit or limit.strip() == "" or limit == "无限制":
        return float("inf")
    if "暂停" in limit or "停止" in limit:
        return -1
    match = re.search(r"(\d+(?:\.\d+)?)", limit)
    if not match:
        return float("inf")
    return float(match.group(1))


def calc_capital_capacity(limit_amount: float) -> dict[str, str]:
    """Capital capacity grading.

    C (infeasible): limit ≤ 1,000 yuan
    B (restricted): limit ≤ 10,000 yuan
    A (feasible):   unlimited or > 10,000 yuan
    """
    if limit_amount == -1:
        return {"grade": "C", "label": "暂停申购"}
    if limit_amount == float("inf"):
        return {"grade": "A", "label": "无限购"}
    if limit_amount <= 1000:
        return {"grade": "C", "label": f"限购{int(limit_amount)}元"}
    if limit_amount <= 10000:
        return {"grade": "B", "label": f"限购{int(limit_amount)}元"}
    return {"grade": "A", "label": f"限购{int(limit_amount)}元"}


def calc_arbitrage_risk(net_yield: float, daily_volatility: float, holding_days: int) -> dict[str, float]:
    """T+N exposure risk quantification using 95% one-sided VaR (Z=1.65).

    Risk exposure = 1.65 × daily_volatility × √holding_days
    """
    z_95 = 1.65
    risk_exposure = z_95 * daily_volatility * math.sqrt(max(holding_days, 1))
    return {
        "risk_exposure": round(risk_exposure, 2),
        "yield_low": round(net_yield - risk_exposure, 2),
        "yield_high": net_yield,
    }


def analyze_arbitrage(fund: dict[str, Any]) -> dict[str, Any]:
    """Full arbitrage feasibility analysis for a single fund/ETF.

    Judgment logic:
    1. Suspended → infeasible
    2. Capital grade C (limit ≤ 1000) → infeasible, yield zeroed
    3. Adjusted yield low < 0 → risky (T+N exposure may eat profits)
    4. Capital grade B (limit ≤ 10000) → risky
    5. Otherwise → feasible
    """
    subscribe_limit = fund.get("subscribe_limit")
    daily_volatility = fund.get("daily_volatility", 1.5)
    holding_days = fund.get("holding_days", 1)
    is_suspended = fund.get("is_suspended", False)
    net_arbitrage_yield = fund.get("net_arbitrage_yield", 0)
    volume = fund.get("volume", 0)

    capital_limit = parse_subscribe_limit(subscribe_limit)
    cap = calc_capital_capacity(capital_limit)
    capital_grade = cap["grade"]
    capital_label = cap["label"]

    net_yield_after_costs = calc_net_yield_after_costs(net_arbitrage_yield)
    risk = calc_arbitrage_risk(net_yield_after_costs, daily_volatility, holding_days)

    traps: list[str] = []

    if capital_grade == "C":
        if capital_limit == -1:
            traps.append("暂停申购，无法套利")
        else:
            traps.append(f"限购{int(capital_limit)}元，资金容量不足")

    if risk["risk_exposure"] > abs(net_yield_after_costs) and net_yield_after_costs > 0:
        traps.append(f"T+{holding_days}敞口{risk['risk_exposure']}% > 收益{net_yield_after_costs}%")

    if is_suspended and capital_limit != -1:
        traps.append("停牌/暂停申购")

    if volume is not None and volume < 500000:
        traps.append("流动性不足")

    if is_suspended or capital_grade == "C":
        feasibility = "infeasible"
        feasibility_label = "不可行"
    elif risk["yield_low"] < 0 or capital_grade == "B":
        feasibility = "risky"
        feasibility_label = "有风险"
    else:
        feasibility = "feasible"
        feasibility_label = "可行"

    return {
        "capital_grade": capital_grade,
        "capital_label": capital_label,
        "capital_limit": capital_limit if capital_limit != float("inf") else 999999,
        "holding_days": holding_days,
        "daily_volatility": daily_volatility,
        "risk_exposure": risk["risk_exposure"],
        "adjusted_yield_low": risk["yield_low"],
        "adjusted_yield_high": risk["yield_high"],
        "net_yield_after_costs": net_yield_after_costs,
        "feasibility": feasibility,
        "feasibility_label": feasibility_label,
        "traps": traps,
        "is_suspended": is_suspended,
    }


FEASIBILITY_ORDER = {"feasible": 0, "risky": 1, "infeasible": 2}
