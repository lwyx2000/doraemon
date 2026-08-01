/**
 * 封闭基金套利分析工具
 *
 * 三大维度:
 * 1. 流动性风险 — 成交量过低，想跑跑不掉
 * 2. 折价收敛路径 — 到期是否转LOF决定收敛确定性
 * 3. 底层持仓信用风险 — 信用评级 + 底层资产类型
 */

import type { FundItem } from '../types'

// ============================================================
// 类型定义
// ============================================================

export type LiquidityLevel = 'ample' | 'moderate' | 'illiquid'
export type ConvergenceCertainty = 'certain' | 'likely' | 'uncertain'
export type CreditRiskLevel = 'safe' | 'watch' | 'risky'

export interface ClosedFundAnalysis {
  /** 流动性等级 */
  liquidity: LiquidityLevel
  /** 流动性标签 */
  liquidityLabel: string
  /** 日成交量(手) */
  volume: number
  /** 换手估算 (成交量 / 假设份额) */
  turnoverEstimate: number

  /** 折价收敛确定性 */
  convergence: ConvergenceCertainty
  /** 收敛标签 */
  convergenceLabel: string
  /** 是否到期转LOF */
  isLofConvertible: boolean
  /** 折价率(%) */
  discountPct: number
  /** 剩余期限解析(天) */
  remainingDays: number
  /** 年化折价收敛收益率(%) = |折价率| / 剩余年数 */
  convergenceYield: number

  /** 信用风险等级 */
  creditRisk: CreditRiskLevel
  /** 信用标签 */
  creditLabel: string
  /** 底层持仓评级 */
  creditRating: string
  /** 底层资产类型 */
  underlyingType: string

  /** 综合套利评分 (0-100, 越高越值得关注) */
  score: number
  /** 风险提示列表 */
  warnings: string[]
}

// ============================================================
// 辅助函数
// ============================================================

/**
 * 将 "28 Days" / "1.4 Years" / "312 Days" 解析为天数
 */
export function parseRemainingDays(term?: string): number {
  if (!term) return 365
  const match = term.match(/([\d.]+)\s*(Day|Year)/i)
  if (!match) return 365
  const val = parseFloat(match[1])
  return match[2].toLowerCase().startsWith('year') ? Math.round(val * 365) : Math.round(val)
}

// ============================================================
// 核心分析函数
// ============================================================

/**
 * 流动性风险评估
 *
 * 封闭基金日成交量 < 10万 → 极差，大资金无法退出
 * < 30万 → 一般，小额可进出
 * >= 30万 → 充足
 */
function analyzeLiquidity(volume: number): {
  level: LiquidityLevel
  label: string
  turnover: number
} {
  // 假设基金总份额约 5000万份 (典型封闭基金规模)
  const totalShares = 50000000
  const turnover = Math.round((volume / totalShares) * 10000) / 100

  let level: LiquidityLevel
  let label: string

  if (volume < 100000) {
    level = 'illiquid'
    label = '极差'
  } else if (volume < 300000) {
    level = 'moderate'
    label = '一般'
  } else {
    level = 'ample'
    label = '充足'
  }

  return { level, label, turnover }
}

/**
 * 折价收敛路径分析
 *
 * 关键判断: 到期是否转LOF
 * - 转LOF: 到期后可按净值申赎，折价必然收敛 → 确定性高
 * - 不转LOF: 到期清盘结算，折价收敛取决于清算净值，存在不确定性
 *
 * 收敛收益率 = |折价率| / 剩余年数 (年化)
 */
function analyzeConvergence(fund: FundItem): {
  certainty: ConvergenceCertainty
  label: string
  isLofConvertible: boolean
  remainingDays: number
  convergenceYield: number
} {
  const isLofConvertible = fund.is_lof_convertible ?? false
  const remainingDays = parseRemainingDays(fund.remaining_term)
  const remainingYears = remainingDays / 365
  // 仅对折价品种(premium_pct < 0)计算收敛收益，溢价品种不存在折价收敛套利
  const isDiscount = fund.premium_pct < 0
  const discountPct = isDiscount ? Math.abs(fund.premium_pct) : 0
  const convergenceYield = remainingYears > 0
    ? Math.round((discountPct / remainingYears) * 100) / 100
    : discountPct

  let certainty: ConvergenceCertainty
  let label: string

  if (isLofConvertible) {
    certainty = 'certain'
    label = '确定收敛'
  } else if (remainingDays < 180) {
    // 不转LOF但即将到期，清算接近净值
    certainty = 'likely'
    label = '大概率收敛'
  } else {
    certainty = 'uncertain'
    label = '不确定'
  }

  return { certainty, label, isLofConvertible, remainingDays, convergenceYield }
}

