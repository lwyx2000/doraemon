// ============================================================
// 战术信号 / 胜率扫描 展示层共享模块（ETF、可转债等页面复用）
// 色语义与折溢价一致：超卖/负偏离=机会绿，超买/高估=警示红
// ============================================================
import { h } from 'vue'
import { NTag } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import type { TacticalSignal, WinrateScanItem, WinrateStats, WinrateYearlyItem } from '../types'

/** 触发样本少于该值时统计不可靠（与后端 MIN_SAMPLES 一致） */
export const WINRATE_MIN_SAMPLES = 20

export type TacticalState = 'oversold' | 'overbought' | 'neutral'

/** 战术信号判定：偏离度/RSI/布林三者任一超卖即超卖，RSI 或布林超买即超买 */
export function tacticalStateOf(t: TacticalSignal | undefined | null): TacticalState | null {
  if (!t || t.error) return null
  if (
    (t.bias_20 != null && t.bias_20 <= -3) ||
    (t.rsi_14 != null && t.rsi_14 <= 30) ||
    (t.boll_pos != null && t.boll_pos <= 5)
  ) return 'oversold'
  if (
    (t.rsi_14 != null && t.rsi_14 >= 70) ||
    (t.boll_pos != null && t.boll_pos >= 95)
  ) return 'overbought'
  return 'neutral'
}

type HelpTitle = (title: string, helpKey: string) => any

function wrColor(wr: number): string {
  // 胜率色语义：≥55 绿（机会）、≤45 红（警惕）
  return wr >= 55 ? 'var(--color-success)' : wr <= 45 ? 'var(--color-danger)' : 'var(--text-secondary)'
}

function insufficientNode() {
  return h('span', { style: { color: 'var(--text-muted)', fontSize: '10px' } }, '样本不足')
}

// ---- 战术信号列（4 列：MA20偏离度 / RSI14 / 布林位置 / 当前信号）----
/**
 * @param getSignal 按标的代码取战术快照
 * @param symbolOf 从表格行取标的代码
 */
export function buildTacticalSignalColumns<T>(opts: {
  titleWithHelp: HelpTitle
  getSignal: (symbol: string) => TacticalSignal | undefined
  symbolOf: (row: T) => string
}): DataTableColumns<T> {
  const { titleWithHelp, getSignal, symbolOf } = opts
  return [
    {
      title: titleWithHelp('MA20偏离度', 'bias_20'), key: 'bias_20', align: 'right' as const,
      render: (row: T) => {
        const t = getSignal(symbolOf(row))
        if (!t || t.error || t.bias_20 == null) return '-'
        // 前复权口径色语义与折溢价一致：负偏离(超卖)=机会绿，正偏离(超买)=警示红
        const color = t.bias_20 <= -3 ? 'var(--color-success)' : t.bias_20 >= 3 ? 'var(--color-danger)' : 'var(--text-secondary)'
        return h('span', { style: { color, fontWeight: 700 } }, `${t.bias_20 >= 0 ? '+' : ''}${t.bias_20}%`)
      },
    },
    {
      title: titleWithHelp('RSI (14)', 'rsi_14'), key: 'rsi_14', align: 'right' as const,
      render: (row: T) => {
        const t = getSignal(symbolOf(row))
        if (!t || t.error || t.rsi_14 == null) return '-'
        const color = t.rsi_14 <= 30 ? 'var(--color-success)' : t.rsi_14 >= 70 ? 'var(--color-danger)' : 'var(--text-secondary)'
        return h('span', { style: { color, fontWeight: 700 } }, t.rsi_14.toFixed(1))
      },
    },
    {
      title: titleWithHelp('布林位置', 'boll_pos'), key: 'boll_pos', align: 'right' as const,
      render: (row: T) => {
        const t = getSignal(symbolOf(row))
        if (!t || t.error || t.boll_pos == null) return '-'
        const color = t.boll_pos <= 10 ? 'var(--color-success)' : t.boll_pos >= 90 ? 'var(--color-danger)' : 'var(--text-secondary)'
        return h('span', { style: { color } }, `${t.boll_pos.toFixed(0)}%`)
      },
    },
    {
      title: titleWithHelp('当前信号', 'tactical_signal'), key: 'tactical_signal', align: 'center' as const,
      render: (row: T) => {
        const t = getSignal(symbolOf(row))
        if (!t || t.error) return h('span', { style: { color: 'var(--text-muted)', fontSize: '11px' } }, t?.error ?? '-')
        const state = tacticalStateOf(t)
        if (state === null) return '-'
        const map: Record<TacticalState, { text: string; type: 'success' | 'error' | 'default' }> = {
          oversold: { text: '超卖·关注', type: 'success' },
          overbought: { text: '超买·谨慎', type: 'error' },
          neutral: { text: '中性', type: 'default' },
        }
        const item = map[state]
        return h(NTag, { size: 'small', type: item.type, bordered: false }, { default: () => item.text })
      },
    },
  ]
}

