<script setup lang="ts">
defineOptions({ name: 'IndexAnalysis' })
import { ref, computed, watch, h, reactive, onMounted } from 'vue'
import { NButton, NDataTable, NModal, NInput, useMessage } from 'naive-ui'
import { SearchOutline, ExpandOutline } from '@vicons/ionicons5'
import { useAsyncData } from '../composables/useApi'
import { api } from '../utils/api'
import type { IndexValuation } from '../types'
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
const { data: indices, loading, error, refresh: refetch } = useAsyncData<IndexValuation[]>(() => api.getIndices().then(r => r.data))
const selectedIndex = ref<IndexValuation | null>(null)
onMounted(refetch)
const timeWindow = ref('3Y')
const valMethod = ref('PE (TTM)')

// 自定义指数弹窗
const showCustomIndex = ref(false)
const customForm = reactive({ name: '', code: '' })
function openCustomIndex() {
  customForm.name = ''
  customForm.code = ''
  showCustomIndex.value = true
}
function submitCustomIndex() {
  if (!customForm.name.trim() || !customForm.code.trim()) {
    message.warning('请填写指数名称和代码')
    return
  }
  if (!indices.value) indices.value = []
  const newIdx: IndexValuation = {
    name: customForm.name.trim(),
    code: customForm.code.trim(),
    level: 1000,
    change_pct: 0,
    pe: 12,
    pe_percentile: 30,
    pb: 1.2,
    pb_percentile: 25,
    category: 'opportunity',
    change_3m_pct: 0,
    win_rate: 0,
    market: 'a_share',
  }
  indices.value.push(newIdx)
  message.success(`已添加自定义指数: ${newIdx.name}`)
  showCustomIndex.value = false
}

// 放大查看弹窗
const showZoomChart = ref(false)

// 仅取有估值数据的指数用于 PE 分析（科创板/科创50/中证A500 等暂无估值，不在分析页展示）
const analyzableIndices = computed(() => (indices.value ?? []).filter(i => i.hasValuation !== false))

