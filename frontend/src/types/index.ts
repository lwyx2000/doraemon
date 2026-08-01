// ============================================================
// Financial data types matching the API documentation
// ============================================================

export interface ApiResponse<T> {
  code: number
  message: string
  data: T
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
  level: number
  change_pct: number
  pe: number
  pb: number
  pe_percentile: number
  pb_percentile: number
  category: 'undervalued' | 'normal' | 'overvalued' | 'opportunity'
  change_3m_pct: number
  win_rate: number
}

export interface ConvertibleBond {
  name: string
  code: string
  price: number
  change_pct: number
  conv_value: number
  premium_pct: number
  ytm: number
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
  price: number
  iopv: number
  premium_pct: number
  premium_percentile: number
  net_arbitrage_yield: number
  remaining_term?: string
  annualized?: number
  est_ytm?: number
  maturity?: string
  volume: number
  // 套利风险量化
  subscribe_limit?: string       // 申购限额描述 (如 "限购 100 元" / "无限制")
  daily_volatility?: number      // 日波动率(%)
  holding_days?: number          // 套利资金占用天数 (T+N到账)
  is_suspended?: boolean         // 是否停牌/暂停申购
  // 封闭基金专属
  nav?: number                   // 基金净值
  credit_rating?: string         // 底层持仓信用评级
  is_lof_convertible?: boolean   // 到期是否转LOF (决定折价收敛路径)
  underlying_type?: string       // 底层资产类型
}

// ETF 基金（集思录策略：折溢价套利 / 网格交易 / 行业轮动 / 估值定投）
export interface EtfFund {
  name: string
  code: string
  category: 'broad' | 'industry' | 'cross_border' | 'theme'
  sub_category: string
  price: number
  iopv: number
  premium_pct: number
  volume: number
  // 折溢价套利
  premium_percentile: number
  net_arbitrage_yield: number
  subscribe_limit?: string
  // 套利风险量化
  daily_volatility?: number      // 日波动率(%)
  holding_days?: number          // 套利资金占用天数 (T+N到账, 跨境ETF=2, 境内=1)
  is_suspended?: boolean         // 是否停牌/暂停申购
  // 网格交易参数
  grid_low: number
  grid_high: number
  grid_step: number
  grid_yield_est: number
  // 行业轮动
  momentum_score: number
  // 估值定投
  pe?: number
  pe_percentile?: number
  val_category?: 'undervalued' | 'normal' | 'overvalued'
  dividend_rate?: number
}


export interface ReitItem {
  name: string
  code: string
  market_price: number
  annual_distribution: number
  dividend_rate: number
  irr: number
  occupancy_rate: number
  project_name: string
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
  target_asset: 'cb' | 'lof' | 'reit'
  rules: StrategyRule[]
  active: boolean
  createdAt: string
}

export interface AiConfig {
  provider: string
  apiKey: string
  endpoint: string
  temperature: number
  cronExpression: string
  enabled: boolean
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

export interface MacroData {
  erp: number
  erp_percentile_3y: number
  erp_percentile_5y: number
  erp_percentile_10y: number
  dr007: number
  gc001: number
  indices: IndexValuation[]
}
