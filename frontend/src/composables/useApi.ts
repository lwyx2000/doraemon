import { ref, type Ref } from 'vue'
import { api, ApiError, isGatewayNoData } from '../utils/api'
import type { SectionSourceMeta } from '../types'

/**
 * 判断某次请求返回是否为请求信封 { data, meta }（requestWithMeta 的产物）。
 * 精确匹配：meta 必须是含 isMock 字段的对象，避免误拆普通业务数据。
 */
function isEnvelope(result: unknown): result is { data: unknown; meta: SectionSourceMeta } {
  if (!result || typeof result !== 'object') return false
  const m = (result as Record<string, unknown>).meta
  return typeof m === 'object' && m !== null && 'isMock' in (m as Record<string, unknown>)
}

/**
 * Composable to wrap real API calls with loading/error state.
 * 兼容两种返回：
 *  - requestWithMeta 信封 { data, meta }：自动拆出 data 与 meta（meta 含 isMock / gatewayEmpty 等信号）
 *  - 普通 request 标量/数组：data 直接为业务数据，meta 为 null
 * 页面可借此渲染「网关无数据」等来源级状态（见 isGatewayNoData）。
 * 泛型 T 始终代表「业务数据本身」（即信封内的 data），便于页面直接消费数组/对象。
 */
export function useAsyncData<T>(fetcher: () => Promise<T | { data: T; meta?: SectionSourceMeta }>) {
  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(true)
  const error = ref<string | null>(null)
  const meta = ref<SectionSourceMeta | null>(null) as Ref<SectionSourceMeta | null>

  async function execute() {
    loading.value = true
    error.value = null
    try {
      const result = await fetcher()
      if (isEnvelope(result)) {
        data.value = (result.data as T) ?? null
        meta.value = result.meta ?? null
      } else {
        data.value = result as T
        meta.value = null
      }
    } catch (e) {
      meta.value = null
      if (e instanceof ApiError) {
        error.value = e.message
      } else {
        error.value = String(e)
      }
    } finally {
      loading.value = false
    }
  }

  function refresh() {
    return execute()
  }

  return { data, loading, error, meta, execute, refresh }
}

export { api, ApiError, isGatewayNoData }
