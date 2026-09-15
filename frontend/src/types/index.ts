// ============================================================
// Financial data types matching the API documentation
// ============================================================

export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface DataSourceStatus {
  akshareConnected: boolean
  jisiluLoggedIn: boolean
  timestamp: string
}

export interface RealtimeQuote {
  source: string
  code: string
  name: string
  type: string
  latest_price: number
  open_price: number
  pre_close: number
  high_price: number
  low_price: number
  price_change: number
  price_change_pct: number
  volume: number
  market_time: string
  request_time: string
  delay_seconds: number
}

export interface KlineItem {
  date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
}

export interface FuturesContract {
  symbol: string
  name: string
  latest_price: number
  change_pct: number
  volume: number
  open_interest: number
  basis: number
  maturity: string
}

export interface MarketAnalysis {
  symbol: string
  spot_price: number
  futures_prices: Array<{
    contract: string
    price: number
    basis: number
    annualized_basis: number
  }>
  total_open_interest: number
  volume_today: number
  sentiment: 'bullish' | 'bearish' | 'neutral'
  analysis_time: string
}

export interface CacheConfig {
  enabled: boolean
  ttl_seconds: number
  max_size: number
  method?: string
}

export interface FavoriteItem {
  id: string
  code: string
  name: string
  type: 'index' | 'lof' | 'closed' | 'reit' | 'cb'
  added_at: string
  note?: string
}

export interface MonitorDashboard {
  system_uptime: string
  api_calls_today: number
  cache_hit_rate: number
  active_connections: number
  last_error: string | null
  services: Array<{
    name: string
    status: 'healthy' | 'degraded' | 'down'
    latency_ms: number
  }>
}

export interface IndexValuation {
  name: string
  code: string
  level: number
  change_pct: number
  pe: number | null
  pb: number | null
  pe_percentile: number | null
  pb_percentile: number | null
  category: 'undervalued' | 'normal' | 'overvalued' | 'opportunity' | 'unknown'
  change_3m_pct: number
  win_rate: number
  hasValuation?: boolean
  market: 'a_share' | 'hk' | 'us'
}

// 指数估值历史序列点（乐咕乐股真实数据，PE TTM / PB）
export interface IndexValuationHistPoint {
  date: string
  value: number
  index_level: number | null
}

// 股债利差历史序列点（ valuation_service 计算）
export interface SpreadHistoryPoint {
  date: string
  spread: number       // 股债利差(%)
  pb: number           // 当期PB
  yield_10y: number    // 10年期国债收益率(%)
  roe_mean: number     // ROE均值(小数)
  earnings_yield: number // 收益率 = ROE均值/PB (%)
}

export interface SwSector {
  code: string
  name: string
  price: number | null
  prev_close: number | null
  change_pct: number | null
  pe: number | null
  ttm_pe: number | null
  pb: number | null
  dividend_yield: number | null
  count: number | null
}

export interface SwSectorHistoryItem {
  code: string
  name: string
  date: string
  price: number | null
  prev_close: number | null
  change_pct: number | null
  pe: number | null
  ttm_pe: number | null
  pb: number | null
  dividend_yield: number | null
  count: number | null
}

/** 申万一级行业历史估值数据项（来自 index_analysis_daily_sw） */
export interface SwSectorValuationItem {
  code: string
  name: string
  date: string
  price: number | null
  change_pct: number | null
  turnover_rate: number | null
  pe: number | null
  pb: number | null
  dividend_yield: number | null
  avg_price: number | null
  turnover_ratio: number | null
  circ_market_cap: number | null
}

/** 宽基指数估值分位 + 拥挤度 */
export interface BroadIndexValuation {
  name: string
  code: string
  pb: number | null
  pe_ttm: number | null
  roe_mean: number | null       // ROE近5年均值 (%)
  spread: number | null          // 股债利差 (%)
  valuation_percentile: number | null  // 估值分位 0-100, 越小越便宜
  crowding: number | null        // 拥挤度 0-100, 越小相对越便宜
  yield_10y: number | null       // 10年期国债收益率 (%)
  cpi_yoy: number | null         // CPI同比 (%)
  is_benchmark: boolean
  pb_history: ValuationHistPoint[]
  spread_history: SpreadHistPoint[]
}

export interface ValuationHistPoint {
  date: string
  pb: number | null
  index_value: number | null
}

export interface SpreadHistPoint {
  date: string
  spread: number
  pb: number
  yield_10y: number
  roe_mean: number
  earnings_yield: number
}