// ---- 胜率/凯利列（10 列，扫描完成后追加）----
/**
 * @param statsOf 按标的代码取单持有期统计（样本<20 返回 '样本不足'）
 * @param getScanItem 按标的代码取原始扫描结果（触发次数/分年度）
 */
export function buildWinrateColumns<T>(opts: {
  titleWithHelp: HelpTitle
  statsOf: (symbol: string, hz: '5d' | '10d' | '20d') => WinrateStats | '样本不足' | null
  getScanItem: (symbol: string) => WinrateScanItem | undefined
  symbolOf: (row: T) => string
}): DataTableColumns<T> {
  const { titleWithHelp, statsOf, getScanItem, symbolOf } = opts

  function winrateCell(row: T, hz: '5d' | '10d' | '20d') {
    const s = statsOf(symbolOf(row), hz)
    if (s === null) return '-'
    if (s === '样本不足') return insufficientNode()
    if (s.win_rate == null) return '-'
    return h('span', { style: { color: wrColor(s.win_rate), fontWeight: 700 } }, `${s.win_rate}%`)
  }

  function payoffCell(row: T) {
    const s = statsOf(symbolOf(row), '10d')
    if (s === null) return '-'
    if (s === '样本不足') return insufficientNode()
    if (s.payoff == null) return h('span', { style: { color: 'var(--color-success)' } }, '无亏损')
    const color = s.payoff >= 1.5 ? 'var(--color-success)' : s.payoff >= 1 ? 'var(--text-secondary)' : 'var(--color-danger)'
    return h('span', { style: { color, fontWeight: 600 } }, s.payoff.toFixed(2))
  }

  function kellyCell(row: T, mode: 'half' | 'full') {
    const s = statsOf(symbolOf(row), '10d')
    if (s === null) return '-'
    if (s === '样本不足') return insufficientNode()
    const v = mode === 'half' ? s.half_kelly : s.kelly
    if (v == null) return '-'
    if (v <= 0) return h('span', { style: { color: 'var(--color-danger)', fontWeight: 700, fontSize: '11px' } }, '负期望')
    const isHalf = mode === 'half'
    return h('span', {
      style: {
        color: isHalf ? 'var(--color-primary)' : 'var(--text-secondary)',
        fontWeight: isHalf ? 700 : 500,
      },
    }, `${v}%`)
  }

  // 样本内/样本外胜率（10日口径）：样本外是策略"没见过"的后 30% 时段，
  // 样本外胜率明显劣于样本内 → 过拟合警报。样本外样本 <5 时仅显示灰色 n=N 不下结论。
  function splitCell(row: T, kind: 'is' | 'oos') {
    const s = statsOf(symbolOf(row), '10d')
    if (s === null) return '-'
    if (s === '样本不足') return insufficientNode()
    const isOos = kind === 'oos'
    const n = isOos ? s.oos_samples : s.is_samples
    const wr = isOos ? s.oos_win_rate : s.is_win_rate
    if (n == null || wr == null) return '-' // 旧版缓存无此字段
    if (isOos && n < 5) {
      return h('span', { style: { color: 'var(--text-muted)', fontSize: '10px' } }, `n=${n}`)
    }
    return h('span', { style: { color: wrColor(wr), fontWeight: 600, fontSize: isOos ? '11px' : undefined } }, `${wr}% (n=${n})`)
  }

  // 分年度胜率（10日口径，近 3 年）：紧凑显示如 "23:67% 24:60%"，悬停看完整信息
  function yearlyCell(row: T) {
    const w = getScanItem(symbolOf(row))
    const ys = w && !w.error ? w.yearly_10d : undefined
    if (!ys || ys.length === 0) return '-'
    const text = ys.map(y => `${y.year.slice(2)}:${y.win_rate == null ? '-' : `${y.win_rate}%`}`).join(' ')
    const tip = ys.map(y => `${y.year}年：${y.win_rate == null ? '-' : `${y.win_rate}%`}（${y.samples}次触发）`).join('\n')
    return h('span', {
      title: tip,
      style: { color: 'var(--text-secondary)', fontSize: '11px', whiteSpace: 'nowrap', cursor: 'default' },
    }, text)
  }

  return [
    {
      title: titleWithHelp('触发次数', 'winrate_triggers'), key: 'triggers', align: 'center' as const,
      render: (row: T) => {
        const w = getScanItem(symbolOf(row))
        if (!w || w.error) return '-'
        return h('span', { style: { color: 'var(--text-secondary)' } }, `${w.triggers}`)
      },
    },
    { title: titleWithHelp('5日胜率', 'winrate_nd'), key: 'wr_5d', align: 'right' as const, render: (row: T) => winrateCell(row, '5d') },
    { title: titleWithHelp('10日胜率', 'winrate_nd'), key: 'wr_10d', align: 'right' as const, render: (row: T) => winrateCell(row, '10d') },
    { title: titleWithHelp('20日胜率', 'winrate_nd'), key: 'wr_20d', align: 'right' as const, render: (row: T) => winrateCell(row, '20d') },
    { title: titleWithHelp('赔率(10日)', 'payoff_ratio'), key: 'payoff', align: 'right' as const, render: (row: T) => payoffCell(row) },
    { title: titleWithHelp('半凯利仓位', 'half_kelly'), key: 'half_kelly', align: 'right' as const, render: (row: T) => kellyCell(row, 'half') },
    { title: titleWithHelp('凯利 f*', 'kelly_full'), key: 'kelly', align: 'right' as const, render: (row: T) => kellyCell(row, 'full') },
    { title: titleWithHelp('样本内(10日)', 'winrate_is'), key: 'wr_is', align: 'right' as const, render: (row: T) => splitCell(row, 'is') },
    { title: titleWithHelp('样本外(10日)', 'winrate_oos'), key: 'wr_oos', align: 'right' as const, render: (row: T) => splitCell(row, 'oos') },
    { title: titleWithHelp('分年度(10日)', 'winrate_yearly'), key: 'wr_yearly', align: 'right' as const, render: (row: T) => yearlyCell(row) },
  ]
}

