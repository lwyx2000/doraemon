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
    is_admin: bool = False
    force_change: bool = False


class RegisterRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    # 常规改密必填；被管理员强制改密的用户可省略（免旧密码改密）
    old_password: Optional[str] = None
    new_password: str


class BrokerAccountRequest(BaseModel):
    """已废弃：券商管理重构为终端/券商模型，保留仅供兼容旧引用（不应再使用）。"""
    broker: str
    account: str = ""


class TerminalRequest(BaseModel):
    """终端管理：一个终端（设备/渠道）可挂多个券商。"""
    name: str
    remark: str = ""


class BrokerRequest(BaseModel):
    """券商：account 由客户端自传作为主标识；name 券商名；remark 备注。"""
    name: str
    account: str
    remark: str = ""


class AccountNameRequest(BaseModel):
    name: str


# ============================================================
# Market Data
# ============================================================

class IndexValuation(BaseModel):
    name: str
    code: str
    # 上游行情缺失时置 None（前端显示"—"），绝不伪造为 0（Pydantic 亦须为可选，否则 None 触发 500）
    level: Optional[float] = None
    change_pct: Optional[float] = None
    pe: float | None = None
    pb: float | None = None
    pe_percentile: float | None = None
    pb_percentile: float | None = None
    category: str
    change_3m_pct: float | None = None
    # win_rate：条件胜率（±10% PE 区间持有 3 个月正收益占比），
    # 由 _enrich_valuation_with_history 用同口径历史序列实算；样本<10 个月或无历史序列时为 None
    win_rate: float | None = None
    # 近1年涨跌幅(%)：同口径 PB/PE 历史序列月度桶实算
    change_1y_pct: float | None = None
    market: str = "a_share"  # a_share, hk, us
    hasValuation: bool | None = None  # False=实时行情补录（科创综指等），无估值数据，前端显示"—"
    valuation_date: str | None = None  # 上游行情快照日期 YYYY-MM-DD
    pe_as_of: str | None = None        # PE/PB 历史快照日期（分位基于该序列）


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
    volumeChange: Optional[float] = None
    prevDayVolume: Optional[float] = None


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
    category: Optional[str] = None
    sub_category: Optional[str] = None
    price: float
    iopv: float
    premium_pct: float
    premium_percentile: Optional[float] = None  # 需历史溢价率序列，无源时为 None（前端显示 -）
    net_arbitrage_yield: float
    remaining_term: Optional[str] = None
    annualized: Optional[float] = None
    est_ytm: Optional[float] = None
    maturity: Optional[str] = None
    volume: Optional[int] = None  # 新浪兜底源提供成交额(元)；麦蕊源缺失时为 None
    subscribe_limit: Optional[str] = None
    daily_volatility: Optional[float] = None
    holding_days: Optional[int] = None
    is_suspended: Optional[bool] = None
    nav: Optional[float] = None
    change_pct: Optional[float] = None
    credit_rating: Optional[str] = None
    is_lof_convertible: Optional[bool] = None
    underlying_type: Optional[str] = None
    # 篮子自算估值（跨境 LOF/QDII，参考 lofarb；数据不足时后端不写→前端显示 -）
    nav_date: Optional[str] = None
    est_nav: Optional[float] = None
    est_premium_pct: Optional[float] = None
    est_base_date: Optional[str] = None
    est_price_date: Optional[str] = None
    est_position: Optional[float] = None
    # 估值方法口径：basket=篮子加权，index=单指数跟踪（代理，前端加「~」标注）
    est_method: Optional[str] = None
    est_index_symbol: Optional[str] = None
    est_index_resid_pct: Optional[float] = None
    est_index_proxy: Optional[bool] = None
    # 期货结算价口径（method=futures）
    est_futures_symbol: Optional[str] = None
    est_futures_price_kind: Optional[str] = None      # settle / live
    est_futures_resid_pct: Optional[float] = None
    # 估值误差自检（T3）：用历史 est_nav 与基金公司公布的真实净值比对。
    # 没有回填样本时后端**不写**这些字段（前端显示 '-'），不能写 0 —— 0 会被读成「零误差」。
    valuation_error: Optional[float] = None        # 最近一次：est_nav/nav_actual - 1，单位 %
    valuation_error_date: Optional[str] = None     # 该误差对应的净值日
    valuation_error_n: Optional[int] = None        # 近 20 日有效样本数
    valuation_error_mae: Optional[float] = None    # 近 20 日平均绝对误差（%）
    valuation_error_max: Optional[float] = None    # 近 20 日最大绝对误差（%）
    arbitrage_analysis: Optional[ArbitrageAnalysis] = None


