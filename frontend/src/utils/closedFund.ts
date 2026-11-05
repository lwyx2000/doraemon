/**
 * 封闭基金分析 —— 前端展示适配层
 *
 * 2026-11-05 口径治理：流动性 / 收敛路径 / 信用 / 评分的**唯一计算源**
 * 已收敛到后端 `backend/utils/closed_fund.py`（接口 /funds/closed/analysis）。
 * 这里只把后端蛇形字段映射成表格用的驼峰视图，不再重复实现一遍启发式规则，
 * 避免前后端算法漂移导致同一只基金在两个页面显示不同结论。
 *
 * 关键口径（与后端一致）：
 * - premium_pct 为带符号溢折价率：负=折价、正=溢价；只有折价品种有 discountPct。
 * - quoteMissing=true 的行没有有效场内报价，premium_pct=0 不是「平价」，一律排除统计。
 * - 缺 remaining_term 时后端用 maturity 补算 termDays；仍无期限则为 null，
 *   收敛收益率也为 null —— 绝不默认 365 天。
 * - creditRating / isLofConvertible 在当前数据源里全部未披露，属中性状态，不是风险结论。
 * - volume 是成交额(元)，不是「手」；无份额数据，因此不计算换手率。
 */

import type { FundItem } from '../types'

export type LiquidityLevel = 'ample' | 'moderate' | 'illiquid'
export type ConvergenceCertainty = 'certain' | 'likely' | 'uncertain' | 'unknown'
export type CreditRiskLevel = 'safe' | 'watch' | 'risky' | 'unknown'

export interface ClosedFundAnalysis {
  /** 是否有有效场内报价 */
  quoteMissing: boolean
  /** 流动性等级 */
  liquidity: LiquidityLevel
  liquidityLabel: string
  /** 日成交额(元) */
  volume: number
  /** 日成交额(万元)，表格展示用 */
  volumeWan: number

  /** 折价收敛确定性 */
  convergence: ConvergenceCertainty
  convergenceLabel: string
  /** null = 数据源未披露是否转LOF（不是 false） */
  isLofConvertible: boolean | null
  /** 仅折价品种为正数，溢价/无报价为 null */
  discountPct: number | null
  /** 剩余天数；null = 无可靠期限 */
  remainingDays: number | null
  termSource: string | null
  /** 年化折价收敛收益率(%)，无折价/无期限/期限<30天时为 null */
  convergenceYield: number | null
  yieldCapped: boolean

  creditRisk: CreditRiskLevel
  creditLabel: string
  creditRating: string
  underlyingType: string

  score: number
  warnings: string[]
}

/**
 * 将 "28 Days" / "1.4 Years" 解析为天数；无有效期限返回 null。
 * 兼容旧调用，但页面应优先使用后端 `term_days`（已含 maturity 补算）。
 */
export function parseRemainingDays(term?: string): number | null {
  if (!term) return null
  const match = String(term).match(/([\d.]+)\s*(Day|Year)/i)
  if (!match) return null
  const val = parseFloat(match[1])
  if (!(val > 0)) return null
  const days = match[2].toLowerCase().startsWith('year') ? Math.round(val * 365) : Math.round(val)
  return days > 0 ? days : null
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/**
 * 后端分析字段 → 展示视图。
 * 若某行没有后端分析字段（例如旧版 mock 数据），给出中性占位而不是伪造结论。
 */
export function analyzeClosedFund(fund: FundItem): ClosedFundAnalysis {
  const hasBackend = fund.score !== undefined && fund.warnings !== undefined
  const volume = num(fund.volume) ?? 0
  const premium = num(fund.premium_pct)

  if (!hasBackend) {
    return {
      quoteMissing: true,
      liquidity: 'illiquid',
      liquidityLabel: '数据缺失',
      volume,
      volumeWan: Math.round(volume / 100) / 100,
      convergence: 'unknown',
      convergenceLabel: '数据缺失',
      isLofConvertible: null,
      discountPct: null,
      remainingDays: parseRemainingDays(fund.remaining_term ?? undefined),
      termSource: null,
      convergenceYield: null,
      yieldCapped: false,
      creditRisk: 'unknown',
      creditLabel: '未披露',
      creditRating: '未披露',
      underlyingType: '未披露',
      score: 0,
      warnings: ['缺少后端分析字段，本行不参与统计'],
    }
  }

  const quoteMissing = fund.quote_missing === true
  const discountPct = num(fund.discount_pct)
  return {
    quoteMissing,
    liquidity: fund.liquidity ?? 'illiquid',
    liquidityLabel: fund.liquidity_label ?? '—',
    volume,
    volumeWan: num(fund.volume_wan) ?? Math.round(volume / 100) / 100,
    convergence: fund.convergence ?? 'unknown',
    convergenceLabel: fund.convergence_label ?? '路径未披露',
    isLofConvertible: fund.is_lof_convertible ?? null,
    // 兼容旧后端（无 discount_pct 字段）：仅折价品种按 -premium_pct 推出
    discountPct: quoteMissing
      ? null
      : discountPct ?? (premium !== null && premium < 0 ? Math.abs(premium) : null),
    remainingDays: num(fund.term_days) ?? parseRemainingDays(fund.remaining_term ?? undefined),
    termSource: fund.term_source ?? (fund.term_from_maturity ? 'maturity' : null),
    convergenceYield: num(fund.convergence_yield),
    yieldCapped: fund.yield_capped === true,
    creditRisk: fund.credit_risk ?? 'unknown',
    creditLabel: fund.credit_label ?? '未披露',
    creditRating: fund.credit_rating || '未披露',
    underlyingType: fund.underlying_type || '未披露',
    score: num(fund.score) ?? 0,
    warnings: fund.warnings ?? [],
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

export const CONVERGENCE_ORDER: Record<ConvergenceCertainty, number> = {
  certain: 0,
  likely: 1,
  uncertain: 2,
  unknown: 3,
}