// ---- CSV 导出单元格（与 buildWinrateColumns 口径一致）----
/** 返回 [触发次数, 5日胜率, 10日胜率, 20日胜率, 赔率, 半凯利, 凯利, 样本内, 样本外, 分年度] */
export function winrateExportCells(item: WinrateScanItem | undefined): (string | number)[] {
  const pick = (hz: '5d' | '10d' | '20d'): WinrateStats | '样本不足' => {
    const s = item && !item.error ? item[`stats_${hz}`] : undefined
    if (!s || s.samples < WINRATE_MIN_SAMPLES) return '样本不足'
    return s
  }
  const s5 = pick('5d')
  const s10 = pick('10d')
  const s20 = pick('20d')
  const val = (s: WinrateStats | '样本不足', key: 'win_rate' | 'payoff' | 'half_kelly' | 'kelly') =>
    s === '样本不足' ? s : (s[key] ?? '无亏损')
  const splitVal = (key: 'is_win_rate' | 'oos_win_rate') =>
    s10 === '样本不足'
      ? s10
      : s10[key] == null
        ? ''
        : `${s10[key]}% (n=${s10[key === 'is_win_rate' ? 'is_samples' : 'oos_samples']})`
  const yearlyText: string = item && !item.error && item.yearly_10d?.length
    ? item.yearly_10d.map((y: WinrateYearlyItem) => `${y.year}:${y.win_rate == null ? '-' : `${y.win_rate}%`}(${y.samples})`).join('; ')
    : ''
  return [
    item && !item.error ? item.triggers : '',
    val(s5, 'win_rate'), val(s10, 'win_rate'), val(s20, 'win_rate'),
    val(s10, 'payoff'), val(s10, 'half_kelly'), val(s10, 'kelly'),
    splitVal('is_win_rate'), splitVal('oos_win_rate'), yearlyText,
  ]
}
