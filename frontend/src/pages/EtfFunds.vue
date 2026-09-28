<script setup lang="ts">
defineOptions({ name: 'EtfFunds' })
import { ref, computed, h, onMounted, watch } from 'vue'
import { NDataTable, NButton, NIcon, NTag, NSelect, NInputNumber, useMessage } from 'naive-ui'
import type { PaginationProps } from 'naive-ui'
import {
  SwapHorizontalOutline,
  GridOutline,
  TrendingUpOutline,
  BarChartOutline,
  FlashOutline,
  StatsChartOutline,
  Download,
  RefreshOutline,
  WarningOutline,
  ChevronDownOutline,
  ChevronUpOutline,
} from '@vicons/ionicons5'
import { NCollapseTransition } from 'naive-ui'
import { api, useAsyncData, isGatewayNoData } from '../composables/useApi'
import { useSignalScan } from '../composables/useSignalScan'
import {
  buildTacticalSignalColumns,
  buildWinrateColumns,
  tacticalStateOf as tacticalState,
  winrateExportCells,
} from '../utils/signalDisplay'
import type { EtfFund } from '../types'
import { exportToCSV } from '../utils/export'
import { analyzeArbitrageBatch, FEASIBILITY_ORDER } from '../utils/arbitrage'
import type { ArbitrageAnalysis } from '../utils/arbitrage'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import StatCard from '../components/StatCard.vue'
import TabBar from '../components/TabBar.vue'
import PercentileIndicator from '../components/PercentileIndicator.vue'
import LoadingState from '../components/LoadingState.vue'
import SectionFallback from '../components/SectionFallback.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: etfs, loading, error, meta, execute: refetch } = useAsyncData<EtfFund[]>(
  () => api.getFunds('etf') as unknown as Promise<EtfFund[]>,
)
const gatewayEmpty = computed(() => isGatewayNoData(meta.value))
const activeTab = ref<string>('arbitrage')
const scanning = ref(false)

// 套利陷阱与策略说明的折叠状态
const trapExpanded = ref(false)
const strategyExpanded = ref(false)

const tabs = [
  { key: 'arbitrage', label: '折溢价套利', icon: SwapHorizontalOutline },
  { key: 'grid', label: '网格交易', icon: GridOutline },
  { key: 'rotation', label: '行业轮动', icon: TrendingUpOutline },
  { key: 'valuation', label: '估值定投', icon: BarChartOutline },
  { key: 'tactical', label: '战术信号', icon: FlashOutline },
]

// ---- 战术信号 + 胜率扫描（Tab 懒加载，后端当日缓存；共享逻辑见 useSignalScan）----
const TACTICAL_LIMIT = 100
const {
  selectedStrategyId, selectedParams, strategyOptions, strategyParams, loadStrategies,
  tacticalMap, tacticalLoading, tacticalLoaded, loadTactical,
  winrateMap, winrateLoading, winrateLoaded, winrateMeta, scanWinrate, statsOf,
} = useSignalScan(
  // 按成交额取前 100 只（流动性优先），批量计算偏离度/RSI/布林位置
  () => [...(etfs.value ?? [])].sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0)).map(e => e.code),
  { onError: msg => message.error(msg), notify: msg => message.success(msg), limit: TACTICAL_LIMIT },
)

watch(activeTab, tab => {
  if (tab === 'tactical' && !tacticalLoaded.value) loadTactical()
  if (tab === 'tactical') loadStrategies()
})

// 套利可行性分析映射 (code → ArbitrageAnalysis)
const arbitrageAnalysisMap = computed(() => {
  if (!etfs.value) return new Map<string, ArbitrageAnalysis>()
  return analyzeArbitrageBatch(etfs.value)
})

// ---- 套利陷阱识别：按类型汇总 + 高危标的 Top N ----
const trapCategories = [
  { key: 'blocked', label: '暂停申购/停牌', match: /暂停|停牌/, tone: 'danger' },
  { key: 'limit', label: '限购资金不足', match: /限购/, tone: 'danger' },
  { key: 'exposure', label: 'T+N 敞口', match: /敞口/, tone: 'warning' },
  { key: 'liquidity', label: '流动性不足', match: /流动性/, tone: 'muted' },
] as const

const trappedEtfs = computed(() =>
  (etfs.value ?? []).filter(e => (arbitrageAnalysisMap.value.get(e.code)?.traps.length ?? 0) > 0),
)

const trapSummary = computed(() =>
  trapCategories
    .map(c => ({
      ...c,
      count: trappedEtfs.value.filter(e =>
        (arbitrageAnalysisMap.value.get(e.code)?.traps ?? []).some(t => c.match.test(t)),
      ).length,
    }))
    .filter(c => c.count > 0),
)

// 高危标的：按溢价率绝对值降序取前 10（表格里的灰行可看全部）
const trapOffenders = computed(() =>
  [...trappedEtfs.value]
    .sort((a, b) => Math.abs(b.premium_pct) - Math.abs(a.premium_pct))
    .slice(0, 10),
)

function trapTone(trap: string): string {
  if (/暂停申购|停牌/.test(trap)) return 'tag-danger'
  if (/敞口|限购/.test(trap)) return 'tag-warning'
  return 'tag-muted'
}

