// ============================================================
// API client for the Financial Data Gateway
// ============================================================

// 未显式配置 VITE_API_BASE 时，默认走「当前页面同源」由 nginx 反代 /api 到 backend，
// 这样无论用哪个 IP/域名访问都能自动适配，不再写死 127.0.0.1:8001 导致浏览器 Failed to fetch。
const API_BASE = import.meta.env.VITE_API_BASE || (typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:8001')

export class ApiError extends Error {
  status: number
  data?: unknown

  constructor(status: number, message: string, data?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

/**
 * 发送请求并返回 { data, meta }。
 * meta 为后端 ApiResponse 中的附加信息（如数据来源标记 isMock/dataSource）。
 */
async function requestWithMeta<T>(
  path: string,
  params?: Record<string, string | number | undefined | null>,
  options?: RequestInit
): Promise<{ data: T; meta?: SectionSourceMeta }> {
  const url = new URL(path, API_BASE)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    })
  }

  const isFormData = options?.body instanceof FormData
  const res = await fetch(url.toString(), {
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...(localStorage.getItem('qt_token') ? { Authorization: `Bearer ${localStorage.getItem('qt_token')}` } : {}),
      ...options?.headers,
    },
    ...options,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(
      res.status,
      body.message || `HTTP ${res.status}`,
      body
    )
  }

  const json = await res.json()
  // The API wraps responses in { code, message, data }
  if (json.code !== undefined && json.code !== 200) {
    throw new ApiError(json.code, json.message || 'Unknown error', json)
  }

  return { data: json.data ?? json, meta: json.meta }
}

async function request<T>(
  path: string,
  params?: Record<string, string | number | undefined | null>,
  options?: RequestInit
): Promise<T> {
  const res = await requestWithMeta<T>(path, params, options)
  return res.data
}

