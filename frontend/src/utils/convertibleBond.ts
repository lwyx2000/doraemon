/**
 * 可转债套利分析工具
 *
 * 两大功能：
 * 1. 转股套利可行性判断 — 负溢价≠可套利，需叠加正股涨停/转股期/T+1敞口三重判断
 * 2. IV vs HV 波动率对比 — IV < HV 是 Delta 对冲套利入场信号
 */

import type { ConvertibleBond } from '../types'

// ============================================================
// 类型定义
// ============================================================

export type ConversionFeasibility = 'feasible' | 'risky' | 'infeasible' | 'n/a'
export type VolArbSignal = 'undervalued' | 'fair' | 'overvalued' | 'n/a'

export interface ConversionArbitrage {
  /** 是否负溢价 (转股套利前提) */
  isNegativePremium: boolean
  /** 转股套利理论收益率(%) = (转股价值 - 转债价格) / 转债价格 × 100 */
  theoreticalYield: number
  /** 是否处于转股期 */
  isInConversionPeriod: boolean
  /** 正股是否涨停 */
  isStockLimitUp: boolean
  /** 正股是否停牌 */
  isStockSuspended: boolean
  /** T+1 隔夜敞口风险(%) — 正股日波动率作为近似 */
  overnightRisk: number
  /** 综合可行性 */
  feasibility: ConversionFeasibility
  /** 可行性标签 */
  feasibilityLabel: string
  /** 阻碍因素列表 */
  blockers: string[]
}

export interface VolatilityAnalysis {
  /** 隐含波动率 IV(%) */
  iv: number
  /** 历史波动率 HV(%) */
  hv: number
  /** 波动率差 IV - HV(%) */
  spread: number
  /** 波动率比率 IV / HV */
  ratio: number
  /** 估值信号 */
  signal: VolArbSignal
  /** 信号标签 */
  signalLabel: string
  /** Delta对冲套利建议 */
  suggestion: string
}

// ============================================================
// 转股套利可行性判断
// ============================================================

/**
 * 转股套利可行性分析
 *
 * 套利链路: 买入转债 → 转股 → 卖出正股
 * 三重阻碍:
 * 1. 正股涨停 → 卖不出正股，套利失败
 * 2. 未进入转股期 → 无法转股，负溢价是"伪机会"
 * 3. T+1交收 → 转股后正股T+1才能卖，隔夜跳空风险
 *
 * @param bond          转债数据
 * @param stockVolatility 正股日波动率(%)，用于估算T+1隔夜敞口
 */
export function analyzeConversionArbitrage(
  bond: ConvertibleBond,
  stockVolatility?: number,
): ConversionArbitrage {
  const isNegativePremium = bond.premium_pct < 0
  const theoreticalYield = isNegativePremium
    ? Math.round(((bond.conv_value - bond.price) / bond.price) * 10000) / 100
    : 0
  // 默认 false — 数据缺失时不能假设在转股期，避免制造假套利机会
  const isInConversionPeriod = bond.is_in_conversion_period ?? false
  const isStockLimitUp = bond.stock_limit_up ?? false
  const isStockSuspended = bond.stock_suspended ?? false
  // T+1隔夜敞口 = 正股日波动率 (近似)
  const overnightRisk = stockVolatility ?? bond.hv ?? 2.0

  const blockers: string[] = []

  // 阻碍1: 正股停牌 — 转股后无法卖出，资金锁死
  if (isStockSuspended) {
    blockers.push('正股停牌，转股后无法卖出')
  }

  // 阻碍2: 正股涨停
  if (isStockLimitUp) {
    blockers.push('正股涨停，无法卖出')
  }

  // 阻碍3: 未进入转股期
  if (!isInConversionPeriod) {
    blockers.push('未进入转股期')
  }

  // 阻碍4: T+1隔夜敞口大于套利收益
  if (isNegativePremium && overnightRisk > Math.abs(theoreticalYield)) {
    blockers.push(`T+1敞口${overnightRisk}% > 套利收益${theoreticalYield}%`)
  }

  // 可行性判定
  let feasibility: ConversionFeasibility
  let feasibilityLabel: string

  if (!isNegativePremium) {
    feasibility = 'n/a'
    feasibilityLabel = '非负溢价'
  } else if (isStockSuspended || isStockLimitUp || !isInConversionPeriod) {
    feasibility = 'infeasible'
    feasibilityLabel = '不可行'
  } else if (overnightRisk > Math.abs(theoreticalYield)) {
    feasibility = 'risky'
    feasibilityLabel = '有风险'
  } else {
    feasibility = 'feasible'
    feasibilityLabel = '可行'
  }

  return {
    isNegativePremium,
    theoreticalYield,
    isInConversionPeriod,
    isStockLimitUp,
    isStockSuspended,
    overnightRisk,
    feasibility,
    feasibilityLabel,
    blockers,
  }
}

