"""Pydantic models for QuantTerminal Pro API.

All request/response schemas matching the API design document.
"""

from datetime import date, datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ============================================================
# Common
# ============================================================

class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: Optional[T] = None
    # 附加信息（如数据来源标记 isMock / dataSource / mockTime，供前端横幅展示）
    meta: Optional[dict[str, Any]] = None


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
    username: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class BrokerAccountRequest(BaseModel):
    broker: str
    account: str = ""


class AccountNameRequest(BaseModel):
    name: str


# ============================================================
# Market Data
# ============================================================

class IndexValuation(BaseModel):
    name: str
    code: str
    level: float
    change_pct: float
    pe: float
    pb: float
    pe_percentile: float
    pb_percentile: float
    category: str
    change_3m_pct: float
    win_rate: float
    market: str = "a_share"  # a_share, hk, us


class MarketIndex(BaseModel):
    name: str
    code: str
    price: float
    change: float
    changePct: float


class MarketOverview(BaseModel):
    date: str
    status: str
    indices: list[MarketIndex]
    upCount: int
    downCount: int
    flatCount: int
    totalVolume: float
    volumeChange: float


class BoardSector(BaseModel):
    rank: int
    name: str
    code: str
    price: float
    change: float
    changePct: float
    upCount: int
    downCount: int
    leadingStock: str
    leadingStockChange: float
    type: str


class IndustryFlow(BaseModel):
    name: str
    inflow: Optional[float] = None
    inflowPct: Optional[float] = None
    changePct: Optional[float] = None


class FundFlows(BaseModel):
    date: str
    mainInflow: Optional[float] = None
    mainInflowPct: Optional[float] = None
    superLargeInflow: Optional[float] = None
    superLargeInflowPct: Optional[float] = None
    largeInflow: Optional[float] = None
    largeInflowPct: Optional[float] = None
    mediumInflow: Optional[float] = None
    mediumInflowPct: Optional[float] = None
    smallInflow: Optional[float] = None
    smallInflowPct: Optional[float] = None
    industryFlows: list[IndustryFlow]
    source: Optional[str] = None
    mainFlowAvailable: Optional[bool] = None


class ZTStock(BaseModel):
    code: str
    name: str
    price: float
    changePct: float
    turnover: float
    marketCap: float
    firstZtTime: str
    lastZtTime: str
    炸板次数: int
    连板数: int
    industry: str


class DTStock(BaseModel):
    code: str
    name: str
    price: float
    changePct: float
    turnover: float
    marketCap: float
    continuousDt: int
    industry: str


class PrevZTPerformance(BaseModel):
    avgChange: float
    topPerformer: str
    topPerformerChange: float


class ZTStats(BaseModel):
    date: str
    ztCount: int
    dtCount: int
    prevZTPerformance: PrevZTPerformance
    ztList: list[ZTStock]
    dtList: list[DTStock]


class FundRankingItem(BaseModel):
    rank: int
    code: str
    name: str
    type: str
    nav: float
    changePct: float
    change: float
    volume: int | None
    premiumPct: float | None


