// ============================================================
// 战术信号 + 胜率扫描 共享组合式逻辑（ETF、可转债等页面复用）
// 后端: POST /signals/tactical/batch（当日内存缓存）
//       POST /signals/winrate/scan（当日持久缓存 + 凯利/半凯利 + 样本内外/分年度）
// ============================================================
import { ref, computed, watch } from 'vue'
import { signalApi } from '../utils/api'
import type { TacticalSignal, StrategyDef, WinrateScanItem, WinrateScanResult, WinrateStats, WinratePooledSummary, WinrateGateConfig, WinrateGateSummary, WinrateExposureSummary } from '../types'
import { WINRATE_MIN_SAMPLES } from '../utils/signalDisplay'

/** 单次批量计算的标的上限（后端路由硬上限 200） */
export const SIGNAL_SCAN_LIMIT = 100

/**
 * 大盘门禁预设（与后端 DEFAULT_GATE_INDICES 一致）。
 * 单指数档位的 require 取 'all' 与 'any' 等价。
 */
export const GATE_PRESETS: Record<string, { indices: string[]; require: 'any' | 'all' }> = {
  any3: { indices: ['000300', '000852', '399006'], require: 'any' },
  all3: { indices: ['000300', '000852', '399006'], require: 'all' },
  hs300: { indices: ['000300'], require: 'all' },
  csi1000: { indices: ['000852'], require: 'all' },
  gem: { indices: ['399006'], require: 'all' },
}
export const GATE_PRESET_OPTIONS = [
  { label: '三指数任一满足', value: 'any3' },
  { label: '三指数全部满足', value: 'all3' },
  { label: '仅沪深300', value: 'hs300' },
  { label: '仅中证1000', value: 'csi1000' },
  { label: '仅创业板指', value: 'gem' },
]
export const GATE_FAST = 10
export const GATE_SLOW = 20

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
  /** v3 汇总可信度评估；旧缓存 / 旧后端无此字段时为 null */
  const winratePooled = ref<WinratePooledSummary | null>(null)

  // ---- v4 大盘门禁：默认关闭，未展示开关的复用页面行为与 v3 完全一致 ----
  const gateEnabled = ref(false)
  const gatePreset = ref('any3')
  /** enabled=false 时返回 null → API 不带 gate 字段 → 后端不做任何过滤 */
  const gateConfig = computed<WinrateGateConfig | null>(() => {
    if (!gateEnabled.value) return null
    const preset = GATE_PRESETS[gatePreset.value] ?? GATE_PRESETS.any3
    return { enabled: true, indices: [...preset.indices], require: preset.require, fast: GATE_FAST, slow: GATE_SLOW }
  })
  /** 本次扫描的门禁执行摘要；未启用 / 旧缓存为 null */
  const winrateGate = ref<WinrateGateSummary | null>(null)

  // ---- v5 仓位口径：分级减仓策略走逐日账本，既有策略仍为满仓固定持有 ----
  /** 旧后端 / 旧缓存无 exposure 字段时为 null，未展示卡片的复用页面行为不变 */
  const winrateExposure = ref<WinrateExposureSummary | null>(null)

  async function scanWinrate() {
    if (winrateLoading.value) return
    const codes = getSymbols().slice(0, limit)
    if (!codes.length) return
    winrateLoading.value = true
    // 换策略/换参数/换门禁重扫时先清掉上次的汇总，避免新旧口径混读
    winratePooled.value = null
    winrateGate.value = null
    winrateExposure.value = null
    try {
      const res = await signalApi.winrateScan(codes, selectedStrategyId.value, collectParams(), gateConfig.value)
      const data: WinrateScanResult = Array.isArray(res)
        ? (res as any)
        : ((res as any).data ?? { scan_date: '', from_cache: false, results: [] })
      const map = new Map<string, WinrateScanItem>()
      ;(data.results ?? []).forEach(r => map.set(r.symbol, r))
      winrateMap.value = map
      // 旧缓存可能是裸数组（v2 之前），没有 pooled / gate / exposure；页面据此隐藏汇总卡片
      winratePooled.value = Array.isArray(res) ? null : (data.pooled ?? null)
      winrateGate.value = Array.isArray(res) ? null : (data.gate ?? null)
      winrateExposure.value = Array.isArray(res) ? null : (data.exposure ?? null)
      winrateLoaded.value = true
      const sName = strategies.value.find(s => s.id === selectedStrategyId.value)?.name ?? selectedStrategyId.value
      const gateTag = gateEnabled.value ? ' · 大盘门禁开' : ''
      // 口径标签跟到 meta，四个复用页面都能看出本次是满仓还是分级仓位
      const exposureTag = winrateExposure.value?.mode === 'ladder' ? ' · 分级仓位' : ''
      winrateMeta.value = `${sName} · ${data.scan_date} ${data.from_cache ? '（当日缓存）' : '（首次计算）'}${gateTag}${exposureTag}`
      opts.notify?.(`胜率扫描完成：${map.size} 只（次日收盘买入、扣成本口径${gateEnabled.value ? '、大盘门禁' : ''}）`)
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
    winrateMap, winrateLoading, winrateLoaded, winrateMeta, winratePooled, scanWinrate,
    // 大盘门禁（v4，默认关闭）
    gateEnabled, gatePreset, gateConfig, winrateGate,
    // 仓位口径摘要（v5，旧后端为 null）
    winrateExposure,
    // 查询
    statsOf,
  }
}
