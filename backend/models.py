"""Pydantic models for QuantTerminal Pro API.

All request/response schemas matching the API design document.
"""

from datetime import date, datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ============================================================
# Common
# ============================================================

class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: Optional[T] = None


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str


# ============================================================
# Market Data
# ============================================================

class IndexValuation(BaseModel):
    name: str
    level: float
    change_pct: float
    pe: float
    pb: float
    pe_percentile: float
    pb_percentile: float
    category: str
    change_3m_pct: float
    win_rate: float


class MacroData(BaseModel):
    erp: float
    erp_percentile_3y: float
    erp_percentile_5y: float
    erp_percentile_10y: float
    dr007: float
    gc001: float
    indices: list[IndexValuation]


class KlineItem(BaseModel):
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: int


# ============================================================
# Fund / ETF
# ============================================================

class ArbitrageAnalysis(BaseModel):
    capital_grade: str
    capital_label: str
    capital_limit: float
    holding_days: int
    daily_volatility: float
    risk_exposure: float
    adjusted_yield_low: float
    adjusted_yield_high: float
    net_yield_after_costs: float
    feasibility: str
    feasibility_label: str
    traps: list[str]
    is_suspended: bool


class FundItem(BaseModel):
    name: str
    code: str
    type: str
    price: float
    iopv: float
    premium_pct: float
    premium_percentile: float
    net_arbitrage_yield: float
    remaining_term: Optional[str] = None
    annualized: Optional[float] = None
    est_ytm: Optional[float] = None
    maturity: Optional[str] = None
    volume: int
    subscribe_limit: Optional[str] = None
    daily_volatility: Optional[float] = None
    holding_days: Optional[int] = None
    is_suspended: Optional[bool] = None
    nav: Optional[float] = None
    credit_rating: Optional[str] = None
    is_lof_convertible: Optional[bool] = None
    underlying_type: Optional[str] = None
    arbitrage_analysis: Optional[ArbitrageAnalysis] = None


class ClosedFundAnalysis(BaseModel):
    code: str
    liquidity: str
    liquidity_label: str
    convergence: str
    convergence_label: str
    convergence_yield: float
    credit_risk: str
    credit_label: str
    score: int
    warnings: list[str]


class EtfFund(BaseModel):
    name: str
    code: str
    category: str
    sub_category: str
    price: float
    iopv: float
    premium_pct: float
    volume: int
    premium_percentile: float
    net_arbitrage_yield: float
    subscribe_limit: Optional[str] = None
    daily_volatility: Optional[float] = None
    holding_days: Optional[int] = None
    is_suspended: Optional[bool] = None
    grid_low: float = 0
    grid_high: float = 0
    grid_step: float = 0
    grid_yield_est: float = 0
    momentum_score: int = 0
    pe: Optional[float] = None
    pe_percentile: Optional[float] = None
    val_category: Optional[str] = None
    dividend_rate: Optional[float] = None
    arbitrage_analysis: Optional[ArbitrageAnalysis] = None


# ============================================================
# Convertible Bonds
# ============================================================

class ConversionArbitrage(BaseModel):
    is_negative_premium: bool
    theoretical_yield: float
    is_in_conversion_period: bool
    is_stock_limit_up: bool
    is_stock_suspended: bool
    overnight_risk: float
    feasibility: str
    feasibility_label: str
    blockers: list[str]


class VolatilityAnalysis(BaseModel):
    iv: float
    hv: float
    spread: float
    ratio: float
    signal: str
    signal_label: str
    suggestion: str