export interface SwSectorStrength {
  code: string
  name: string
  today_change_pct: number | null
  cum_change_pct: number | null
  relative_strength: number | null
  pe: number | null
  pb: number | null
  dividend_yield: number | null
  latest_date: string
}

export interface ConvertibleBond {
  name: string
  code: string
  price: number
  change_pct: number
  conv_value: number
  premium_pct: number
  ytm: number
  ytm_approx?: boolean            // YTM 是否为本地近似估算(非集思录真实值)
  remaining_years: number
  rating: string
  redemption_days: number
  total_redemption_days: number
  tag: string
  tag_type: 'double_low' | 'undervalued' | 'high_risk' | 'stable_yield' | 'mean_reversion' | 'defensive'
  double_low_score?: number
  // 条款触发进度 (PRD 页面三)
  putback_days?: number
  total_putback_days?: number
  revision_days?: number
  total_revision_days?: number
  // 正股风控指标 (PRD 页面三)
  altman_z_score?: number
  pledge_rate?: number
  is_st_risk?: boolean
  stock_name?: string
  stock_code?: string
  // 转股套利可行性分析
  iv?: number                       // 隐含波动率(%)
  hv?: number                       // 正股历史波动率(%)
  is_in_conversion_period?: boolean // 是否处于转股期
  stock_limit_up?: boolean          // 正股是否涨停
  stock_price?: number              // 正股现价
  stock_change_pct?: number         // 正股涨跌幅(%)
  stock_suspended?: boolean         // 正股是否停牌
}

export interface FundItem {
  name: string
  code: string
  type: 'lof' | 'closed' | 'qdii'
  category?: 'broad' | 'industry' | 'cross_border' | 'theme'
  sub_category?: string
  price: number
  iopv: number
  premium_pct: number
  premium_percentile: number | null   // 需历史溢价率序列，无源时为 null（前端显示 -）
  net_arbitrage_yield: number
  remaining_term?: string
  annualized?: number
  est_ytm?: number
  maturity?: string
  volume: number | null               // 新浪兜底源提供成交额(元)；麦蕊源缺失时为 null
  // 套利风险量化
  subscribe_limit?: string       // 申购限额描述 (如 "限购 100 元" / "无限制" / "暂停申购")
  daily_volatility?: number      // 日波动率(%)
  holding_days?: number          // 套利资金占用天数 (T+N到账)
  is_suspended?: boolean         // 是否停牌/暂停申购
  change_pct?: number            // 涨跌幅(%)
  // 封闭基金专属
  nav?: number                   // 基金净值
  nav_date?: string              // 净值披露日期
  credit_rating?: string         // 底层持仓信用评级
  is_lof_convertible?: boolean   // 到期是否转LOF (决定折价收敛路径)
  underlying_type?: string       // 底层资产类型
}

// ETF 基金（集思录策略：折溢价套利 / 网格交易 / 行业轮动 / 估值定投）
export interface EtfFund {
  name: string
  code: string
  category: 'broad' | 'industry' | 'cross_border' | 'theme'
  sub_category?: string
  price: number
  iopv: number
  premium_pct: number
  volume: number | null          // 新浪兜底源提供成交额(元)；缺失时为 null
  // 折溢价套利
  premium_percentile: number | null   // 需历史溢价率序列，无源时为 null（前端显示 -）
  net_arbitrage_yield: number
  subscribe_limit?: string
  // 套利风险量化
  daily_volatility?: number      // 日波动率(%)
  holding_days?: number          // 套利资金占用天数 (T+N到账, 跨境ETF=2, 境内=1)
  is_suspended?: boolean         // 是否停牌/暂停申购
  // 网格交易参数（需 K 线计算，无源时为 null，前端显示 -）
  grid_low?: number | null
  grid_high?: number | null
  grid_step?: number | null
  grid_yield_est?: number | null
  // 行业轮动（需 K 线计算，无源时为 null，前端显示 -）
  momentum_score?: number | null
  // 估值定投
  pe?: number | null
  pe_percentile?: number | null
  val_category?: 'undervalued' | 'normal' | 'overvalued' | null
  dividend_rate?: number | null
  change_pct?: number
}


export interface ReitItem {
  name: string
  code: string
  market_price: number
  change_pct?: number | null
  // 以下基本面字段 AkShare 实时接口无法直接获取，缺失时为 null（不虚构数值）
  annual_distribution?: number | null
  dividend_rate?: number | null
  irr?: number | null
  occupancy_rate?: number | null
  project_name?: string | null
  // 深度分析字段
  nav?: number                   // 基金净值 (用于NAV溢折价套利)
  volume?: number                // 日成交量 (流动性风险)
  dscr?: number                  // 偿债备付率 (Debt Service Coverage Ratio)
  occupancy_trend?: number       // 出租率环比变化(%)
  asset_type?: string            // 底层资产类型 (产业园/仓储/高速公路/水务)
  leverage_ratio?: number        // 杠杆率(%)
}

