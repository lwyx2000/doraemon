<script setup lang="ts">
defineOptions({ name: 'IndexAnalysis' })
import { ref, computed, watch, h, onMounted } from 'vue'
import { NButton, NDataTable, NModal, NEmpty, NTag, useMessage } from 'naive-ui'
import { SearchOutline, ExpandOutline } from '@vicons/ionicons5'
import { api } from '../utils/api'
import type { BroadIndexValuation, SpreadHistoryPoint, SectionSourceMeta } from '../types'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import PercentileIndicator from '../components/PercentileIndicator.vue'
import IconButton from '../components/IconButton.vue'
import LoadingState from '../components/LoadingState.vue'
import BaseChart from '../components/BaseChart.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'

const message = useMessage()
const loading = ref(false)
const data = ref<BroadIndexValuation[]>([])
const meta = ref<SectionSourceMeta | null>(null)
const selectedIndex = ref<BroadIndexValuation | null>(null)

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
onMounted(loadData)

// 时间窗口
const timeWindow = ref('3Y')
const timeWindows = ['1Y', '3Y', '5Y', '10Y', '全部']

// 放大查看弹窗
const showZoomChart = ref(false)

// 表格 meta
const tableMeta = computed(() =>
  meta.value?.updateTime
    ? `最后更新: ${meta.value.updateTime}`
    : `数据源: ${meta.value?.dataSource ?? '实时数据'}`,
)

// ============================================================
// 股债利差历史序列（随选中指数加载，全量数据前端按时间窗口截取）
// ============================================================
const spreadHist = ref<SpreadHistoryPoint[]>([])
const histLoading = ref(false)

watch(
  () => selectedIndex.value?.name,
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

// 按时间窗口截取利差序列
const windowedHist = computed(() => {
  const list = spreadHist.value
  if (!list.length || timeWindow.value === '全部') return list
  const years = timeWindow.value === '1Y' ? 1 : timeWindow.value === '3Y' ? 3 : timeWindow.value === '5Y' ? 5 : 10
  const cutoff = new Date()
  cutoff.setFullYear(cutoff.getFullYear() - years)
  const cutoffStr = cutoff.toISOString().slice(0, 10)
  return list.filter(p => p.date >= cutoffStr)
})

const winLabel = computed(() => (timeWindow.value === '全部' ? '全部历史' : `近${timeWindow.value.replace('Y', '')}年`))

function quantile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q
  const base = Math.floor(pos)
  const rest = pos - base
  return sorted[base + 1] !== undefined ? sorted[base] + rest * (sorted[base + 1] - sorted[base]) : sorted[base]
}

// 利差序列统计：窗口内估值分位/分位线/极值均值全部由利差历史序列计算
// 文档方案：估值分位 = 比历史上百分之多少的时候更贵 = 100 − 利差升序百分位
const bandStats = computed(() => {
  const values = windowedHist.value.map(p => p.spread)
  if (values.length < 2) return null
  const sorted = [...values].sort((a, b) => a - b)
  const current = values[values.length - 1]
  const below = sorted.filter(v => v <= current).length
  const spreadPct = Math.round((below / sorted.length) * 1000) / 10
  const valuationPercentile = Math.round((1 - below / sorted.length) * 1000) / 10
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
    spreadPercentile: spreadPct,
    valuationPercentile,
    count: values.length,
    firstDate: windowedHist.value[0].date,
    lastDate: windowedHist.value[windowedHist.value.length - 1].date,
  }
})

