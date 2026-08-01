// ============================================================
// API client for the Financial Data Gateway
// ============================================================

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public data?: unknown
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(
  path: string,
  params?: Record<string, string | number | undefined | null>,
  options?: RequestInit
): Promise<T> {
  const url = new URL(path, API_BASE)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    })
  }

  const res = await fetch(url.toString(), {
    headers: {
      'Content-Type': 'application/json',
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

  return json.data ?? json
}

export const api = {
  // ---- Health ----
  health: () => request<{ status: string }>('/health'),

  // ---- Quote APIs ----
  getRealtime: (code: string, type = 'index', source = 'auto') =>
    request<RealtimeQuote>('/api/quote/realtime', { code, type, source }),

  getKline: (code: string, type = 'INDEX', start_date?: string, end_date?: string) =>
    request<KlineItem[]>('/api/quote/kline', { code, type, start_date, end_date }),

  getSpot: (codes = 'IC:000905,IM:000852') =>
    request<Record<string, number>>('/api/quote/spot', { codes }),

  getFutures: (symbol = 'IC') =>
    request<FuturesContract[]>('/api/quote/futures', { symbol }),

  getAnalysis: (symbol = 'IC') =>
    request<MarketAnalysis>('/api/quote/analysis', { symbol }),

  // ---- AkShare Proxy ----
  getAkShare: (method: string, params?: Record<string, string | number>) =>
    request<unknown[]>('/api/ak', { method, ...params }),

  // ---- US / HK / Global ----
  getUsRealtime: (code: string) =>
    request<RealtimeQuote>('/api/us/realtime', { code }),

  getHkRealtime: (code: string, board = 'main') =>
    request<RealtimeQuote>('/api/hk/realtime', { code, board }),

  getYfRealtime: (symbol: string) =>
    request<RealtimeQuote>('/api/yf/realtime', { symbol }),

  // ---- Config ----
  getConfig: (method: string) =>
    request<CacheConfig>(`/api/config/${method}`),

  updateConfig: (config: Partial<CacheConfig> & { method: string }) =>
    request<CacheConfig>('/api/config', undefined, {
      method: 'POST',
      body: JSON.stringify(config),
    }),

  // ---- Favorites ----
  getFavorites: (userId: string) =>
    request<FavoriteItem[]>(`/api/favorites/${userId}`),

  // ---- Monitor ----
  getDashboard: () =>
    request<MonitorDashboard>('/api/monitor/dashboard'),
}

// ---- Type imports for API ----
import type {
  RealtimeQuote,
  KlineItem,
  FuturesContract,
  MarketAnalysis,
  CacheConfig,
  FavoriteItem,
  MonitorDashboard,
} from '../types'