export interface StrategyRule {
  id: string
  field: string
  operator: string
  value: string
  logic: 'AND' | 'OR'
}

export interface Strategy {
  id: string
  name: string
  target_asset: 'cb' | 'lof' | 'qdii' | 'reit' | 'etf' | 'fund'
  rules: StrategyRule[]
  sort_by?: string | null
  sort_order?: 'asc' | 'desc'
  limit_count?: number | null
  active: boolean
  ai_tracking?: boolean
  createdAt: string
}

// 策略字段元数据（后端 /strategies/meta 返回）
export interface AssetFieldDef {
  key: string
  label: string
  type: 'number' | 'enum' | 'text'
  unit?: string
  options?: string[]
}

export interface AssetMeta {
  key: string
  label: string
  fields: AssetFieldDef[]
}

export interface AiConfig {
  provider: string
  apiKey: string
  endpoint: string
  temperature: number
  cronExpression: string
  enabled: boolean
  model?: string
}

export interface AiReport {
  date: string
  macroAssessment: string
  strategyMatches: Array<{
    strategyName: string
    items: Array<{
      name: string
      reason: string
    }>
  }>
  arbitrageAlerts: Array<{
    name: string
    premium: number
    netYield: number
    assessment: string
  }>
  createdAt: string
}

export interface AlertRule {
  id: string
  name: string
  type: 'price' | 'premium' | 'discount' | 'ytm'
  target: string
  condition: 'above' | 'below' | 'crosses'
  value: number
  channels: Array<'popup' | 'dingtalk' | 'wechat' | 'email'>
  active: boolean
}

export interface AlertEvent {
  id: number
  rule_id: string
  triggered_at: string
  target_code: string | null
  target_name: string | null
  actual_value: number | null
  message: string | null
  is_read: boolean
}

export interface AlertScanResult {
  scanned_rules: number
  triggered_events: number
  notifications_sent: Record<string, number>
  events: AlertEvent[]
}

export interface NotificationConfig {
  wecom_webhook_url: string | null
  dingtalk_webhook_url: string | null
  email_smtp_host: string | null
  email_smtp_port: number | null
  email_username: string | null
  email_password: string | null
  email_from: string | null
  email_to: string | null
}

// ============================================================
// 持仓分析（HoldingsAnalysis）
// ============================================================

export type HoldingType = 'stock' | 'etf' | 'fund_otc' | 'option' | 'future' | 'hk_stock'

export interface Holding {
  id: string
  code: string
  name: string
  type: HoldingType
  type_label: string
  broker: string
  account: string
  quantity: number
  cost_price: number
  manual_price: number | null
  open_date: string | null
  currency: string
  price: number | null
  price_source: 'manual' | 'auto' | null
  market_value: number | null
  pnl: number | null
  pnl_pct: number | null
  daily_pnl: number | null
  daily_pct: number | null
  stop_loss_pct: number | null
  take_profit_pct: number | null
  fair_value: number | null
  val_pct: number | null
  valuation: 'over' | 'under' | 'fair' | null
  grid_lower: number | null
  grid_upper: number | null
  grid_step: number | null
  grid_signal: 'buy' | 'sell' | 'hold' | null
  grid_level: number | null
  grid_total: number | null
  grid_pos_pct: number | null
  grid_at_bound: 'low' | 'high' | null
  alert_status: 'stop_loss' | 'take_profit' | null
}

export interface HoldingAllocation {
  key: string
  label: string
  market_value: number
  weight_pct: number
}

export interface HoldingSummary {
  total_market_value: number
  total_cost: number
  total_pnl: number
  total_pnl_pct: number
  daily_pnl: number
  holding_count: number
  priced_count: number
  allocation_by_type: HoldingAllocation[]
  allocation_by_broker: HoldingAllocation[]
  allocation_by_account: HoldingAllocation[]
  warnings: Array<{ level: 'warn' | 'danger'; text: string }>
  quote_time: string | null
}

export interface HoldingsView {
  items: Holding[]
  summary: HoldingSummary
}

export interface HoldingImportResult {
  added: number
  updated: number
  failed: Array<{ index: number; code: string; reason: string }>
}

// 券商账号（个人中心维护，持仓页筛选/导入选用）
export interface BrokerAccount {
  id: string
  broker: string
  account: string
  created_at: string
  updated_at: string
}

