"""Market data service — macro indicators, index valuations, K-line history."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from mock_data import MOCK_MACRO_DATA


def _generate_kline_data(code: str, count: int = 50) -> list[dict]:
    """Generate deterministic mock K-line data via random walk.

    The seed is derived from the ``code`` string so that the same code
    always produces the same series.

    Args:
        code: Instrument code used to seed the RNG.
        count: Number of daily data points to generate.

    Returns:
        List of dicts with keys: date, open, close, high, low, volume.
    """
    seed = sum(ord(c) for c in code)
    rng = random.Random(seed)

    base_price = 1.0 + (seed % 100) / 10.0  # range 1.0 - 10.0
    today = datetime.now()
    price = base_price
    points: list[dict] = []

    for i in range(count):
        date_str = (today - timedelta(days=count - 1 - i)).strftime("%Y-%m-%d")
        open_price = round(price, 3)
        change = rng.uniform(-0.03, 0.03)
        close_price = round(open_price * (1 + change), 3)
        high = round(max(open_price, close_price) * (1 + rng.uniform(0, 0.02)), 3)
        low = round(min(open_price, close_price) * (1 - rng.uniform(0, 0.02)), 3)
        volume = rng.randint(500_000, 5_000_000)
        points.append(
            {
                "date": date_str,
                "open": open_price,
                "close": close_price,
                "high": high,
                "low": low,
                "volume": volume,
            }
        )
        price = close_price

    return points


def _filter_by_date_range(
    points: list[dict],
    start_date: str | None,
    end_date: str | None,
) -> list[dict]:
    """Filter K-line points by an optional [start_date, end_date] range."""
    if not start_date and not end_date:
        return points
    result = points
    if start_date:
        result = [p for p in result if p["date"] >= start_date]
    if end_date:
        result = [p for p in result if p["date"] <= end_date]
    return result


def get_macro_data() -> dict:
    """Return mock macro data (ERP, interbank rates, index valuations)."""
    return MOCK_MACRO_DATA


def get_indices(category: str | None = None, date: str | None = None) -> list[dict]:
    """Return index valuations, optionally filtered by category.

    The ``date`` parameter is accepted for API compatibility but mock data
    does not vary by date.
    """
    indices = MOCK_MACRO_DATA.get("indices", [])
    if category:
        indices = [idx for idx in indices if idx.get("category") == category]
    return list(indices)


def get_index_history(
    code: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Generate mock daily K-line history for an index code."""
    points = _generate_kline_data(code, count=50)
    return _filter_by_date_range(points, start_date, end_date)


def get_kline(
    code: str,
    type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Generate mock K-line data for a quote code.

    The ``type`` parameter (e.g. ``daily`` / ``weekly``) is accepted but
    mock data is always daily.
    """
    points = _generate_kline_data(code, count=50)
    return _filter_by_date_range(points, start_date, end_date)
