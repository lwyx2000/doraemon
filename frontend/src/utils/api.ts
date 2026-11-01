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

// ============================================================
// 全局 401 拦截：会话过期（token 在服务端已失效）时清掉失效 token 并自动跳登录页，
// 避免所有需要登录的页面（持仓/预警/策略/AI 配置…）裸显「401」错误。
// 仅触发一次跳转；removeItem 幂等，重复 401 不会循环导航。
// 排除 /auth/login、/auth/register 自身，否则登录/注册失败会被误判为过期而循环跳转。
// ============================================================
let _sessionExpiredHandled = false
function handleSessionExpired(path: string): void {
  if (_sessionExpiredHandled) return
  if (path.includes('/auth/login') || path.includes('/auth/register')) return
  _sessionExpiredHandled = true
  localStorage.removeItem('qt_token')
  const redirect = typeof window !== 'undefined' ? window.location.pathname + window.location.search : '/'
  // 动态 import 避免 api.ts 与 router 形成静态循环依赖（只在出错时加载）
  import('../router')
    .then((m) => m.default.push({ path: '/login', query: { redirect } }))
    .catch(() => {
      if (typeof window !== 'undefined') window.location.href = '/login'
    })
}

/**
 * 重置「会话过期一次性开关」。
 * 必须在建立新会话时调用（见 useAuth.setAuth）：该开关只置位、永不复位，
 * 而 Login.vue 登录成功后走 router.push 软导航，JS 模块上下文跨登录保持，
 * 若不重置，重新登录后的第二次会话过期不会再跳登录页，页面只会裸显错误条。
 */
