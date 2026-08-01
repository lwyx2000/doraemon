"""Convertible bond service — list/detail with arbitrage & volatility analysis."""

from __future__ import annotations

from typing import Any

from mock_data import MOCK_CONVERTIBLE_BONDS
from utils.convertible_bond import (
    analyze_conversion_arbitrage,
    analyze_volatility,
    CONVERSION_ORDER,
    VOL_SIGNAL_ORDER,
)


def _attach_analyses(bond: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``bond`` with conversion & volatility analyses attached."""
    item = dict(bond)
    item["conversion_analysis"] = analyze_conversion_arbitrage(bond)
    item["volatility_analysis"] = analyze_volatility(bond)
    return item


def get_convertible_bonds(
    price_min: float | None = None,
    price_max: float | None = None,
    premium_max: float | None = None,
    rating: str | None = None,
    ytm_min: float | None = None,
    double_low_max: float | None = None,
    feasibility: str | None = None,
    vol_signal: str | None = None,
) -> list[dict]:
    """Return convertible bonds filtered by the given criteria.

    Each bond is enriched with ``conversion_analysis`` and
    ``volatility_analysis`` before filtering.
    """
    results = [_attach_analyses(bond) for bond in MOCK_CONVERTIBLE_BONDS]

    filtered: list[dict] = []
    for item in results:
        if price_min is not None and item.get("price", 0) < price_min:
            continue
        if price_max is not None and item.get("price", 0) > price_max:
            continue
        if premium_max is not None and item.get("premium_pct", 0) > premium_max:
            continue
        if rating is not None and item.get("rating", "") != rating:
            continue
        if ytm_min is not None and item.get("ytm", 0) < ytm_min:
            continue
        if double_low_max is not None:
            double_low_score = item.get("double_low_score")
            if double_low_score is not None and double_low_score > double_low_max:
                continue
        if feasibility is not None:
            conv = item.get("conversion_analysis") or {}
            if conv.get("feasibility") != feasibility:
                continue
        if vol_signal is not None:
            vol = item.get("volatility_analysis") or {}
            if vol.get("signal") != vol_signal:
                continue
        filtered.append(item)

    return filtered


def get_convertible_bond_detail(code: str) -> dict | None:
    """Return a single convertible bond by ``code`` with analyses, or None."""
    for bond in MOCK_CONVERTIBLE_BONDS:
        if bond.get("code") == code:
            return _attach_analyses(bond)
    return None