// 账户名（独立列表，持仓页编辑时选用）
export interface AccountName {
  id: string
  name: string
  created_at: string
  updated_at: string
}

export interface HoldingSnapshot {
  id: string
  snap_date: string
  total_market_value: number
  total_cost: number
  total_pnl: number
  total_pnl_pct: number
  daily_pnl: number
  holding_count: number
  priced_count: number
  created_at: string
}

// 宏观指标（/api/v1/market/macro/indicators）
export interface MacroIndicators {
  erp: number
  erp_percentile_3y: number
  erp_percentile_5y: number
  erp_percentile_10y: number
  dr007: number
  gc001: number
}

export interface MacroData {
  erp: number
  erp_percentile_3y: number
  erp_percentile_5y: number
  erp_percentile_10y: number
  dr007: number
  gc001: number
  indices: IndexValuation[]
  // 新增：大盘行情数据
  marketOverview?: MarketOverview
  boardSectors?: BoardSector[]
  fundFlows?: FundFlows
  ztStats?: ZTStats
  fundRanking?: FundRankingItem[]
}

// 分区接口返回的附加信息（ApiResponse.meta），用于“模拟/真实数据”横幅
// 每个分区独立判断数据来源，任一接口失败/回退 mock 不影响其他模块
export interface SectionSourceMeta {
  isMock: boolean
  dataSource?: string
  mockTime?: string | null
  updateTime?: string | null
}

// 市场概况（三大指数、涨跌家数、成交额）
export interface MarketOverview {
  date: string
  status: '开盘中' | '已收盘' | '休市'
  indices: {
    name: string
    code: string
    price: number
    change: number
    changePct: number
  }[]
  upCount: number
  downCount: number
  flatCount: number
  totalVolume: number // 成交额（亿）
  volumeChange: number | null // 较上一日变化（亿），null 表示上游无数据
}

// 板块数据（行业/概念）
export interface BoardSector {
  rank: number
  name: string
  code: string
  price: number
  change: number
  changePct: number
  upCount: number
  downCount: number
  leadingStock: string
  leadingStockChange: number
  type: 'industry' | 'concept'
}

// 资金流向
export interface FundFlows {
  date: string
  mainInflow: number | null // 主力净流入（亿）
  mainInflowPct: number | null
  superLargeInflow: number | null // 超大单净流入
  superLargeInflowPct: number | null
  largeInflow: number | null // 大单净流入
  largeInflowPct: number | null
  mediumInflow: number | null // 中单净流入
  mediumInflowPct: number | null
  smallInflow: number | null // 小单净流入
  smallInflowPct: number | null
  // 行业资金流向排行
  industryFlows: IndustryFundFlow[]
  source?: 'eastmoney' | 'board_proxy'
  mainFlowAvailable?: boolean
}

export interface IndustryFundFlow {
  name: string
  inflow: number | null
  inflowPct: number | null
  changePct: number | null
}

// 涨跌停统计
export interface ZTStats {
  date: string
  ztCount: number // 涨停数
  dtCount: number // 跌停数
  ztList: ZTStock[]
  dtList: DTStock[]
  // 昨日涨停表现
  prevZTPerformance?: {
    avgChange: number
    topPerformer: string
    topPerformerChange: number
  }
}

export interface ZTStock {
  code: string
  name: string
  price: number
  changePct: number
  turnover: number
  marketCap: number
  firstZtTime: string
  lastZtTime: string
 炸板次数: number
 连板数: number
  industry: string
}

export interface DTStock {
  code: string
  name: string
  price: number
  changePct: number
  turnover: number
  marketCap: number
  continuousDt: number
  industry: string
}

// 龙虎榜数据（useMarketData 使用）
export interface LHBItem {
  rank: number
  code: string
  name: string
  date: string
  closePrice: number
  changePct: number
  netBuy: number
  buyAmount: number
  sellAmount: number
  turnover: number
  turnoverRatio: number
  reason: string
}

// 基金涨跌排行
export interface FundRankingItem {
  rank: number
  code: string
  name: string
  type: 'ETF' | 'LOF' | 'QDII' | '场外基金'
  nav: number // 净值
  changePct: number // 涨跌幅
  change: number // 涨跌额
  volume?: number // 成交额（万）
  premiumPct?: number // 折溢价率（场内基金）
}

// 贵金属: 黄金/白银现货价格 + 金银比
export interface PreciousMetalQuote {
  name: string
  symbol: string
  price: number
  unit: string
  date: string
  changePct: number | null
  rawPrice?: number // 原始报价(如白银元/千克)
  rawUnit?: string
  history: { date: string; price: number }[]
}

