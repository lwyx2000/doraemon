"""Convertible bond arbitrage analysis — 唯一口径来源（前端只做字段适配）。

转股套利可行性 —— 负溢价 ≠ 可套利，需叠加正股停牌/涨停/转股期/T+1 敞口

重要原则（2026-11-06）：上游未披露的字段一律为 None，分析必须把「数据缺失」
与「业务结论」区分开。旧实现用 `?? false` / `?? 0` / `hv=2.0` 把未知当成
「不在转股期」「隔夜风险 2%」，导致所有负溢价债恒判「不可行」。
IV/HV / 质押率 / Altman Z 无上游源，字段已整体移除（不再占位显示）。
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
    # 波动率无上游源时恒为 None，T+1 敞口判断自动跳过（不再用固定值伪造）
    overnight = stock_volatility

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


CONVERSION_ORDER = {"feasible": 0, "risky": 1, "unknown": 2, "infeasible": 3, "n/a": 4}