// ============================================================
// IV / HV 波动率分析
// ============================================================

/**
 * IV vs HV 波动率分析
 *
 * IV (Implied Volatility): 转债价格隐含的正股未来波动率预期
 * HV (Historical Volatility): 正股过去30/60日实际波动率
 *
 * 信号判定:
 * - IV < HV × 0.85 → undervalued (期权部分被低估，Delta对冲买入信号)
 * - IV > HV × 1.15 → overvalued (期权部分被高估，可考虑卖出转债)
 * - 其余 → fair (合理区间)
 *
 * Delta对冲套利: 买入低估的转债期权部分，融券对冲正股Delta，赚波动率回归
 */
export function analyzeVolatility(bond: ConvertibleBond): VolatilityAnalysis {
  const iv = bond.iv ?? 0
  const hv = bond.hv ?? 0
  const spread = Math.round((iv - hv) * 100) / 100
  const ratio = hv > 0 ? Math.round((iv / hv) * 100) / 100 : 0

  let signal: VolArbSignal
  let signalLabel: string
  let suggestion: string

  if (iv === 0 || hv === 0) {
    signal = 'n/a'
    signalLabel = '数据缺失'
    suggestion = '波动率数据不足，无法判断'
  } else if (ratio < 0.85) {
    signal = 'undervalued'
    signalLabel = 'IV低估'
    suggestion = `IV低于HV ${Math.abs(spread)}%，转债期权被低估，可买入转债+融券正股做Delta对冲`
  } else if (ratio > 1.15) {
    signal = 'overvalued'
    signalLabel = 'IV高估'
    suggestion = `IV高于HV ${spread}%，转债期权被高估，可卖出转债或做空期权部分`
  } else {
    signal = 'fair'
    signalLabel = '合理'
    suggestion = `IV/HV=${ratio}，波动率处于合理区间，无套利信号`
  }

  return { iv, hv, spread, ratio, signal, signalLabel, suggestion }
}

// ============================================================
// 批量分析
// ============================================================

/**
 * 批量转股套利分析
 */
export function analyzeConversionBatch(
  bonds: ConvertibleBond[],
): Map<string, ConversionArbitrage> {
  const map = new Map<string, ConversionArbitrage>()
  for (const b of bonds) {
    map.set(b.code, analyzeConversionArbitrage(b))
  }
  return map
}

/**
 * 批量波动率分析
 */
export function analyzeVolatilityBatch(
  bonds: ConvertibleBond[],
): Map<string, VolatilityAnalysis> {
  const map = new Map<string, VolatilityAnalysis>()
  for (const b of bonds) {
    map.set(b.code, analyzeVolatility(b))
  }
  return map
}

/**
 * 可行性排序权重 (用于 sort)
 */
export const CONVERSION_ORDER: Record<ConversionFeasibility, number> = {
  feasible: 0,
  risky: 1,
  infeasible: 2,
  'n/a': 3,
}

/**
 * 波动率信号排序权重 (低估优先)
 */
export const VOL_SIGNAL_ORDER: Record<VolArbSignal, number> = {
  undervalued: 0,
  overvalued: 1,
  fair: 2,
  'n/a': 3,
}
