// ============================================================
// 战术信号 + 胜率扫描 共享组合式逻辑（ETF、可转债等页面复用）
// 后端: POST /signals/tactical/batch（当日内存缓存）
//       POST /signals/winrate/scan（当日持久缓存 + 凯利/半凯利 + 样本内外/分年度）
// ============================================================
import { ref, computed, watch } from 'vue'
import { signalApi } from '../utils/api'
import type { TacticalSignal, StrategyDef, WinrateScanItem, WinrateScanResult, WinrateStats } from '../types'
import { WINRATE_MIN_SAMPLES } from '../utils/signalDisplay'

/** 单次批量计算的标的上限（后端路由硬上限 200） */
export const SIGNAL_SCAN_LIMIT = 100

export interface SignalScanOptions {
  /** 计算失败提示（传入页面 message.error 的封装） */
  onError: (msg: string) => void
  /** 扫描完成提示（可选） */
  notify?: (msg: string) => void
  /** 单次计算标的数上限 */
  limit?: number
}

/**
 * @param getSymbols 返回参与计算的标的代码列表（排序/筛选由调用方决定，内部截断到 limit）
 */
export function useSignalScan(getSymbols: () => string[], opts: SignalScanOptions) {
  const limit = opts.limit ?? SIGNAL_SCAN_LIMIT

  // ---- 策略目录与参数 ----
  const strategies = ref<StrategyDef[]>([])
  const strategiesLoaded = ref(false)
  const selectedStrategyId = ref('bias')
  const selectedParams = ref<Record<string, number>>({})

  const strategyOptions = computed(() =>
    strategies.value.map(s => ({ label: `${s.name}（${s.category}）`, value: s.id })),
  )
  const strategyParams = computed(() =>
    strategies.value.find(s => s.id === selectedStrategyId.value)?.params ?? [],
  )

  async function loadStrategies() {
    if (strategiesLoaded.value) return
    try {
      const res = await signalApi.getStrategies()
      strategies.value = Array.isArray(res) ? res : ((res as any).data ?? [])
      strategiesLoaded.value = true
      applyDefaultParams()
    } catch {
      // 目录获取失败时下拉为空，扫描仍可用当前策略默认参数
    }
  }

  function applyDefaultParams() {
    const p: Record<string, number> = {}
    strategyParams.value.forEach(pd => { p[pd.key] = pd.default ?? 0 })
    selectedParams.value = p
  }
  watch(selectedStrategyId, applyDefaultParams)

  function collectParams(): Record<string, number> {
    const params: Record<string, number> = {}
    strategyParams.value.forEach(pd => {
      const v = selectedParams.value[pd.key]
      params[pd.key] = v == null ? (pd.default ?? 0) : v
    })
    return params
  }

  // ---- 战术信号快照（偏离度/RSI/布林，当日缓存）----
  const tacticalMap = ref<Map<string, TacticalSignal>>(new Map())
  const tacticalLoading = ref(false)
  const tacticalLoaded = ref(false)

  async function loadTactical() {
    if (tacticalLoading.value) return
    const codes = getSymbols().slice(0, limit)
    if (!codes.length) return
    tacticalLoading.value = true
    try {
      const res = await signalApi.tacticalBatch(codes)
      const list: TacticalSignal[] = Array.isArray(res) ? res : ((res as any).data ?? [])
      const map = new Map<string, TacticalSignal>()
      list.forEach(t => map.set(t.symbol, t))
      tacticalMap.value = map
      tacticalLoaded.value = true
    } catch (e: any) {
      opts.onError('战术信号计算失败：' + (e.message || e))
    } finally {
      tacticalLoading.value = false
    }
  }

  // ---- 胜率扫描（次日收盘买入/持有N日收盘卖出/扣成本 + 凯利仓位）----
  const winrateMap = ref<Map<string, WinrateScanItem>>(new Map())
  const winrateLoading = ref(false)
  const winrateLoaded = ref(false)
  const winrateMeta = ref('')

  async function scanWinrate() {
    if (winrateLoading.value) return
    const codes = getSymbols().slice(0, limit)
    if (!codes.length) return
    winrateLoading.value = true
    try {
      const res = await signalApi.winrateScan(codes, selectedStrategyId.value, collectParams())
      const data: WinrateScanResult = Array.isArray(res)
        ? (res as any)
        : ((res as any).data ?? { scan_date: '', from_cache: false, results: [] })
      const map = new Map<string, WinrateScanItem>()
      ;(data.results ?? []).forEach(r => map.set(r.symbol, r))
      winrateMap.value = map
      winrateLoaded.value = true
      const sName = strategies.value.find(s => s.id === selectedStrategyId.value)?.name ?? selectedStrategyId.value
      winrateMeta.value = `${sName} · ${data.scan_date} ${data.from_cache ? '（当日缓存）' : '（首次计算）'}`
      opts.notify?.(`胜率扫描完成：${map.size} 只（次日收盘买入、扣成本口径）`)
    } catch (e: any) {
      opts.onError('胜率扫描失败：' + (e.message || e))
    } finally {
      winrateLoading.value = false
    }
  }

  // ---- 单持有期统计查询（样本<20 → '样本不足'）----
  function statsOf(symbol: string, hz: '5d' | '10d' | '20d'): WinrateStats | '样本不足' | null {
    const w = winrateMap.value.get(symbol)
    if (!w || w.error) return null
    const s = w[`stats_${hz}`]
    if (!s) return null
    if (s.samples < WINRATE_MIN_SAMPLES) return '样本不足'
    return s
  }

  return {
    // 策略
    strategies, strategiesLoaded, selectedStrategyId, selectedParams,
    strategyOptions, strategyParams, loadStrategies,
    // 战术信号
    tacticalMap, tacticalLoading, tacticalLoaded, loadTactical,
    // 胜率扫描
    winrateMap, winrateLoading, winrateLoaded, winrateMeta, scanWinrate,
    // 查询
    statsOf,
  }
}