// 统计卡片 — 套利tab使用可行性分级，其他tab保持原逻辑
const feasibleCount = computed(() =>
  etfs.value
    ? etfs.value.filter(e => {
        const a = arbitrageAnalysisMap.value.get(e.code)
        return a && a.feasibility === 'feasible' && Math.abs(e.premium_pct) > 0.5
      }).length
    : 0,
)
const riskyCount = computed(() =>
  etfs.value
    ? etfs.value.filter(e => {
        const a = arbitrageAnalysisMap.value.get(e.code)
        return a && a.feasibility === 'risky' && Math.abs(e.premium_pct) > 0.5
      }).length
    : 0,
)
const infeasibleCount = computed(() =>
  etfs.value
    ? etfs.value.filter(e => {
        const a = arbitrageAnalysisMap.value.get(e.code)
        return a && a.feasibility === 'infeasible' && Math.abs(e.premium_pct) > 0.5
      }).length
    : 0,
)
const arbitrageCount = computed(() => etfs.value?.filter(e => Math.abs(e.premium_pct) > 3).length ?? 0)
const gridCount = computed(() => etfs.value?.filter(e => e.category === 'industry' || e.category === 'cross_border').length ?? 0)
const undervaluedCount = computed(() => etfs.value?.filter(e => e.val_category === 'undervalued').length ?? 0)
const avgCrossBorderPremium = computed(() => {
  const cb = etfs.value?.filter(e => e.category === 'cross_border') ?? []
  if (!cb.length) return 0
  return cb.reduce((s, e) => s + e.premium_pct, 0) / cb.length
})

// 动态统计卡片 — 套利tab显示可行性分级，战术tab显示信号分布
const statCards = computed(() => {
  if (activeTab.value === 'arbitrage') {
    return [
      { label: '可行套利', value: feasibleCount.value, sub: '资金+敞口均达标', color: 'var(--color-success)', tip: '资金充足且敞口可控，可执行的套利标的数量' },
      { label: '有风险', value: riskyCount.value, sub: 'T+N敞口或资金受限', color: 'var(--color-warning)', tip: 'T+N敞口或资金受限，套利收益存在不确定性的标的数量' },
      { label: '不可行', value: infeasibleCount.value, sub: '限购/停牌/暂停', color: 'var(--color-danger)', tip: '限购/停牌/暂停导致无法执行的套利标的数量' },
      { label: '跨境溢价均值', value: `${avgCrossBorderPremium.value.toFixed(2)}%`, sub: 'QDII ETF 平均', color: 'var(--color-primary)', tip: 'QDII跨境ETF的平均折溢价率，正值=溢价，负值=折价' },
    ]
  }
  if (activeTab.value === 'tactical') {
    const list = [...tacticalMap.value.values()].filter(t => !t.error)
    const oversold = list.filter(t => tacticalState(t) === 'oversold').length
    const overbought = list.filter(t => tacticalState(t) === 'overbought').length
    const nearLower = list.filter(t => t.boll_pos != null && t.boll_pos <= 10).length
    const avgBias = list.length ? list.reduce((s, t) => s + (t.bias_20 ?? 0), 0) / list.length : 0
    return [
      { label: '超卖·关注', value: oversold, sub: '偏离度/RSI/布林触发', color: 'var(--color-success)', tip: 'MA20偏离度≤-3%、RSI≤30或触及布林下轨的标的数量，可能出现超卖反弹' },
      { label: '超买·谨慎', value: overbought, sub: 'RSI/布林触发', color: 'var(--color-danger)', tip: 'RSI≥70或触及布林上轨的标的数量，短期回调风险' },
      { label: '贴下轨', value: nearLower, sub: '布林位置 ≤ 10%', color: 'var(--color-warning)', tip: '价格位于布林带下部10%区域的标的数量' },
      { label: '平均偏离度', value: `${avgBias.toFixed(2)}%`, sub: 'MA20 BIAS 均值', color: 'var(--color-primary)', tip: '样本ETF相对MA20偏离度的平均值，负值表示整体处于均线下方' },
    ]
  }
  return [
    { label: '套利机会', value: arbitrageCount.value, sub: '溢价 > 3%', color: 'var(--color-danger)', tip: '折溢价率绝对值超过3%的ETF数量' },
    { label: '网格推荐', value: gridCount.value, sub: '行业/跨境 ETF', color: 'var(--color-primary)', tip: '行业/跨境ETF波动率较高，适合网格区间交易' },
    { label: '低估定投', value: undervaluedCount.value, sub: 'PE 分位 < 30%', color: 'var(--color-success)', tip: 'PE历史分位低于30%的低估ETF，适合定投' },
    { label: '跨境溢价均值', value: `${avgCrossBorderPremium.value.toFixed(2)}%`, sub: 'QDII ETF 平均', color: 'var(--color-warning)', tip: 'QDII跨境ETF的平均折溢价率，正值=溢价，负值=折价' },
  ]
})

// 各 tab 的数据筛选
const displayEtfs = computed(() => {
  if (!etfs.value) return []
  if (activeTab.value === 'arbitrage') {
    // 套利tab: 按可行性分级排序，同级内按调整后收益下限降序
    return etfs.value
      .filter(e => Math.abs(e.premium_pct) > 0.5)
      .sort((a, b) => {
        const fa = arbitrageAnalysisMap.value.get(a.code)
        const fb = arbitrageAnalysisMap.value.get(b.code)
        if (!fa || !fb) return Math.abs(b.premium_pct) - Math.abs(a.premium_pct)
        const orderDiff = FEASIBILITY_ORDER[fa.feasibility] - FEASIBILITY_ORDER[fb.feasibility]
        if (orderDiff !== 0) return orderDiff
        return fb.adjustedYieldLow - fa.adjustedYieldLow
      })
  }
  if (activeTab.value === 'grid') {
    return etfs.value.filter(e => e.category === 'industry' || e.category === 'cross_border').sort((a, b) => (b.grid_yield_est ?? 0) - (a.grid_yield_est ?? 0))
  }
  if (activeTab.value === 'rotation') {
    return [...etfs.value].filter(e => e.category === 'industry' || e.category === 'theme').sort((a, b) => (b.momentum_score ?? 0) - (a.momentum_score ?? 0))
  }
  if (activeTab.value === 'tactical') {
    // 仅显示已计算出战术信号的标的，偏离度最负（超卖最深）在前
    return etfs.value
      .filter(e => tacticalMap.value.has(e.code))
      .sort((a, b) => (tacticalMap.value.get(a.code)?.bias_20 ?? 99) - (tacticalMap.value.get(b.code)?.bias_20 ?? 99))
  }
  // valuation
  return etfs.value.filter(e => e.category === 'broad' || e.category === 'theme').sort((a, b) => (a.pe_percentile ?? 99) - (b.pe_percentile ?? 99))
})