// ============================================================
// ECharts option — PE 估值带 (replaces static SVG)
// ============================================================
const peBandChartOption = computed(() => {
  const idx = selectedIndex.value
  if (!idx || idx.pe == null) return {}
  // Simulated 3-year PE history (decreasing trend toward current undervaluation)
  const labels = ['2021-05', '2021-09', '2022-01', '2022-05', '2022-09', '2023-01', '2023-05', '2023-09', '2024-01', '当前']
  const currentPe = idx.pe
  // Build a smooth descending curve from ~max3y toward current
  const startPe = currentPe * 1.65
  const peData = labels.map((_, i) => {
    const t = i / (labels.length - 1)
    // gentle wave around a downward trend
    const trend = startPe - (startPe - currentPe) * t
    const wave = Math.sin(t * Math.PI * 2.2) * (currentPe * 0.08)
    return Number((trend + wave).toFixed(2))
  })
  const p90 = currentPe * 1.6
  const p70 = currentPe * 1.35
  const p50 = currentPe * 1.18
  const p10 = currentPe * 0.92
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `${p.axisValue}<br/>PE: <b>${p.value}</b>`
      },
    },
    grid: { top: 16, right: 16, bottom: 28, left: 36 },
    xAxis: {
      type: 'category',
      data: labels,
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
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        showSymbol: true,
        data: peData,
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
            { yAxis: p90, lineStyle: { color: 'rgba(220,38,38,0.5)' }, label: { formatter: '90%', position: 'end', fontSize: 9, color: '#dc2626' } },
            { yAxis: p70, lineStyle: { color: 'rgba(249,115,22,0.5)' }, label: { formatter: '70%', position: 'end', fontSize: 9, color: '#f97316' } },
            { yAxis: p50, lineStyle: { color: 'rgba(107,114,128,0.5)' }, label: { formatter: '50%', position: 'end', fontSize: 9, color: '#6b7280' } },
            { yAxis: p10, lineStyle: { color: 'rgba(59,130,246,0.5)' }, label: { formatter: '10%', position: 'end', fontSize: 9, color: '#3b82f6' } },
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

const timeWindows = ['1Y', '3Y', '5Y', '全部']
const valMethods = ['PE (TTM)', 'PB (MRQ)', 'PS', '股息率']

const peAnalysis = computed(() => {
  const idx = selectedIndex.value
  if (!idx || idx.pe == null || idx.pe_percentile == null) return { current: 0, min3y: 0, avg3y: 0, max3y: 0, percentile: 0, assessment: '请选择指数' }
  // 基于当前 PE 和百分位推算历史区间
  // 百分位 < 50% → 当前低于中位数，历史区间上移
  const pct = idx.pe_percentile
  const current = idx.pe
  // 估算近3年中位数：当前PE在百分位的相对位置反推
  const median = pct > 0 && pct < 100
    ? Math.round((current / (pct / 100 + 0.15)) * 100) / 100
    : current
  const max3y = Math.round(median * (1 + (100 - pct) / 100 * 0.6) * 100) / 100
  const min3y = Math.round(median * (1 - pct / 100 * 0.5) * 100) / 100
  const avg3y = Math.round((median + max3y + min3y) / 3 * 100) / 100

  // 生成评估文案
  let assessment = ''
  const name = idx.name
  if (pct < 20) {
    assessment = `${name}当前PE(TTM)为${current}倍，处于近3年历史区间的第${pct}百分位，属于极度低估区域。相比历史中位数${median}倍存在显著的估值折价。PB为${idx.pb}倍，接近多年低点。长期风险收益比偏向正的对称收益，适合定投建仓。`
  } else if (pct < 40) {
    assessment = `${name}当前PE(TTM)为${current}倍，处于近3年历史区间的第${pct}百分位，估值偏低。相比历史中位数${median}倍有一定折价空间，可逢低布局。`
  } else if (pct < 60) {
    assessment = `${name}当前PE(TTM)为${current}倍，处于近3年历史区间的第${pct}百分位，估值处于中性水平。接近历史中位数${median}倍，不具备明显的估值优势或劣势。`
  } else if (pct < 80) {
    assessment = `${name}当前PE(TTM)为${current}倍，处于近3年历史区间的第${pct}百分位，估值偏高。相比历史中位数${median}倍有一定溢价，追高需谨慎。`
  } else {
    assessment = `${name}当前PE(TTM)为${current}倍，处于近3年历史区间的第${pct}百分位，属于极度高估区域。远高于历史中位数${median}倍，估值泡沫风险较大，建议减仓或回避。`
  }
  return { current, min3y, avg3y, max3y, percentile: pct, assessment }
})

const columns = [
  { title: '指数名称', key: 'name', render: (row: IndexValuation) => h('span', { class: 'index-name' }, row.name) },
  { title: '点位', key: 'level', align: 'right' as const, render: (row: IndexValuation) => row.level.toLocaleString() },
  {
    title: '涨跌幅', key: 'change_pct', align: 'right' as const,
    render: (row: IndexValuation) => h(
      'span',
      { style: { color: row.change_pct >= 0 ? 'var(--color-success)' : 'var(--color-danger)' } },
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
      { style: { color: row.change_3m_pct >= 0 ? 'var(--color-success)' : 'var(--color-danger)' } },
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
    <PageHeader title="指数估值分析" subtitle="宽基指数估值历史分位与 PE 估值带分析" helpKey="indexAnalysis">
      <template #actions>
        <n-button size="tiny" @click="exportCSV">导出CSV</n-button>
        <n-button size="tiny" type="primary" @click="openCustomIndex">自定义指数</n-button>
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
      <DataPanel class="table-panel" title="宽基指数全景" meta="最后更新: 2026-07-23 15:00:00">
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
      <DataPanel class="detail-panel" :title="`${selectedIndex?.name ?? ''} PE估值带分析`" meta="估值视角: 历史百分位法">
        <template #actions>
          <IconButton :icon="SearchOutline" label="放大查看" @click="showZoomChart = true" />
          <IconButton :icon="ExpandOutline" label="全屏" @click="toggleFullscreen" />
        </template>

        <!-- Chart Area -->
        <div class="chart-area">
          <div class="chart-legend">
            <div class="legend-item"><span class="legend-line solid" />PE (TTM)</div>
            <div class="legend-item"><span class="legend-line dashed-red" />90% 分位</div>
            <div class="legend-item"><span class="legend-line dashed-orange" />70% 分位</div>
            <div class="legend-item"><span class="legend-line dashed-gray" />50% 分位</div>
            <div class="legend-item"><span class="legend-line dashed-blue" />10% 分位</div>
          </div>
          <BaseChart :option="peBandChartOption" :height="220" />
        </div>

        <!-- Analysis Summary -->
        <div class="analysis-summary">
          <h3>估值评估</h3>
          <p>{{ peAnalysis.assessment }}</p>
          <div class="summary-stats">
            <div class="summary-stat">
              <span class="ss-label">近3年最低</span>
              <span class="ss-value">{{ peAnalysis.min3y }}x</span>
            </div>
            <div class="summary-stat">
              <span class="ss-label">近3年平均</span>
              <span class="ss-value">{{ peAnalysis.avg3y }}x</span>
            </div>
            <div class="summary-stat">
              <span class="ss-label">近3年最高</span>
              <span class="ss-value">{{ peAnalysis.max3y }}x</span>
            </div>
          </div>
        </div>
      </DataPanel>
    </div>
    </div>

    <!-- 自定义指数弹窗 -->
    <n-modal v-model:show="showCustomIndex" preset="card" title="添加自定义指数" style="width: 420px; max-width: 92vw;" :bordered="false">
      <div style="display: flex; flex-direction: column; gap: 12px;">
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; font-weight: 700; color: var(--text-muted);">指数名称</label>
          <n-input v-model:value="customForm.name" placeholder="例如：中证红利低波" />
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; font-weight: 700; color: var(--text-muted);">指数代码</label>
          <n-input v-model:value="customForm.code" placeholder="例如：930904.CSI" />
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px;">
          <n-button size="small" @click="showCustomIndex = false">取消</n-button>
          <n-button size="small" type="primary" @click="submitCustomIndex">添加</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 放大查看图表弹窗 -->
    <n-modal v-model:show="showZoomChart" preset="card" :title="`${selectedIndex?.name ?? ''} PE估值带（放大）`" style="width: 880px; max-width: 94vw;" :bordered="false">
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
