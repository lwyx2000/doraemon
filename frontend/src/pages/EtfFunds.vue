<script setup lang="ts">
defineOptions({ name: 'EtfFunds' })
import { ref, computed, h, onMounted } from 'vue'
import { NDataTable, NButton, NIcon, NTag, useMessage } from 'naive-ui'
import {
  SwapHorizontalOutline,
  GridOutline,
  TrendingUpOutline,
  BarChartOutline,
  Download,
  RefreshOutline,
  WarningOutline,
} from '@vicons/ionicons5'
import { api } from '../composables/useApi'
import { useAsyncData } from '../composables/useApi'
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
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: etfs, loading, error, execute: refetch } = useAsyncData<EtfFund[]>(
  () => api.getFunds('etf') as unknown as Promise<EtfFund[]>,
)
const activeTab = ref<string>('arbitrage')
const scanning = ref(false)

const tabs = [
  { key: 'arbitrage', label: '折溢价套利', icon: SwapHorizontalOutline },
  { key: 'grid', label: '网格交易', icon: GridOutline },
  { key: 'rotation', label: '行业轮动', icon: TrendingUpOutline },
  { key: 'valuation', label: '估值定投', icon: BarChartOutline },
]

// 套利可行性分析映射 (code → ArbitrageAnalysis)
const arbitrageAnalysisMap = computed(() => {
  if (!etfs.value) return new Map<string, ArbitrageAnalysis>()
  return analyzeArbitrageBatch(etfs.value)
})

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

