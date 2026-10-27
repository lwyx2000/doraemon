// ============================================================
// Financial data types matching the API documentation
// ============================================================

export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

// ---- 认证相关类型 ----
export interface LoginResult {
  token: string
  expires_at: string
  username: string
  is_admin?: boolean
  force_change?: boolean
}

export interface AdminUserItem {
  pk_user: number
  username: string
  is_admin: boolean
  must_change_password: boolean
}

export interface AdminListUsersResponse {
  users: AdminUserItem[]
}

export interface AdminResetPasswordResponse {
  username: string
  new_password: string
  must_change_password: boolean
}

export interface DataSourceStatus {
  akshareConnected: boolean
  jisiluLoggedIn: boolean
  /** 上游细分状态：no_cookie（未配置）/ cookie_invalid（已失效）/ logged_in */
  jisiluStatus?: string | null
  /** 上游给的中文说明 */
  jisiluMessage?: string | null
  /** 是否已配置 cookie（区分「没配」与「过期」） */
  jisiluHasCookie?: boolean | null
  /** 上游是否支持动态登录（支持则无需人工刷新） */
  jisiluCanDynamicLogin?: boolean | null
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
  // 上游行情缺失时为 null（显示"—"），与后端 models.IndexValuation 一致
  level: number | null
  change_pct: number | null
  pe: number | null
  pb: number | null
  pe_percentile: number | null
  pb_percentile: number | null
  category: 'undervalued' | 'normal' | 'overvalued' | 'opportunity' | 'unknown'
  change_3m_pct: number | null
  /** 条件胜率（±10% PE 区间持有 3 个月正收益占比），后端同口径实算；样本不足或无历史序列时为 null */
  win_rate: number | null
  /** 近1年涨跌幅（%）：同口径 PB/PE 历史序列月度桶实算，替代 win_rate 列 */
  change_1y_pct?: number | null
  hasValuation?: boolean
  market: 'a_share' | 'hk' | 'us'
  /** 上游行情快照日期（YYYY-MM-DD），如 2026-10-13 */
  valuation_date?: string | null
  /** PE/PB 历史快照日期（YYYY-MM-DD，每日 18:35 写入），分位即基于该序列 */
  pe_as_of?: string | null
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
  zscore?: number | null  // 该时点「10年滚动 MAD 稳健 Z-score」
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

/** 行业热力图趋势：单个行业在窗口内的每日涨跌幅与当日排名 */
export interface SwRankTrendDailyItem {
  date: string
  change_pct: number
  rank: number
}

/** 行业热力图趋势：单个行业（按窗口内平均排名升序排列） */
export interface SwRankTrendSector {
  code: string
  name: string
  avg_rank: number | null
  daily: SwRankTrendDailyItem[]
}

/** 行业热力图趋势数据（GET /market/sw-sectors/rank-trend） */
export interface SwRankTrendData {
  dates: string[]
  sectors: SwRankTrendSector[]
  meta: { trade_days: number; latest_date: string | null }
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
  // 等权(eq)/中位(med)口径（2026-10-27，与 legulegu 等权/中位对齐）
  pb_eq: number | null
  pb_med: number | null
  pe_ttm_eq: number | null        // PE(TTM)纳亏 等权
  pe_ttm_med: number | null       // PE(TTM)纳亏 中位
  pe_ttm_ex_eq: number | null     // PE(TTM)剔亏 等权
  pe_ttm_ex_med: number | null    // PE(TTM)剔亏 中位
  roe_mean: number | null       // ROE近5年均值 (%)
  spread: number | null          // 股债利差 (%)
  valuation_percentile: number | null  // 估值分位 0-100, 越小越便宜
  pe_percentile: number | null    // PE 历史分位 0-100, 高=贵
  pb_percentile: number | null    // PB 历史分位 0-100, 高=贵
  // 近 10Y（120 个月）窗口分位：对齐万得/中证官方常用口径，可直接跨源对比
  pe_percentile_10y?: number | null
  pb_percentile_10y?: number | null
  // 等权/中位分位（全史 + 近10Y），与加权口径一致
  pb_eq_percentile?: number | null
  pb_eq_percentile_10y?: number | null
  pb_med_percentile?: number | null
  pb_med_percentile_10y?: number | null
  pe_ttm_eq_percentile?: number | null
  pe_ttm_eq_percentile_10y?: number | null
  pe_ttm_med_percentile?: number | null
  pe_ttm_med_percentile_10y?: number | null
  pe_ttm_ex_eq_percentile?: number | null
  pe_ttm_ex_eq_percentile_10y?: number | null
  pe_ttm_ex_med_percentile?: number | null
  pe_ttm_ex_med_percentile_10y?: number | null
  crowding: number | null        // 拥挤度 0-100, 越小相对越便宜
  // ERP 稳健 Z-score（MAD，最近10年滚动窗口）：>1.5 低估 / <-1.5 高估 / 之间 中性
  erp_zscore: number | null
  erp_zscore_class: 'low' | 'neutral' | 'high' | null
  erp_zscore_median?: number | null
  erp_zscore_mad?: number | null
  erp_zscore_window_samples?: number | null
  insufficient_history?: boolean  // 历史样本不足（< MIN_HISTORY_SAMPLES），分位已置空
  history_samples?: number | null // 可用的 PB 历史月度样本数
  yield_10y: number | null       // 10年期国债收益率 (%)
  cpi_yoy: number | null         // CPI同比 (%)
  is_benchmark: boolean
  pb_history: ValuationHistPoint[]
  pe_history: PeHistPoint[]
  price_history: PriceHistPoint[]
  spread_history: SpreadHistPoint[]
}

export interface ValuationHistPoint {
  date: string
  pb: number | null
  index_value: number | null
  // 等权/中位口径（2026-10-27），供详情抽屉画对比线
  pb_eq?: number | null
  pb_med?: number | null
}

export interface PeHistPoint {
  date: string
  /** 纳亏口径（亏损股进分母）：绝对值展示 */
  pe_ttm: number | null
  /** 剔亏口径（仅聚 PE>0）：分位计算基准；旧行为 null，消费方回退 pe_ttm */
  pe_ttm_ex?: number | null
  pe_static: number | null
  // 等权/中位口径（2026-10-27）
  pe_ttm_eq?: number | null
  pe_ttm_med?: number | null
  pe_ttm_ex_eq?: number | null
  pe_ttm_ex_med?: number | null
}

export interface PriceHistPoint {
  date: string
  value: number
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

/** 申万一级行业估值分位 + 拥挤度 */
export interface IndustryValuation {
  code: string
  name: string | null
  pe: number | null
  pb: number | null
  dividend_yield: number | null
  pe_percentile: number | null   // PE 历史分位 0-100, 高=贵
  pb_percentile: number | null   // PB 历史分位 0-100, 高=贵
  crowding: number | null        // 行业PB/全APB 历史分位 0-100, 高=相对贵
  month_points: number
  data_points: number
}

// 网关 /api/project/info 自描述信息（doraemon 后端透传，结构以网关为准，故字段宽松）
export interface ProjectInfo {
  meta?: {
    name?: string
    version?: string
    description?: string
    capabilities?: string[]
    tech_stack?: string[]
  }
  api_count?: number
  datasources?: {
    count?: number
    categories?: Record<string, {
      name?: string
      description?: string
      status?: string
      sources?: Array<{ name?: string; status?: string; [k: string]: any }>
      [k: string]: any
    }>
    [k: string]: any
  }
  failover_chains?: Record<string, {
    level?: string
    chain?: string[]
    healthy?: string[]
    [k: string]: any
  }>
  api_catalog?: Array<{
    group?: string
    method?: string
    path?: string
    source?: string
    failover?: string
    [k: string]: any
  }>
  cache_strategy?: any
  [key: string]: any
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
  // 申赎 / 费率（后端新列：麦蕊日度快照 + 本地费率库）
  nav_date?: string | null              // 净值披露日期
  share?: number | null                 // 最新份额(亿份)
  scale?: number | null                 // 最新规模(亿元)
  mgmt_fee?: number | null              // 管理费率(%)
  custody_fee?: number | null           // 托管费率(%)
  subscribe_fee?: number | null         // 最高申购费率(%)
  redemption_fee?: number | null        // 最高赎回费率(%)
  net_subscribe_share?: number | null   // 日净申赎份额(亿份，正=净申购/流入)
  net_subscribe_amount?: number | null  // 日净申赎额(亿元，正=净申购/流入)
  net_subscribe_date?: string | null    // 快照截止日期
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

/** LLM 渠道（OpenAI 兼容多渠道，api_key 读出脱敏） */
export interface AiChannel {
  id: string
  name: string
  provider: string
  apiKey: string
  endpoint: string
  model: string
  temperature: number
  maxTokens: number
  hasKey: boolean
  createdAt?: string
  updatedAt?: string
}

export interface AiChannelPreset {
  label: string
  endpoint: string
  model: string
}

export interface AiChannelsView {
  activeId: string | null
  channels: AiChannel[]
  presets: Record<string, AiChannelPreset>
}

/** 知识库 */
export interface KnowledgeDocMeta {
  id: string
  category: string
  title: string
  file?: string
  tags: string[]
  /** import=用户导入（SQLite 持久化，可启停/删除）；缺省=内置（随镜像分发，只读） */
  source?: 'builtin' | 'import'
  enabled?: boolean
  char_count?: number
  updated_at?: string
}

export interface KnowledgeDoc extends KnowledgeDocMeta {
  content: string
}

export interface KnowledgeIndex {
  version: number
  updated: string
  categories: Array<{ id: string; name: string; icon: string }>
  docs: KnowledgeDocMeta[]
}

/** AI 流式（SSE）事件 */
export interface AiStreamMeta {
  type: 'meta'
  context_type?: string
  context?: Record<string, unknown> | null
  docs?: Array<{ id?: string; title?: string; snippet?: string; source?: 'builtin' | 'import' }>
}

export interface AiStreamError {
  type: 'error'
  code: string
  message: string
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

// 历史持仓（已平仓，从「当前持仓」删除动作归档而来）
export interface HoldingHistory {
  id: string
  code: string
  name: string
  type: HoldingType
  broker: string
  account: string
  quantity: number
  cost_price: number
  close_price: number | null
  realized_pnl: number | null
  open_date: string | null
  currency: string
  closed_at: string | null
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
  gatewayEmpty?: boolean
  note?: string | null
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
  prevDayVolume?: number | null // 上一日成交额（亿），来自本地每日落库；null 表示无历史
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

// 贪婪恐惧指数（Fear & Greed Index）：6 指标 min-max 加权情绪温度计
// 计分：上涨占比 0.25 + 涨停(剔ST) 0.20 + 指数距52周高点 0.15 + 量能比 0.20
//       + 融资余额20日变化 0.10 + (100 − 波动率得分) 0.10；缺失分项按权重归一化
export interface FearGreedPoint {
  date: string
  // 原始指标
  rawAdvanceRatio: number | null // 上涨家数占比（0-1）
  rawLimitUp: number | null // 涨停家数（剔 ST）
  rawPosition: number | null // 上证指数距 52 周高点（%）
  rawTurnoverRatio: number | null // 量能比：当日成交额 ÷ 20 日均
  rawMarginChg20: number | null // 沪市融资余额 20 日变化率（%）
  rawVol20: number | null // 上证指数 20 日年化波动率（%）
  // 分项得分（0-100，波动率已反向）
  advance: number | null
  limitUp: number | null
  position: number | null
  turnover: number | null
  margin: number | null
  vol: number | null
  totalScore: number | null // 恐贪总值（缺失分项按权重归一化）
  componentsUsed: number // 参与合计的分项数（<6 即回填近似日）
  source: string | null // live=定时采集 / backfill=历史回填
  capturedAt: string | null
}

export interface FearGreedLatest extends FearGreedPoint {
  label?: string // 档位：极度恐慌 / 均衡 / 极度贪婪
}

export interface FearGreedStatus {
  rows: number
  firstDate: string | null
  lastDate: string | null
  scheduler?: {
    running: boolean
    collectTime: string
    backfill: { running: boolean }
  }
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

/** 战术信号快照（批量接口，基于 qfq 前复权日线） */
export interface TacticalSignal {
  symbol: string
  price: number | null
  /** MA20 偏离度(%)：(close − MA20) / MA20 × 100 */
  bias_20: number | null
  rsi_14: number | null
  /** 布林位置：0=下轨, 100=上轨 */
  boll_pos: number | null
  ma_20: number | null
  date: string | null
  error: string | null
}

/** 单持有期胜率统计（次日收盘买入、持有N日收盘卖出、已扣成本） */
export interface WinrateStats {
  samples: number
  win_rate: number | null
  avg_gain: number | null
  avg_loss: number | null
  /** 赔率 = 平均盈利 / |平均亏损|；无亏损样本为 null */
  payoff: number | null
  /** 凯利 f*（封顶20%，负期望=0），单位 % */
  kelly: number | null
  /** 半凯利 = f* 的一半，建议仓位 */
  half_kelly: number | null
  // 以下为 P3 防过拟合字段（v2 扫描结构），旧缓存可能缺失 → 全部可选
  /** 样本内（前 70% 时段）样本数 */
  is_samples?: number
  /** 样本内胜率 (%) */
  is_win_rate?: number | null
  /** 样本外（后 30% 时段，策略没见过的验证段）样本数 */
  oos_samples?: number
  /** 样本外胜率 (%) */
  oos_win_rate?: number | null
}

/** 分年度胜率项（10日持有期口径） */
export interface WinrateYearlyItem {
  year: string
  samples: number
  win_rate: number | null
}

/** 单只标的胜率扫描结果 */
export interface WinrateScanItem {
  symbol: string
  error: string | null
  triggers: number
  stats_5d: WinrateStats | null
  stats_10d: WinrateStats | null
  stats_20d: WinrateStats | null
  /** 近 3 年分年度胜率（10日口径）；数据不足/出错时为 null */
  yearly_10d?: WinrateYearlyItem[] | null
}

/** 胜率扫描响应 */
export interface WinrateScanResult {
  scan_date: string
  from_cache: boolean
  results: WinrateScanItem[]
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

// ===================== 红利策略研究（红利基金研究页） =====================
export interface DividendSignal {
  action: 'add' | 'hold_low' | 'hold' | 'stop' | 'reduce'
  label: string
  color: string
  reason: string
}

export interface DividendIndexMetric {
  code: string
  name: string
  pe: number | null
  pe_date: string | null
  pe_percentile: number | null
  pe_min: number | null
  pe_max: number | null
  pe_p25: number | null
  pe_median: number | null
  pe_p75: number | null
  window_days: number | null
  window_start: string | null
  /** PE 数据陈旧标记：中证接口不可用，PE 沿用本地序列最后一期 */
  pe_stale: boolean
  dividend_yield: number | null
  dy_date: string | null
  dy_stale: boolean
  yield_10y: number | null
  eb_ratio: number | null
  dy_spread: number | null
  signals: { eb: DividendSignal | null; pe: DividendSignal | null; dy: DividendSignal | null }
  conflict: boolean
  pe_series: { date: string; pe: number | null }[]
}

export interface DividendFund {
  code: string
  name: string
  type: string
  market: string
  share_class: string
  index_code: string | null
  index_name: string | null
  pe: number | null
  pe_percentile: number | null
  dividend_yield: number | null
  eb_ratio: number | null
  signals: DividendIndexMetric['signals'] | null
  // 规模 / 费率：由 fund_fee_service 后台渐进补全（同花顺 fund_info_ths，落 DuckDB）
  scale: number | null
  scale_date: string | null
  mgmt_fee: number | null
  custody_fee: number | null
  subscribe_fee: number | null
  manager: string | null
  /** 识别不上时它实际跟踪的指数原文（如「标普中国A股红利机会指数收益率」），用于说明留空原因 */
  tracking_text?: string | null
  // 三类补充指标（fund_extra_metrics_service 后台渐进补全，落 DuckDB）
  tracking_error: number | null
  tracking_error_n?: number | null
  payout_freq: number | null
  sector_concentration: number | null
  sector_count?: number | null
  /** 现金流线专用：股息率拿不到时，后端给出的具体原因（前端据此显示「为什么是 —」） */
  dy_reason?: string | null
  dy_date?: string | null
  /** 现金流线专用：指数 PE 的估值日期（红利的同名指标也用它提示新鲜度） */
  pe_date?: string | null
}

export interface DividendFeeProgress {
  filled: number
  total: number
  running: boolean
  round_done: number
  round_total: number
  ok: number
  fail: number
  skipped: number
  rounds: number
  started_at: string | null
  finished_at: string | null
  last_error: string | null
  /** 上一轮是否因疑似限流而中止 */
  throttled: boolean
  /** 连续被限流中止的次数 */
  throttle_streak: number
  /** 下一次自动续跑还需等待的小时数（0 = 无需等待） */
  retry_in_hours: number
  /** 永久失败、后台不再重试的基金只数（上游彻底无数据等不可恢复原因） */
  perm_failed: number
}

/**
 * 现金流基金名录（独立一条线，2026-10-07 用户拍板「单开 Tab」）。
 * 复用 DividendFund 字段结构：规模/费率同样是后台补全列位（当前未纳入补全清单，显示 —）。
 */
export interface CashflowOverview {
  /** ⚠️ 只吐 etf（场内 ETF）：场外 A/C/E 份额不进这条线（2026-10-07 用户拍板「只要场内」） */
  funds: { etf: DividendFund[] }
  counts: {
    etf: number
    /** 已回填到真实跟踪指数的不同指数个数（中证 932365/932366/932367/932368/932369 + 国证 980092） */
    index: number
    /** 拿到官方 PE 估值的指数个数（只有中证那 5 个；国证 / 富时两个源都不覆盖） */
    index_valued: number
    excluded: number
    excluded_detail: Record<string, number>
  }
  /**
   * 现金流指数估值（2026-10-07 用户拍板「要补估值」）。
   * 只有 PE 一路：中证官方「滚动市盈率」（随指数日频发布）。
   * ⚠️ 股息率恒 None——现金流类不是股息导向，中证不披露官方股息率，且官方估值接口当前不可用。
   */
  indices: DividendIndexMetric[]
  /** 估值源覆盖不到的指数 → 带 reason，前端照着解释「为什么没有」，不假填数 */
  no_data_indices: { code: string; name: string; reason: string }[]
  yield_10y: number | null
  /** 口径说明原文本，前端 Tab 顶部直接展示，避免被当成官方编制 */
  gate: string
  updated_at: string
  /** 指数估值的更新时间（与名录各自独立缓存，分开展示） */
  index_updated_at: string
  fee_progress: DividendFeeProgress | null
  extra_progress: DividendFeeProgress | null
}

/** 中证官方指数信息（编制说明 / 简称全称 / 调样频率），null = 中证取数失败，不 mock */
export interface DividendIndexCompilation {
  code: string
  name: string | null
  full_name: string | null
  desc: string | null
  adj_freq: string | null
  weighting: string | null
  compliance: string | null
  fetched_at: string | null
}

/** 点指数行弹窗：跟踪该指数的场内/场外基金 + 编制说明 + 代表基金业绩比较基准 */
export interface DividendIndexFunds {
  code: string
  name: string | null
  pe: number | null
  pe_percentile: number | null
  dividend_yield: number | null
  eb_ratio: number | null
  signals: DividendIndexMetric['signals'] | null
  compilation: DividendIndexCompilation | null
  benchmark_samples: { code: string; name: string | null; benchmark: string }[]
  funds: { onshore: DividendFund[]; offshore: DividendFund[] }
  counts: { onshore: number; offshore: number; total: number }
}

/** 「业绩比较基准 → 跟踪指数」识别进度 */
export interface DividendIndexMapProgress {
  ok: boolean
  matched: number
  this_round: number
  throttled: boolean
  retry_in_hours: number
}

/** 单只红利基金的季报持仓（东财 fund_portfolio_hold_em，T-1 季度口径） */
export interface DividendFundHoldings {
  code: string
  quarter: string | null
  source: string | null
  stock_count: number
  row_count: number
  fetched_at: string | null
  stale: boolean
  rows: {
    stock_code: string
    stock_name: string | null
    pct: number | null
    shares: number | null
    mv: number | null
    quarter: string | null
    seq: number | null
  }[]
}

export interface DividendOverview {
  updated_at: string
  yield_10y: number | null
  yield_10y_date: string | null
  indices: DividendIndexMetric[]
  funds: { etf: DividendFund[]; passive: DividendFund[]; active: DividendFund[] }
  fee_progress: DividendFeeProgress | null
  extra_progress: DividendFeeProgress | null
  counts: {
    etf: number
    passive: number
    /** ⚠️ 名录口径（2026-10-06）：纯债/主动不进名录，该桶恒为 0 */
    active: number
    index: number
    /** 被闸门剔除的只数合计（不含「名字不命中红利关键词」的全市场其余基金） */
    excluded: number
    /** 剔除明细：non_passive=主动 / bond=纯债 / money=货币 / no_name_hit=名字不命中 */
    excluded_detail: { non_passive: number; bond: number; money: number; no_name_hit: number }
  }
  thresholds: {
    eb_add: number
    eb_low: number
    eb_risk: number
    pe_reduce: number
    pe_stop: number
    pe_add: number
    dy_hold: number
    dy_stop: number
  } | null
  pending_fields: string[]
}

// ===================== 后台任务监控（任务监控页） =====================
export interface JobRun {
  started_at: string | null
  finished_at: string | null
  status: 'running' | 'success' | 'failed'
  duration_ms: number | null
  error: string | null
}

export interface JobInfo {
  job_id: string
  name: string
  schedule: string
  job_type: string // scheduled | manual | startup
  enabled: boolean
  triggerable: boolean
  last_run_at: string | null
  last_status: 'never' | 'success' | 'failed' | 'running'
  last_status_label: string
  last_duration_ms: number | null
  last_error: string | null
  next_run_at: string | null
  run_count: number
  fail_count: number
  recent_runs: JobRun[]
}

// ============================================================
// 长期视角（老钱日日谈 A股看板数据源，爬取落库）
// 数据来源：https://ashare.laoqianriritan.com（页面须注明来源与抓取时间）
// ============================================================

/** 单源抓取状态（后端 base_lqr_source_meta，查询响应统一附带） */
export interface LqrSourceMeta {
  fetchedAt: string | null // 我方抓取时间（CST）
  upstreamUpdated: string | null // 上游数据生成/更新时间
  rows: number
  ok: boolean
  error?: string | null
}

/** 行业 CAGR 指标 */
export interface LqrIndustryMetrics {
  cagrFull: number | null // 全区间年化（2005 起）
  cagr7y: number | null
  cagr5y: number | null
  cagr3y: number | null
}

/** 申万行业年度涨跌幅（热力图） */
export interface LqrSwIndustry {
  name: string
  code: string
  rets: (number | null)[] // 与 years 平行的年度涨跌幅（%）
  ytd: number | null // 年内至今涨跌幅（%）
  ytdYear: number | null
  metrics: LqrIndustryMetrics | null
}

export interface LqrSwReturns extends LqrSourceMeta {
  years: number[]
  industries: LqrSwIndustry[]
}

/** 指数收益三因子拆解项 */
export interface LqrReturnDecompItem {
  code: string
  name: string
  start: string
  end: string
  totalReturnPct: number | null // 全收益区间涨幅（%）
  dividendPct: number | null // 股息贡献（%）
  earningsPct: number | null // 盈利贡献（%）
  valuationPct: number | null // 估值贡献（%）
  peStart: number | null
  peEnd: number | null
}

export interface LqrReturnDecomp extends LqrSourceMeta {
  indexes: LqrReturnDecompItem[]
}

/** 趋势温度：个股 MA250 上方占比（日频） */
export interface LqrStockMaPoint {
  date: string
  total: number | null
  aboveMa250: number | null
  pctAbove: number | null
}

/** 趋势温度：行业 MACD>0 占比（月频） */
export interface LqrIndustryMacdPoint {
  date: string // YYYY-MM
  total: number | null
  positiveCount: number | null
  pctPositive: number | null
}

export interface LqrTrendTemperature extends LqrSourceMeta {
  stockMa250: LqrStockMaPoint[]
  industryMacd: LqrIndustryMacdPoint[]
}

/** 宽基指数全收益净值序列 */
export interface LqrWideBaseSeries {
  name: string
  note: string
  dates: string[]
  values: (number | null)[]
}

export interface LqrWideBase extends LqrSourceMeta {
  series: Record<string, LqrWideBaseSeries>
}

/** 华证六因子净值序列 */
export interface LqrHuazhengSeries {
  name: string
  dates: string[]
  values: (number | null)[]
}

export interface LqrHuazheng extends LqrSourceMeta {
  factors: Record<string, LqrHuazhengSeries>
}

/** 长期视角数据状态（/longterm/status） */
export interface LqrStatus {
  swReturns: number
  swMetrics: number
  returnDecomp: number
  trendTemp: number
  wideBase: number
  huazheng: number
  sources: Record<string, LqrSourceMeta>
  scheduler?: {
    running: boolean
    collectTime: string
    manualCollect: { running: boolean }
  }
}
