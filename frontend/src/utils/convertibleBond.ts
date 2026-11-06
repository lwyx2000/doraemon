/**
 * 可转债分析 —— 后端字段适配层（不再是独立实现）
 *
 * 后端 `/api/v1/cb/convertible-bonds` 已在 `utils/convertible_bond.py` 中算好
 * `conversion_analysis` 与 `volatility_analysis`，此处只做 snake_case → camelCase
 * 转换，保证前端展示与后端口径严格一致（历史上两端各算一遍，结论会漂移）。
 *
 * 无上游源的字段一律为 null，不得在前端用 `?? false` / `?? 0` 补默认值 ——
 * 那会把「数据缺失」伪装成「未进入转股期」「隔夜风险 2%」等业务结论。
 */

import type { ConvertibleBond } from '../types'

export type ConversionFeasibility = 'feasible' | 'risky' | 'unknown' | 'infeasible' | 'n/a'
export type VolArbSignal = 'undervalued' | 'fair' | 'overvalued' | 'n/a'

export interface ConversionArbitrage {
  isNegativePremium: boolean
  theoreticalYield: number
  isInConversionPeriod: boolean | null
  isStockLimitUp: boolean | null
  isStockSuspended: boolean | null
  overnightRisk: number | null
  feasibility: ConversionFeasibility
  feasibilityLabel: string
  blockers: string[]
  dataMissing: string[]
}

export interface VolatilityAnalysis {
  iv: number | null
  hv: number | null
  spread: number | null
  ratio: number | null
  signal: VolArbSignal
  signalLabel: string
  suggestion: string
}

/** 后端 snake_case 分析对象（Pydantic 序列化结果） */
type BackendConversion = {
  is_negative_premium?: boolean
  theoretical_yield?: number
  is_in_conversion_period?: boolean | null
  is_stock_limit_up?: boolean | null
  is_stock_suspended?: boolean | null
  overnight_risk?: number | null
  feasibility?: string
  feasibility_label?: string
  blockers?: string[]
  data_missing?: string[]
}
type BackendVolatility = {
  iv?: number | null
  hv?: number | null
  spread?: number | null
  ratio?: number | null
  signal?: string
  signal_label?: string
  suggestion?: string
}

function toConversion(a: BackendConversion | null | undefined): ConversionArbitrage | null {
  if (!a) return null
  return {
    isNegativePremium: a.is_negative_premium ?? false,
    theoreticalYield: a.theoretical_yield ?? 0,
    isInConversionPeriod: a.is_in_conversion_period ?? null,
    isStockLimitUp: a.is_stock_limit_up ?? null,
    isStockSuspended: a.is_stock_suspended ?? null,
    overnightRisk: a.overnight_risk ?? null,
    feasibility: (a.feasibility ?? 'n/a') as ConversionFeasibility,
    feasibilityLabel: a.feasibility_label ?? '—',
    blockers: a.blockers ?? [],
    dataMissing: a.data_missing ?? [],
  }
}

function toVolatility(v: BackendVolatility | null | undefined): VolatilityAnalysis | null {
  if (!v) return null
  return {
    iv: v.iv ?? null,
    hv: v.hv ?? null,
    spread: v.spread ?? null,
    ratio: v.ratio ?? null,
    signal: (v.signal ?? 'n/a') as VolArbSignal,
    signalLabel: v.signal_label ?? '数据源未接入',
    suggestion: v.suggestion ?? '当前网关未提供 IV / HV，无法生成波动率套利信号',
  }
}

/** 单只转债的转股套利分析（直接读后端结论） */
export function analyzeConversionArbitrage(bond: ConvertibleBond): ConversionArbitrage | null {
  return toConversion(bond.conversion_analysis)
}

/** 单只转债的波动率分析（直接读后端结论） */
export function analyzeVolatility(bond: ConvertibleBond): VolatilityAnalysis | null {
  return toVolatility(bond.volatility_analysis)
}

export function analyzeConversionBatch(bonds: ConvertibleBond[]): Map<string, ConversionArbitrage> {
  const map = new Map<string, ConversionArbitrage>()
  for (const b of bonds) {
    const a = analyzeConversionArbitrage(b)
    if (a) map.set(b.code, a)
  }
  return map
}

export function analyzeVolatilityBatch(bonds: ConvertibleBond[]): Map<string, VolatilityAnalysis> {
  const map = new Map<string, VolatilityAnalysis>()
  for (const b of bonds) {
    const v = analyzeVolatility(b)
    if (v) map.set(b.code, v)
  }
  return map
}

export const CONVERSION_ORDER: Record<ConversionFeasibility, number> = {
  feasible: 0,
  risky: 1,
  unknown: 2,
  infeasible: 3,
  'n/a': 4,
}

export const VOL_SIGNAL_ORDER: Record<VolArbSignal, number> = {
  undervalued: 0,
  overvalued: 1,
  fair: 2,
  'n/a': 3,
}
