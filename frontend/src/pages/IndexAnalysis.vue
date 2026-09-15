<script setup lang="ts">
defineOptions({ name: 'IndexAnalysis' })
import { ref, computed, watch, h, onMounted } from 'vue'
import { NButton, NDataTable, NModal, NEmpty, useMessage } from 'naive-ui'
import { SearchOutline, ExpandOutline } from '@vicons/ionicons5'
import { useAsyncData } from '../composables/useApi'
import { api } from '../utils/api'
import type { IndexValuation, IndexValuationHistPoint, SectionSourceMeta } from '../types'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import PercentileIndicator from '../components/PercentileIndicator.vue'
import CategoryTag from '../components/CategoryTag.vue'
import IconButton from '../components/IconButton.vue'
import LoadingState from '../components/LoadingState.vue'
import BaseChart from '../components/BaseChart.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const indicesMeta = ref<SectionSourceMeta | null>(null)
const { data: indices, loading, error, refresh: refetch } = useAsyncData<IndexValuation[]>(async () => {
  const r = await api.getIndices()
  indicesMeta.value = r.meta ?? null
  return r.data
})
const selectedIndex = ref<IndexValuation | null>(null)
onMounted(refetch)
const timeWindow = ref('3Y')
const valMethods = ['PE (TTM)', 'PB (MRQ)'] as const
const valMethod = ref<(typeof valMethods)[number]>('PE (TTM)')
const indicator = computed<'pe' | 'pb'>(() => (valMethod.value.startsWith('PE') ? 'pe' : 'pb'))
const valUnit = computed(() => (indicator.value === 'pe' ? 'PE(TTM)' : 'PB(MRQ)'))

// 放大查看弹窗
const showZoomChart = ref(false)

// 仅取有估值数据的指数用于分析（科创板/科创50/中证A500 等暂无估值，不在分析页展示）
const analyzableIndices = computed(() => (indices.value ?? []).filter(i => i.hasValuation !== false))

// 表格"最后更新"来自接口 meta（真实时间，不再写死）
const tableMeta = computed(() =>
  indicesMeta.value?.updateTime
    ? `最后更新: ${indicesMeta.value.updateTime}`
    : `数据源: ${indicesMeta.value?.dataSource ?? '实时数据'}`,
)

// ============================================================
// 估值历史序列（真实数据：乐咕乐股 PE TTM / PB 序列，随选中指数/估值方法切换加载）
// ============================================================
const valHist = ref<IndexValuationHistPoint[]>([])
const histLoading = ref(false)

watch(
  () => [selectedIndex.value?.name, indicator.value] as [string | undefined, 'pe' | 'pb'],
  async ([name, ind]) => {
    if (!name) {
      valHist.value = []
      return
    }
    histLoading.value = true
    try {
      const r = await api.getIndexValuationHistory(name, ind)
      valHist.value = r.data ?? []
    } catch {
      valHist.value = []
    } finally {
      histLoading.value = false
    }
  },
  { immediate: true },
)