// 各 tab 列定义
const arbitrageColumns = [
  { title: '基金名称', key: 'name', render: (row: EtfFund) => h('span', { class: 'etf-name' }, row.name) },
  { title: '代码', key: 'code', render: (row: EtfFund) => h('span', { class: 'etf-code' }, row.code) },
  { title: titleWithHelp('折溢价率', 'premium_pct'), key: 'premium_pct', align: 'right' as const,
    render: (row: EtfFund) => {
      const color = row.premium_pct >= 5 ? 'var(--color-danger)' : row.premium_pct >= 1 ? 'var(--color-warning)' : 'var(--text-secondary)'
      return h('span', { style: { color, fontWeight: 700 } }, `${row.premium_pct >= 0 ? '+' : ''}${row.premium_pct}%`)
    },
  },
  {
    title: titleWithHelp('溢价百分位', 'premium_percentile'), key: 'premium_percentile', align: 'center' as const,
    render: (row: EtfFund) => h(PercentileIndicator, { value: row.premium_percentile }),
  },
  {
    title: titleWithHelp('套利收益(区间)', 'net_arbitrage_yield'), key: 'net_arbitrage_yield', align: 'right' as const,
    render: (row: EtfFund) => {
      const a = arbitrageAnalysisMap.value.get(row.code)
      if (!a) return '-'
      // 不可行: 收益归零，灰色显示
      if (a.feasibility === 'infeasible') {
        return h('div', { class: 'yield-cell' }, [
          h('span', { class: 'yield-strike' }, `+${row.net_arbitrage_yield}%`),
          h('span', { class: 'yield-zero' }, '收益归零'),
        ])
      }
      // 可行/有风险: 显示 [下限, 上限] 区间
      const lowColor = a.adjustedYieldLow < 0 ? 'var(--color-danger)' : 'var(--color-success)'
      return h('div', { class: 'yield-cell' }, [
        h('span', { class: 'yield-range' }, [
          h('span', { style: { color: lowColor, fontWeight: 700 } }, `${a.adjustedYieldLow >= 0 ? '+' : ''}${a.adjustedYieldLow}%`),
          h('span', { class: 'yield-sep' }, ' ~ '),
          h('span', { style: { color: 'var(--color-success)', fontWeight: 700 } }, `+${a.adjustedYieldHigh}%`),
        ]),
      ])
    },
  },
  {
    title: titleWithHelp('资金容量', 'capital_grade'), key: 'capital', align: 'center' as const,
    render: (row: EtfFund) => {
      const a = arbitrageAnalysisMap.value.get(row.code)
      if (!a) return '-'
      const gradeStyle: Record<string, { bg: string; color: string }> = {
        A: { bg: 'var(--tag-green-bg)', color: 'var(--tag-green-text)' },
        B: { bg: 'var(--tag-orange-bg)', color: 'var(--tag-orange-text)' },
        C: { bg: 'var(--tag-red-bg)', color: 'var(--tag-red-text)' },
      }
      const s = gradeStyle[a.capitalGrade]
      return h('div', { class: 'capital-cell' }, [
        h('span', { class: 'capital-grade', style: { background: s.bg, color: s.color } }, a.capitalGrade),
        h('span', { class: 'capital-label' }, a.capitalLabel),
      ])
    },
  },
  {
    title: titleWithHelp('T+N', 'holding_days'), key: 'holding_days', align: 'center' as const,
    render: (row: EtfFund) => {
      const a = arbitrageAnalysisMap.value.get(row.code)
      if (!a) return '-'
      const cls = a.holdingDays >= 2 ? 'holding-risky' : 'holding-normal'
      return h('span', { class: ['holding-badge', cls] }, `T+${a.holdingDays}`)
    },
  },
  {
    title: titleWithHelp('敞口风险', 'risk_exposure'), key: 'risk_exposure', align: 'right' as const,
    render: (row: EtfFund) => {
      const a = arbitrageAnalysisMap.value.get(row.code)
      if (!a) return '-'
      const exceeds = a.riskExposure > Math.abs(row.net_arbitrage_yield)
      const color = exceeds ? 'var(--color-danger)' : a.riskExposure > 2 ? 'var(--color-warning)' : 'var(--text-secondary)'
      return h('span', { style: { color, fontWeight: exceeds ? 700 : 500 } }, `${a.riskExposure}%`)
    },
  },
  {
    title: titleWithHelp('可行性', 'feasibility'), key: 'feasibility', align: 'center' as const,
    render: (row: EtfFund) => {
      const a = arbitrageAnalysisMap.value.get(row.code)
      if (!a) return '-'
      const feasStyle: Record<string, { bg: string; color: string }> = {
        feasible: { bg: 'var(--tag-green-bg)', color: 'var(--tag-green-text)' },
        risky: { bg: 'var(--tag-orange-bg)', color: 'var(--tag-orange-text)' },
        infeasible: { bg: 'var(--tag-red-bg)', color: 'var(--tag-red-text)' },
      }
      const s = feasStyle[a.feasibility]
      const children: any[] = [
        h('span', { class: 'feas-badge', style: { background: s.bg, color: s.color } }, a.feasibilityLabel),
      ]
      if (a.traps.length > 0) {
        children.push(
          h('span', { class: 'trap-count', title: a.traps.join('\n') }, `${a.traps.length}项陷阱`),
        )
      }
      return h('div', { class: 'feas-cell' }, children)
    },
  },
  { title: titleWithHelp('成交量', 'volume'), key: 'volume', align: 'right' as const, render: (row: EtfFund) => formatVol(row.volume) },
]

