"""REITs service — list with NAV / sustainability / liquidity analysis."""

from __future__ import annotations

from typing import Any

from mock_data import MOCK_REITS
from utils.reits import analyze_reits


def get_reits(
    asset_type: str | None = None,
    min_dividend: float | None = None,
    nav_level: str | None = None,
    sustainability: str | None = None,
) -> list[dict]:
    """Return REITs filtered by the given criteria.

    Each REIT is enriched by merging the ``analyze_reits`` result directly
    into the item dict before filtering.
    """
    results: list[dict] = []
    for reit in MOCK_REITS:
        item = dict(reit)
        analysis = analyze_reits(reit)
        item.update(analysis)
        results.append(item)

    filtered: list[dict] = []
    for item in results:
        if asset_type is not None and item.get("asset_type") != asset_type:
            continue
        if min_dividend is not None and item.get("dividend_rate", 0) < min_dividend:
            continue
        if nav_level is not None and item.get("nav_level") != nav_level:
            continue
        if sustainability is not None and item.get("sustainability") != sustainability:
            continue
        filtered.append(item)

    return filtered
