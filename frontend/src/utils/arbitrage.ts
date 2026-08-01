/**
 * 套利可行性分析工具
 *
 * 核心解决两个"假机会"问题：
 * 1. 限购品种收益归零 — QDII/跨境ETF外汇额度受限，限购100元的品种套利收益不可行
 * 2. T+N 敞口量化 — 跨境ETF T+2到账，期间净值波动可能吞噬全部套利收益
 */

import type { EtfFund, FundItem } from '../types'

// ============================================================
// 类型定义
// ============================================================

export type CapitalGrade = 'A' | 'B' | 'C'
export type Feasibility = 'feasible' | 'risky' | 'infeasible'

export interface ArbitrageAnalysis {
  /** 资金容量等级: A=可行, B=受限, C=不可行 */
  capitalGrade: CapitalGrade
  /** 资金容量描述 (如 "限购100元" / "无限购") */
  capitalLabel: string
  /** 申购限额金额(元), Infinity = 无限制 */
  capitalLimit: number
  /** 套利资金占用天数 (T+N) */
  holdingDays: number
  /** 标的日波动率(%) */
  dailyVolatility: number
  /** T+N 期间敞口风险(%) — 95%单侧 VaR */
  riskExposure: number
  /** 调整后收益下限(%) = 原始净收益 - 敞口风险 */
  adjustedYieldLow: number
  /** 调整后收益上限(%) = 原始净收益 (无上行调整) */
  adjustedYieldHigh: number
  /** 扣除交易成本后的净套利收益(%) */
  netYieldAfterCosts: number
  /** 综合可行性 */
  feasibility: Feasibility
  /** 可行性标签文字 */
  feasibilityLabel: string
  /** 陷阱标记列表 */
  traps: string[]
  /** 是否停牌/暂停申购 */
  isSuspended: boolean
}

// ============================================================
// 交易成本模型
// ============================================================

/**
 * 交易成本参数
 *
 * 套利链路: T日申购 → T+N日到账 → 二级市场卖出
 * 成本 = 申购费 + 卖出佣金 + 冲击成本
 */
export const TRADING_COSTS = {
  /** ETF/LOF 场内申购费率(%)，通常 0.1%-0.5% */
  subscriptionFeeRate: 0.15,
  /** 卖出佣金费率(%)，通常 0.01%-0.05% */
  sellCommissionRate: 0.03,
  /** 冲击成本估算(%)，小资金约 0.05%-0.1% */
  impactCost: 0.05,
}

/**
 * 计算扣除交易成本后的净套利收益率
 *
 * @param grossYield 毛套利收益率(%)
 * @returns 扣除成本后的净收益率(%)
 */
export function calcNetYieldAfterCosts(grossYield: number): number {
  const totalCosts = TRADING_COSTS.subscriptionFeeRate + TRADING_COSTS.sellCommissionRate + TRADING_COSTS.impactCost
  return Math.round((grossYield - totalCosts) * 100) / 100
}

// ============================================================
// 核心计算函数
// ============================================================

/**
 * 解析申购限额字符串，返回限额金额(元)
 * "限购 100 元" → 100
 * "限购 500 元" → 500
 * "暂停申购" → -1 (特殊标记，表示完全不可申购)
 * "无限制" / undefined → Infinity
 */
export function parseSubscribeLimit(limit?: string): number {
  if (!limit || limit === '无限制' || limit.trim() === '') return Infinity
  // "暂停申购" / "暂停" → 返回 -1，由 calcCapitalCapacity 判定为 C 级
  if (limit.includes('暂停') || limit.includes('停止')) return -1
  const match = limit.match(/(\d+(?:\.\d+)?)/)
  if (!match) return Infinity
  return parseFloat(match[1])
}

/**
 * 资金容量分级
 * C级(不可行): 限购 ≤ 1,000 元 — 资金容量极小，套利收益无法覆盖成本
 * B级(受限):   限购 ≤ 10,000 元 — 资金容量有限，大资金无法参与
 * A级(可行):   无限购 或 > 10,000 元
 */
export function calcCapitalCapacity(limitAmount: number): {
  grade: CapitalGrade
  label: string
} {
  if (limitAmount === -1) return { grade: 'C', label: '暂停申购' }
  if (limitAmount === Infinity) return { grade: 'A', label: '无限购' }
  if (limitAmount <= 1000) return { grade: 'C', label: `限购${limitAmount}元` }
  if (limitAmount <= 10000) return { grade: 'B', label: `限购${limitAmount}元` }
  return { grade: 'A', label: `限购${limitAmount}元` }
}

/**
 * T+N 敞口风险量化
 *
 * 套利链路: T日申购 → T+N日份额到账 → 二级市场卖出
 * 期间持有ETF份额，净值波动直接侵蚀套利收益
 *
 * 使用 95% 单侧 VaR (Z=1.65) 估算下行风险:
 *   风险敞口 = 1.65 × 日波动率 × √持有天数
 *
 * @param netYield       原始净套利收益率(%)
 * @param dailyVolatility 标的日波动率(%)
 * @param holdingDays     套利资金占用天数
 */