const gridColumns = [
  { title: '基金名称', key: 'name', render: (row: EtfFund) => h('span', { class: 'etf-name' }, row.name) },
  { title: '子类', key: 'sub_category', render: (row: EtfFund) => h(NTag, { size: 'small', bordered: false }, { default: () => row.sub_category ?? '-' }) },
  { title: '现价', key: 'price', align: 'right' as const, render: (row: EtfFund) => (row.price ?? 0).toFixed(3) },
  { title: titleWithHelp('网格下限', 'grid_low'), key: 'grid_low', align: 'right' as const, render: (row: EtfFund) => row.grid_low != null ? row.grid_low.toFixed(3) : '-' },
  { title: titleWithHelp('网格上限', 'grid_high'), key: 'grid_high', align: 'right' as const, render: (row: EtfFund) => row.grid_high != null ? row.grid_high.toFixed(3) : '-' },
  { title: titleWithHelp('间距', 'grid_step'), key: 'grid_step', align: 'center' as const, render: (row: EtfFund) => row.grid_step != null ? h('span', { class: 'grid-step' }, `${row.grid_step}%`) : '-' },
  {
    title: titleWithHelp('预估年化', 'grid_yield_est'), key: 'grid_yield_est', align: 'right' as const,
    render: (row: EtfFund) => row.grid_yield_est != null
      ? h('span', { style: { color: 'var(--color-primary)', fontWeight: 700 } }, `${row.grid_yield_est}%`)
      : '-',
  },
  { title: titleWithHelp('成交量', 'volume'), key: 'volume', align: 'right' as const, render: (row: EtfFund) => formatVol(row.volume) },
  {
    title: titleWithHelp('估值', 'pe_percentile'), key: 'pe_percentile', align: 'center' as const,
    render: (row: EtfFund) => row.pe_percentile != null
      ? h(PercentileIndicator, { value: row.pe_percentile })
      : '-',
  },
]

const rotationColumns = [
  { title: '排名', key: 'rank', align: 'center' as const, render: (_: EtfFund, i: number) => h('span', { class: 'rank-badge' }, `${i + 1}`) },
  { title: '基金名称', key: 'name', render: (row: EtfFund) => h('span', { class: 'etf-name' }, row.name) },
  { title: '子类', key: 'sub_category', render: (row: EtfFund) => h(NTag, { size: 'small', bordered: false }, { default: () => row.sub_category }) },
  {
    title: titleWithHelp('动量得分', 'momentum_score'), key: 'momentum_score', align: 'right' as const,
    render: (row: EtfFund) => {
      const score = row.momentum_score
      if (score == null) return '-'
      const color = score >= 80 ? 'var(--color-danger)' : score >= 65 ? 'var(--color-primary)' : 'var(--text-muted)'
      return h('div', { class: 'momentum-cell' }, [
        h('span', { style: { color, fontWeight: 700 } }, `${score}`),
        h('div', { class: 'momentum-bar' }, [h('div', { class: 'momentum-fill', style: { width: `${score}%`, background: color } })]),
      ])
    },
  },
  {
    title: titleWithHelp('估值百分位', 'pe_percentile'), key: 'pe_percentile', align: 'center' as const,
    render: (row: EtfFund) => row.pe_percentile != null ? h(PercentileIndicator, { value: row.pe_percentile }) : '-',
  },
  { title: titleWithHelp('PE', 'pe'), key: 'pe', align: 'right' as const, render: (row: EtfFund) => row.pe?.toFixed(1) ?? '-' },
  { title: titleWithHelp('成交量', 'volume'), key: 'volume', align: 'right' as const, render: (row: EtfFund) => formatVol(row.volume) },
]