class ClosedFundAnalysis(BaseModel):
    # 原始基金字段（前端表格展示需要）
    name: str = ""
    code: str = ""
    type: str = "closed"
    price: float = 0
    # 封闭基金无 IOPV / 净套利收益上游源：显式置 None，不伪装成 0 或复制 premium_pct
    iopv: Optional[float] = None
    premium_pct: float = 0          # 溢折价率(%)：负值=折价、正值=溢价；无报价时为 0，须结合 quote_missing 判读
    premium_percentile: Optional[float] = None
    net_arbitrage_yield: Optional[float] = None
    remaining_term: Optional[str] = None   # 剩余期限(如 "1.39 Years")，由 maturity 补算后一般都有值
    annualized: Optional[float] = None     # 年化收益（源未提供时为 None，前端显示 —）
    est_ytm: Optional[float] = None        # 预估到期收益（源未提供时为 None，前端显示 —）
    maturity: Optional[str] = None         # 到期日 YYYY-MM-DD
    volume: int = 0                        # 成交额(元)，不是「手」
    nav: Optional[float] = None            # 基金净值
    nav_date: Optional[str] = None         # 净值披露日期
    credit_rating: Optional[str] = None
    underlying_type: Optional[str] = None
    is_lof_convertible: Optional[bool] = None
    change_pct: float = 0
    # ---- 数据质量标记（前端据此排除无报价行、缺期限行，不再默认 365 天）----
    quote_missing: bool = False             # price<=0：无有效场内报价，其 premium_pct=0 不是真实平价
    term_days: Optional[int] = None         # 剩余天数；remaining_term 优先、maturity 补算
    term_source: Optional[str] = None       # remaining_term / maturity / None
    term_from_maturity: Optional[bool] = None
    yield_capped: bool = False              # 剩余期限<30天，年化收敛收益率不具参考性
    # ---- 后端分析字段（前端只做展示适配，不再重复计算）----
    volume_wan: Optional[float] = None      # 成交额(万元)
    discount_pct: Optional[float] = None    # 仅折价品种为正数，溢价/无报价为 None
    liquidity: str = "illiquid"
    liquidity_label: str = "极差"
    convergence: str = "unknown"
    convergence_label: str = "路径未披露"
    convergence_yield: Optional[float] = None
    credit_risk: str = "unknown"
    credit_label: str = "未披露"
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
    volume: Optional[int] = None
    premium_percentile: Optional[float] = None
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
    # ETF 申赎 / 费率（麦蕊日度快照 + 本地费率库，定时补全）
    nav_date: Optional[str] = None                # 净值披露日期
    share: Optional[float] = None                 # 最新份额(亿份)
    scale: Optional[float] = None                 # 最新规模(亿元)
    mgmt_fee: Optional[float] = None              # 管理费率(%)
    custody_fee: Optional[float] = None           # 托管费率(%)
    subscribe_fee: Optional[float] = None         # 最高申购费率(%)
    redemption_fee: Optional[float] = None        # 最高赎回费率(%)
    net_subscribe_share: Optional[float] = None   # 日净申赎份额(亿份，正=净申购)
    net_subscribe_amount: Optional[float] = None  # 日净申赎额(亿元，正=净申购/流入)
    net_subscribe_date: Optional[str] = None      # 快照截止日期


# ============================================================
# Convertible Bonds
# ============================================================

class ConversionArbitrage(BaseModel):
    is_negative_premium: bool
    theoretical_yield: float
    # None = 上游未披露，不得默认 False/0 伪造成业务结论
    is_in_conversion_period: Optional[bool] = None
    is_stock_limit_up: Optional[bool] = None
    is_stock_suspended: Optional[bool] = None
    overnight_risk: Optional[float] = None
    feasibility: str
    feasibility_label: str
    blockers: list[str] = []
    data_missing: list[str] = []


class ConvertibleBond(BaseModel):
    name: str
    code: str
    price: float
    change_pct: Optional[float] = None
    conv_value: float = 0
    premium_pct: float = 0
    # 集思录真实「到期税前收益」；异常值/unavailable 时为 None（绝不重算近似值）
    ytm: Optional[float] = None
    ytm_approx: bool = False  # 兼容旧前端；现恒为 False（近似逻辑已删除）
    remaining_years: Optional[float] = None
    rating: str = ""
    # 无源条款进度一律 None；旧版写死 0/15，会把「无数据」显示成「0/15天」
    redemption_days: Optional[int] = None
    total_redemption_days: Optional[int] = None
    tag: str = ""
    tag_type: str = ""
    double_low_score: Optional[float] = None
    putback_days: Optional[int] = None
    total_putback_days: Optional[int] = None
    revision_days: Optional[int] = None
    total_revision_days: Optional[int] = None
    is_st_risk: Optional[bool] = None
    stock_name: Optional[str] = None
    stock_code: Optional[str] = None
    stock_price: Optional[float] = None
    stock_change_pct: Optional[float] = None
    stock_pb: Optional[float] = None
    is_in_conversion_period: Optional[bool] = None
    stock_limit_up: Optional[bool] = None
    stock_suspended: Optional[bool] = None
    # 集思录存续债真实字段（2026-11-06 换主源后新增）
    remaining_size: Optional[float] = None
    turnover_rate: Optional[float] = None
    volume_raw: Optional[float] = None     # 仅用于排序，单位未在上游标注，UI 不展示绝对值
    has_trade: bool = False                # False=无成交/待上市，统计与策略须排除
    maturity_date: Optional[str] = None
    last_trade_date: Optional[str] = None
    conversion_start_date: Optional[str] = None
    redemption_trigger_price: Optional[float] = None
    putback_trigger_price: Optional[float] = None
    redemption_status: Optional[str] = None
    data_source: Optional[str] = None
    conversion_analysis: Optional[ConversionArbitrage] = None


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
# 机器/外部程序上传（无鉴权）
# ============================================================