class ConvertibleBond(BaseModel):
    name: str
    code: str
    price: float
    change_pct: float = 0
    conv_value: float = 0
    premium_pct: float = 0
    ytm: float = 0
    remaining_years: float = 0
    rating: str = ""
    redemption_days: int = 0
    total_redemption_days: int = 15
    tag: str = ""
    tag_type: str = ""
    double_low_score: Optional[float] = None
    putback_days: Optional[int] = None
    total_putback_days: Optional[int] = None
    revision_days: Optional[int] = None
    total_revision_days: Optional[int] = None
    altman_z_score: Optional[float] = None
    pledge_rate: Optional[float] = None
    is_st_risk: Optional[bool] = None
    stock_name: Optional[str] = None
    stock_code: Optional[str] = None
    iv: Optional[float] = None
    hv: Optional[float] = None
    is_in_conversion_period: Optional[bool] = None
    stock_limit_up: Optional[bool] = None
    stock_price: Optional[float] = None
    stock_change_pct: Optional[float] = None
    stock_suspended: Optional[bool] = None
    conversion_analysis: Optional[ConversionArbitrage] = None
    volatility_analysis: Optional[VolatilityAnalysis] = None


# ============================================================
# REITs
# ============================================================

class ReitItem(BaseModel):
    name: str
    code: str
    market_price: float
    annual_distribution: float
    dividend_rate: float
    irr: float
    occupancy_rate: float
    project_name: str
    nav: Optional[float] = None
    volume: Optional[int] = None
    dscr: Optional[float] = None
    occupancy_trend: Optional[float] = None
    asset_type: Optional[str] = None
    leverage_ratio: Optional[float] = None
    # Analysis fields (populated by backend)
    nav_premium_pct: Optional[float] = None
    nav_level: Optional[str] = None
    nav_label: Optional[str] = None
    safety_margin: Optional[str] = None
    sustainability: Optional[str] = None
    sustainability_label: Optional[str] = None
    liquidity: Optional[str] = None
    liquidity_label: Optional[str] = None
    score: Optional[int] = None
    warnings: list[str] = []


# ============================================================
# Portfolio
# ============================================================

class FavoriteItem(BaseModel):
    id: str
    code: str
    name: str
    type: str
    added_at: Optional[str] = None
    note: Optional[str] = None


class FavoriteCreate(BaseModel):
    code: str
    name: str
    type: str
    note: Optional[str] = None


class Portfolio(BaseModel):
    id: str
    user_id: str
    name: str
    created_at: Optional[str] = None


class PortfolioItemCreate(BaseModel):
    code: str
    name: str
    type: str
    quantity: float
    cost_price: float


# ============================================================
# Strategy
# ============================================================

class StrategyRule(BaseModel):
    id: Optional[str] = None
    field: str
    operator: str
    value: str
    logic: str = "AND"


class Strategy(BaseModel):
    id: str
    name: str
    target_asset: str
    rules: list[StrategyRule]
    active: bool = True
    createdAt: Optional[str] = None


class StrategyCreate(BaseModel):
    name: str
    target_asset: str
    rules: list[StrategyRule]


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None


# ============================================================
# Alert
# ============================================================

class AlertRule(BaseModel):
    id: str
    name: str
    type: str
    target: str
    condition: str
    value: float
    channels: list[str]
    active: bool = True


class AlertRuleCreate(BaseModel):
    name: str
    type: str
    target: str
    condition: str
    value: float
    channels: list[str]


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None


class AlertEvent(BaseModel):
    id: int
    rule_id: str
    triggered_at: str
    target_code: Optional[str] = None
    target_name: Optional[str] = None
    actual_value: Optional[float] = None
    message: Optional[str] = None
    is_read: bool = False


# ============================================================
# AI
# ============================================================

class AiReport(BaseModel):
    date: str
    macro_assessment: str
    strategy_matches: list[dict[str, Any]]
    arbitrage_alerts: list[dict[str, Any]]
    created_at: Optional[str] = None


class AiConfig(BaseModel):
    provider: str
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    temperature: float = 0.7
    cron_expression: Optional[str] = None
    enabled: bool = False


# ============================================================
# Monitor
# ============================================================

class ServiceStatus(BaseModel):
    name: str
    status: str
    latency_ms: int


class MonitorDashboard(BaseModel):
    system_uptime: str
    api_calls_today: int
    cache_hit_rate: float
    active_connections: int
    last_error: Optional[str] = None
    services: list[ServiceStatus]


class CacheConfig(BaseModel):
    enabled: bool
    ttl_seconds: int
    max_size: int
    method: Optional[str] = None