const valuationColumns = [
  { title: '基金名称', key: 'name', render: (row: EtfFund) => h('span', { class: 'etf-name' }, row.name) },
  { title: '代码', key: 'code', render: (row: EtfFund) => h('span', { class: 'etf-code' }, row.code) },
  {
    title: '估值分类', key: 'val_category', align: 'center' as const,
    render: (row: EtfFund) => {
      // 无 ETF 级 PE 数据时显示 '-'，避免把缺失数据误标为"合理"
      if (row.val_category == null) return '-'
      const map: Record<string, { text: string; type: 'success' | 'warning' | 'error' }> = {
        undervalued: { text: '低估', type: 'success' },
        normal: { text: '合理', type: 'warning' },
        overvalued: { text: '高估', type: 'error' },
      }
      const item = map[row.val_category]
      return h(NTag, { size: 'small', type: item.type, bordered: false }, { default: () => item.text })
    },
  },
  { title: titleWithHelp('PE (TTM)', 'pe'), key: 'pe', align: 'right' as const, render: (row: EtfFund) => row.pe != null ? row.pe.toFixed(2) : '-' },
  {
    title: titleWithHelp('PE 百分位', 'pe_percentile'), key: 'pe_percentile', align: 'center' as const,
    render: (row: EtfFund) => row.pe_percentile != null ? h(PercentileIndicator, { value: row.pe_percentile }) : '-',
  },
  {
    title: '股息率', key: 'dividend_rate', align: 'right' as const,
    render: (row: EtfFund) => row.dividend_rate ? h('span', { style: { color: 'var(--color-success)' } }, `${row.dividend_rate}%`) : '-',
  },
  { title: '现价', key: 'price', align: 'right' as const, render: (row: EtfFund) => (row.price ?? 0).toFixed(3) },
  {
    title: '定投建议', key: 'action', align: 'center' as const,
    render: (row: EtfFund) => {
      if (row.val_category == null) return '-'
      const map = {
        undervalued: { text: '加倍定投', type: 'success' as const },
        normal: { text: '正常定投', type: 'info' as const },
        overvalued: { text: '暂停定投', type: 'error' as const },
      }
      const item = map[row.val_category]
      return h(NTag, { size: 'small', type: item.type, round: true, bordered: false }, { default: () => item.text })
    },
  },
]

// 战术信号列：身份三列（名称/代码/现价）+ 共享信号四列（偏离度/RSI/布林/信号）
const tacticalColumns = [
  { title: '基金名称', key: 'name', render: (row: EtfFund) => h('span', { class: 'etf-name' }, row.name) },
  { title: '代码', key: 'code', render: (row: EtfFund) => h('span', { class: 'etf-code' }, row.code) },
  {
    title: titleWithHelp('现价', 'price_qfq'), key: 'price', align: 'right' as const,
    render: (row: EtfFund) => {
      const t = tacticalMap.value.get(row.code)
      if (!t || t.error || t.price == null) return '-'
      return t.price.toFixed(3)
    },
  },
  ...buildTacticalSignalColumns<EtfFund>({
    titleWithHelp,
    getSignal: code => tacticalMap.value.get(code),
    symbolOf: row => row.code,
  }),
]

// ---- 胜率/凯利列（扫描完成后追加到战术信号表，列定义共享于 signalDisplay）----
const winrateColumns = buildWinrateColumns<EtfFund>({
  titleWithHelp,
  statsOf,
  getScanItem: code => winrateMap.value.get(code),
  symbolOf: row => row.code,
})

const columns = computed(() => {
  if (activeTab.value === 'arbitrage') return arbitrageColumns
  if (activeTab.value === 'grid') return gridColumns
  if (activeTab.value === 'rotation') return rotationColumns
  if (activeTab.value === 'tactical') {
    return winrateLoaded.value ? [...tacticalColumns, ...winrateColumns] : tacticalColumns
  }
  return valuationColumns
})

// 策略说明
const strategyNotes: Record<string, { title: string; desc: string }> = {
  arbitrage: {
    title: '折溢价套利策略 (含可行性分析)',
    desc: '当 ETF 二级市场价格高于 IOPV 净值时（溢价），场内申购 ETF 份额后于二级市场卖出套利。系统已对每个套利机会执行三维可行性分析：①资金容量分级（A/B/C，限购≤1000元直接标为不可行）；②T+N敞口量化（95%VaR = 1.65×日波动率×√持有天数，跨境ETF T+2到账期间净值波动可能吞噬收益）；③陷阱识别（限购/停牌/流动性不足）。收益列显示为区间值[下限, 上限]，下限为扣除T+N敞口后的最差情况。不可行标的灰色置底，不参与套利排序。',
  },
  grid: {
    title: '网格交易策略',
    desc: '在震荡区间内将价格划分为若干网格，跌一格买入、涨一格卖出，机械赚取波动收益。行业 ETF 波动率高于宽基，更适合网格。建议网格间距 2%-4%，每格仓位均等，设置底部兜底价防单边下跌。',
  },
  rotation: {
    title: '行业轮动策略',
    desc: '按动量得分（近 20 日涨幅、成交额加权）在行业/主题 ETF 之间轮动，持有前 3-5 名强势品种。每月或每周调仓，避免追逐极端高估品种，结合估值百分位过滤。',
  },
  valuation: {
    title: '估值定投策略',
    desc: '基于宽基 ETF 的 PE/PB 历史百分位调节定投金额：低估加倍、合理正常、高估暂停。比无脑定投收益更高，适合长期投资者。沪深300、中证500、红利 ETF 是核心配置标的。',
  },
  tactical: {
    title: '战术信号（偏离度 / RSI / 布林 + 胜率扫描）',
    desc: '基于前复权日线的战术层工具。①战术快照：MA20偏离度(BIAS)衡量价格偏离均线的程度，负值=超卖；RSI(14)衡量涨跌动能，≤30超卖、≥70超买；布林位置表示价格在布林带中的相对位置（0%=下轨、100%=上轨）。三者同向时信号更可靠。②胜率扫描：选定策略与参数后，统计全市场 ETF 历史上每次信号触发后"次日收盘买入、持有N个交易日后收盘卖出"的胜率与赔率，已扣双边佣金0.06%+冲击0.05%；凯利 f* = 胜率 − (1−胜率)/赔率，建议仓位一律取半凯利且封顶20%，f*≤0 为负期望（不建议参与），样本<20 不下结论。③防过拟合：将历史按时间拆为样本内（前70%）与样本外（后30%）两段，样本外是策略"没见过"的验证段，样本外胜率明显劣于样本内时提示过拟合风险（样本外样本<5 不下结论）；分年度胜率（10日口径，近3年）用于观察策略在不同市场环境下的稳定性。战略配置为主、战术偏离为辅。',
  },
}