// ============================================================
// ECharts option — 股债利差估值带（历史序列 + 分位线）
// ============================================================
const spreadChartOption = computed(() => {
  const stats = bandStats.value
  const pts = windowedHist.value
  if (!stats || pts.length < 2) return {}
  // 月频序列降采样到 ≤200 点，保留末点
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
    grid: { top: 16, right: 44, bottom: 28, left: 44 },
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

// Auto-select first index once data loads
watch(data, (list) => {
  if (list && list.length && !selectedIndex.value) {
    selectedIndex.value = list[0]
  }
}, { immediate: true })

function selectIndex(index: BroadIndexValuation) {
  selectedIndex.value = index
}

// 估值评估：基于股债利差历史序列
const valAnalysis = computed(() => {
  const idx = selectedIndex.value
  if (!idx) {
    return {
      current: null as number | null,
      spread: null as number | null,
      min: null as number | null,
      avg: null as number | null,
      max: null as number | null,
      percentile: null as number | null,
      assessment: '请选择指数',
    }
  }
  const stats = bandStats.value
  const name = idx.name
  if (stats) {
    const pct = stats.valuationPercentile
    let assessment = ''
    const scope = `${winLabel.value}股债利差序列（${stats.count}个样本，${stats.firstDate} ~ ${stats.lastDate}）`
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
    return {
      current: stats.current,
      spread: stats.current,
      min: stats.min,
      avg: stats.avg,
      max: stats.max,
      percentile: pct,
      assessment,
    }
  }
  // 无历史序列
  const upstreamPct = idx.valuation_percentile
  if (upstreamPct == null) {
    return {
      current: null, spread: null, min: null, avg: null, max: null, percentile: null,
      assessment: `${name}暂无股债利差历史数据（上游数据源未覆盖该指数）。`,
    }
  }
  return {
    current: idx.spread,
    spread: idx.spread,
    min: null, avg: null, max: null,
    percentile: upstreamPct,
    assessment: `${name}当前股债利差为${idx.spread?.toFixed(2) ?? '—'}%，上游估值分位${upstreamPct.toFixed(1)}%。该指数无逐日利差历史序列，区间统计不可用。`,
  }
})

// 估值分位颜色/标签
function percentileColor(pct: number | null): string {
  if (pct == null) return 'default'
  if (pct < 30) return 'success'
  if (pct < 70) return 'warning'
  return 'error'
}

function percentileLabel(pct: number | null): string {
  if (pct == null) return '—'
  if (pct < 30) return '便宜'
  if (pct < 70) return '正常'
  return '过热'
}

function crowdingColor(pct: number | null): string {
  if (pct == null) return 'default'
  if (pct < 30) return 'success'
  if (pct < 70) return 'warning'
  return 'error'
}

// 宏观参数
const macroParams = computed(() => {
  if (!data.value.length) return null
  const first = data.value[0]
  return {
    yield_10y: first.yield_10y,
    cpi_yoy: first.cpi_yoy,
  }
})

const columns = [
  {
    title: '指数',
    key: 'name',
    width: 110,
    fixed: 'left' as const,
    render: (row: BroadIndexValuation) => h('span', { class: 'index-name' }, row.name + (row.is_benchmark ? ' ★' : '')),
  },
  {
    title: 'PB',
    key: 'pb',
    width: 70,
    align: 'right' as const,
    render: (row: BroadIndexValuation) => row.pb != null ? row.pb.toFixed(2) : '—',
  },
  {
    title: 'PE(TTM)',
    key: 'pe_ttm',
    width: 80,
    align: 'right' as const,
    render: (row: BroadIndexValuation) => row.pe_ttm != null ? row.pe_ttm.toFixed(1) : '—',
  },
  {
    title: 'ROE均值',
    key: 'roe_mean',
    width: 90,
    align: 'right' as const,
    render: (row: BroadIndexValuation) => row.roe_mean != null ? row.roe_mean.toFixed(2) + '%' : '—',
  },
  {
    title: '股债利差',
    key: 'spread',
    width: 90,
    align: 'right' as const,
    render: (row: BroadIndexValuation) => row.spread != null ? row.spread.toFixed(2) + '%' : '—',
  },
  {
    title: '估值分位',
    key: 'valuation_percentile',
    width: 130,
    align: 'center' as const,
    render: (row: BroadIndexValuation) => h('div', { style: 'display:flex; align-items:center; justify-content:center; gap:6px;' }, [
      h(PercentileIndicator, { value: row.valuation_percentile, width: 50 }),
      h(NTag, { type: percentileColor(row.valuation_percentile), size: 'small', bordered: false }, () => percentileLabel(row.valuation_percentile)),
    ]),
  },
  {
    title: '拥挤度',
    key: 'crowding',
    width: 120,
    align: 'center' as const,
    render: (row: BroadIndexValuation) => h('div', { style: 'display:flex; align-items:center; justify-content:center; gap:6px;' }, [
      h(PercentileIndicator, { value: row.crowding, width: 50 }),
      h(NTag, { type: crowdingColor(row.crowding), size: 'small', bordered: false }, () => row.crowding != null ? row.crowding.toFixed(0) + '%' : '—'),
    ]),
  },
]

const rowProps = (row: BroadIndexValuation) => ({
  style: 'cursor: pointer',
  onClick: () => selectIndex(row),
})

function exportCSV() {
  const headers = ['指数', 'PB', 'PE(TTM)', 'ROE均值(%)', '股债利差(%)', '估值分位(%)', '拥挤度(%)']
  const rows = data.value.map(idx => [
    idx.name, idx.pb ?? '', idx.pe_ttm ?? '', idx.roe_mean ?? '',
    idx.spread ?? '', idx.valuation_percentile ?? '', idx.crowding ?? '',
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
    skeleton
    :min-height="520"
    text="正在加载指数估值数据..."
    @retry="loadData"
  >
    <div v-if="selectedIndex" class="analysis-page">
    <!-- Page Header -->
    <PageHeader title="指数估值分析" subtitle="基于股债利差的估值分位与拥挤度分析" helpKey="indexAnalysis">
      <template #actions>
        <n-button size="tiny" @click="exportCSV">导出CSV</n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="indexAnalysis" />

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
        <span class="param-label">通胀调整</span>
        <span class="param-value">0.3 × CPI</span>
      </div>
      <div class="param-item">
        <span class="param-label">基准指数</span>
        <span class="param-value">中证800 ★</span>
      </div>
      <div class="param-item" v-if="meta">
        <span class="param-label">数据来源</span>
        <span class="param-value">{{ meta.dataSource }}</span>
      </div>
    </div>

    <!-- 方法论提示 -->
    <div class="method-hint">
      <strong>股债利差</strong> = ROE均值(近5年) ÷ PB − 10年期国债收益率 + 0.3 × CPI同比。
      <strong>估值分位</strong> = 利差在历史中的百分位（越小=越便宜）。
      <n-tag type="success" size="small" :bordered="false">&lt;30% 便宜</n-tag>
      <n-tag type="warning" size="small" :bordered="false">30-70% 正常</n-tag>
      <n-tag type="error" size="small" :bordered="false">&gt;70% 过热</n-tag>
      &nbsp;&nbsp;<strong>拥挤度</strong>：指数PB ÷ 基准PB 的历史分位，衡量相对估值。
    </div>

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
    </section>

    <!-- Main Layout -->
    <div class="main-grid">
      <!-- Left: Index Table -->
      <DataPanel class="table-panel" title="宽基指数估值全景" :meta="tableMeta">
        <n-data-table
          :columns="columns"
          :data="data"
          :row-key="(row: BroadIndexValuation) => row.name"
          :bordered="false"
          :single-line="false"
          size="small"
          :row-props="rowProps"
          :row-class-name="(row: BroadIndexValuation) => selectedIndex?.name === row.name ? 'selected-row' : ''"
        />
      </DataPanel>

      <!-- Right: Detail Panel -->
      <DataPanel class="detail-panel" :title="`${selectedIndex?.name ?? ''} 股债利差估值带`" :meta="bandStats ? `估值视角: ${winLabel}股债利差历史序列` : '估值视角: 上游估值分位'">
        <template #actions>
          <IconButton :icon="SearchOutline" label="放大查看" @click="showZoomChart = true" />
          <IconButton :icon="ExpandOutline" label="全屏" @click="toggleFullscreen" />
        </template>

        <!-- Chart Area -->
        <div class="chart-area">
          <template v-if="bandStats">
            <div class="chart-legend">
              <div class="legend-item"><span class="legend-line solid" />股债利差</div>
              <div class="legend-item"><span class="legend-line dashed-red" />90% 分位</div>
              <div class="legend-item"><span class="legend-line dashed-orange" />70% 分位</div>
              <div class="legend-item"><span class="legend-line dashed-gray" />50% 分位</div>
              <div class="legend-item"><span class="legend-line dashed-blue" />10% 分位</div>
            </div>
            <BaseChart :option="spreadChartOption" :height="220" />
          </template>
          <div v-else class="chart-placeholder">
            {{ histLoading ? '股债利差历史序列加载中...' : '该指数暂无利差历史数据（上游数据源未覆盖）' }}
          </div>
        </div>

        <!-- Analysis Summary -->
        <div class="analysis-summary">
          <h3>估值评估</h3>
          <p>{{ valAnalysis.assessment }}</p>
          <div class="summary-stats">
            <div class="summary-stat">
              <span class="ss-label">{{ winLabel }}最低利差</span>
              <span class="ss-value">{{ valAnalysis.min != null ? valAnalysis.min + '%' : '—' }}</span>
            </div>
            <div class="summary-stat">
              <span class="ss-label">{{ winLabel }}平均利差</span>
              <span class="ss-value">{{ valAnalysis.avg != null ? valAnalysis.avg + '%' : '—' }}</span>
            </div>
            <div class="summary-stat">
              <span class="ss-label">{{ winLabel }}最高利差</span>
              <span class="ss-value">{{ valAnalysis.max != null ? valAnalysis.max + '%' : '—' }}</span>
            </div>
          </div>
        </div>
      </DataPanel>
    </div>
    </div>

    <!-- 取数失败/空数据时的显式空态 -->
    <div v-else-if="!loading" class="empty-page">
      <n-empty description="暂无指数估值数据（上游取数失败或返回为空）">
        <template #extra>
          <n-button size="small" @click="loadData">重试</n-button>
        </template>
      </n-empty>
    </div>

    <!-- 放大查看图表弹窗 -->
    <n-modal v-model:show="showZoomChart" preset="card" :title="`${selectedIndex?.name ?? ''} 股债利差估值带（放大）`" style="width: 880px; max-width: 94vw;" :bordered="false">
      <BaseChart :option="spreadChartOption" :height="420" />
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

/* Macro Params */
.macro-params {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  flex-shrink: 0;
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

/* Method Hint */
.method-hint {
  padding: 10px 16px;
  background: var(--bg-subtle);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.8;
  flex-shrink: 0;
}

.method-hint strong {
  color: var(--text-primary);
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

/* Main Grid */
.main-grid {
  display: flex;
  gap: 14px;
  flex: 1;
  min-height: 0;
}

/* DataPanel as flex items */
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

.empty-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 420px;
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

@media (max-width: 768px) {
  .main-grid { flex-direction: column; }
  .filter-bar { flex-wrap: wrap; gap: 8px; }
  .summary-stats { flex-wrap: wrap; }
}
</style>