class HoldingUploadItem(BaseModel):
    """持仓机器上传条目（无鉴权接口 /holdings/import/api 使用）。

    字段与 HoldingImportItem 对齐；code/name/quantity/cost_price 必填。
    """
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


class HoldingUploadRequest(BaseModel):
    """无鉴权持仓上传：调用方须以 user_id 或 username 指明归属用户。

    增量合并（merge）：按 code+type+account 去重，重复导入=覆盖更新；
    覆盖前旧数据写入 biz_holdings_history 表留痕。

    券商归属（2026-11 重构：终端管理）：
    - account：券商账号，由**客户端自传**作为主标识（不再由后端生成 BRK-xxxx code）；
    - broker_code：历史字段别名，等同于 account（旧外部程序可继续传，便于兼容）；
    - broker_name / remark：可选，随上传一并登记券商名 / 备注（首见该 account 时自动建券商，落默认终端）；
    - terminal：可选，指定归属终端 id（留空自动落到该用户默认终端）。
    account 与 broker_code 皆为空 → 整批进入 failed（不整体拒绝）。
    """
    user_id: Optional[int] = None
    username: Optional[str] = None
    source: Optional[str] = ""       # 来源程序标记，写入历史表便于追溯
    account: Optional[str] = None          # 券商账号，客户端自传主标识
    broker_code: Optional[str] = None      # 历史别名，等同于 account
    broker_name: Optional[str] = None      # 可选：券商名
    remark: Optional[str] = None           # 可选：券商备注
    terminal: Optional[str] = None         # 可选：归属终端 id
    items: list[HoldingUploadItem]


class TradeImportItem(BaseModel):
    """成交记录条目（无鉴权接口 /trades/import 使用）。

    按交易日全量覆盖：同 (user, trade_date) 旧记录会被删除后重插。
    """
    code: str
    name: Optional[str] = ""
    type: Optional[str] = "stock"    # stock / etf / fund_otc / option / future / hk_stock
    broker: Optional[str] = ""
    account: Optional[str] = ""
    direction: str                   # buy / sell（买入 / 卖出）
    price: float                     # 成交价
    quantity: float                  # 成交数量
    amount: Optional[float] = None   # 成交额（价×量，可选，缺失后端按 price*quantity 计算）
    fee: Optional[float] = None      # 手续费（可选）
    trade_time: Optional[str] = None # 成交时间 YYYY-MM-DD HH:MM:SS（可选）


class TradeUploadRequest(BaseModel):
    """无鉴权成交上传：trade_date 为该批归属交易日（必填，YYYY-MM-DD）。

    已存在同 (user, trade_date) 的旧记录会被全量覆盖（删除后重插）；
    新 trade_date 直接全量新增。

    券商归属（2026-11 重构：终端管理）：
    - account：券商账号，由**客户端自传**作为主标识；
    - broker_code：历史字段别名，等同于 account；
    - broker_name / remark：可选，随上传一并登记券商名 / 备注（首见该 account 时自动建券商）；
    - terminal：可选，指定归属终端 id（留空自动落到默认终端）。
    account 与 broker_code 皆为空 → 整批进入 failed（不整体拒绝）。
    """
    user_id: Optional[int] = None
    username: Optional[str] = None
    source: Optional[str] = ""
    account: Optional[str] = None          # 券商账号，客户端自传主标识
    broker_code: Optional[str] = None      # 历史别名，等同于 account
    broker_name: Optional[str] = None      # 可选：券商名
    remark: Optional[str] = None           # 可选：券商备注
    terminal: Optional[str] = None         # 可选：归属终端 id
    trade_date: str                  # YYYY-MM-DD，必填，归属交易日
    items: list[TradeImportItem]


class DailyTradeImportRequest(BaseModel):
    """JWT 版每日成交导入（/trading/import/daily）：按 (用户, 交易日) 全量覆盖。

    与无鉴权 /trades/import 写入同一张 biz_trades 表，供页面内手工补录 / 粘贴导入使用。
    items 为自由字段字典，由 trades_service 逐行校验。
    """
    trade_date: str
    items: list[dict]
    source: Optional[str] = "web"


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


class AiChannel(BaseModel):
    """LLM 渠道（OpenAI 兼容）。api_key 读出时脱敏，写入空表示不修改。"""
    id: str
    name: str
    provider: str
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    model: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 2048
    has_key: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AiChannelsView(BaseModel):
    active_id: Optional[str] = None
    channels: list[AiChannel] = []
    presets: dict[str, dict[str, str]] = {}


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