// volume 为成交额(元)：1亿=1e8，1万=1e4；缺失时显示 '-'（麦蕊源无此列）
function formatVol(v: number | null): string {
  if (v == null) return '-'
  if (v >= 100000000) return `${(v / 100000000).toFixed(2)}亿`
  if (v >= 10000) return `${(v / 10000).toFixed(0)}万`
  return v.toString()
}

// 页面加载时获取数据
onMounted(() => {
  refetch()
})

function scan() {
  scanning.value = true
  message.loading('正在扫描 ETF 套利机会...', { duration: 1500 })
  setTimeout(() => {
    scanning.value = false
    const feasible = etfs.value?.filter(e => {
      const a = arbitrageAnalysisMap.value.get(e.code)
      return a && a.feasibility === 'feasible' && Math.abs(e.premium_pct) > 0.5
    }).length ?? 0
    const infeasible = etfs.value?.filter(e => {
      const a = arbitrageAnalysisMap.value.get(e.code)
      return a && a.feasibility === 'infeasible' && Math.abs(e.premium_pct) > 0.5
    }).length ?? 0
    message.success(`扫描完成：${feasible} 个可行套利，${infeasible} 个不可行(限购/停牌)`)
  }, 1500)
}

// 表格分页：每页默认 20 行，客户端分页（参考可转债页面）
const pagination = ref<PaginationProps>({
  page: 1,
  pageSize: 20,
  showSizePicker: true,
  pageSizes: [10, 20, 50, 100],
  onChange: (page: number) => { pagination.value.page = page },
  onUpdatePageSize: (pageSize: number) => {
    pagination.value.pageSize = pageSize
    pagination.value.page = 1
  },
})

// 切换 tab 或筛选变化时回到第一页
watch(activeTab, () => { pagination.value.page = 1 })