export function resetSessionExpiredFlag(): void {
  _sessionExpiredHandled = false
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
    // 会话过期：清失效 token 并自动导向登录页（登录/注册请求除外）
    if (res.status === 401) {
      handleSessionExpired(path)
    }
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

/**
 * 判断某区块/图表是否「网关无数据」：真实模式（非 mock）下，上游数据源未返回任何数据。
 * 与「本就该为空」（如用户无持仓、筛选无匹配）区分开——后者 gatewayEmpty 为 false。
 */
export function isGatewayNoData(meta?: SectionSourceMeta | ChartSourceMeta | null): boolean {
  if (!meta) return false
  return !meta.isMock && meta.gatewayEmpty === true
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
  // 大盘宏观数据（Dashboard / IndexValuation 分区接口）
  // ============================================================
  // 宏观指标（ERP / DR007 / GC001）
  getMacroIndicators: () =>
    requestWithMeta<MacroIndicators>('/api/v1/market/macro/indicators'),

  // 市场概况（指数行情、涨跌家数、成交额）
  // force=true 穿透 10 分钟进程内缓存（2026-10-17 P2-3，Dashboard 刷新按钮用）
  getMarketOverview: (force?: boolean) =>
    requestWithMeta<MarketOverview>('/api/v1/market/overview', force ? { force: '1' } : undefined),

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

  // 贪婪恐惧指数：最新一日（含 6 分项得分 + 原始指标）
  getFearGreedLatest: () =>
    requestWithMeta<FearGreedLatest>('/api/v1/market/fear-greed/latest'),

  // 贪婪恐惧指数：历史序列（升序，供曲线）
  getFearGreedHistory: (days = 120) =>
    requestWithMeta<FearGreedPoint[]>('/api/v1/market/fear-greed/history', { days }),

  // 贪婪恐惧指数：落库情况 + 定时任务/回填线程状态
  getFearGreedStatus: () =>
    requestWithMeta<FearGreedStatus>('/api/v1/market/fear-greed/status'),

  // 贪婪恐惧指数：手动采集当日（收盘后调用最佳）
  collectFearGreed: () =>
    requestWithMeta<{ ok: boolean; totalScore: number | null; label: string | null }>(
      '/api/v1/market/fear-greed/collect',
      undefined,
      { method: 'POST' }
    ),

  // 贪婪恐惧指数：后台回填历史（涨停池仅近数月有历史）
  backfillFearGreed: (days = 120) =>
    requestWithMeta<{ started: boolean; message?: string }>(
      `/api/v1/market/fear-greed/backfill?days=${days}`,
      undefined,
      { method: 'POST' }
    ),

  // 长期视角（老钱日日谈 A股看板）：申万行业年度涨跌幅热力图
  getLongtermSwReturns: () =>
    requestWithMeta<LqrSwReturns>('/api/v1/longterm/sw-returns'),

  // 长期视角：指数收益三因子拆解（股息/盈利/估值）
  getLongtermReturnDecomp: () =>
    requestWithMeta<LqrReturnDecomp>('/api/v1/longterm/return-decomp'),

  // 长期视角：市场趋势温度（个股 MA250 上方占比 + 行业 MACD>0 占比）
  getLongtermTrendTemperature: () =>
    requestWithMeta<LqrTrendTemperature>('/api/v1/longterm/trend-temperature'),

  // 长期视角：宽基指数全收益净值（days=0 全量，否则每指数截取最近 N 个点）
  getLongtermWideBase: (days = 0) =>
    requestWithMeta<LqrWideBase>('/api/v1/longterm/wide-base', { days }),

  // 长期视角：华证六因子净值（days=0 全量，否则每因子截取最近 N 个点）
  getLongtermHuazheng: (days = 0) =>
    requestWithMeta<LqrHuazheng>('/api/v1/longterm/huazheng', { days }),

  // 长期视角：各源抓取状态 + 定时任务状态
  getLongtermStatus: () =>
    requestWithMeta<LqrStatus>('/api/v1/longterm/status'),

  // 长期视角：手动触发一次采集（首次部署后调用一次即全量落库）
  collectLongterm: (asyncMode = true) =>
    requestWithMeta<{ started: boolean; mode: string; message?: string }>(
      `/api/v1/longterm/collect?async_mode=${asyncMode}`,
      undefined,
      { method: 'POST' }
    ),

  // 红利策略研究：红利指数估值 + 全市场红利基金名录
  getDividendOverview: () =>
    requestWithMeta<DividendOverview>('/api/v1/dividend/overview'),

  refreshDividend: () =>
    requestWithMeta<{ ok: boolean }>('/api/v1/dividend/refresh', undefined, { method: 'POST' }),

  // 点指数行弹窗：该指数跟踪的场内/场外基金 + 中证官方编制说明
  getDividendIndexFunds: (code: string) =>
    requestWithMeta<DividendIndexFunds>(`/api/v1/dividend/index-funds?code=${encodeURIComponent(code)}`),

  // 双击基金行弹窗：该基金的季报持仓明细（逐只后台补全，落库后纯读）
  getDividendFundHoldings: (code: string) =>
    requestWithMeta<DividendFundHoldings>(`/api/v1/dividend/fund-holdings?code=${encodeURIComponent(code)}`),

  // 「业绩比较基准 → 跟踪指数」识别进度 / 手动触发
  getDividendIndexMapProgress: () =>
    requestWithMeta<DividendIndexMapProgress>('/api/v1/dividend/index-map-progress'),

  fillDividendIndexMap: (limit = 40) =>
    requestWithMeta<{ matched: number }>(`/api/v1/dividend/fill-index-map?limit=${limit}`, undefined, {
      method: 'POST',
    }),

  // 红利基金规模/费率：后台渐进补全（同花顺 fund_info_ths，逐只查询）
  fillDividendFees: (limit = 80) =>
    requestWithMeta<DividendFeeProgress>(`/api/v1/dividend/fill-fees?limit=${limit}`, undefined, {
      method: 'POST',
    }),

  getDividendFeeProgress: () =>
    requestWithMeta<DividendFeeProgress>('/api/v1/dividend/fee-progress'),

  // 红利/现金流三类补充指标：跟踪误差 / 分红频率 / 行业集中度（后台渐进补全）
  fillExtraMetrics: (limit = 80) =>
    requestWithMeta<DividendFeeProgress>(`/api/v1/dividend/fill-extra-metrics?limit=${limit}`, undefined, {
      method: 'POST',
    }),

  getExtraMetricsProgress: () =>
    requestWithMeta<DividendFeeProgress>('/api/v1/dividend/extra-metrics-progress'),

  // 现金流基金名录：独立一条线（名称含「现金流」+ 被动指数型），与红利名录互不干扰
  getCashflowFunds: (force = false) =>
    requestWithMeta<CashflowOverview>(
      `/api/v1/dividend/cashflow-funds${force ? '?force=1' : ''}`,
    ),

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

  // A股行业热力图趋势：最近 N 个交易日每日行业涨跌幅与当日排名（本地快照表）
  getSwSectorRankTrend: (days: number = 20) =>
    request<SwRankTrendData>('/api/v1/market/sw-sectors/rank-trend', { days }),

  // ============================================================
  // 基金数据（LOF / ETF / 封基）
  // ============================================================
  // force=true 穿透后端 30s 列表缓存（刷新按钮用），否则同参数 30s 内命中缓存
  getFunds: (type?: string, min_premium?: number, feasibility?: string, force?: boolean) =>
    requestWithMeta<FundItem[]>('/api/v1/funds', { type, min_premium, feasibility, force: force ? '1' : undefined }),

  getClosedFundAnalysis: () =>
    requestWithMeta<FundItem[]>('/api/v1/funds/closed/analysis'),

  // ---- Convertible Bonds ----
  getConvertibleBonds: (force?: boolean) =>
    requestWithMeta<ConvertibleBond[]>('/api/v1/cb/convertible-bonds', force ? { force: '1' } : undefined),

  // ---- REITs ----
  getReits: (force?: boolean) =>
    requestWithMeta<ReitItem[]>('/api/v1/reits/reits', force ? { force: '1' } : undefined),

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

  // 持仓上传（无鉴权外部接口：增量合并，按 code+type+account 去重）
  importHoldingsApi: (body: {
    username: string
    source?: string
    account: string
    broker_name?: string
    remark?: string
    terminal?: string
    items: Array<Record<string, unknown>>
  }) =>
    request<HoldingImportResult>('/api/v1/holdings/import/api', undefined, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // 成交记录导入（无鉴权外部接口：按 (user, trade_date) 覆盖上传）
  importTrades: (body: {
    username: string
    source?: string
    account: string
    broker_name?: string
    remark?: string
    terminal?: string
    trade_date: string
    items: Array<Record<string, unknown>>
  }) =>
    request<TradeImportResult>('/api/v1/trades/import', undefined, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

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

  getHoldingHistory: () =>
    request<HoldingHistory[]>('/api/v1/holdings/history'),

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

  // 后台任务监控（定时/后台任务执行状态）
  getJobs: () =>
    request<JobInfo[]>('/api/v1/jobs'),

  runJob: (jobId: string) =>
    request<{ job_id: string; ok: boolean; message: string }>(
      `/api/v1/jobs/${jobId}/run`,
      undefined,
      { method: 'POST' },
    ),

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
  // LLM 多渠道管理（OpenAI 兼容）
  // ============================================================
  getAiChannels: async () => {
    const raw = await request<any>('/api/v1/ai/channels')
    return {
      activeId: raw.active_id ?? null,
      channels: (raw.channels ?? []).map(adaptAiChannel) as AiChannel[],
      presets: (raw.presets ?? {}) as Record<string, AiChannelPreset>,
    } as AiChannelsView
  },

  createAiChannel: async (body: {
    name: string
    provider: string
    api_key: string
    endpoint?: string
    model?: string
    temperature?: number
    max_tokens?: number
  }) => adaptAiChannel(await request<any>('/api/v1/ai/channels', undefined, {
    method: 'POST',
    body: JSON.stringify(body),
  })),

  updateAiChannel: async (id: string, body: Record<string, unknown>) =>
    adaptAiChannel(await request<any>(`/api/v1/ai/channels/${id}`, undefined, {
      method: 'PUT',
      body: JSON.stringify(body),
    })),

  deleteAiChannel: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/ai/channels/${id}`, undefined, { method: 'DELETE' }),

  testAiChannel: (id: string) =>
    request<{ ok: boolean; latency_ms: number; reply: string; model: string }>(
      `/api/v1/ai/channels/${id}/test`,
      undefined,
      { method: 'POST' },
    ),

  setActiveAiChannel: (id: string) =>
    request<{ active_id: string }>('/api/v1/ai/channels/active', undefined, {
      method: 'POST',
      body: JSON.stringify({ id }),
    }),

  // ============================================================
  // 知识库（backend/knowledge/ 单一真源）
  // ============================================================
  getKnowledge: () => request<KnowledgeIndex>('/api/v1/ai/knowledge'),

  getKnowledgeDoc: (id: string) => request<KnowledgeDoc>(`/api/v1/ai/knowledge/${id}`),

  importKnowledgeDoc: (data: { title: string; content: string; tags?: string[] }) =>
    request<KnowledgeDocMeta>('/api/v1/ai/knowledge/import', undefined, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  deleteKnowledgeDoc: (id: string) =>
    request<{ id: string; deleted: boolean }>(`/api/v1/ai/knowledge/${id}`, undefined, {
      method: 'DELETE',
    }),

  toggleKnowledgeDoc: (id: string, enabled: boolean) =>
    request<KnowledgeDocMeta>(`/api/v1/ai/knowledge/${id}/toggle`, undefined, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),

  // ============================================================
  // AI 解读 / 问答（SSE 流式）
  // ============================================================
  interpretAi: (contextType: 'dashboard' | 'fear_greed', handlers: AiStreamHandlers, signal?: AbortSignal) =>
    streamAi('/api/v1/ai/interpret', { context_type: contextType }, handlers, signal),

  chatAi: (
    message: string,
    contextType: 'dashboard' | 'fear_greed' | null,
    history: Array<{ role: string; content: string }>,
    handlers: AiStreamHandlers,
    signal?: AbortSignal,
  ) =>
    streamAi('/api/v1/ai/chat', { message, context_type: contextType, history }, handlers, signal),

  // ============================================================
  // 终端 / 券商（终端管理：一个终端可含多个券商，持仓页/个人中心维护）
  // ============================================================
  getTerminals: () =>
    request<Terminal[]>('/api/v1/terminals'),

  createTerminal: (name: string, remark = '') =>
    request<Terminal>('/api/v1/terminals', undefined, {
      method: 'POST',
      body: JSON.stringify({ name, remark }),
    }),

  updateTerminal: (id: string, name: string, remark = '') =>
    request<Terminal>(`/api/v1/terminals/${id}`, undefined, {
      method: 'PUT',
      body: JSON.stringify({ name, remark }),
    }),

  deleteTerminal: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/terminals/${id}`, undefined, {
      method: 'DELETE',
    }),

  // 券商：terminalId 缺省时拉取全部券商（导入下拉用）
  getBrokers: (terminalId?: string) =>
    request<Broker[]>(`/api/v1/terminals${terminalId ? `/${terminalId}/brokers` : '/brokers'}`),

  createBroker: (terminalId: string, name: string, account: string, remark = '') =>
    request<Broker>(`/api/v1/terminals/${terminalId}/brokers`, undefined, {
      method: 'POST',
      body: JSON.stringify({ name, account, remark }),
    }),

  updateBroker: (
    terminalId: string,
    brokerId: string,
    body: Partial<Pick<Broker, 'name' | 'account' | 'remark' | 'fk_terminal'>>,
  ) =>
    request<Broker>(`/api/v1/terminals/${terminalId}/brokers/${brokerId}`, undefined, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  deleteBroker: (terminalId: string, brokerId: string) =>
    request<{ deleted: boolean }>(`/api/v1/terminals/${terminalId}/brokers/${brokerId}`, undefined, {
      method: 'DELETE',
    }),

  // 上传留痕日志（持仓页「上传记录」tab）
  getImportLogs: (limit = 100) =>
    request<ImportLog[]>('/api/v1/import-logs', { limit }),

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
    request<LoginResult>('/api/v1/auth/login', undefined, {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  register: (username: string, password: string) =>
    request<LoginResult>('/api/v1/auth/register', undefined, {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  changePassword: (oldPassword: string | undefined, newPassword: string) =>
    request<{ changed: boolean; username: string }>('/api/v1/auth/password', undefined, {
      method: 'PUT',
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    }),

  // 管理员：列出全部用户（不含密码哈希）
  adminListUsers: () =>
    request<AdminListUsersResponse>('/api/v1/auth/admin/list-users', undefined, {
      method: 'POST',
    }),

  // 管理员：重置指定用户密码（newPassword 省略则由后端生成临时密码）
  adminResetPassword: (username: string, newPassword?: string) =>
    request<AdminResetPasswordResponse>('/api/v1/auth/admin/reset-password', undefined, {
      method: 'POST',
      body: JSON.stringify({ username, new_password: newPassword }),
    }),

  // ============================================================
  // 宽基指数估值分位 + 拥挤度（基于股债利差方法论）
  // ============================================================
  getBroadIndexValuation: () =>
    requestWithMeta<BroadIndexValuation[]>('/api/v1/valuation/broad-indices'),

  // 申万一级行业估值分位 + 拥挤度（行业 PE/PB 历史 + 全A PB 分母）
  getIndustryValuation: () =>
    requestWithMeta<IndustryValuation[]>('/api/v1/valuation/industries'),

  getSingleIndexValuation: (indexName: string) =>
    requestWithMeta<BroadIndexValuation>(`/api/v1/valuation/indices/${encodeURIComponent(indexName)}`),

  // 单指数股债利差历史序列（全量，供估值带图表）
  getIndexSpreadHistory: (indexName: string) =>
    requestWithMeta<SpreadHistoryPoint[]>(`/api/v1/valuation/indices/${encodeURIComponent(indexName)}/spread-history`),

  // 网关数据源自描述信息（/api/project/info 代理）
  getProjectInfo: () =>
    requestWithMeta<ProjectInfo>('/api/v1/datasources/project-info'),
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

function adaptAiChannel(raw: any): AiChannel {
  return {
    id: raw.id,
    name: raw.name ?? '',
    provider: raw.provider ?? 'custom',
    apiKey: raw.api_key ?? '',
    endpoint: raw.endpoint ?? '',
    model: raw.model ?? '',
    temperature: raw.temperature ?? 0.3,
    maxTokens: raw.max_tokens ?? 2048,
    hasKey: raw.has_key ?? false,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  }
}

// ============================================================
// AI 流式（SSE）：fetch + ReadableStream 解析 data: 帧。
// 事件序列：meta → delta* → done；异常为 error 帧（not_configured 等）。
// ============================================================
export interface AiStreamHandlers {
  onMeta?: (meta: AiStreamMeta) => void
  onDelta?: (text: string) => void
  onError?: (err: AiStreamError) => void
  onDone?: () => void
}

export async function streamAi(
  path: string,
  body: Record<string, unknown>,
  handlers: AiStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('qt_token')
  const res = await fetch(new URL(path, API_BASE).toString(), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    let message = `HTTP ${res.status}`
    try {
      const j = await res.json()
      message = j.message || message
    } catch {
      /* 非 JSON 响应用状态码 */
    }
    if (res.status === 401) handleSessionExpired(path)
    throw new ApiError(res.status, message)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''
    for (const frame of frames) {
      const line = frame.trim()
      if (!line.startsWith('data:')) continue
      try {
        const obj = JSON.parse(line.slice(5).trim())
        if (obj.type === 'meta') handlers.onMeta?.(obj)
        else if (obj.type === 'delta') handlers.onDelta?.(obj.text || '')
        else if (obj.type === 'error') handlers.onError?.(obj)
        else if (obj.type === 'done') handlers.onDone?.()
      } catch {
        /* 单帧解析失败跳过，不中断流 */
      }
    }
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
  /** 批量战术信号快照（MA20偏离度 / RSI14 / 布林位置），当日缓存 */
  tacticalBatch: (symbols: string[]) =>
    request<TacticalSignal[]>('/api/v1/signals/tactical/batch', undefined, {
      method: 'POST',
      body: JSON.stringify({ symbols }),
    }),
  /** 胜率扫描：次日收盘买入、持有N日收盘卖出、扣成本；当日+同参数缓存 */
  winrateScan: (symbols: string[], strategyId: string, params?: Record<string, any>) =>
    request<WinrateScanResult>('/api/v1/signals/winrate/scan', undefined, {
      method: 'POST',
      body: JSON.stringify({ symbols, strategy_id: strategyId, params: params || {} }),
    }),
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

// ---- 市场复盘图表（MarketCharts）----
export interface ChartSeries {
  name: string
  data: (number | null)[]
  color?: string
}
export interface ChartPanel {
  dates: string[]
  series: ChartSeries[]
  bands?: ChartSeries[]
  thresholds?: { yAxis: number; label: string; color: string }[]
}
export interface ChartSourceMeta {
  isMock: boolean
  dataSource?: string | null
  updateTime?: string | null
  note?: string | null
  stale?: boolean
  ageMinutes?: number | null
  lastOkTime?: string | null
  breakerOpen?: boolean
  gatewayEmpty?: boolean
}
export interface MarketChart {
  id: string
  title: string
  description: string
  layout: 'single' | 'prism'
  primary: ChartPanel
  secondary?: ChartPanel
  meta?: ChartSourceMeta
}
export interface ChartMeta {
  id: string
  title: string
  description: string
}

export const chartsApi = {
  list: () => requestWithMeta<ChartMeta[]>('/api/v1/charts'),
  all: (force?: boolean) =>
    requestWithMeta<MarketChart[]>('/api/v1/charts/all', force ? { force: '1' } : undefined),
  get: (id: string, force?: boolean) =>
    requestWithMeta<MarketChart>(`/api/v1/charts/${id}`, force ? { force: '1' } : undefined),
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
  FearGreedPoint,
  FearGreedLatest,
  FearGreedStatus,
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
  AiChannel,
  AiChannelPreset,
  AiChannelsView,
  KnowledgeIndex,
  KnowledgeDoc,
  KnowledgeDocMeta,
  AiStreamMeta,
  AiStreamError,
  Holding,
  HoldingsView,
  HoldingImportResult,
  TradeImportResult,
  HoldingSnapshot,
  HoldingHistory,
  DataSourceStatus,
  CacheConfig,
  MonitorDashboard,
  JobInfo,
  AlertEvent,
  AlertScanResult,
  NotificationConfig,
  PreciousMetals,
  SwSector,
  SwSectorHistoryItem,
  SwSectorValuationItem,
  SwSectorStrength,
  SwRankTrendData,
  BroadIndexValuation,
  IndustryValuation,
  SpreadHistoryPoint,
  ProjectInfo,
  Terminal,
  Broker,
  AccountName,
  StrategyDef,
  SignalResult,
  TacticalSignal,
  WinrateScanResult,
  TrackedSignal,
  LibraryStrategy,
  LibraryBacktestResult,
  TrackedLibrary,
  LoginResult,
  AdminListUsersResponse,
  AdminResetPasswordResponse,
  CashflowOverview,
  DividendOverview,
  DividendFeeProgress,
  DividendIndexFunds,
  DividendIndexMapProgress,
  DividendFundHoldings,
  LqrSwReturns,
  LqrReturnDecomp,
  LqrTrendTemperature,
  LqrWideBase,
  LqrHuazheng,
  LqrStatus,
  ImportLog,
} from '../types'
