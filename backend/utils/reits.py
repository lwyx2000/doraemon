"""REITs deep analysis — ported from frontend utils/reits.ts.

Three dimensions:
1. NAV premium/discount arbitrage — market price vs NAV
2. Dividend sustainability — DSCR + occupancy trend + leverage
3. Liquidity risk — secondary market volume
"""

from typing import Any


def _analyze_nav_premium(price: float, nav: float | None) -> dict[str, Any]:
    if not nav or nav == 0:
        return {"premium_pct": 0, "level": "fair", "label": "无NAV", "safety_margin": "数据缺失"}

    premium_pct = round((price - nav) / nav * 10000) / 100

    if premium_pct < -3:
        return {"premium_pct": premium_pct, "level": "discount", "label": "折价",
                "safety_margin": f"安全垫{abs(premium_pct)}%"}
    elif premium_pct > 3:
        return {"premium_pct": premium_pct, "level": "premium", "label": "溢价",
                "safety_margin": f"溢价{premium_pct}%，追高风险"}
    else:
        return {"premium_pct": premium_pct, "level": "fair", "label": "合理",
                "safety_margin": "合理区间"}


def _analyze_sustainability(dscr: float, occupancy_trend: float, leverage_ratio: float) -> dict[str, str]:
    risk_points = 0

    if dscr < 1.2:
        risk_points += 2
    elif dscr < 1.5:
        risk_points += 1

    if occupancy_trend < -3:
        risk_points += 2
    elif occupancy_trend < 0:
        risk_points += 1

    if leverage_ratio > 40:
        risk_points += 2
    elif leverage_ratio > 30:
        risk_points += 1

    if risk_points >= 3:
        return {"level": "at_risk", "label": "可持续性差"}
    elif risk_points >= 1:
        return {"level": "watch", "label": "需关注"}
    else:
        return {"level": "sustainable", "label": "可持续"}


def _analyze_liquidity(volume: int | None) -> dict[str, str]:
    vol = volume or 0
    if vol < 500_000:
        return {"level": "illiquid", "label": "极差"}
    if vol < 1_500_000:
        return {"level": "moderate", "label": "一般"}
    return {"level": "ample", "label": "充足"}


def _calc_score(dividend_rate: float, irr: float, nav_level: str, sustainability: str, liquidity: str) -> int:
    yield_score = min(dividend_rate * 5, 30)
    irr_score = min(irr * 3, 10)
    nav_score = {"discount": 20, "fair": 10, "premium": 0}[nav_level]
    sustain_score = {"sustainable": 25, "watch": 12, "at_risk": 0}[sustainability]
    liquid_score = {"ample": 15, "moderate": 8, "illiquid": 0}[liquidity]
    return round(yield_score + irr_score + nav_score + sustain_score + liquid_score)


def analyze_reits(reit: dict[str, Any]) -> dict[str, Any]:
    nav = _analyze_nav_premium(reit.get("market_price", 0), reit.get("nav"))
    sustain = _analyze_sustainability(
        reit.get("dscr", 1.5),
        reit.get("occupancy_trend", 0),
        reit.get("leverage_ratio", 30),
    )
    liq = _analyze_liquidity(reit.get("volume"))

    warnings: list[str] = []
    if nav["level"] == "premium":
        warnings.append(f"溢价{nav['premium_pct']}%，追高风险")
    if sustain["level"] == "at_risk":
        warnings.append("分红可持续性差")
    if liq["level"] == "illiquid":
        warnings.append("二级市场流动性极差")
    if reit.get("dscr", 99) < 1.2:
        warnings.append(f"DSCR={reit.get('dscr')}，偿债能力不足")
    if reit.get("occupancy_trend", 0) < -3:
        warnings.append(f"出租率下降{abs(reit.get('occupancy_trend', 0))}%")

    score = _calc_score(
        reit.get("dividend_rate") or 0,
        reit.get("irr") or 0,
        nav["level"],
        sustain["level"],
        liq["level"],
    )

    return {
        "nav_premium_pct": nav["premium_pct"],
        "nav_level": nav["level"],
        "nav_label": nav["label"],
        "safety_margin": nav["safety_margin"],
        "sustainability": sustain["level"],
        "sustainability_label": sustain["label"],
        "dscr": reit.get("dscr", 0),
        "occupancy_trend": reit.get("occupancy_trend", 0),
        "leverage_ratio": reit.get("leverage_ratio", 0),
        "liquidity": liq["level"],
        "liquidity_label": liq["label"],
        "volume": reit.get("volume", 0),
        "score": score,
        "warnings": warnings,
    }