function exportEtf() {
  if (activeTab.value === 'tactical' && !tacticalLoaded.value) {
    message.warning('战术信号尚未计算完成，请稍后再导出')
    return
  }
  const headersMap: Record<string, string[]> = {
    arbitrage: ['基金名称', '代码', '折溢价率', '溢价百分位', '收益下限%', '收益上限%', '资金容量', 'T+N', '敞口风险%', '可行性', '陷阱', '成交量'],
    grid: ['基金名称', '子类', '现价', '网格下限', '网格上限', '间距', '预估年化', '成交量', '估值百分位'],
    rotation: ['排名', '基金名称', '子类', '动量得分', '估值百分位', 'PE', '成交量'],
    valuation: ['基金名称', '代码', '估值分类', 'PE', 'PE百分位', '股息率', '现价', '定投建议'],
    tactical: ['基金名称', '代码', '现价', 'MA20偏离度%', 'RSI14', '布林位置%', '当前信号'],
  }
  const headers = [...headersMap[activeTab.value]]
  if (activeTab.value === 'tactical' && winrateLoaded.value) {
    headers.push('触发次数', '5日胜率%', '10日胜率%', '20日胜率%', '赔率(10日)', '半凯利%(10日)', '凯利%(10日)',
      '样本内胜率%(10日)', '样本外胜率%(10日)', '分年度胜率%(10日)')
  }
  const rows = displayEtfs.value.map(e => {
    const a = arbitrageAnalysisMap.value.get(e.code)
    if (activeTab.value === 'arbitrage' && a) {
      return [
        e.name, e.code, e.premium_pct, e.premium_percentile ?? '',
        a.adjustedYieldLow, a.adjustedYieldHigh, a.capitalLabel,
        `T+${a.holdingDays}`, a.riskExposure, a.feasibilityLabel,
        a.traps.join('; '), e.volume ?? '',
      ]
    }
    if (activeTab.value === 'tactical') {
      const t = tacticalMap.value.get(e.code)
      const state = tacticalState(t)
      const stateText = state === 'oversold' ? '超卖·关注' : state === 'overbought' ? '超买·谨慎' : state === 'neutral' ? '中性' : ''
      const base = [e.name, e.code, t?.price ?? '', t?.bias_20 ?? '', t?.rsi_14 ?? '', t?.boll_pos ?? '', stateText]
      if (winrateLoaded.value) {
        base.push(...winrateExportCells(winrateMap.value.get(e.code)))
      }
      return base
    }
    return [
      e.name, e.code, e.price, e.iopv, e.premium_pct, e.premium_percentile ?? '',
      e.net_arbitrage_yield, e.subscribe_limit ?? '', e.volume ?? '',
    ]
  })
  exportToCSV(`etf_${activeTab.value}_${new Date().toISOString().slice(0, 10)}`, headers, rows)
  message.success(`已导出 ${rows.length} 条 ETF 数据`)
}
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    skeleton
    :min-height="520"
    text="正在加载 ETF 基金数据..."
    @retry="refetch"
  >
    <SectionFallback v-if="gatewayEmpty" :gateway-empty="true" :min-height="520" @retry="refetch" />
    <div v-else-if="etfs" class="etf-page">
      <PageHeader title="ETF 基金策略" subtitle="集思录 ETF 策略汇总：折溢价套利 / 网格交易 / 行业轮动 / 估值定投" helpKey="etfFunds">
        <template #actions>
          <n-button size="small" :loading="scanning" @click="scan">
            <template #icon><n-icon :component="RefreshOutline" /></template>
            扫描
          </n-button>
          <n-button size="small" @click="exportEtf">
            <template #icon><n-icon :component="Download" /></template>
            导出
          </n-button>
        </template>
      </PageHeader>
      <GlossaryPanel page-key="etfFunds" />

      <!-- 策略说明（可折叠，默认收起） -->
      <div class="strategy-note">
        <button class="note-toggle" @click="strategyExpanded = !strategyExpanded">
          <span class="note-header-left">
            <n-icon :component="tabs.find(t => t.key === activeTab)?.icon ?? SwapHorizontalOutline" size="18" />
            <h4>{{ strategyNotes[activeTab].title }}</h4>
          </span>
          <n-icon :component="strategyExpanded ? ChevronUpOutline : ChevronDownOutline" size="16" class="note-arrow" />
        </button>
        <NCollapseTransition :show="strategyExpanded">
          <p>{{ strategyNotes[activeTab].desc }}</p>
        </NCollapseTransition>
      </div>

      <!-- 统计卡片 -->
      <div class="stat-grid">
        <StatCard
          v-for="(card, i) in statCards"
          :key="i"
          :label="card.label"
          :value="card.value"
          :sub="card.sub"
          :color="card.color"
          :tip="card.tip"
        />
      </div>

      <!-- 策略 Tab + 数据表 -->
      <DataPanel>
        <template #actions>
          <TabBar v-model="activeTab" :tabs="tabs" />
        </template>
        <!-- 胜率扫描工具栏（仅战术信号Tab） -->
        <div v-if="activeTab === 'tactical'" class="tactical-toolbar">
          <n-select
            v-model="selectedStrategyId"
            :options="strategyOptions"
            size="small"
            placeholder="选择策略"
            style="width: 200px"
          />
          <div v-for="p in strategyParams" :key="p.key" class="param-field">
            <span class="param-label">{{ p.label }}</span>
            <n-input-number
              v-model="selectedParams[p.key]"
              size="small"
              style="width: 110px"
              :min="p.min"
              :max="p.max"
              :step="p.step ?? 1"
            />
          </div>
          <n-button size="small" type="primary" :loading="winrateLoading" :disabled="!tacticalLoaded" @click="scanWinrate">
            <template #icon><n-icon :component="StatsChartOutline" /></template>
            扫描胜率
          </n-button>
          <span v-if="winrateMeta" class="scan-meta">{{ winrateMeta }}</span>
        </div>
        <n-data-table
          :columns="columns"
          :data="displayEtfs"
          :row-key="(row: EtfFund) => row.code"
          :bordered="false"
          :single-line="false"
          size="small"
          :pagination="pagination"
          :row-class-name="(row: EtfFund) => {
            if (activeTab !== 'arbitrage') return ''
            const a = arbitrageAnalysisMap.get(row.code)
            return a?.feasibility === 'infeasible' ? 'row-infeasible' : ''
          }"
          :row-props="(row: EtfFund) => ({ onClick: () => message.info(`${row.name} 详情`), style: 'cursor: pointer' })"
        />
        <div class="table-footer">
          <span v-if="activeTab === 'tactical'" class="footer-info">
            {{ tacticalLoading
              ? '战术信号计算中（首次约需数十秒，当日缓存）...'
              : `已计算 ${tacticalMap.size} 只（按成交额取前 ${TACTICAL_LIMIT} 只，基于前复权日线）` }}
          </span>
          <span v-else class="footer-info">当前 {{ displayEtfs.length }} 条 ETF 数据</span>
        </div>
      </DataPanel>

      <!-- 套利陷阱警告 (仅套利tab显示) -->
      <div v-if="activeTab === 'arbitrage'" class="trap-warnings">
        <div class="trap-header" @click="trapExpanded = !trapExpanded">
          <n-icon :component="WarningOutline" size="16" />
          <span>套利陷阱识别</span>
          <span v-if="trappedEtfs.length" class="trap-total">共 {{ trappedEtfs.length }} 只标记</span>
          <n-icon :component="trapExpanded ? ChevronUpOutline : ChevronDownOutline" size="16" class="trap-arrow" />
        </div>

        <NCollapseTransition :show="trapExpanded">
          <!-- 按类型汇总 -->
          <div v-if="trapSummary.length" class="trap-summary">
            <div v-for="c in trapSummary" :key="c.key" class="trap-chip" :class="`trap-chip-${c.tone}`">
              <span class="trap-chip-label">{{ c.label }}</span>
              <span class="trap-chip-count">{{ c.count }}</span>
            </div>
          </div>

          <!-- 高危标的 Top N -->
          <div v-if="trapOffenders.length" class="trap-list">
            <div v-for="etf in trapOffenders" :key="etf.code" class="trap-row">
              <span class="trap-name" :title="etf.name">{{ etf.name }}</span>
              <span class="trap-premium" :class="etf.premium_pct > 0 ? 'premium-pos' : 'premium-neg'">
                {{ etf.premium_pct >= 0 ? '+' : '' }}{{ etf.premium_pct }}%
              </span>
              <div class="trap-tags">
                <span
                  v-for="(trap, i) in arbitrageAnalysisMap.get(etf.code)?.traps"
                  :key="i"
                  class="trap-tag"
                  :class="`trap-tag-${trapTone(trap)}`"
                >{{ trap }}</span>
              </div>
            </div>
            <div v-if="trappedEtfs.length > trapOffenders.length" class="trap-more">
              还有 {{ trappedEtfs.length - trapOffenders.length }} 只，见上方表格（灰行 = 不可行）
            </div>
          </div>
          <div v-else class="trap-empty">暂无陷阱标记</div>
        </NCollapseTransition>
      </div>

    </div>
  </LoadingState>