export function calcArbitrageRisk(
  netYield: number,
  dailyVolatility: number,
  holdingDays: number,
): { riskExposure: number; yieldLow: number; yieldHigh: number } {
  const Z_95_ONE_SIDED = 1.65
  const riskExposure = Z_95_ONE_SIDED * dailyVolatility * Math.sqrt(Math.max(holdingDays, 1))
  return {
    riskExposure: Math.round(riskExposure * 100) / 100,
    yieldLow: Math.round((netYield - riskExposure) * 100) / 100,
    yieldHigh: netYield,
  }
}

// ============================================================
// 综合分析
// ============================================================

interface AnalyzeOptions {
  /** 申购限额描述 (覆盖 fund 自带字段) */
  subscribeLimit?: string
  /** 日波动率(%) (覆盖 fund 自带字段) */
  dailyVolatility?: number
  /** 套利资金占用天数 (覆盖 fund 自带字段) */
  holdingDays?: number
}

/**
 * 对单只基金/ETF 执行全套套利可行性分析
 *
 * 判定逻辑:
 * 1. 停牌 → 直接不可行
 * 2. 资金容量C级(限购≤1000元) → 不可行，收益归零
 * 3. 调整后收益下限 < 0 → 有风险 (T+N敞口可能吞噬收益)
 * 4. 资金容量B级(限购≤10000元) → 有风险
 * 5. 其余 → 可行
 */
export function analyzeArbitrage(
  fund: EtfFund | FundItem,
  options?: AnalyzeOptions,
): ArbitrageAnalysis {
  const subscribeLimit =
    options?.subscribeLimit ?? (fund as EtfFund).subscribe_limit
  const dailyVolatility =
    options?.dailyVolatility ?? (fund as any).daily_volatility ?? 1.5
  const holdingDays =
    options?.holdingDays ?? (fund as any).holding_days ?? 1
  const isSuspended = (fund as any).is_suspended ?? false

  const capitalLimit = parseSubscribeLimit(subscribeLimit)
  const { grade: capitalGrade, label: capitalLabel } =
    calcCapitalCapacity(capitalLimit)

  // 扣除交易成本后的净套利收益
  const netYieldAfterCosts = calcNetYieldAfterCosts(fund.net_arbitrage_yield)

  const { riskExposure, yieldLow, yieldHigh } = calcArbitrageRisk(
    netYieldAfterCosts,
    dailyVolatility,
    holdingDays,
  )

  const traps: string[] = []

  // 陷阱1: 资金容量C级
  if (capitalGrade === 'C') {
    traps.push(`限购${capitalLimit}元，资金容量不足`)
  }

  // 陷阱2: T+N敞口大于套利收益
  if (riskExposure > Math.abs(netYieldAfterCosts) && netYieldAfterCosts > 0) {
    traps.push(`T+${holdingDays}敞口${riskExposure}% > 收益${netYieldAfterCosts}%`)
  }

  // 陷阱3: 停牌
  if (isSuspended) {
    traps.push('停牌/暂停申购')
  }

  // 陷阱4: 流动性不足 (成交量 < 50万)
  if (fund.volume < 500000) {
    traps.push('流动性不足')
  }

  // 可行性判定
  let feasibility: Feasibility
  let feasibilityLabel: string

  if (isSuspended || capitalGrade === 'C') {
    feasibility = 'infeasible'
    feasibilityLabel = '不可行'
  } else if (yieldLow < 0 || capitalGrade === 'B') {
    feasibility = 'risky'
    feasibilityLabel = '有风险'
  } else {
    feasibility = 'feasible'
    feasibilityLabel = '可行'
  }

  return {
    capitalGrade,
    capitalLabel,
    capitalLimit,
    holdingDays,
    dailyVolatility,
    riskExposure,
    adjustedYieldLow: yieldLow,
    adjustedYieldHigh: yieldHigh,
    netYieldAfterCosts,
    feasibility,
    feasibilityLabel,
    traps,
    isSuspended,
  }
}

/**
 * 批量分析，返回 code → ArbitrageAnalysis 的映射
 */
export function analyzeArbitrageBatch(
  funds: Array<EtfFund | FundItem>,
): Map<string, ArbitrageAnalysis> {
  const map = new Map<string, ArbitrageAnalysis>()
  for (const f of funds) {
    map.set(f.code, analyzeArbitrage(f))
  }
  return map
}

/**
 * 可行性排序权重 (用于 sort)
 * feasible=0, risky=1, infeasible=2
 */
export const FEASIBILITY_ORDER: Record<Feasibility, number> = {
  feasible: 0,
  risky: 1,
  infeasible: 2,
}
