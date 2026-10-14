/**
 * 贪婪恐惧指数（Fear & Greed）展示层共用工具。
 * 宏观看板紧凑面板（FearGreedPanel.vue）与详情页（FearGreed.vue）共用，
 * 避免 6 分项定义/配色/文案在两处漂移。
 */
import type { FearGreedLatest } from '../types'

export function fmt(v: number | null | undefined, digits = 2): string {
  return v == null ? '—' : v.toFixed(digits)
}

/** 分项得分配色：恐慌绿 → 均衡灰 → 贪婪红（A股红涨绿跌直觉） */
export function scoreColor(s: number | null | undefined): string {
  if (s == null) return 'var(--text-muted)'
  if (s >= 75) return '#dc2626'
  if (s >= 55) return '#f0523f'
  if (s > 45) return '#717782'
  if (s > 25) return '#3ba55d'
  return '#16a34a'
}

export function labelType(label: string | undefined): 'error' | 'success' | 'default' {
  if (label === '极度贪婪') return 'error'
  if (label === '极度恐慌') return 'success'
  return 'default'
}

export interface FearGreedMetricView {
  key: string
  name: string
  weight: string
  score: number | null
  raw: string
  tip: string
}

/** 6 分项定义（顺序 = 权重降序），与后端权重 0.25/0.20/0.20/0.15/0.10/0.10 对应 */
export function buildFearGreedMetrics(l: FearGreedLatest): FearGreedMetricView[] {
  return [
    {
      key: 'advance',
      name: '上涨家数占比',
      weight: '25%',
      score: l.advance,
      raw: l.rawAdvanceRatio == null ? '—' : `${(l.rawAdvanceRatio * 100).toFixed(1)}%`,
      tip: '上涨 ÷ (上涨+下跌+平盘)，赚钱效应广度',
    },
    {
      key: 'limitUp',
      name: '涨停家数（剔 ST）',
      weight: '20%',
      score: l.limitUp,
      raw: l.rawLimitUp == null ? '—' : `${l.rawLimitUp} 家`,
      tip: '乐咕「真实涨停」口径，剔除 ST 与新股',
    },
    {
      key: 'turnover',
      name: '量能比',
      weight: '20%',
      score: l.turnover,
      raw: l.rawTurnoverRatio == null ? '—' : `${fmt(l.rawTurnoverRatio)}×`,
      tip: '当日成交额 ÷ 20 日均成交额（上证指数口径）',
    },
    {
      key: 'position',
      name: '指数距 52 周高点',
      weight: '15%',
      score: l.position,
      raw: l.rawPosition == null ? '—' : `${fmt(l.rawPosition, 1)}%`,
      tip: '上证收盘 ÷ 过去一年最高收盘（替代创新高/新低比）',
    },
    {
      key: 'margin',
      name: '融资余额 20 日变化',
      weight: '10%',
      score: l.margin,
      raw: l.rawMarginChg20 == null ? '—' : `${fmt(l.rawMarginChg20)}%`,
      tip: '沪市融资余额变化率（替代已停止披露的北向资金）',
    },
    {
      key: 'vol',
      name: '波动率（反向）',
      weight: '10%',
      score: l.vol,
      raw: l.rawVol20 == null ? '—' : `${fmt(l.rawVol20, 1)}%`,
      tip: '上证 20 日年化历史波动率，越高越恐慌（得分已反向）',
    },
  ]
}