</template>

<style>
.etf-name {
  font-family: 'Work Sans', sans-serif;
  font-weight: 600;
  color: var(--text-primary);
}
.etf-code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-muted);
}
.grid-step {
  display: inline-block;
  padding: 1px 6px;
  background: var(--bg-hover);
  border-radius: 3px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  color: var(--color-primary);
}
.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--bg-hover);
  font-family: 'Work Sans', sans-serif;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-secondary);
}
.momentum-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}
.momentum-bar {
  width: 60px;
  height: 3px;
  background: var(--border-default);
  border-radius: 2px;
  overflow: hidden;
}
.momentum-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}

/* === 套利收益区间 === */
.yield-cell { display: flex; flex-direction: column; gap: 2px; align-items: flex-end; }
.yield-range { display: flex; align-items: center; gap: 2px; font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.yield-sep { color: var(--text-muted); font-size: 10px; }
.yield-strike { text-decoration: line-through; color: var(--text-muted); font-size: 11px; font-family: 'JetBrains Mono', monospace; }
.yield-zero { font-size: 9px; color: var(--color-danger); font-weight: 700; }

/* === 资金容量 === */
.capital-cell { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.capital-grade {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 3px;
  font-family: 'Work Sans', sans-serif; font-size: 10px; font-weight: 800;
}
.capital-label { font-size: 9px; color: var(--text-muted); }

/* === T+N 持有天数 === */
.holding-badge {
  display: inline-block; padding: 2px 8px; border-radius: 3px;
  font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 700;
}
.holding-badge.holding-risky { background: var(--tag-orange-bg); color: var(--tag-orange-text); }
.holding-badge.holding-normal { background: var(--tag-gray-bg); color: var(--tag-gray-text); }

/* === 可行性 === */
.feas-cell { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.feas-badge {
  display: inline-block; padding: 2px 10px; border-radius: 3px;
  font-family: 'Work Sans', sans-serif; font-size: 10px; font-weight: 700;
}
.trap-count {
  font-size: 8px; color: var(--color-danger); cursor: help;
  text-decoration: underline; text-decoration-style: dotted;
}

/* === 不可行行灰化 === */
.n-data-table-tr.row-infeasible {
  opacity: 0.45;
  background: var(--bg-subtle) !important;
}
.n-data-table-tr.row-infeasible:hover {
  opacity: 0.7;
}
</style>

<style scoped>
.etf-page { display: flex; flex-direction: column; gap: 14px; }

/* === 战术信号 · 胜率扫描工具栏 === */
.tactical-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.param-field { display: inline-flex; align-items: center; gap: 4px; }
.param-label { font-size: 12px; color: var(--text-secondary); white-space: nowrap; }
.scan-meta { font-size: 11px; color: var(--text-muted); }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
@media (max-width: 768px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}

.strategy-note {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-left: 3px solid var(--color-primary);
  border-radius: 10px;
  overflow: hidden;
}
.note-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 12px 18px;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: background 0.15s ease;
}
.note-toggle:hover {
  background: var(--bg-hover);
}
.note-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-primary);
}
.note-header-left h4 {
  margin: 0;
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.note-arrow {
  color: var(--text-muted);
  transition: transform 0.2s ease;
}
.strategy-note p {
  margin: 0;
  padding: 0 18px 14px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

/* 表格底部信息 */
.table-footer {
  padding: 8px 4px 4px;
  display: flex;
  justify-content: flex-end;
}
.footer-info {
  font-size: 12px;
  color: var(--text-muted);
}

/* === 套利陷阱警告 === */
.trap-warnings {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-left: 3px solid var(--color-danger);
  border-radius: 10px;
  overflow: hidden;
}
.trap-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 18px;
  color: var(--color-danger);
  font-family: 'Work Sans', sans-serif;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.02em;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s ease;
}
.trap-header:hover {
  background: var(--bg-hover);
}
.trap-total {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: 0;
  margin-left: auto;
}
.trap-arrow {
  color: var(--text-muted);
  transition: transform 0.2s ease;
}
/* 按类型汇总 chips */
.trap-summary {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 0 18px 10px;
}
.trap-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 11px;
  font-weight: 600;
}
.trap-chip-label {
  font-family: 'Work Sans', sans-serif;
}
.trap-chip-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 800;
}
.trap-chip-danger { background: var(--tag-red-bg); color: var(--tag-red-text); }
.trap-chip-warning { background: var(--tag-orange-bg); color: var(--tag-orange-text); }
.trap-chip-muted { background: var(--tag-gray-bg); color: var(--tag-gray-text); }
.trap-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 0 18px 14px;
}
.trap-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 0;
  border-bottom: 1px dashed var(--border-subtle);
}
.trap-row:last-child {
  border-bottom: none;
}
.trap-name {
  min-width: 150px;
  max-width: 220px;
  color: var(--text-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trap-premium {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  min-width: 52px;
}
.trap-premium.premium-pos { color: var(--color-danger); }
.trap-premium.premium-neg { color: var(--color-success); }
.trap-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.trap-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 700;
}
.trap-tag-danger { background: var(--tag-red-bg); color: var(--tag-red-text); }
.trap-tag-warning { background: var(--tag-orange-bg); color: var(--tag-orange-text); }
.trap-tag-muted { background: var(--tag-gray-bg); color: var(--tag-gray-text); }
.trap-more {
  font-size: 11px;
  color: var(--text-muted);
  padding-top: 4px;
}
.trap-empty {
  font-size: 12px;
  color: var(--text-muted);
  font-style: italic;
  padding: 0 18px 14px;
}
</style>
