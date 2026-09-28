<script setup lang="ts">
defineOptions({ name: 'IndexValuation' })
import { ref, computed, watch, onMounted } from 'vue'
import { NDataTable, NTag, NSpin, NEmpty, NModal, NButton, NAlert, NTabs, NTabPane, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { api } from '../utils/api'
import type { BroadIndexValuation, IndustryValuation, SectionSourceMeta, SpreadHistoryPoint } from '../types'
import PageHeader from '../components/PageHeader.vue'
import PercentileIndicator from '../components/PercentileIndicator.vue'
import BaseChart from '../components/BaseChart.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import MethodologyGuide from '../components/MethodologyGuide.vue'

const message = useMessage()
const loading = ref(false)
const data = ref<BroadIndexValuation[]>([])
const meta = ref<(SectionSourceMeta & { status?: string; message?: string }) | null>(null)

async function loadData() {
  loading.value = true
  try {
    const res = await api.getBroadIndexValuation()
    data.value = res.data
    meta.value = res.meta ?? null
  } catch (e: any) {
    message.error('获取估值数据失败: ' + (e?.message || e))
    data.value = []
  } finally {
    loading.value = false
  }
}

// ==================== 全A整体估值分位（头条，文章方法论的「总开关」） ====================
const overall = computed(() => (meta.value as any)?.overall ?? null)
const benchmarkName = computed(() => (meta.value as any)?.benchmarkName ?? overall.value?.name ?? '中证全指')

// ==================== 行业估值（申万一级） ====================
const industryData = ref<IndustryValuation[]>([])
const industryLoading = ref(false)
const industryMeta = ref<(SectionSourceMeta & {
  status?: string
  message?: string
  insufficientHistory?: boolean
  tradeDays?: number
  snapshotStats?: Record<string, any>
}) | null>(null)

async function loadIndustry() {
  industryLoading.value = true
  try {
    const res = await api.getIndustryValuation()
    industryData.value = res.data || []
    industryMeta.value = res.meta ?? null
  } catch (e: any) {
    message.error('获取行业估值数据失败: ' + (e?.message || e))
    industryData.value = []
  } finally {
    industryLoading.value = false
  }
}

const activeTab = ref<'broad' | 'industry'>('broad')
function handleTabChange(tab: string) {
  activeTab.value = tab as 'broad' | 'industry'
  if (tab === 'industry' && !industryData.value.length && !industryLoading.value && !industryMeta.value) {
    loadIndustry()
  }
}

onMounted(() => { loadData(); loadIndustry() })

// ==================== 估值分位颜色 ====================
function percentileColor(pct: number | null): 'default' | 'success' | 'warning' | 'error' {
  if (pct == null) return 'default'
  if (pct < 30) return 'success'   // 便宜
  if (pct < 70) return 'warning'   // 正常
  return 'error'                    // 过热
}

function percentileLabel(pct: number | null): string {
  if (pct == null) return '—'
  if (pct < 30) return '便宜'
  if (pct < 70) return '正常'
  return '过热'
}

function crowdingColor(pct: number | null): 'default' | 'success' | 'warning' | 'error' {
  if (pct == null) return 'default'
  if (pct < 30) return 'success'
  if (pct < 70) return 'warning'
  return 'error'
}

// ==================== 表格列定义 ====================
const columns: DataTableColumns<BroadIndexValuation> = [
  {
    title: '指数',
    key: 'name',
    width: 110,
    fixed: 'left',
    render: (row) => row.name + (row.is_benchmark ? ' ★' : ''),
  },
  {
    title: 'PB',
    key: 'pb',
    width: 80,
    align: 'right',
    render: (row) => row.pb != null ? row.pb.toFixed(2) : '—',
  },
  {
    title: 'PE(TTM)',
    key: 'pe_ttm',
    width: 90,
    align: 'right',
    render: (row) => row.pe_ttm != null ? row.pe_ttm.toFixed(1) : '—',
  },
  {
    title: 'ROE均值(5Y)',
    key: 'roe_mean',
    width: 110,
    align: 'right',
    render: (row) => row.roe_mean != null ? row.roe_mean.toFixed(2) + '%' : '—',
  },
  {
    title: '股债利差',
    key: 'spread',
    width: 100,
    align: 'right',
    render: (row) => row.spread != null ? row.spread.toFixed(2) + '%' : '—',
  },
  {
    title: '估值分位',
    key: 'valuation_percentile',
    width: 140,
    align: 'center',
    render: (row) => h('div', { style: 'display:flex; align-items:center; justify-content:center; gap:6px;' }, [
      h(PercentileIndicator, { value: row.valuation_percentile, width: 60 }),
      h(NTag, { type: percentileColor(row.valuation_percentile), size: 'small', bordered: false }, () => percentileLabel(row.valuation_percentile)),
    ]),
  },
  {
    title: 'PE分位',
    key: 'pe_percentile',
    width: 140,
    align: 'center',
    render: (row) => h('div', { style: 'display:flex; align-items:center; justify-content:center; gap:6px;' }, [
      h(PercentileIndicator, { value: row.pe_percentile, width: 60 }),
      h(NTag, { type: percentileColor(row.pe_percentile), size: 'small', bordered: false }, () => percentileLabel(row.pe_percentile)),
    ]),
  },
  {
    title: 'PB分位',
    key: 'pb_percentile',
    width: 140,
    align: 'center',
    render: (row) => h('div', { style: 'display:flex; align-items:center; justify-content:center; gap:6px;' }, [
      h(PercentileIndicator, { value: row.pb_percentile, width: 60 }),
      h(NTag, { type: percentileColor(row.pb_percentile), size: 'small', bordered: false }, () => percentileLabel(row.pb_percentile)),
    ]),
  },
  {
    title: '拥挤度',
    key: 'crowding',
    width: 140,
    align: 'center',
    render: (row) => h('div', { style: 'display:flex; align-items:center; justify-content:center; gap:6px;' }, [
      h(PercentileIndicator, { value: row.crowding, width: 60 }),
      h(NTag, { type: crowdingColor(row.crowding), size: 'small', bordered: false }, () => row.crowding != null ? row.crowding.toFixed(0) + '%' : '—'),
    ]),
  },
]

// ==================== 行业估值表格列 ====================
function pctColor(pct: number | null): string {
  if (pct == null) return 'var(--text-primary)'
  if (pct < 30) return '#16a34a'
  if (pct > 70) return '#dc2626'
  return 'var(--text-primary)'
}

const industryColumns: DataTableColumns<IndustryValuation> = [
  {
    title: '行业',
    key: 'name',
    width: 130,
    fixed: 'left',
    render: (row) => row.name || row.code,
  },
  {
    title: 'PE',
    key: 'pe',
    width: 80,
    align: 'right',
    render: (row) => row.pe != null ? row.pe.toFixed(1) : '—',
  },
  {
    title: 'PB',
    key: 'pb',
    width: 80,
    align: 'right',
    render: (row) => row.pb != null ? row.pb.toFixed(2) : '—',
  },
  {
    title: '股息率',
    key: 'dividend_yield',
    width: 90,
    align: 'right',
    render: (row) => row.dividend_yield != null ? row.dividend_yield.toFixed(2) + '%' : '—',
  },
  {
    title: 'PE分位',
    key: 'pe_percentile',
    width: 130,
    align: 'center',
    render: (row) => h('div', { style: 'display:flex; align-items:center; justify-content:center; gap:6px;' }, [
      h(PercentileIndicator, { value: row.pe_percentile, width: 60 }),
      h(NTag, { type: percentileColor(row.pe_percentile), size: 'small', bordered: false }, () => percentileLabel(row.pe_percentile)),
    ]),
  },
  {
    title: 'PB分位',
    key: 'pb_percentile',
    width: 130,
    align: 'center',
    render: (row) => h('div', { style: 'display:flex; align-items:center; justify-content:center; gap:6px;' }, [
      h(PercentileIndicator, { value: row.pb_percentile, width: 60 }),
      h(NTag, { type: percentileColor(row.pb_percentile), size: 'small', bordered: false }, () => percentileLabel(row.pb_percentile)),
    ]),
  },
  {
    title: '拥挤度',
    key: 'crowding',
    width: 130,
    align: 'center',
    render: (row) => h('div', { style: 'display:flex; align-items:center; justify-content:center; gap:6px;' }, [
      h(PercentileIndicator, { value: row.crowding, width: 60 }),
      h(NTag, { type: percentileColor(row.crowding), size: 'small', bordered: false }, () => row.crowding != null ? row.crowding.toFixed(0) + '%' : '—'),
    ]),
  },
]

import { h } from 'vue'

// 行点击直接打开详情弹窗
const rowProps = (row: BroadIndexValuation) => ({
  style: 'cursor: pointer',
  onClick: () => openDetail(row),
})

// 导出宽基估值 CSV（原指数分析页功能）
function exportCSV() {
  const headers = ['指数', 'PB', 'PE(TTM)', 'ROE均值(%)', '股债利差(%)', '估值分位(%)', 'PE分位(%)', 'PB分位(%)', '拥挤度(%)']
  const rows = data.value.map(idx => [
    idx.name, idx.pb ?? '', idx.pe_ttm ?? '', idx.roe_mean ?? '',
    idx.spread ?? '', idx.valuation_percentile ?? '',
    idx.pe_percentile ?? '', idx.pb_percentile ?? '', idx.crowding ?? '',
  ])
  const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `index_valuation_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
  message.success(`已导出 ${rows.length} 条指数数据`)
}

// ==================== 详情弹窗 ====================
const detailVisible = ref(false)
const selectedItem = ref<BroadIndexValuation | null>(null)

// 全量股债利差历史（打开弹窗时异步拉取，区别于行内自带的 120 月截断）
const spreadHist = ref<SpreadHistoryPoint[]>([])
const histLoading = ref(false)

function openDetail(row: BroadIndexValuation) {
  selectedItem.value = row
  detailVisible.value = true
}

watch(
  () => selectedItem.value?.name,
  async (name) => {
    if (!name) {
      spreadHist.value = []
      return
    }
    histLoading.value = true
    try {
      const r = await api.getIndexSpreadHistory(name)
      spreadHist.value = r.data ?? []
    } catch {
      spreadHist.value = []
    } finally {
      histLoading.value = false
    }
  },
  { immediate: true },
)

// 时间窗口：全量序列前端截取
const timeWindow = ref('全部')
const timeWindows = ['1Y', '3Y', '5Y', '10Y', '全部']
const winLabel = computed(() => (timeWindow.value === '全部' ? '全部历史' : `近${timeWindow.value.replace('Y', '')}年`))

const windowedHist = computed(() => {
  const list = spreadHist.value
  if (!list.length || timeWindow.value === '全部') return list
  const years = timeWindow.value === '1Y' ? 1 : timeWindow.value === '3Y' ? 3 : timeWindow.value === '5Y' ? 5 : 10
  const cutoff = new Date()
  cutoff.setFullYear(cutoff.getFullYear() - years)
  const cutoffStr = cutoff.toISOString().slice(0, 10)
  return list.filter(p => p.date >= cutoffStr)
})

function quantile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q
  const base = Math.floor(pos)
  const rest = pos - base
  return sorted[base + 1] !== undefined ? sorted[base] + rest * (sorted[base + 1] - sorted[base]) : sorted[base]
}

// 窗口内利差统计 + 估值分位（100 − 升序百分位，与列表口径一致）
const bandStats = computed(() => {
  const values = windowedHist.value.map(p => p.spread)
  if (values.length < 2) return null
  const sorted = [...values].sort((a, b) => a - b)
  const current = values[values.length - 1]
  const below = sorted.filter(v => v <= current).length
  const r2 = (n: number) => Math.round(n * 100) / 100
  return {
    current: r2(current),
    min: r2(sorted[0]),
    max: r2(sorted[sorted.length - 1]),
    avg: r2(values.reduce((s, v) => s + v, 0) / values.length),
    p90: r2(quantile(sorted, 0.9)),
    p70: r2(quantile(sorted, 0.7)),
    p50: r2(quantile(sorted, 0.5)),
    p10: r2(quantile(sorted, 0.1)),
    valuationPercentile: Math.round((1 - below / sorted.length) * 1000) / 10,
    count: values.length,
    firstDate: windowedHist.value[0].date,
    lastDate: windowedHist.value[windowedHist.value.length - 1].date,
  }
})

// 股债利差估值带：历史序列 + 90/70/50/10 分位线（月频降采样 ≤200 点）
const spreadBandOption = computed(() => {
  const stats = bandStats.value
  const pts = windowedHist.value
  if (!stats || pts.length < 2) return {}
  const step = Math.max(1, Math.floor(pts.length / 200))
  const sampled = pts.filter((_, i) => i % step === 0 || i === pts.length - 1)
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `${p.axisValue}<br/>股债利差: <b>${p.value}%</b>`
      },
    },
    grid: { top: 16, right: 52, bottom: 28, left: 44 },
    xAxis: {
      type: 'category',
      data: sampled.map(p => p.date),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#c1c6d7' } },
      axisLabel: { fontSize: 10, color: '#717782' },
    },
    yAxis: {
      type: 'value',
      name: '利差(%)',
      nameTextStyle: { fontSize: 10, color: '#717782' },
      scale: true,
      axisLabel: { fontSize: 10, color: '#717782', formatter: '{value}%' },
      splitLine: { lineStyle: { type: 'dashed', color: 'rgba(0,0,0,0.06)' } },
    },
    series: [
      {
        type: 'line',
        smooth: false,
        showSymbol: false,
        data: sampled.map(p => p.spread),
        lineStyle: { width: 2, color: '#005ea1' },
        itemStyle: { color: '#005ea1' },
        areaStyle: {
          opacity: 0.1,
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(0, 94, 161, 0.35)' },
              { offset: 1, color: 'rgba(0, 94, 161, 0)' },
            ],
          },
        },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { type: 'dashed', width: 1 },
          data: [
            { yAxis: stats.p90, lineStyle: { color: 'rgba(220,38,38,0.5)' }, label: { formatter: '90%', position: 'end', fontSize: 9, color: '#dc2626' } },
            { yAxis: stats.p70, lineStyle: { color: 'rgba(249,115,22,0.5)' }, label: { formatter: '70%', position: 'end', fontSize: 9, color: '#f97316' } },
            { yAxis: stats.p50, lineStyle: { color: 'rgba(107,114,128,0.5)' }, label: { formatter: '50%', position: 'end', fontSize: 9, color: '#6b7280' } },
            { yAxis: stats.p10, lineStyle: { color: 'rgba(59,130,246,0.5)' }, label: { formatter: '10%', position: 'end', fontSize: 9, color: '#3b82f6' } },
          ],
        },
      },
    ],
  }
})

// 估值评估文字（与文章方法论一致的五档判断）
const valAnalysis = computed(() => {
  const idx = selectedItem.value
  if (!idx || !bandStats.value) return null
  const stats = bandStats.value
  const pct = stats.valuationPercentile
  const name = idx.name
  const scope = `${winLabel.value}股债利差序列（${stats.count}个样本，${stats.firstDate} ~ ${stats.lastDate}）`
  let assessment: string
  if (pct < 20) {
    assessment = `${name}当前股债利差为${stats.current}%，处于${scope}的估值分位${pct}%（极度低估区域），利差显著高于历史中位数${stats.p50}%，股票相对债券极具吸引力，适合定投建仓。`
  } else if (pct < 30) {
    assessment = `${name}当前股债利差为${stats.current}%，处于${scope}的估值分位${pct}%（价值机会区），利差高于历史中位数${stats.p50}%，股票相对便宜，可逢低布局。`
  } else if (pct < 70) {
    assessment = `${name}当前股债利差为${stats.current}%，处于${scope}的估值分位${pct}%（正常区间），接近历史中位数${stats.p50}%，估值中性，不具备明显的估值优势或劣势。`
  } else if (pct < 80) {
    assessment = `${name}当前股债利差为${stats.current}%，处于${scope}的估值分位${pct}%（估值偏高），利差低于历史中位数${stats.p50}%，股票相对偏贵，追高需谨慎。`
  } else {
    assessment = `${name}当前股债利差为${stats.current}%，处于${scope}的估值分位${pct}%（极度高估区域），利差远低于历史中位数${stats.p50}%，注意估值回落风险，建议减仓或回避。`
  }
  return { stats, assessment }
})

// PB / PE / 点数历史走势图（后端返回最近120个月，跟随时间窗口截取）
function sliceByWindow<T extends { date: string }>(list: T[] | undefined): T[] {
  if (!list?.length || timeWindow.value === '全部') return list ?? []
  const years = timeWindow.value === '1Y' ? 1 : timeWindow.value === '3Y' ? 3 : timeWindow.value === '5Y' ? 5 : 10
  const cutoff = new Date()
  cutoff.setFullYear(cutoff.getFullYear() - years)
  const cutoffStr = cutoff.toISOString().slice(0, 10)
  return list.filter(p => p.date >= cutoffStr)
}

// 网关 index-valuation 对宽基指数返回的 pe_ttm 与 pe_static 恒等（实测 100% 相同，属上游数据问题），
// 仅当二者真有差异时才画第二条线，避免两条完全重合的误导线。
const peStaticDiffers = computed(() => {
  const h = selectedItem.value?.pe_history
  return Array.isArray(h) && h.some(r => r.pe_static != null && r.pe_ttm != null && r.pe_static !== r.pe_ttm)
})

const pbChartOption = computed(() => {
  const hist = sliceByWindow(selectedItem.value?.pb_history)
  if (!hist.length) return {}
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 30, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: hist.map(h => h.date), boundaryGap: false, axisLabel: { fontSize: 10, color: '#717782' } },
    yAxis: { type: 'value', name: 'PB', scale: true, axisLabel: { fontSize: 10, color: '#717782' } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 5 }],
    series: [{
      name: 'PB',
      type: 'line',
      data: hist.map(h => h.pb),
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 2, color: '#f59e0b' },
      itemStyle: { color: '#f59e0b' },
      areaStyle: { color: 'rgba(245,158,11,0.1)' },
    }],
  }
})

const peChartOption = computed(() => {
  const hist = sliceByWindow(selectedItem.value?.pe_history)
  if (!hist.length) return {}
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) =>
        params.map((p: any) => `${p.marker}${p.seriesName}: <b>${p.value ?? '—'}</b>`).join('<br/>'),
    },
    legend: { data: ['PE(TTM)', ...(peStaticDiffers.value ? ['PE(静态)'] : [])], top: 0, textStyle: { fontSize: 10, color: '#717782' } },
    grid: { left: 50, right: 30, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: hist.map(h => h.date), boundaryGap: false, axisLabel: { fontSize: 10, color: '#717782' } },
    yAxis: { type: 'value', name: 'PE', scale: true, axisLabel: { fontSize: 10, color: '#717782' } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 5 }],
    series: [
      {
        name: 'PE(TTM)',
        type: 'line',
        data: hist.map(h => h.pe_ttm),
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#005ea1' },
        itemStyle: { color: '#005ea1' },
      },
      ...(peStaticDiffers.value ? [{
        name: 'PE(静态)',
        type: 'line',
        data: hist.map(h => h.pe_static),
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#94a3b8', type: 'dashed' },
        itemStyle: { color: '#94a3b8' },
      }] : []),
    ],
  }
})

const priceChartOption = computed(() => {
  const hist = sliceByWindow(selectedItem.value?.price_history)
  if (!hist.length) return {}
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `${p.axisValue}<br/>指数点数: <b>${Number(p.value).toLocaleString('zh-CN')}</b>`
      },
    },
    grid: { left: 66, right: 30, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: hist.map(h => h.date), boundaryGap: false, axisLabel: { fontSize: 10, color: '#717782' } },
    yAxis: { type: 'value', name: '点数', scale: true, axisLabel: { fontSize: 10, color: '#717782' } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 5 }],
    series: [{
      name: '指数点数',
      type: 'line',
      data: hist.map(h => h.value),
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 2, color: '#16a34a' },
      itemStyle: { color: '#16a34a' },
      areaStyle: { color: 'rgba(22,163,74,0.08)' },
    }],
  }
})

// ==================== 宏观参数展示 ====================
const macroParams = computed(() => {
  if (!data.value.length) return null
  const first = data.value[0]
  return {
    yield_10y: first.yield_10y,
    cpi_yoy: first.cpi_yoy,
  }
})
</script>

<template>
  <div class="index-valuation-page">
    <PageHeader title="宽基指数估值分析" subtitle="股债利差估值分位 + 拥挤度" helpKey="indexValuation">
      <template #actions>
        <n-button size="tiny" @click="exportCSV">导出CSV</n-button>
      </template>
    </PageHeader>

    <!-- 页面顶部说明：估值方法说明（公众号方法论）+ 缩写词典，均为可折叠、默认隐藏 -->
    <div class="top-guides">
      <MethodologyGuide />
      <GlossaryPanel page-key="indexValuation" />
    </div>

    <!-- 全A整体估值分位（头条：文章方法论的「总开关」） -->
    <div v-if="overall" class="overall-card">
      <div class="overall-head">
        <span class="overall-title">全A整体估值分位</span>
        <n-tag :type="percentileColor(overall.valuation_percentile)" size="small" :bordered="false">
          {{ percentileLabel(overall.valuation_percentile) }}
        </n-tag>
        <span class="overall-sub">基准 = {{ overall.name }}（万得全A代理）</span>
      </div>
      <div class="overall-body">
        <div class="overall-pct" :style="{ color: pctColor(overall.valuation_percentile) }">
          {{ overall.valuation_percentile != null ? overall.valuation_percentile.toFixed(1) + '%' : '—' }}
        </div>
        <div class="overall-metrics">
          <div class="om"><span>PB</span><b>{{ overall.pb?.toFixed(2) ?? '—' }}</b></div>
          <div class="om"><span>PE(TTM)</span><b>{{ overall.pe_ttm?.toFixed(1) ?? '—' }}</b></div>
          <div class="om"><span>ROE均值(5Y)</span><b>{{ overall.roe_mean?.toFixed(2) ?? '—' }}%</b></div>
          <div class="om"><span>股债利差</span><b>{{ overall.spread?.toFixed(2) ?? '—' }}%</b></div>
        </div>
      </div>
    </div>

    <!-- Tab：宽基指数 / 行业估值 -->
    <n-tabs v-model:value="activeTab" type="line" @update:value="handleTabChange">
      <n-tab-pane name="broad" tab="宽基指数">
        <!-- 宏观参数 -->
        <div v-if="macroParams" class="macro-params">
          <div class="param-item">
            <span class="param-label">10年期国债收益率</span>
            <span class="param-value">{{ macroParams.yield_10y != null ? macroParams.yield_10y.toFixed(2) + '%' : '—' }}</span>
          </div>
          <div class="param-item">
            <span class="param-label">CPI同比</span>
            <span class="param-value">{{ macroParams.cpi_yoy != null ? macroParams.cpi_yoy.toFixed(2) + '%' : '—' }}</span>
          </div>
          <div class="param-item">
            <span class="param-label">通胀调整系数</span>
            <span class="param-value">0.3 × CPI</span>
          </div>
          <div class="param-item">
            <span class="param-label">基准指数</span>
            <span class="param-value">{{ benchmarkName }} ★</span>
          </div>
          <div class="param-item" v-if="meta">
            <span class="param-label">数据来源</span>
            <span class="param-value">{{ meta.dataSource }}</span>
          </div>
        </div>

        <!-- 方法论提示 -->
        <div class="method-hint">
          <strong>估值分位</strong>：基于股债利差 = ROE均值/PB − 国债收益率 + 0.3×CPI，取历史百分位。
          <n-tag type="success" size="small" :bordered="false">&lt;30% 便宜</n-tag>
          <n-tag type="warning" size="small" :bordered="false">30-70% 正常</n-tag>
          <n-tag type="error" size="small" :bordered="false">&gt;70% 过热</n-tag>
          &nbsp;&nbsp;<strong>拥挤度</strong>：指数PB / 全A(PB) 的历史分位，衡量相对估值。
        </div>

        <!-- 数据源不可用横幅（优雅降级，替代白屏/499） -->
        <n-alert
          v-if="meta && meta.status === 'unavailable'"
          type="warning"
          :show-icon="true"
          title="估值数据源暂不可用"
          style="margin-bottom: 12px"
        >
          {{ meta.message || '远程网关指数 PE/PB 接口异常，估值功能已降级，请稍后重试。' }}
        </n-alert>

        <!-- 数据表格 -->
        <n-spin :show="loading">
          <n-data-table
            v-if="data.length"
            :columns="columns"
            :data="data"
            :bordered="false"
            :single-line="false"
            size="small"
            :max-height="560"
            :scroll-x="1130"
            :row-props="rowProps"
          />
          <n-empty v-else-if="!loading" description="暂无数据，请确保后端服务正常运行" style="padding: 60px 0" />
        </n-spin>
      </n-tab-pane>

      <n-tab-pane name="industry" tab="行业估值">
        <!-- 累积中提示：本地每日累积，历史样本不足时分位仅供参考 -->
        <n-alert
          v-if="industryMeta && industryMeta.insufficientHistory"
          type="info"
          :show-icon="true"
          title="行业估值快照累积中"
          style="margin-bottom: 12px"
        >
          数据源已切换为本地每日累积（网关 sw_index_first_info），当前已积累
          {{ industryMeta.tradeDays ?? 0 }} 个交易日。分位 / 拥挤度为初步参考，历史越长越准。
        </n-alert>
        <n-alert
          v-if="industryMeta && industryMeta.status === 'unavailable'"
          type="warning"
          :show-icon="true"
          title="行业估值快照暂不可用"
          style="margin-bottom: 12px"
        >
          {{ industryMeta.message || '行业估值快照（本地 base_sw_sector_daily）尚未累积到数据，请确认网关可访问或稍后重试。' }}
        </n-alert>
        <n-spin :show="industryLoading">
          <n-data-table
            v-if="industryData.length"
            :columns="industryColumns"
            :data="industryData"
            :bordered="false"
            :single-line="false"
            size="small"
            :max-height="560"
            :scroll-x="780"
          />
          <n-empty v-else-if="!industryLoading" description="暂无行业估值数据" style="padding: 60px 0" />
        </n-spin>
      </n-tab-pane>
    </n-tabs>

    <!-- 详情弹窗：点击列表行打开 -->
    <n-modal
      v-model:show="detailVisible"
      preset="card"
      :title="selectedItem ? `${selectedItem.name} · 指数详情` : '指数详情'"
      style="width: 96vw; max-width: 96vw"
      :bordered="false"
    >
      <div v-if="selectedItem" class="detail-content">
        <!-- 当前数据卡片 -->
        <div class="detail-stats">
          <div class="stat-item">
            <span class="stat-label">当前PB</span>
            <span class="stat-value">{{ selectedItem.pb?.toFixed(2) ?? '—' }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">PE(TTM)</span>
            <span class="stat-value">{{ selectedItem.pe_ttm?.toFixed(1) ?? '—' }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">ROE均值(5Y)</span>
            <span class="stat-value">{{ selectedItem.roe_mean?.toFixed(2) ?? '—' }}%</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">股债利差</span>
            <span class="stat-value">{{ selectedItem.spread?.toFixed(2) ?? '—' }}%</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">估值分位</span>
            <span class="stat-value" :style="{ color: (selectedItem.valuation_percentile ?? 50) < 30 ? '#16a34a' : (selectedItem.valuation_percentile ?? 50) > 70 ? '#dc2626' : 'var(--text-primary)' }">
              {{ selectedItem.valuation_percentile?.toFixed(1) ?? '—' }}%
            </span>
          </div>
          <div class="stat-item">
            <span class="stat-label">拥挤度</span>
            <span class="stat-value" :style="{ color: (selectedItem.crowding ?? 50) < 30 ? '#16a34a' : (selectedItem.crowding ?? 50) > 70 ? '#dc2626' : 'var(--text-primary)' }">
              {{ selectedItem.crowding?.toFixed(1) ?? '—' }}%
            </span>
          </div>
        </div>

        <!-- 股债利差估值带（全量历史 + 分位线） -->
        <div class="detail-section">
          <div class="section-head">
            <h4 class="section-title">股债利差估值带</h4>
            <div class="btn-group">
              <button
                v-for="tw in timeWindows"
                :key="tw"
                :class="['btn-opt', { active: timeWindow === tw }]"
                @click="timeWindow = tw"
              >
                {{ tw }}
              </button>
            </div>
          </div>
          <template v-if="valAnalysis">
            <div class="chart-legend">
              <div class="legend-item"><span class="legend-line solid" />股债利差</div>
              <div class="legend-item"><span class="legend-line dashed-red" />90% 分位</div>
              <div class="legend-item"><span class="legend-line dashed-orange" />70% 分位</div>
              <div class="legend-item"><span class="legend-line dashed-gray" />50% 分位</div>
              <div class="legend-item"><span class="legend-line dashed-blue" />10% 分位</div>
            </div>
            <BaseChart :option="spreadBandOption" :height="260" />
            <div class="analysis-summary">
              <p>{{ valAnalysis.assessment }}</p>
              <div class="summary-stats">
                <div class="summary-stat">
                  <span class="ss-label">{{ winLabel }}最低利差</span>
                  <span class="ss-value">{{ valAnalysis.stats.min }}%</span>
                </div>
                <div class="summary-stat">
                  <span class="ss-label">{{ winLabel }}平均利差</span>
                  <span class="ss-value">{{ valAnalysis.stats.avg }}%</span>
                </div>
                <div class="summary-stat">
                  <span class="ss-label">{{ winLabel }}最高利差</span>
                  <span class="ss-value">{{ valAnalysis.stats.max }}%</span>
                </div>
                <div class="summary-stat">
                  <span class="ss-label">{{ winLabel }}估值分位</span>
                  <span class="ss-value">{{ valAnalysis.stats.valuationPercentile }}%</span>
                </div>
              </div>
            </div>
          </template>
          <n-empty
            v-else
            :description="histLoading ? '股债利差历史序列加载中...' : '该指数暂无利差历史数据（上游数据源未覆盖）'"
            style="padding: 30px 0"
          />
        </div>

        <!-- PB / PE 历史走势（并排网格，一次显示多图） -->
        <div class="detail-charts-grid">
          <div class="detail-section">
            <h4 class="section-title">PB 历史走势（{{ winLabel }}）</h4>
            <BaseChart v-if="pbChartOption && Object.keys(pbChartOption).length" :option="pbChartOption" :height="240" />
            <n-empty v-else description="暂无PB历史数据" style="padding: 30px 0" />
          </div>

          <!-- PE 历史走势 -->
          <div class="detail-section">
            <div class="section-head">
              <h4 class="section-title">PE 历史走势（{{ winLabel }}）</h4>
              <div class="chart-legend" v-if="peStaticDiffers">
                <div class="legend-item"><span class="legend-line solid" />PE(TTM)</div>
                <div class="legend-item"><span class="legend-line dashed-gray" />PE(静态)</div>
              </div>
              <span v-else class="legend-note">PE(TTM) 与 PE(静态) 在该数据源取值相同，仅显示其一</span>
            </div>
            <BaseChart v-if="peChartOption && Object.keys(peChartOption).length" :option="peChartOption" :height="240" />
            <n-empty v-else description="暂无PE历史数据" style="padding: 30px 0" />
          </div>
        </div>

        <!-- 指数点数历史走势 -->
        <div class="detail-section">
          <h4 class="section-title">指数点数历史走势（{{ winLabel }}）</h4>
          <BaseChart v-if="priceChartOption && Object.keys(priceChartOption).length" :option="priceChartOption" :height="220" />
          <n-empty v-else description="暂无点数历史数据" style="padding: 30px 0" />
        </div>

        <!-- 公式说明 -->
        <div class="formula-hint">
          <n-text depth="3" style="font-size: 12px; line-height: 1.8">
            股债利差 = ROE均值(近5年) ÷ PB − 10年期国债收益率 + 0.3 × CPI同比<br>
            估值分位 = 100 − 利差在历史中的升序百分位（越小=越便宜）<br>
            拥挤度 = (指数PB ÷ 中证全指PB) 在历史中的百分位（越小=相对越便宜）
          </n-text>
        </div>
      </div>
    </n-modal>
  </div>
</template>

<style scoped>
.index-valuation-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.top-guides {
  display: flex;
  flex-direction: column;
}
.top-guides > :last-child {
  margin-bottom: 0;
}

.macro-params {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.param-label {
  font-size: 11px;
  color: var(--text-muted);
}

.param-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.method-hint {
  padding: 10px 16px;
  background: var(--bg-subtle);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.8;
}

.method-hint strong {
  color: var(--text-primary);
}

.overall-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 20px;
  background: linear-gradient(135deg, var(--bg-card), var(--bg-subtle));
  border: 1px solid var(--border-default);
  border-radius: 10px;
}

.overall-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.overall-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.overall-sub {
  font-size: 11px;
  color: var(--text-muted);
}

.overall-body {
  display: flex;
  align-items: center;
  gap: 28px;
  flex-wrap: wrap;
}

.overall-pct {
  font-family: 'JetBrains Mono', monospace;
  font-size: 38px;
  font-weight: 800;
  line-height: 1;
}

.overall-metrics {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}

.om {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.om span {
  font-size: 11px;
  color: var(--text-muted);
}

.om b {
  font-family: 'JetBrains Mono', monospace;
  font-size: 15px;
  color: var(--text-primary);
}

.detail-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-height: 88vh;
  overflow-y: auto;
  padding-right: 4px;
}

.detail-charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.legend-note {
  font-size: 11px;
  color: var(--text-muted);
  align-self: center;
}

@media (max-width: 960px) {
  .detail-charts-grid {
    grid-template-columns: 1fr;
  }
}

.detail-stats {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: var(--bg-subtle);
  border-radius: 8px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-label {
  font-size: 11px;
  color: var(--text-muted);
}

.stat-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.detail-section {
  display: flex;
  flex-direction: column;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

/* 时间窗口按钮组（原指数分析页样式） */
.btn-group {
  display: flex;
  background: var(--bg-hover);
  border-radius: 4px;
  padding: 2px;
  border: 1px solid var(--border-default);
}

.btn-opt {
  padding: 2px 10px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  border: none;
  background: transparent;
  border-radius: 3px;
  cursor: pointer;
  color: var(--text-muted);
  transition: all 0.15s;
}

.btn-opt:hover { background: var(--bg-active); }
.btn-opt.active {
  background: var(--color-primary);
  color: white;
  box-shadow: 0 1px 3px rgba(0,0,0,0.15);
}

/* 估值带图例（原指数分析页样式） */
.chart-legend {
  display: flex;
  gap: 14px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.legend-line {
  width: 12px;
  height: 2px;
  border-radius: 1px;
}
.legend-line.solid { background: #005ea1; }
.legend-line.dashed-red { border-top: 1px dashed rgba(220,38,38,0.6); height: 0; }
.legend-line.dashed-orange { border-top: 1px dashed rgba(249,115,22,0.6); height: 0; }
.legend-line.dashed-gray { border-top: 1px dashed rgba(107,114,128,0.6); height: 0; }
.legend-line.dashed-blue { border-top: 1px dashed rgba(59,130,246,0.6); height: 0; }

/* 估值评估摘要 */
.analysis-summary {
  margin-top: 12px;
  padding: 12px 14px;
  background: var(--bg-subtle);
  border-radius: 8px;
}

.analysis-summary p {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
  margin: 0;
}

.summary-stats {
  display: flex;
  gap: 12px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.summary-stat {
  flex: 1;
  min-width: 90px;
  background: var(--bg-hover);
  padding: 8px;
  border-radius: 4px;
  text-align: center;
}

.ss-label {
  display: block;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.ss-value {
  display: block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin-top: 2px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
}

.formula-hint {
  padding: 10px 14px;
  background: var(--bg-subtle);
  border-radius: 6px;
}
</style>
