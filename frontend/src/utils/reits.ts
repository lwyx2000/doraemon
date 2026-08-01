/**
 * 公募 REITs 深度分析工具
 *
 * 三大维度:
 * 1. NAV 溢折价套利 — 市价 vs 基金净值，折价=安全垫
 * 2. 分红可持续性 — DSCR + 出租率趋势 + 杠杆率
 * 3. 流动性风险 — 二级市场成交量
 */

import type { ReitItem } from '../types'

// ============================================================
// 类型定义
// ============================================================

export type NavPremiumLevel = 'discount' | 'fair' | 'premium'
export type SustainabilityLevel = 'sustainable' | 'watch' | 'at_risk'
export type ReitsLiquidityLevel = 'ample' | 'moderate' | 'illiquid'

export interface ReitsAnalysis {
  /** NAV 溢折价率(%) = (市价 - NAV) / NAV × 100 */
  navPremiumPct: number
  /** 溢折价等级 */
  navLevel: NavPremiumLevel
  /** 溢折价标签 */
  navLabel: string
  /** 安全垫描述 */
  safetyMargin: string

  /** 分红可持续性等级 */
  sustainability: SustainabilityLevel
  /** 可持续性标签 */
  sustainabilityLabel: string
  /** 偿债备付率 */
  dscr: number
  /** 出租率趋势(%) */
  occupancyTrend: number
  /** 杠杆率(%) */
  leverageRatio: number

  /** 流动性等级 */
  liquidity: ReitsLiquidityLevel
  /** 流动性标签 */
  liquidityLabel: number | string
  /** 日成交量 */
  volume: number

  /** 综合评分 (0-100, 越高越有配置价值) */
  score: number
  /** 风险提示 */
  warnings: string[]
}

// ============================================================
// 核心分析函数
// ============================================================

/**
 * NAV 溢折价分析
 *
 * 折价 > 3% → 折价交易，有安全垫
 * 溢价 > 3% → 溢价交易，追高风险
 * 中间 → 合理区间
 */
function analyzeNavPremium(price: number, nav?: number): {
  premiumPct: number
  level: NavPremiumLevel
  label: string
  safetyMargin: string
} {
  if (!nav || nav === 0) {
    return { premiumPct: 0, level: 'fair', label: '无NAV', safetyMargin: '数据缺失' }
  }

  const premiumPct = Math.round(((price - nav) / nav) * 10000) / 100

  let level: NavPremiumLevel
  let label: string
  let safetyMargin: string

  if (premiumPct < -3) {
    level = 'discount'
    label = '折价'
    safetyMargin = `安全垫${Math.abs(premiumPct)}%`
  } else if (premiumPct > 3) {
    level = 'premium'
    label = '溢价'
    safetyMargin = `溢价${premiumPct}%，追高风险`
  } else {
    level = 'fair'
    label = '合理'
    safetyMargin = '合理区间'
  }

  return { premiumPct, level, label, safetyMargin }
}

/**
 * 分红可持续性分析
 *
 * 三因子:
 * 1. DSCR (偿债备付率): >=1.5 健康, 1.2-1.5 关注, <1.2 风险
 * 2. 出租率趋势: >0 改善, =0 稳定, <0 恶化 (<-3% 警告)
 * 3. 杠杆率: <30% 健康, 30-40% 关注, >40% 风险
 */
function analyzeSustainability(
  dscr: number,
  occupancyTrend: number,
  leverageRatio: number,
): {
  level: SustainabilityLevel
  label: string
} {
  let riskPoints = 0

  // DSCR
  if (dscr < 1.2) riskPoints += 2
  else if (dscr < 1.5) riskPoints += 1

  // 出租率趋势
  if (occupancyTrend < -3) riskPoints += 2
  else if (occupancyTrend < 0) riskPoints += 1

  // 杠杆率
  if (leverageRatio > 40) riskPoints += 2
  else if (leverageRatio > 30) riskPoints += 1

  let level: SustainabilityLevel
  let label: string

  if (riskPoints >= 3) {
    level = 'at_risk'
    label = '可持续性差'
  } else if (riskPoints >= 1) {
    level = 'watch'
    label = '需关注'
  } else {
    level = 'sustainable'
    label = '可持续'
  }

  return { level, label }
}

