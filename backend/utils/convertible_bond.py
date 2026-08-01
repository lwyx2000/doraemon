"""Convertible bond arbitrage analysis — ported from frontend utils/convertibleBond.ts.

Two analyses:
1. Conversion arbitrage feasibility — negative premium ≠ arbitrageable
2. IV vs HV volatility comparison — IV < HV is delta-hedge entry signal
"""

from typing import Any, Optional


def analyze_conversion_arbitrage(bond: dict[str, Any], stock_volatility: Optional[float] = None) -> dict[str, Any]:
    """Conversion arbitrage feasibility analysis.

    Arbitrage path: buy CB → convert to stock → sell stock
    Three blockers:
    1. Stock suspended → can't sell stock after conversion
    2. Stock limit-up → can't sell stock
    3. Not in conversion period → can't convert
    4. T+1 overnight exposure > arbitrage yield
    """
    premium_pct = bond.get("premium_pct", 0)
    is_negative_premium = premium_pct < 0
    conv_value = bond.get("conv_value", 0)
    price = bond.get("price", 0)

    theoretical_yield = round((conv_value - price) / price * 100, 2) if is_negative_premium else 0

    is_in_conversion_period = bond.get("is_in_conversion_period", False)
    is_stock_limit_up = bond.get("stock_limit_up", False)
    is_stock_suspended = bond.get("stock_suspended", False)
    overnight_risk = stock_volatility if stock_volatility is not None else bond.get("hv", 2.0)

    blockers: list[str] = []

    if is_stock_suspended:
        blockers.append("正股停牌，转股后无法卖出")
    if is_stock_limit_up:
        blockers.append("正股涨停，无法卖出")
    if not is_in_conversion_period:
        blockers.append("未进入转股期")
    if is_negative_premium and overnight_risk > abs(theoretical_yield):
        blockers.append(f"T+1敞口{overnight_risk}% > 套利收益{theoretical_yield}%")

    if not is_negative_premium:
        feasibility = "n/a"
        feasibility_label = "非负溢价"
    elif is_stock_suspended or is_stock_limit_up or not is_in_conversion_period:
        feasibility = "infeasible"
        feasibility_label = "不可行"
    elif overnight_risk > abs(theoretical_yield):
        feasibility = "risky"
        feasibility_label = "有风险"
    else:
        feasibility = "feasible"
        feasibility_label = "可行"

    return {
        "is_negative_premium": is_negative_premium,
        "theoretical_yield": theoretical_yield,
        "is_in_conversion_period": is_in_conversion_period,
        "is_stock_limit_up": is_stock_limit_up,
        "is_stock_suspended": is_stock_suspended,
        "overnight_risk": overnight_risk,
        "feasibility": feasibility,
        "feasibility_label": feasibility_label,
        "blockers": blockers,
    }


def analyze_volatility(bond: dict[str, Any]) -> dict[str, Any]:
    """IV vs HV volatility analysis.

    Signal:
    - IV < HV × 0.85 → undervalued (buy CB + short stock for delta hedge)
    - IV > HV × 1.15 → overvalued (sell CB)
    - Otherwise → fair
    """
    iv = bond.get("iv", 0) or 0
    hv = bond.get("hv", 0) or 0
    spread = round(iv - hv, 2)
    ratio = round(iv / hv, 2) if hv > 0 else 0

    if iv == 0 or hv == 0:
        return {
            "iv": iv, "hv": hv, "spread": spread, "ratio": ratio,
            "signal": "n/a", "signal_label": "数据缺失",
            "suggestion": "波动率数据不足，无法判断",
        }
    elif ratio < 0.85:
        return {
            "iv": iv, "hv": hv, "spread": spread, "ratio": ratio,
            "signal": "undervalued", "signal_label": "IV低估",
            "suggestion": f"IV低于HV {abs(spread)}%，转债期权被低估，可买入转债+融券正股做Delta对冲",
        }
    elif ratio > 1.15:
        return {
            "iv": iv, "hv": hv, "spread": spread, "ratio": ratio,
            "signal": "overvalued", "signal_label": "IV高估",
            "suggestion": f"IV高于HV {spread}%，转债期权被高估，可卖出转债或做空期权部分",
        }
    else:
        return {
            "iv": iv, "hv": hv, "spread": spread, "ratio": ratio,
            "signal": "fair", "signal_label": "合理",
            "suggestion": f"IV/HV={ratio}，波动率处于合理区间，无套利信号",
        }


CONVERSION_ORDER = {"feasible": 0, "risky": 1, "infeasible": 2, "n/a": 3}
VOL_SIGNAL_ORDER = {"undervalued": 0, "overvalued": 1, "fair": 2, "n/a": 3}