/**
 * 底层持仓信用风险
 *
 * 评级 AAA → 安全
 * 评级 AA+ / AA → 关注
 * 评级 AA- 以下 / 无评级 → 风险
 */
function analyzeCredit(rating?: string, underlyingType?: string): {
  level: CreditRiskLevel
  label: string
} {
  let level: CreditRiskLevel
  let label: string

  if (!rating || rating === '-') {
    level = 'risky'
    label = '无评级'
  } else if (rating === 'AAA') {
    level = 'safe'
    label = '安全'
  } else if (rating.startsWith('AA')) {
    level = 'watch'
    label = '关注'
  } else {
    level = 'risky'
    label = '风险'
  }

  return { level, label }
}

/**
 * 综合评分 (0-100)
 *
 * 评分权重:
 * - 折价收敛收益率 × 3 (越高越好)
 * - 收敛确定性: certain=25, likely=15, uncertain=5
 * - 流动性: ample=20, moderate=10, illiquid=0
 * - 信用: safe=15, watch=8, risky=0
 */
function calcScore(
  convergenceYield: number,
  certainty: ConvergenceCertainty,
  liquidity: LiquidityLevel,
  creditRisk: CreditRiskLevel,
): number {
  const yieldScore = Math.min(convergenceYield * 3, 40)
  const certaintyScore = { certain: 25, likely: 15, uncertain: 5 }[certainty]
  const liquidityScore = { ample: 20, moderate: 10, illiquid: 0 }[liquidity]
  const creditScore = { safe: 15, watch: 8, risky: 0 }[creditRisk]
  return Math.round(yieldScore + certaintyScore + liquidityScore + creditScore)
}

// ============================================================
// 综合分析
// ============================================================

export function analyzeClosedFund(fund: FundItem): ClosedFundAnalysis {
  const { level: liquidity, label: liquidityLabel, turnover: turnoverEstimate } =
    analyzeLiquidity(fund.volume)
  const { certainty: convergence, label: convergenceLabel, isLofConvertible, remainingDays, convergenceYield } =
    analyzeConvergence(fund)
  const { level: creditRisk, label: creditLabel } =
    analyzeCredit(fund.credit_rating, fund.underlying_type)

  const warnings: string[] = []

  if (liquidity === 'illiquid') {
    warnings.push('成交量极低，大资金无法退出')
  }
  if (convergence === 'uncertain') {
    warnings.push('不转LOF且期限较长，折价收敛不确定')
  }
  if (creditRisk === 'risky') {
    warnings.push('底层持仓信用风险较高')
  }
  if (convergenceYield < 3) {
    warnings.push('年化收敛收益率偏低')
  }

  const score = calcScore(convergenceYield, convergence, liquidity, creditRisk)

  return {
    liquidity,
    liquidityLabel,
    volume: fund.volume,
    turnoverEstimate,
    convergence,
    convergenceLabel,
    isLofConvertible,
    discountPct: fund.premium_pct,
    remainingDays,
    convergenceYield,
    creditRisk,
    creditLabel,
    creditRating: fund.credit_rating ?? '-',
    underlyingType: fund.underlying_type ?? '-',
    score,
    warnings,
  }
}

export function analyzeClosedFundBatch(
  funds: FundItem[],
): Map<string, ClosedFundAnalysis> {
  const map = new Map<string, ClosedFundAnalysis>()
  for (const f of funds) {
    map.set(f.code, analyzeClosedFund(f))
  }
  return map
}

/**
 * 收敛确定性排序权重
 */
export const CONVERGENCE_ORDER: Record<ConvergenceCertainty, number> = {
  certain: 0,
  likely: 1,
  uncertain: 2,
}