/**
 * 流动性分析
 *
 * REITs 成交量 < 50万 → 极差
 * < 150万 → 一般
 * >= 150万 → 充足
 */
function analyzeReitsLiquidity(volume?: number): {
  level: ReitsLiquidityLevel
  label: string
} {
  const vol = volume ?? 0

  if (vol < 500000) return { level: 'illiquid', label: '极差' }
  if (vol < 1500000) return { level: 'moderate', label: '一般' }
  return { level: 'ample', label: '充足' }
}

/**
 * 综合评分 (0-100)
 *
 * 权重:
 * - 分红率: min(rate × 5, 30)
 * - NAV折价: discount=20, fair=10, premium=0
 * - 可持续性: sustainable=25, watch=12, at_risk=0
 * - 流动性: ample=15, moderate=8, illiquid=0
 * - IRR: min(irr × 3, 10)
 */
function calcReitsScore(
  dividendRate: number,
  irr: number,
  navLevel: NavPremiumLevel,
  sustainability: SustainabilityLevel,
  liquidity: ReitsLiquidityLevel,
): number {
  const yieldScore = Math.min(dividendRate * 5, 30)
  const irrScore = Math.min(irr * 3, 10)
  const navScore = { discount: 20, fair: 10, premium: 0 }[navLevel]
  const sustainScore = { sustainable: 25, watch: 12, at_risk: 0 }[sustainability]
  const liquidScore = { ample: 15, moderate: 8, illiquid: 0 }[liquidity]
  return Math.round(yieldScore + irrScore + navScore + sustainScore + liquidScore)
}

// ============================================================
// 综合分析
// ============================================================

export function analyzeReits(reit: ReitItem): ReitsAnalysis {
  const { premiumPct: navPremiumPct, level: navLevel, label: navLabel, safetyMargin } =
    analyzeNavPremium(reit.market_price, reit.nav)
  const { level: sustainability, label: sustainabilityLabel } =
    analyzeSustainability(
      reit.dscr ?? 1.5,
      reit.occupancy_trend ?? 0,
      reit.leverage_ratio ?? 30,
    )
  const { level: liquidity, label: liquidityLabel } =
    analyzeReitsLiquidity(reit.volume)

  const warnings: string[] = []

  if (navLevel === 'premium') {
    warnings.push(`溢价${navPremiumPct}%，追高风险`)
  }
  if (sustainability === 'at_risk') {
    warnings.push('分红可持续性差')
  }
  if (liquidity === 'illiquid') {
    warnings.push('二级市场流动性极差')
  }
  if ((reit.dscr ?? 99) < 1.2) {
    warnings.push(`DSCR=${reit.dscr}，偿债能力不足`)
  }
  if ((reit.occupancy_trend ?? 0) < -3) {
    warnings.push(`出租率下降${Math.abs(reit.occupancy_trend ?? 0)}%`)
  }

  const score = calcReitsScore(
    reit.dividend_rate,
    reit.irr,
    navLevel,
    sustainability,
    liquidity,
  )

  return {
    navPremiumPct,
    navLevel,
    navLabel,
    safetyMargin,
    sustainability,
    sustainabilityLabel,
    dscr: reit.dscr ?? 0,
    occupancyTrend: reit.occupancy_trend ?? 0,
    leverageRatio: reit.leverage_ratio ?? 0,
    liquidity,
    liquidityLabel,
    volume: reit.volume ?? 0,
    score,
    warnings,
  }
}

export function analyzeReitsBatch(
  reits: ReitItem[],
): Map<string, ReitsAnalysis> {
  const map = new Map<string, ReitsAnalysis>()
  for (const r of reits) {
    map.set(r.code, analyzeReits(r))
  }
  return map
}