// 动态统计卡片 — 套利tab显示可行性分级
const statCards = computed(() => {
  if (activeTab.value === 'arbitrage') {
    return [
      { label: '可行套利', value: feasibleCount.value, sub: '资金+敞口均达标', color: 'var(--color-success)', tip: '资金充足且敞口可控，可执行的套利标的数量' },
      { label: '有风险', value: riskyCount.value, sub: 'T+N敞口或资金受限', color: 'var(--color-warning)', tip: 'T+N敞口或资金受限，套利收益存在不确定性的标的数量' },
      { label: '不可行', value: infeasibleCount.value, sub: '限购/停牌/暂停', color: 'var(--color-danger)', tip: '限购/停牌/暂停导致无法执行的套利标的数量' },
      { label: '跨境溢价均值', value: `${avgCrossBorderPremium.value.toFixed(2)}%`, sub: 'QDII ETF 平均', color: 'var(--color-primary)', tip: 'QDII跨境ETF的平均折溢价率，正值=溢价，负值=折价' },
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
    return etfs.value.filter(e => e.category === 'industry' || e.category === 'cross_border').sort((a, b) => b.grid_yield_est - a.grid_yield_est)
  }
  if (activeTab.value === 'rotation') {
    return [...etfs.value].filter(e => e.category === 'industry' || e.category === 'theme').sort((a, b) => b.momentum_score - a.momentum_score)
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
  { title: '子类', key: 'sub_category', render: (row: EtfFund) => h(NTag, { size: 'small', bordered: false }, { default: () => row.sub_category }) },
  { title: '现价', key: 'price', align: 'right' as const, render: (row: EtfFund) => row.price.toFixed(3) },
  { title: titleWithHelp('网格下限', 'grid_low'), key: 'grid_low', align: 'right' as const, render: (row: EtfFund) => row.grid_low.toFixed(3) },
  { title: titleWithHelp('网格上限', 'grid_high'), key: 'grid_high', align: 'right' as const, render: (row: EtfFund) => row.grid_high.toFixed(3) },
  { title: titleWithHelp('间距', 'grid_step'), key: 'grid_step', align: 'center' as const, render: (row: EtfFund) => h('span', { class: 'grid-step' }, `${row.grid_step}%`) },
  {
    title: titleWithHelp('预估年化', 'grid_yield_est'), key: 'grid_yield_est', align: 'right' as const,
    render: (row: EtfFund) => h('span', { style: { color: 'var(--color-primary)', fontWeight: 700 } }, `${row.grid_yield_est}%`),
  },
  { title: '近一年波动', key: 'volume', align: 'right' as const, render: (row: EtfFund) => formatVol(row.volume) },
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
      const map: Record<string, { text: string; type: 'success' | 'warning' | 'error' }> = {
        undervalued: { text: '低估', type: 'success' },
        normal: { text: '合理', type: 'warning' },
        overvalued: { text: '高估', type: 'error' },
      }
      const item = map[row.val_category ?? 'normal']
      return h(NTag, { size: 'small', type: item.type, bordered: false }, { default: () => item.text })
    },
  },
  { title: titleWithHelp('PE (TTM)', 'pe'), key: 'pe', align: 'right' as const, render: (row: EtfFund) => row.pe?.toFixed(2) ?? '-' },
  {
    title: titleWithHelp('PE 百分位', 'pe_percentile'), key: 'pe_percentile', align: 'center' as const,
    render: (row: EtfFund) => row.pe_percentile != null ? h(PercentileIndicator, { value: row.pe_percentile }) : '-',
  },
  {
    title: '股息率', key: 'dividend_rate', align: 'right' as const,
    render: (row: EtfFund) => row.dividend_rate ? h('span', { style: { color: 'var(--color-success)' } }, `${row.dividend_rate}%`) : '-',
  },
  { title: '现价', key: 'price', align: 'right' as const, render: (row: EtfFund) => row.price.toFixed(3) },
  {
    title: '定投建议', key: 'action', align: 'center' as const,
    render: (row: EtfFund) => {
      const cat = row.val_category ?? 'normal'
      const map = {
        undervalued: { text: '加倍定投', type: 'success' as const },
        normal: { text: '正常定投', type: 'info' as const },
        overvalued: { text: '暂停定投', type: 'error' as const },
      }
      return h(NTag, { size: 'small', type: map[cat].type, round: true, bordered: false }, { default: () => map[cat].text })
    },
  },
]

const columns = computed(() => {
  if (activeTab.value === 'arbitrage') return arbitrageColumns
  if (activeTab.value === 'grid') return gridColumns
  if (activeTab.value === 'rotation') return rotationColumns
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
}

function formatVol(v: number): string {
  if (v >= 10000000) return `${(v / 10000000).toFixed(2)}亿`
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

function exportEtf() {
  const headersMap: Record<string, string[]> = {
    arbitrage: ['基金名称', '代码', '折溢价率', '溢价百分位', '收益下限%', '收益上限%', '资金容量', 'T+N', '敞口风险%', '可行性', '陷阱', '成交量'],
    grid: ['基金名称', '子类', '现价', '网格下限', '网格上限', '间距', '预估年化', '成交量', '估值百分位'],
    rotation: ['排名', '基金名称', '子类', '动量得分', '估值百分位', 'PE', '成交量'],
    valuation: ['基金名称', '代码', '估值分类', 'PE', 'PE百分位', '股息率', '现价', '定投建议'],
  }
  const rows = displayEtfs.value.map(e => {
    const a = arbitrageAnalysisMap.value.get(e.code)
    if (activeTab.value === 'arbitrage' && a) {
      return [
        e.name, e.code, e.premium_pct, e.premium_percentile,
        a.adjustedYieldLow, a.adjustedYieldHigh, a.capitalLabel,
        `T+${a.holdingDays}`, a.riskExposure, a.feasibilityLabel,
        a.traps.join('; '), e.volume,
      ]
    }
    return [
      e.name, e.code, e.price, e.iopv, e.premium_pct, e.premium_percentile,
      e.net_arbitrage_yield, e.subscribe_limit ?? '', e.volume,
    ]
  })
  exportToCSV(`etf_${activeTab.value}_${new Date().toISOString().slice(0, 10)}`, headersMap[activeTab.value], rows)
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
    <div v-if="etfs" class="etf-page">
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
        <n-data-table
          :columns="columns"
          :data="displayEtfs"
          :row-key="(row: EtfFund) => row.code"
          :bordered="false"
          :single-line="false"
          size="small"
          :row-class-name="(row: EtfFund) => {
            if (activeTab !== 'arbitrage') return ''
            const a = arbitrageAnalysisMap.get(row.code)
            return a?.feasibility === 'infeasible' ? 'row-infeasible' : ''
          }"
          :row-props="(row: EtfFund) => ({ onClick: () => message.info(`${row.name} 详情`), style: 'cursor: pointer' })"
        />
      </DataPanel>

      <!-- 套利陷阱警告 (仅套利tab显示) -->
      <div v-if="activeTab === 'arbitrage'" class="trap-warnings">
        <div class="trap-header">
          <n-icon :component="WarningOutline" size="16" />
          <span>套利陷阱识别</span>
        </div>
        <div class="trap-list">
          <div v-for="etf in displayEtfs" :key="etf.code" class="trap-row">
            <template v-if="arbitrageAnalysisMap.get(etf.code)?.traps.length">
              <span class="trap-name">{{ etf.name }}</span>
              <div class="trap-tags">
                <span
                  v-for="(trap, i) in arbitrageAnalysisMap.get(etf.code)?.traps"
                  :key="i"
                  class="trap-tag"
                >{{ trap }}</span>
              </div>
            </template>
          </div>
          <div v-if="!displayEtfs.some(e => arbitrageAnalysisMap.get(e.code)?.traps.length)" class="trap-empty">
            暂无陷阱标记
          </div>
        </div>
      </div>

      <!-- 策略说明 -->
      <div class="strategy-note">
        <div class="note-header">
          <n-icon :component="tabs.find(t => t.key === activeTab)?.icon ?? SwapHorizontalOutline" size="18" />
          <h4>{{ strategyNotes[activeTab].title }}</h4>
        </div>
        <p>{{ strategyNotes[activeTab].desc }}</p>
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
  padding: 12px 18px;
}
.note-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  color: var(--color-primary);
}
.note-header h4 {
  margin: 0;
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.strategy-note p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

/* === 套利陷阱警告 === */
.trap-warnings {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-left: 3px solid var(--color-danger);
  border-radius: 10px;
  padding: 12px 18px;
}
.trap-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  color: var(--color-danger);
  font-family: 'Work Sans', sans-serif;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.trap-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.trap-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.trap-name {
  min-width: 140px;
  color: var(--text-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trap-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.trap-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 2px;
  background: var(--tag-red-bg);
  color: var(--tag-red-text);
  font-size: 9px;
  font-weight: 700;
}
.trap-empty {
  font-size: 12px;
  color: var(--text-muted);
  font-style: italic;
}
</style>
