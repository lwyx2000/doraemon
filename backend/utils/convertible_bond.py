"""Convertible bond arbitrage analysis — 唯一口径来源（前端只做字段适配）。

两个分析：
1. 转股套利可行性 —— 负溢价 ≠ 可套利，需叠加正股停牌/涨停/转股期/T+1 敞口
2. IV vs HV 波动率对比 —— IV < HV 是 Delta 对冲入场信号

重要原则（2026-11-06）：上游未披露的字段一律为 None，分析必须把「数据缺失」
与「业务结论」区分开。旧实现用 `?? false` / `?? 0` / `hv=2.0` 把未知当成
「不在转股期」「隔夜风险 2%」，导致所有负溢价债恒判「不可行」。
"""

from typing import Any, Optional


def analyze_conversion_arbitrage(
    bond: dict[str, Any], stock_volatility: Optional[float] = None
) -> dict[str, Any]:
    premium_pct = bond.get("premium_pct") or 0
    conv_value = bond.get("conv_value") or 0
    price = bond.get("price") or 0

    is_negative_premium = premium_pct < 0
    theoretical_yield = (
        round((conv_value - price) / price * 100, 2)
        if is_negative_premium and price > 0
        else 0.0
    )

    # None = 数据源未披露；不得默认 False（那会伪造「未进入转股期」的阻断结论）
    in_period = bond.get("is_in_conversion_period")
    limit_up = bond.get("stock_limit_up")
    suspended = bond.get("stock_suspended")
    overnight = stock_volatility if stock_volatility is not None else bond.get("hv")

    blockers: list[str] = []
    missing: list[str] = []

    if suspended is True:
        blockers.append("正股停牌，转股后无法卖出")
    if limit_up is True:
        blockers.append("正股涨停，无法卖出")
    if in_period is False:
        blockers.append("未进入转股期")

    # T+1 敞口只有拿到真实波动率才参与判断；无 HV 时不再用 2.0 伪造
    if is_negative_premium and overnight is not None and overnight > abs(theoretical_yield):
        blockers.append(f"T+1敞口{overnight}% > 套利收益{theoretical_yield}%")

    if in_period is None:
        missing.append("转股期状态未披露")
    if limit_up is None:
        missing.append("正股涨停状态未披露")
    if suspended is None:
        missing.append("正股停牌状态未披露")
    if overnight is None:
        missing.append("正股波动率(HV)未接入")

    if not is_negative_premium:
        feasibility, label = "n/a", "非负溢价"
    elif suspended is True or limit_up is True or in_period is False:
        feasibility, label = "infeasible", "不可行"
    elif blockers:
        feasibility, label = "risky", "有风险"
    elif missing:
        # 负溢价、无已知阻断，但关键状态未披露 → 不下「可行」结论
        feasibility, label = "unknown", "信息不全"
    else:
        feasibility, label = "feasible", "可行"

    return {
        "is_negative_premium": is_negative_premium,
        "theoretical_yield": theoretical_yield,
        "is_in_conversion_period": in_period,
        "is_stock_limit_up": limit_up,
        "is_stock_suspended": suspended,
        "overnight_risk": overnight,
        "feasibility": feasibility,
        "feasibility_label": label,
        "blockers": blockers,
        "data_missing": missing,
    }


def analyze_volatility(bond: dict[str, Any]) -> dict[str, Any]:
    """IV vs HV 波动率分析；无上游源时明确返回「未接入」而非 0。"""
    iv = bond.get("iv")
    hv = bond.get("hv")
    if iv is None or hv is None:
        return {
            "iv": iv,
            "hv": hv,
            "spread": None,
            "ratio": None,
            "signal": "n/a",
            "signal_label": "数据源未接入",
            "suggestion": "当前网关未提供 IV / HV，无法生成波动率套利信号",
        }

    spread = round(iv - hv, 2)
    ratio = round(iv / hv, 2) if hv > 0 else 0
    if ratio < 0.85:
        signal, label = "undervalued", "IV低估"
        suggestion = f"IV低于HV {abs(spread)}%，可买入转债+融券正股做Delta对冲"
    elif ratio > 1.15:
        signal, label = "overvalued", "IV高估"
        suggestion = f"IV高于HV {spread}%，可考虑卖出转债"
    else:
        signal, label = "fair", "合理"
        suggestion = f"IV/HV={ratio}，波动率处于合理区间，无套利信号"
    return {
        "iv": iv, "hv": hv, "spread": spread, "ratio": ratio,
        "signal": signal, "signal_label": label, "suggestion": suggestion,
    }


CONVERSION_ORDER = {"feasible": 0, "risky": 1, "unknown": 2, "infeasible": 3, "n/a": 4}
VOL_SIGNAL_ORDER = {"undervalued": 0, "overvalued": 1, "fair": 2, "n/a": 3}