// 按时间窗口截取真实序列（1Y/3Y/5Y/10Y/全部）
const windowedHist = computed(() => {
  const list = valHist.value
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

// 真实序列统计：窗口内百分位/分位线/极值均值全部由历史序列计算，不再用公式反推
const bandStats = computed(() => {
  const values = windowedHist.value.map(p => p.value)
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
    percentile: Math.round((below / sorted.length) * 1000) / 10,
    count: values.length,
    firstDate: windowedHist.value[0].date,
    lastDate: windowedHist.value[windowedHist.value.length - 1].date,
  }
})

const winLabel = computed(() => (timeWindow.value === '全部' ? '全部历史' : `近${timeWindow.value.replace('Y', '')}年`))

// ============================================================
// ECharts option — 真实估值带（历史序列 + 真实分位线）
// ============================================================
const peBandChartOption = computed(() => {
  const stats = bandStats.value
  const pts = windowedHist.value
  if (!stats || pts.length < 2) return {}
  // 日频序列降采样到 ≤200 点，保留末点，避免图表过密
  const step = Math.max(1, Math.floor(pts.length / 200))
  const sampled = pts.filter((_, i) => i % step === 0 || i === pts.length - 1)
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `${p.axisValue}<br/>${valUnit.value}: <b>${p.value}</b>`
      },
    },
    grid: { top: 16, right: 44, bottom: 28, left: 40 },
    xAxis: {
      type: 'category',
      data: sampled.map(p => p.date),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#c1c6d7' } },
      axisLabel: { fontSize: 10, color: '#717782' },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { fontSize: 10, color: '#717782' },
      splitLine: { lineStyle: { type: 'dashed', color: 'rgba(0,0,0,0.06)' } },
    },
    series: [
      {
        type: 'line',
        smooth: false,
        showSymbol: false,
        data: sampled.map(p => p.value),
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

// Auto-select first index once data loads
watch(analyzableIndices, (list) => {
  if (list && list.length && !selectedIndex.value) {
    selectedIndex.value = list[0]
  }
}, { immediate: true })

function selectIndex(index: IndexValuation) {
  selectedIndex.value = index
}

const timeWindows = ['1Y', '3Y', '5Y', '10Y', '全部']

// 估值评估：全部基于真实历史序列统计；无序列时仅用上游真实分位，不推算区间
const valAnalysis = computed(() => {
  const idx = selectedIndex.value
  if (!idx) {
    return { current: null as number | null, min: null as number | null, avg: null as number | null, max: null as number | null, percentile: null as number | null, assessment: '请选择指数' }
  }
  const stats = bandStats.value
  const name = idx.name
  const unit = valUnit.value
  if (stats) {
    const pct = stats.percentile
    let assessment = ''
    const scope = `${winLabel.value}真实序列（${stats.count}个样本，${stats.firstDate} ~ ${stats.lastDate}）`
    if (pct < 20) {
      assessment = `${name}当前${unit}为${stats.current}倍，处于${scope}的第${pct}百分位，属于极度低估区域，显著低于历史中位数${stats.p50}倍，长期风险收益比偏向正的对称收益，适合定投建仓。`
    } else if (pct < 40) {
      assessment = `${name}当前${unit}为${stats.current}倍，处于${scope}的第${pct}百分位，估值偏低，低于历史中位数${stats.p50}倍，可逢低布局。`
    } else if (pct < 60) {
      assessment = `${name}当前${unit}为${stats.current}倍，处于${scope}的第${pct}百分位，接近历史中位数${stats.p50}倍，估值中性，不具备明显的估值优势或劣势。`
    } else if (pct < 80) {
      assessment = `${name}当前${unit}为${stats.current}倍，处于${scope}的第${pct}百分位，估值偏高，高于历史中位数${stats.p50}倍，追高需谨慎。`
    } else {
      assessment = `${name}当前${unit}为${stats.current}倍，处于${scope}的第${pct}百分位，属于极度高估区域，远高于历史中位数${stats.p50}倍，注意估值回落风险，建议减仓或回避。`
    }
    return { current: stats.current, min: stats.min, avg: stats.avg, max: stats.max, percentile: pct, assessment }
  }
  // 无历史序列（上游未覆盖该指数）：仅展示列表接口的真实当前值与近5年百分位
  const upstreamCur = indicator.value === 'pe' ? idx.pe : idx.pb
  const upstreamPct = indicator.value === 'pe' ? idx.pe_percentile : idx.pb_percentile
  if (upstreamCur == null && upstreamPct == null) {
    return { current: null, min: null, avg: null, max: null, percentile: null, assessment: `${name}暂无${unit}估值数据（上游数据源未覆盖该指数）。` }
  }
  const pctText = upstreamPct != null ? `，上游近5年百分位第${upstreamPct}%` : ''
  return {
    current: upstreamCur, min: null, avg: null, max: null, percentile: upstreamPct,
    assessment: `${name}当前${unit}为${upstreamCur ?? '—'}倍${pctText}。该指数无逐日估值历史序列，区间统计不可用（不展示推算值）。`,
  }
})

const columns = [
  { title: '指数名称', key: 'name', render: (row: IndexValuation) => h('span', { class: 'index-name' }, row.name) },
  { title: '点位', key: 'level', align: 'right' as const, render: (row: IndexValuation) => row.level.toLocaleString() },
  {
    title: '涨跌幅', key: 'change_pct', align: 'right' as const,
    render: (row: IndexValuation) => h(
      'span',
      { style: { color: row.change_pct >= 0 ? 'var(--color-danger)' : 'var(--color-success)' } },
      `${row.change_pct >= 0 ? '+' : ''}${row.change_pct}%`,
    ),
  },
  {
    title: titleWithHelp('PE百分位', 'pe_percentile'), key: 'pe_percentile', align: 'center' as const,
    render: (row: IndexValuation) => h(PercentileIndicator, { value: row.pe_percentile }),
  },
  {
    title: titleWithHelp('PB百分位', 'pb_percentile'), key: 'pb_percentile', align: 'center' as const,
    render: (row: IndexValuation) => h(PercentileIndicator, { value: row.pb_percentile }),
  },
  {
    title: '分类', key: 'category',
    render: (row: IndexValuation) => h(CategoryTag, { type: row.category }),
  },
  {
    title: '3月变化', key: 'change_3m_pct', align: 'right' as const,
    render: (row: IndexValuation) => h(
      'span',
      { style: { color: row.change_3m_pct >= 0 ? 'var(--color-danger)' : 'var(--color-success)' } },
      `${row.change_3m_pct >= 0 ? '+' : ''}${row.change_3m_pct}%`,
    ),
  },
  { title: titleWithHelp('胜率', 'win_rate'), key: 'win_rate', align: 'right' as const, render: (row: IndexValuation) => `${row.win_rate}%` },
]

const rowProps = (row: IndexValuation) => ({
  style: 'cursor: pointer',
  onClick: () => selectIndex(row),
})

function exportCSV() {
  const headers = ['指数名称', '点位', '涨跌幅', 'PE百分位', 'PB百分位', '分类', '3月变化', '胜率']
  const rows = analyzableIndices.value.map(idx => [
    idx.name, idx.level, idx.change_pct, idx.pe_percentile, idx.pb_percentile,
    idx.category, idx.change_3m_pct, idx.win_rate,
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

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen?.()
  } else {
    document.exitFullscreen?.()
  }
}
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    skeleton
    :min-height="520"
    text="正在加载指数估值数据..."
    @retry="refetch"
  >
    <div v-if="selectedIndex" class="analysis-page">
    <!-- Page Header -->
    <PageHeader title="指数估值分析" subtitle="宽基指数估值历史分位与真实 PE/PB 估值带分析" helpKey="indexAnalysis">
      <template #actions>
        <n-button size="tiny" @click="exportCSV">导出CSV</n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="indexAnalysis" />

    <!-- Top Filter Bar -->
    <section class="filter-bar">
      <div class="filter-group">
        <span class="filter-label">时间窗口:</span>
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
      <div class="filter-divider" />
      <div class="filter-group">
        <span class="filter-label">估值方法:</span>
        <div class="btn-group">
          <button
            v-for="vm in valMethods"
            :key="vm"
            :class="['btn-opt', { active: valMethod === vm }]"
            @click="valMethod = vm"
          >
            {{ vm }}
          </button>
        </div>
      </div>
    </section>

    <!-- Main Layout -->
    <div class="main-grid">
      <!-- Left: Index Table -->
      <DataPanel class="table-panel" title="宽基指数全景" :meta="tableMeta">
        <n-data-table
          :columns="columns"
          :data="analyzableIndices"
          :row-key="(row: IndexValuation) => row.name"
          :bordered="false"
          :single-line="false"
          size="small"
          :row-props="rowProps"
          :row-class-name="(row: IndexValuation) => selectedIndex?.name === row.name ? 'selected-row' : ''"
        />
      </DataPanel>

      <!-- Right: Detail Panel -->
      <DataPanel class="detail-panel" :title="`${selectedIndex?.name ?? ''} ${valUnit}估值带分析`" :meta="bandStats ? `估值视角: ${winLabel}真实历史序列百分位` : '估值视角: 上游近5年百分位'">
        <template #actions>
          <IconButton :icon="SearchOutline" label="放大查看" @click="showZoomChart = true" />
          <IconButton :icon="ExpandOutline" label="全屏" @click="toggleFullscreen" />
        </template>

        <!-- Chart Area -->
        <div class="chart-area">
          <template v-if="bandStats">
            <div class="chart-legend">
              <div class="legend-item"><span class="legend-line solid" />{{ valUnit }}</div>
              <div class="legend-item"><span class="legend-line dashed-red" />90% 分位</div>
              <div class="legend-item"><span class="legend-line dashed-orange" />70% 分位</div>
              <div class="legend-item"><span class="legend-line dashed-gray" />50% 分位</div>
              <div class="legend-item"><span class="legend-line dashed-blue" />10% 分位</div>
            </div>
            <BaseChart :option="peBandChartOption" :height="220" />
          </template>
          <div v-else class="chart-placeholder">
            {{ histLoading ? '估值历史序列加载中...' : '该指数暂无估值历史序列（上游数据源未覆盖），不展示模拟曲线' }}
          </div>
        </div>

        <!-- Analysis Summary -->
        <div class="analysis-summary">
          <h3>估值评估</h3>
          <p>{{ valAnalysis.assessment }}</p>
          <div class="summary-stats">
            <div class="summary-stat">
              <span class="ss-label">{{ winLabel }}最低</span>
              <span class="ss-value">{{ valAnalysis.min != null ? valAnalysis.min + 'x' : '—' }}</span>
            </div>
            <div class="summary-stat">
              <span class="ss-label">{{ winLabel }}平均</span>
              <span class="ss-value">{{ valAnalysis.avg != null ? valAnalysis.avg + 'x' : '—' }}</span>
            </div>
            <div class="summary-stat">
              <span class="ss-label">{{ winLabel }}最高</span>
              <span class="ss-value">{{ valAnalysis.max != null ? valAnalysis.max + 'x' : '—' }}</span>
            </div>
          </div>
        </div>
      </DataPanel>
    </div>
    </div>

    <!-- 取数失败/空数据时的显式空态（修复原先整页白屏无任何提示的问题） -->
    <div v-else-if="!loading && !error" class="empty-page">
      <n-empty description="暂无指数估值数据（上游取数失败或返回为空）">
        <template #extra>
          <n-button size="small" @click="refetch">重试</n-button>
        </template>
      </n-empty>
    </div>

    <!-- 放大查看图表弹窗 -->
    <n-modal v-model:show="showZoomChart" preset="card" :title="`${selectedIndex?.name ?? ''} ${valUnit}估值带（放大）`" style="width: 880px; max-width: 94vw;" :bordered="false">
      <BaseChart :option="peBandChartOption" :height="420" />
    </n-modal>
  </LoadingState>
</template>

<style scoped>
.analysis-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: calc(100vh - 80px);
}

/* Filter Bar */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 4px;
  padding: 12px 16px;
  flex-shrink: 0;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  white-space: nowrap;
}

.btn-group {
  display: flex;
  background: var(--bg-hover);
  border-radius: 4px;
  padding: 2px;
  border: 1px solid var(--border-default);
}

.btn-opt {
  padding: 2px 12px;
  font-family: 'Work Sans', sans-serif;
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

.filter-divider {
  width: 1px;
  height: 24px;
  background: var(--border-default);
}

/* Main Grid */
.main-grid {
  display: flex;
  gap: 14px;
  flex: 1;
  min-height: 0;
}

/* DataPanel as flex items: keep flex sizing + column layout so panel-body can grow */
.table-panel {
  flex: 3;
  display: flex;
  flex-direction: column;
}

.detail-panel {
  flex: 2;
  display: flex;
  flex-direction: column;
}

/* Let the shared DataPanel's body grow and scroll within these panels */
.table-panel :deep(.panel-body),
.detail-panel :deep(.panel-body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.table-panel :deep(.panel-header),
.detail-panel :deep(.panel-header) {
  flex-shrink: 0;
}

/* NDataTable selected row */
:deep(.n-data-table-tr.selected-row) {
  background: rgba(0, 94, 161, 0.08) !important;
  border-left: 3px solid var(--color-primary);
}

.index-name {
  font-family: 'Work Sans', sans-serif;
  font-weight: 600;
  color: var(--text-primary);
}

.chart-area {
  flex: 1;
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.chart-legend {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-family: 'Work Sans', sans-serif;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.legend-line {
  width: 12px;
  height: 2px;
  border-radius: 1px;
}
.legend-line.solid { background: var(--color-primary); }
.legend-line.dashed-red { border-top: 1px dashed rgba(220,38,38,0.6); height: 0; }
.legend-line.dashed-orange { border-top: 1px dashed rgba(249,115,22,0.6); height: 0; }
.legend-line.dashed-gray { border-top: 1px dashed rgba(107,114,128,0.6); height: 0; }
.legend-line.dashed-blue { border-top: 1px dashed rgba(59,130,246,0.6); height: 0; }

.chart-canvas {
  flex: 1;
  border-left: 1px solid var(--border-default);
  border-bottom: 1px solid var(--border-default);
  position: relative;
  min-height: 180px;
}

/* 无估值历史序列时的占位提示（不再展示模拟曲线） */
.chart-placeholder {
  flex: 1;
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 16px;
  font-size: 12px;
  color: var(--text-muted);
  border: 1px dashed var(--border-default);
  border-radius: 4px;
}

/* 取数失败/空数据空态 */
.empty-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 420px;
}

.grid-lines {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.grid-line {
  border-top: 1px solid var(--border-subtle);
}

.band-line {
  position: absolute;
  left: 0;
  right: 0;
  border-top: 1px dashed;
}

.chart-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.chart-tooltip {
  position: absolute;
  left: 60%;
  top: 30%;
  background: var(--bg-card);
  border: 1px solid var(--color-primary);
  padding: 8px;
  border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  z-index: 10;
}

.chart-tooltip .tt-date {
  font-family: 'Work Sans', sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin: 0;
}

.chart-tooltip .tt-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-primary);
  margin: 2px 0 0;
}

.chart-tooltip .tt-sub {
  font-size: 9px;
  color: var(--text-muted);
  margin: 0;
}

.chart-xaxis {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-family: 'Work Sans', sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.analysis-summary {
  padding: 16px;
  background: var(--bg-subtle);
  border-top: 1px solid var(--border-default);
  flex-shrink: 0;
}

.analysis-summary h3 {
  font-family: 'Work Sans', sans-serif;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.analysis-summary p {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0;
}

.summary-stats {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}

.summary-stat {
  flex: 1;
  background: var(--bg-hover);
  padding: 8px;
  border-radius: 4px;
  text-align: center;
}

.ss-label {
  display: block;
  font-family: 'Work Sans', sans-serif;
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

/* Responsive: collapse multi-column grids on smaller screens */
@media (max-width: 768px) {
  .main-grid { flex-direction: column; }
  .filter-bar { flex-wrap: wrap; gap: 8px; }
  .summary-stats { flex-wrap: wrap; }
}
</style>