class MacroIndicators(BaseModel):
    """宏观指标：ERP / DR007 / GC001 等（原 /macro 中的指标部分）

    注: ERP 及其历史分位依赖 10Y 国债收益率(akshare bond_china_yield, 单次区间须<1年),
    取数失败时为 None, 前端做空值兜底, 绝不返回伪造数据。
    """
    erp: float | None = None
    erp_percentile_3y: float | None = None
    erp_percentile_5y: float | None = None
    erp_percentile_10y: float | None = None
    dr007: float | None = None
    gc001: float | None = None


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
    model_config = ConfigDict(extra="allow")
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
    # 原始基金字段（前端 analyzeClosedFundBatch 分析与表格展示需要）
    name: str = ""
    code: str = ""
    type: str = "closed"
    price: float = 0
    iopv: float = 0
    premium_pct: float = 0          # 折价率(%)：负值=折价
    premium_percentile: float = 50
    net_arbitrage_yield: float = 0
    remaining_term: Optional[str] = None   # 剩余期限(如 "312 Days")，源缺失时为 None
    annualized: Optional[float] = None     # 年化收益
    est_ytm: Optional[float] = None        # 预估到期收益
    maturity: Optional[str] = None         # 到期日
    volume: int = 0                        # 成交额(元)
    nav: Optional[float] = None            # 基金净值
    nav_date: Optional[str] = None         # 净值披露日期
    credit_rating: Optional[str] = None
    underlying_type: Optional[str] = None
    is_lof_convertible: Optional[bool] = None
    change_pct: float = 0
    # 后端分析字段（前端不依赖，保留以兼容旧调用）
    liquidity: str = "illiquid"
    liquidity_label: str = "极差"
    convergence: str = "uncertain"
    convergence_label: str = "不确定"
    convergence_yield: float = 0
    credit_risk: str = "risky"
    credit_label: str = "无评级"
    score: int = 0
    warnings: list[str] = []


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
    change_pct: Optional[float] = None
    # 以下基本面字段 AkShare 实时接口无法直接获取，缺失时返回 null（不虚构数值）
    annual_distribution: Optional[float] = None
    dividend_rate: Optional[float] = None
    irr: Optional[float] = None
    occupancy_rate: Optional[float] = None
    project_name: Optional[str] = None
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


class HoldingImportItem(BaseModel):
    """持仓批量导入条目（JSON/CSV 文档导入）"""
    code: str
    name: str
    type: str  # stock / etf / fund_otc / option / future / hk_stock
    broker: Optional[str] = ""
    account: Optional[str] = ""  # 子账户，如 普通 / 两融
    quantity: float
    cost_price: float
    open_date: Optional[str] = None
    currency: Optional[str] = "CNY"
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None


class HoldingImportRequest(BaseModel):
    items: list[HoldingImportItem]


class HoldingUpdate(BaseModel):
    """持仓手动变更（仅传入的字段生效）"""
    quantity: Optional[float] = None
    cost_price: Optional[float] = None
    manual_price: Optional[float] = None
    broker: Optional[str] = None
    account: Optional[str] = None
    name: Optional[str] = None
    open_date: Optional[str] = None
    currency: Optional[str] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    fair_value: Optional[float] = None
    grid_lower: Optional[float] = None
    grid_upper: Optional[float] = None
    grid_step: Optional[float] = None


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
    rules: list[StrategyRule] = []
    sort_by: Optional[str] = None
    sort_order: str = 'asc'
    limit_count: Optional[int] = None
    active: bool = True
    ai_tracking: bool = False  # 是否加入AI决策中心跟踪
    createdAt: Optional[str] = None


class StrategyCreate(BaseModel):
    name: str
    target_asset: str
    rules: list[StrategyRule] = []
    sort_by: Optional[str] = None
    sort_order: str = 'asc'
    limit_count: Optional[int] = None


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None
    ai_tracking: Optional[bool] = None
    rules: Optional[list[StrategyRule]] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None
    limit_count: Optional[int] = None


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
    type: Optional[str] = None
    target: Optional[str] = None
    condition: Optional[str] = None
    value: Optional[float] = None
    channels: Optional[list[str]] = None


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


# ============================================================
# Notification Config
# ============================================================

class NotificationConfig(BaseModel):
    wecom_webhook_url: Optional[str] = None
    dingtalk_webhook_url: Optional[str] = None
    email_smtp_host: Optional[str] = None
    email_smtp_port: Optional[int] = None
    email_username: Optional[str] = None
    email_password: Optional[str] = None
    email_from: Optional[str] = None
    email_to: Optional[str] = None


class AlertScanResult(BaseModel):
    scanned_rules: int
    triggered_events: int
    notifications_sent: dict[str, int] = {}
    events: list[dict[str, Any]] = []
