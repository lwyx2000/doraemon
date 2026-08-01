"""Convertible bond router — list & detail endpoints."""

from fastapi import APIRouter, Query

from models import ApiResponse, ConvertibleBond
from services.convertible_bond_service import (
    get_convertible_bonds,
    get_convertible_bond_detail,
)

router = APIRouter(tags=["convertible-bonds"])


@router.get("/convertible-bonds", response_model=ApiResponse[list[ConvertibleBond]])
async def list_convertible_bonds(
    price_min: float | None = Query(None, description="Minimum price"),
    price_max: float | None = Query(None, description="Maximum price"),
    premium_max: float | None = Query(None, description="Maximum premium percentage"),
    rating: str | None = Query(None, description="Credit rating, e.g. AAA, AA+"),
    ytm_min: float | None = Query(None, description="Minimum yield to maturity"),
    double_low_max: float | None = Query(None, description="Maximum double-low score"),
    feasibility: str | None = Query(
        None,
        description="Conversion arbitrage feasibility: feasible, risky, infeasible, n/a",
    ),
    vol_signal: str | None = Query(
        None,
        description="Volatility signal: undervalued, overvalued, fair, n/a",
    ),
):
    data = get_convertible_bonds(
        price_min=price_min,
        price_max=price_max,
        premium_max=premium_max,
        rating=rating,
        ytm_min=ytm_min,
        double_low_max=double_low_max,
        feasibility=feasibility,
        vol_signal=vol_signal,
    )
    return ApiResponse(data=data)


@router.get("/convertible-bonds/{code}", response_model=ApiResponse[ConvertibleBond])
async def get_convertible_bond(code: str):
    data = get_convertible_bond_detail(code)
    if data is None:
        return ApiResponse(code=404, message="Not found", data=None)
    return ApiResponse(data=data)