export const api = {
  // ============================================================
  // 大盘宏观数据（Dashboard / IndexAnalysis 分区接口）
  // ============================================================
  // 宏观指标（ERP / DR007 / GC001）
  getMacroIndicators: () =>
    requestWithMeta<MacroIndicators>('/api/v1/market/macro/indicators'),

  // 市场概况（指数行情、涨跌家数、成交额）
  getMarketOverview: () =>
    requestWithMeta<MarketOverview>('/api/v1/market/overview'),

  // 板块涨幅排行
  getMarketBoardSectors: () =>
    requestWithMeta<BoardSector[]>('/api/v1/market/board-sectors'),

  // 资金流向
  getMarketFundFlows: () =>
    requestWithMeta<FundFlows>('/api/v1/market/fund-flows'),

  // 涨跌停统计
  getMarketZTStats: () =>
    requestWithMeta<ZTStats>('/api/v1/market/zt-stats'),

  // 基金涨跌排行
  getMarketFundRanking: () =>
    requestWithMeta<FundRankingItem[]>('/api/v1/market/fund-ranking'),

  // 指数估值（跨市场指数估值表）
  getIndices: (category?: string, date?: string) =>
    requestWithMeta<IndexValuation[]>('/api/v1/market/indices', { category, date }),

  // 指数历史 K 线
  getIndexHistory: (code: string) =>
    requestWithMeta<{ date: string; open: number; close: number; high: number; low: number; volume: number }[]>(
      `/api/v1/market/indices/${code}/history`
    ),

  // 指数估值历史序列（乐咕乐股真实数据：PE TTM / PB，供估值带图表）
  getIndexValuationHistory: (name: string, indicator: 'pe' | 'pb') =>
    requestWithMeta<IndexValuationHistPoint[]>('/api/v1/market/indices/valuation-history', { name, indicator }),

  // 数据源连接状态（AkShare 可达 + 集思录登录/可用态）
  getDataSourceStatus: () =>
    requestWithMeta<DataSourceStatus>('/api/v1/market/status'),

  // 贵金属：黄金/白银现货价格 + 金银比（上海黄金交易所 Au99.99 / Ag99.99）
  getPreciousMetals: () =>
    requestWithMeta<PreciousMetals>('/api/v1/market/precious-metals'),

  // 申万一级行业热力图（实时涨跌幅 + PE/PB/股息率，本地 akshare）
  getSwSectors: () =>
    requestWithMeta<SwSector[]>('/api/v1/market/sw-sectors'),

  // 申万一级行业历史走势（单个行业，从 DuckDB 快照读取）
  getSwSectorHistory: (sectorCode: string, days: number = 120) =>
    request<SwSectorHistoryItem[]>(`/api/v1/market/sw-sectors/${sectorCode}/history`, { days }),

  // 申万一级行业相对强度（近 N 日累计涨跌幅 vs 当日涨跌幅）
  getSwSectorStrength: (days: number = 5) =>
    request<SwSectorStrength[]>('/api/v1/market/sw-sectors/relative-strength', { days }),

  // 申万一级行业历史估值数据（PE / PB / 股息率，来自 AkShare index_analysis_daily_sw）
  getSwSectorValuationHistory: (sectorCode?: string, startDate?: string, endDate?: string) =>
    request<SwSectorValuationItem[]>('/api/v1/market/sw-sectors/valuation-history', {
      sector_code: sectorCode,
      start_date: startDate,
      end_date: endDate,
    }),

  // ============================================================
  // 基金数据（LOF / ETF / 封基）
  // ============================================================
  getFunds: (type?: string, min_premium?: number, feasibility?: string) =>
    request<FundItem[]>('/api/v1/funds', { type, min_premium, feasibility }),

  getClosedFundAnalysis: () =>
    request<FundItem[]>('/api/v1/funds/closed/analysis'),

  // ---- Convertible Bonds ----
  getConvertibleBonds: () =>
    request<ConvertibleBond[]>('/api/v1/cb/convertible-bonds'),

  // ---- REITs ----
  getReits: () =>
    request<ReitItem[]>('/api/v1/reits/reits'),

  // ============================================================
  // 预警中心（AlertCenter）
  // ============================================================
  getAlertRules: () =>
    request<AlertRule[]>('/api/v1/alerts/rules'),

  createAlertRule: (body: Partial<AlertRule>) =>
    request<AlertRule>('/api/v1/alerts/rules', undefined, {
      method: 'POST',
      body: JSON.stringify({
        name: body.name,
        type: body.type,
        target: body.target,
        condition: body.condition,
        value: body.value,
        channels: body.channels,
      }),
    }),

  updateAlertRule: (id: string, body: Partial<AlertRule>) =>
    request<AlertRule>(`/api/v1/alerts/rules/${id}`, undefined, {
      method: 'PUT',
      body: JSON.stringify({ name: body.name, active: body.active }),
    }),

  deleteAlertRule: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/alerts/rules/${id}`, undefined, {
      method: 'DELETE',
    }),

  // 预警事件历史
  getAlertEvents: (params?: { is_read?: boolean; since?: string; page?: number; page_size?: number }) =>
    request<{ items: AlertEvent[]; total: number; page: number; page_size: number }>('/api/v1/alerts/events', {
      is_read: params?.is_read !== undefined ? String(params.is_read) : undefined,
      since: params?.since,
      page: params?.page,
      page_size: params?.page_size,
    }),

  markAlertEventRead: (eventId: number) =>
    request<{ read: boolean }>(`/api/v1/alerts/events/${eventId}/read`, undefined, {
      method: 'PUT',
    }),

  // 手动触发预警扫描
  scanAlerts: () =>
    request<AlertScanResult>('/api/v1/alerts/scan', undefined, {
      method: 'POST',
    }),

  // 补全规则更新（支持修改全部字段）
  updateAlertRuleFull: (id: string, body: Partial<AlertRule>) =>
    request<AlertRule>(`/api/v1/alerts/rules/${id}`, undefined, {
      method: 'PUT',
      body: JSON.stringify({
        name: body.name,
        active: body.active,
        type: body.type,
        target: body.target,
        condition: body.condition,
        value: body.value,
        channels: body.channels,
      }),
    }),

  // ============================================================
  // 策略管理（StrategyCenter）
  // ============================================================
  getStrategyMeta: () =>
    request<AssetMeta[]>('/api/v1/strategies/meta'),

  getStrategies: () =>
    request<Strategy[]>('/api/v1/strategies'),

  createStrategy: (body: { name: string; target_asset: string; rules: StrategyRule[]; sort_by?: string | null; sort_order?: string; limit_count?: number | null }) =>
    request<Strategy>('/api/v1/strategies', undefined, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  updateStrategy: (id: string, body: { name?: string; active?: boolean; ai_tracking?: boolean; rules?: StrategyRule[]; sort_by?: string | null; sort_order?: string; limit_count?: number | null }) =>
    request<Strategy>(`/api/v1/strategies/${id}`, undefined, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  deleteStrategy: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/strategies/${id}`, undefined, {
      method: 'DELETE',
    }),

  executeStrategy: (id: string, date?: string) =>
    request<{ items: Record<string, any>[]; total: number; returned: number; strategy: any }>(`/api/v1/strategies/${id}/execute${date ? `?date=${date}` : ''}`),

  // ============================================================
  // AI 决策中心（AiDecisionHub）
  // ============================================================
  getAiReports: async () => {
    const raw = await request<{ items: any[]; total: number; page: number; page_size: number }>('/api/v1/ai/reports')
    return { items: raw.items.map(adaptAiReport), total: raw.total, page: raw.page, page_size: raw.page_size }
  },

  generateAiReport: async () =>
    adaptAiReport(await request<any>('/api/v1/ai/reports/generate', undefined, { method: 'POST' })),

  // ============================================================
  // 持仓分析（HoldingsAnalysis）
  // ============================================================
  getHoldings: (type?: string, broker?: string, account?: string) =>
    request<HoldingsView>('/api/v1/holdings', { type, broker, account }),

  importHoldings: (items: Array<Record<string, unknown>>) =>
    request<HoldingImportResult>('/api/v1/holdings/import', undefined, {
      method: 'POST',
      body: JSON.stringify({ items }),
    }),

  importHoldingsCsv: (file: File, broker?: string, account?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (broker) form.append('broker', broker)
    if (account) form.append('account', account)
    return request<HoldingImportResult>('/api/v1/holdings/import/csv', undefined, {
      method: 'POST',
      body: form,
    })
  },

  updateHolding: (id: string, body: Partial<Pick<Holding,
    'quantity' | 'cost_price' | 'manual_price' | 'broker' | 'account' | 'name' | 'open_date' | 'currency'
    | 'stop_loss_pct' | 'take_profit_pct' | 'fair_value'
    | 'grid_lower' | 'grid_upper' | 'grid_step'>>) =>
    request<Holding>(`/api/v1/holdings/${id}`, undefined, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  deleteHolding: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/holdings/${id}`, undefined, { method: 'DELETE' }),

  getHoldingSnapshots: () =>
    request<HoldingSnapshot[]>('/api/v1/holdings/snapshots'),

  takeHoldingSnapshot: () =>
    request<HoldingSnapshot>('/api/v1/holdings/snapshot', undefined, { method: 'POST' }),

  // ============================================================
  // 系统设置（SystemSettings）
  // ============================================================
  // 缓存配置
  getCacheConfig: () =>
    request<CacheConfig>('/api/v1/monitor/config/all'),

  saveCacheConfig: (cfg: { enabled: boolean; ttl_seconds: number; max_size: number }) =>
    request<CacheConfig>('/api/v1/monitor/config', undefined, {
      method: 'POST',
      body: JSON.stringify(cfg),
    }),

  // 系统监控仪表盘
  getMonitorDashboard: () =>
    request<MonitorDashboard>('/api/v1/monitor/dashboard'),

  // ============================================================
  // 通知渠道配置（NotificationConfig）
  // ============================================================
  getNotificationConfig: () =>
    request<NotificationConfig>('/api/v1/notifications/config'),

  saveNotificationConfig: (cfg: Partial<NotificationConfig>) =>
    request<NotificationConfig>('/api/v1/notifications/config', undefined, {
      method: 'PUT',
      body: JSON.stringify(cfg),
    }),

  testNotification: (channel: 'wechat' | 'dingtalk') =>
    request<{ channel: string; sent: boolean }>('/api/v1/notifications/test', undefined, {
      method: 'POST',
      body: JSON.stringify({ channel }),
    }),

  getAiConfig: async () => adaptAiConfig(await request<any>('/api/v1/ai/config')),

  saveAiConfig: async (cfg: AiConfig) => {
    const raw = await request<any>('/api/v1/ai/config', undefined, {
      method: 'PUT',
      body: JSON.stringify({
        provider: cfg.provider,
        api_key: cfg.apiKey,
        endpoint: cfg.endpoint,
        temperature: cfg.temperature,
        cron_expression: cfg.cronExpression,
        enabled: cfg.enabled,
        model: cfg.model,
      }),
    })
    return adaptAiConfig(raw)
  },

  // ============================================================
  // 券商账号（个人中心维护，持仓页筛选/导入选用）
  // ============================================================
  getBrokerAccounts: () =>
    request<BrokerAccount[]>('/api/v1/broker-accounts'),

  createBrokerAccount: (broker: string, account: string) =>
    request<BrokerAccount>('/api/v1/broker-accounts', undefined, {
      method: 'POST',
      body: JSON.stringify({ broker, account }),
    }),

  updateBrokerAccount: (id: string, broker: string, account: string) =>
    request<BrokerAccount>(`/api/v1/broker-accounts/${id}`, undefined, {
      method: 'PUT',
      body: JSON.stringify({ broker, account }),
    }),

  deleteBrokerAccount: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/broker-accounts/${id}`, undefined, {
      method: 'DELETE',
    }),

  // ============================================================
  // 账户名（个人中心维护，持仓页编辑时选用）
  // ============================================================
  getAccountNames: () =>
    request<AccountName[]>('/api/v1/account-names'),

  createAccountName: (name: string) =>
    request<AccountName>('/api/v1/account-names', undefined, {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),

  updateAccountName: (id: string, name: string) =>
    request<AccountName>(`/api/v1/account-names/${id}`, undefined, {
      method: 'PUT',
      body: JSON.stringify({ name }),
    }),

  deleteAccountName: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/account-names/${id}`, undefined, {
      method: 'DELETE',
    }),

  // ============================================================
  // 认证（登录 / 注册）
  // ============================================================
  login: (username: string, password: string) =>
    request<{ token: string; expires_at: string; username: string }>('/api/v1/auth/login', undefined, {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  register: (username: string, password: string) =>
    request<{ token: string; expires_at: string; username: string }>('/api/v1/auth/register', undefined, {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  changePassword: (oldPassword: string, newPassword: string) =>
    request<{ changed: boolean; username: string }>('/api/v1/auth/password', undefined, {
      method: 'PUT',
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    }),
}

// ============================================================
// AI 字段适配：后端 snake_case → 前端 camelCase
// ============================================================
function adaptAiReport(raw: any): AiReport {
  return {
    date: raw.date,
    macroAssessment: raw.macro_assessment ?? '',
    strategyMatches: (raw.strategy_matches ?? []).map((m: any) => ({
      strategyName: m.strategy_name ?? '',
      items: (m.items ?? []).map((it: any) => ({
        name: it.name ?? '',
        reason: it.reason ?? it.note ?? it.code ?? '',
      })),
    })),
    arbitrageAlerts: (raw.arbitrage_alerts ?? []).map((a: any) => ({
      name: a.name ?? '',
      premium: a.premium ?? a.premium_pct ?? 0,
      netYield: a.net_yield ?? 0,
      assessment: a.assessment ?? '',
    })),
    createdAt: raw.created_at ?? '',
  }
}

function adaptAiConfig(raw: any): AiConfig {
  return {
    provider: raw.provider ?? '',
    apiKey: raw.api_key ?? '',
    endpoint: raw.endpoint ?? '',
    temperature: raw.temperature ?? 0.7,
    cronExpression: raw.cron_expression ?? '',
    enabled: raw.enabled ?? false,
    model: raw.model,
  }
}

// ---- 信号实验室（SignalLab）----
export const signalApi = {
  getStrategies: () =>
    request<StrategyDef[]>('/api/v1/signals/strategies'),
  generate: (symbol: string, strategyId: string, params?: Record<string, any>) =>
    request<SignalResult>('/api/v1/signals/generate', undefined, {
      method: 'POST',
      body: JSON.stringify({ symbol, strategy_id: strategyId, params: params || {} }),
    }),
  getTracked: () =>
    request<TrackedSignal[]>('/api/v1/signals/tracked'),
  addTracked: (symbol: string, strategyId: string, name?: string, params?: Record<string, any>) =>
    request<TrackedSignal>('/api/v1/signals/tracked', undefined, {
      method: 'POST',
      body: JSON.stringify({ symbol, strategy_id: strategyId, name: name || null, params: params || {} }),
    }),
  removeTracked: (id: string) =>
    request<{ ok: boolean }>(`/api/v1/signals/tracked/${id}`, undefined, { method: 'DELETE' }),
  refreshTracked: () =>
    request<TrackedSignal[]>('/api/v1/signals/tracked/refresh'),
}

// ---- 策略中心 · 经典实盘策略库 ----
export const libraryApi = {
  getLibrary: () =>
    request<LibraryStrategy[]>('/api/v1/strategy-library/library'),
  backtest: (id: string, params?: Record<string, any>) =>
    request<LibraryBacktestResult>(`/api/v1/strategy-library/library/${id}/backtest`, undefined, {
      method: 'POST',
      body: JSON.stringify({ params: params || {} }),
    }),
  getTracked: () =>
    request<TrackedLibrary[]>('/api/v1/strategy-library/tracked'),
  addTracked: (libraryId: string, params?: Record<string, any>) =>
    request<{ id: string; library_id: string }>('/api/v1/strategy-library/tracked', undefined, {
      method: 'POST',
      body: JSON.stringify({ library_id: libraryId, params: params || {} }),
    }),
  removeTracked: (id: string) =>
    request<{ ok: boolean }>(`/api/v1/strategy-library/tracked/${id}`, undefined, { method: 'DELETE' }),
  refreshTracked: () =>
    request<TrackedLibrary[]>('/api/v1/strategy-library/tracked/refresh'),
}

// ---- Type imports for API ----
import type {
  MacroIndicators,
  IndexValuation,
  IndexValuationHistPoint,
  FundItem,
  MarketOverview,
  BoardSector,
  FundFlows,
  ZTStats,
  FundRankingItem,
  SectionSourceMeta,
  ConvertibleBond,
  ReitItem,
  AlertRule,
  Strategy,
  StrategyRule,
  AssetMeta,
  AiConfig,
  AiReport,
  Holding,
  HoldingsView,
  HoldingImportResult,
  HoldingSnapshot,
  DataSourceStatus,
  CacheConfig,
  MonitorDashboard,
  AlertEvent,
  AlertScanResult,
  NotificationConfig,
  PreciousMetals,
  SwSector,
  SwSectorHistoryItem,
  SwSectorValuationItem,
  SwSectorStrength,
  BrokerAccount,
  AccountName,
  StrategyDef,
  SignalResult,
  TrackedSignal,
  LibraryStrategy,
  LibraryBacktestResult,
  TrackedLibrary,
} from '../types'
