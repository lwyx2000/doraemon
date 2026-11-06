/**
 * 可转债分析 —— 后端字段适配层（不再是独立实现）
 *
 * 后端 `/api/v1/cb/convertible-bonds` 已在 `utils/convertible_bond.py` 中算好
 * `conversion_analysis`，此处只做 snake_case → camelCase 转换，保证前端展示与
 * 后端口径严格一致（历史上两端各算一遍，结论会漂移）。
 *
 * 无上游源的字段一律为 null，不得在前端用 `?? false` / `?? 0` 补默认值 ——
 * 那会把「数据缺失」伪装成「未进入转股期」「隔夜风险 2%」等业务结论。
 * IV/HV、质押率、Altman Z 无上游源，相关字段与分析已整体移除。
 */

import type { ConvertibleBond } from '../types'

export type ConversionFeasibility = 'feasible' | 'risky' | 'unknown' | 'infeasible' | 'n/a'

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

/** 单只转债的转股套利分析（直接读后端结论） */
export function analyzeConversionArbitrage(bond: ConvertibleBond): ConversionArbitrage | null {
  return toConversion(bond.conversion_analysis)
}

export function analyzeConversionBatch(bonds: ConvertibleBond[]): Map<string, ConversionArbitrage> {
  const map = new Map<string, ConversionArbitrage>()
  for (const b of bonds) {
    const a = analyzeConversionArbitrage(b)
    if (a) map.set(b.code, a)
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