export interface PreciousMetals {
  available: boolean
  updatedAt?: string
  note?: string
  gold: PreciousMetalQuote
  silver: PreciousMetalQuote
  ratio: {
    current: number | null
    unit: string
    history: { date: string; ratio: number }[]
  }
}

// ============================================================
// 信号实验室（SignalLab）：按策略对单个标的物生成买卖点
// ============================================================

export interface StrategyParamDef {
  key: string
  label: string
  type: 'number'
  default?: number
  min?: number
  max?: number
  step?: number
}

export interface StrategyDef {
  id: string
  name: string
  category: string
  desc: string
  params: StrategyParamDef[]
}

export interface SignalPoint {
  date: string
  price: number
  type: 'buy' | 'sell'
  reason: string
}

export interface SignalResult {
  symbol: string
  strategy_id: string
  strategy_name: string
  name: string | null
  error?: string
  current_price: number | null
  current_position: 'long' | 'flat' | null
  latest_signal: string | null
  latest_reason: string | null
  last_signal_date: string | null
  last_signal_type: 'buy' | 'sell' | null
  signal_count: number
  signal_points: SignalPoint[]
  series: { date: string[]; close: number[] }
  kline_start: string | null
  kline_end: string | null
  kline_count: number
}

export interface TrackedSignal {
  id: string
  symbol: string
  name: string
  strategy_id: string
  strategy_name: string
  params: Record<string, any>
  created_at: string
  // 重算后补充
  current_price?: number | null
  current_position?: 'long' | 'flat' | null
  latest_signal?: string | null
  latest_reason?: string | null
  last_signal_date?: string | null
  last_signal_type?: 'buy' | 'sell' | null
  signal_count?: number
  error?: string
}

// ============================================================
// 策略中心 · 经典实盘策略库（Library）
// ============================================================

export interface LibraryParamDef {
  key: string
  label: string
  type: string // number | switch
  default: number
  min?: number
  max?: number
  step?: number
  help?: string
}

export interface LibraryStrategy {
  id: string
  name: string
  category: string
  source: string
  source_note: string
  style: string
  desc: string
  params: LibraryParamDef[]
  kind: 'cb_snapshot' | 'index_rotation'
  members: { code: string; name: string }[]
}

export interface CbBrief {
  code: string
  name: string
  price: number
  premium_pct: number
  double_low_score: number
  ytm?: number
  rating?: string
  stock_name?: string | null
}

export interface HoldingSuggestion {
  code: string
  name: string
  mom_pct: number
  action: string
  members_mom: { code: string; name: string; mom_pct: number }[]
}

export interface BacktestPerf {
  kind?: string
  error?: string
  start_date?: string
  end_date?: string
  trading_days?: number
  cum_return_pct?: number
  annual_return_pct?: number
  max_drawdown_pct?: number
  sharpe?: number
  win_rate_pct?: number
  trades?: number
  excess_pct?: number
  benchmark?: { name: string; cum_return_pct: number; annual_return_pct?: number; max_drawdown_pct?: number }
  curve?: { date: string[]; strategy_nav: number[]; benchmark_nav: number[] }
  current_holding?: HoldingSuggestion | null
  recent_switches?: { date: string; holding: string; code: string; reason: string }[]
  // CB 实时快照
  universe_count?: number
  avg_double_low?: number | null
  avg_price?: number | null
  avg_premium_pct?: number | null
  portfolio?: CbBrief[]
  top_ranking?: CbBrief[]
  note?: string
  updated_at?: string
  hold_n?: number
}

export interface LibraryBacktestResult {
  strategy_id: string
  strategy_name: string
  category: string
  source: string
  source_note: string
  params: Record<string, any>
  backtest: BacktestPerf
}

export interface TrackedLibrary {
  id: string
  library_id: string
  strategy_name: string
  category: string
  source: string
  params: Record<string, any>
  created_at: string
  error?: string
  perf?: {
    kind: string
    cum_return_pct?: number
    annual_return_pct?: number
    max_drawdown_pct?: number
    sharpe?: number
    win_rate_pct?: number
    trades?: number
    excess_pct?: number
    end_date?: string
    universe_count?: number
    avg_double_low?: number | null
    avg_price?: number | null
    avg_premium_pct?: number | null
  }
  portfolio?: CbBrief[]
  current_holding?: HoldingSuggestion | null
  curve?: { date: string[]; strategy_nav: number[]; benchmark_nav: number[] }
  history?: { date: string; cum_return_pct?: number; excess_pct?: number; max_drawdown_pct?: number; avg_double_low?: number }[]
}
