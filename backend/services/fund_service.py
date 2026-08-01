"""Fund service — LOF/QDII/closed-end fund data with arbitrage analysis."""

from __future__ import annotations

from mock_data import MOCK_FUNDS
from utils.arbitrage import analyze_arbitrage
from utils.closed_fund import analyze_closed_fund


def get_funds(
    fund_type: str | None = None,
    min_premium: float | None = None,
    feasibility: str | None = None,
    date: str | None = None,
) -> list[dict]:
    """Return funds with attached arbitrage analysis.

    Filters:
        fund_type:   match ``fund["type"]``.
        min_premium: include only funds with ``premium_pct >= min_premium``.
        feasibility: match ``arbitrage_analysis["feasibility"]``.
        date:        accepted for API compatibility (no-op for mock data).
    """
    result: list[dict] = []

    for fund in MOCK_FUNDS:
        if fund_type and fund.get("type") != fund_type:
            continue
        if min_premium is not None and fund.get("premium_pct", 0) < min_premium:
            continue

        analysis = analyze_arbitrage(fund)
        if feasibility and analysis["feasibility"] != feasibility:
            continue

        item = {**fund, "arbitrage_analysis": analysis}
        result.append(item)

    return result


def get_closed_fund_analysis() -> list[dict]:
    """Return closed-end fund analysis, sorted by score descending."""
    result: list[dict] = []

    for fund in MOCK_FUNDS:
        if fund.get("type") != "closed":
            continue
        analysis = analyze_closed_fund(fund)
        result.append(analysis)

    result.sort(key=lambda x: x.get("score", 0), reverse=True)
    return result
