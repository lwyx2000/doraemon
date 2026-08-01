"""ETF service — ETF fund data with arbitrage analysis and opportunities."""

from __future__ import annotations

from mock_data import MOCK_ETF_FUNDS
from utils.arbitrage import FEASIBILITY_ORDER, analyze_arbitrage


def get_etfs(
    category: str | None = None,
    strategy: str | None = None,
    min_premium: float | None = None,
    feasibility: str | None = None,
) -> list[dict]:
    """Return ETFs with attached arbitrage analysis.

    Filters:
        category:    match ``etf["category"]``.
        strategy:    accepted for API compatibility (no field to filter on).
        min_premium: include only ETFs with ``premium_pct >= min_premium``.
        feasibility: match ``arbitrage_analysis["feasibility"]``.
    """
    result: list[dict] = []

    for etf in MOCK_ETF_FUNDS:
        if category and etf.get("category") != category:
            continue
        if min_premium is not None and etf.get("premium_pct", 0) < min_premium:
            continue

        analysis = analyze_arbitrage(etf)
        if feasibility and analysis["feasibility"] != feasibility:
            continue

        item = {**etf, "arbitrage_analysis": analysis}
        result.append(item)

    return result


def get_etf_arbitrage_opportunities() -> list[dict]:
    """Return ETF arbitrage opportunities.

    Filters ETFs where ``net_arbitrage_yield > 0``, attaches arbitrage
    analysis, and sorts by feasibility (feasible -> risky -> infeasible)
    then by ``net_yield_after_costs`` descending.
    """
    result: list[dict] = []

    for etf in MOCK_ETF_FUNDS:
        if etf.get("net_arbitrage_yield", 0) <= 0:
            continue
        analysis = analyze_arbitrage(etf)
        item = {**etf, "arbitrage_analysis": analysis}
        result.append(item)

    result.sort(
        key=lambda x: (
            FEASIBILITY_ORDER.get(x["arbitrage_analysis"]["feasibility"], 99),
            -x["arbitrage_analysis"]["net_yield_after_costs"],
        )
    )
    return result
