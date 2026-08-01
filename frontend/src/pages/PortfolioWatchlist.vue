<script setup lang="ts">
import { ref, computed, h, reactive } from 'vue'
import { NButton, NIcon, NDataTable, NModal, NInput, NSelect, useMessage } from 'naive-ui'
import { Add, Download, TrendingUpOutline, FilterOutline } from '@vicons/ionicons5'
import { mockFunds } from '../composables/useMockData'
import { useAsyncMock } from '../composables/useApi'
import type { FundItem } from '../types'
import { exportToCSV } from '../utils/export'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import DataPanel from '../components/DataPanel.vue'
import TabBar from '../components/TabBar.vue'
import LoadingState from '../components/LoadingState.vue'
import BaseChart from '../components/BaseChart.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'
import { getFieldTip } from '../composables/helpContent'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: funds, loading, error, refresh: refetch } = useAsyncMock(mockFunds)
const activeTab = ref<string>('index')

// 添加标的弹窗
const showAddModal = ref(false)
const addForm = reactive<{ name: string; code: string; type: FundItem['type'] }>({ name: '', code: '', type: 'lof' })
const typeOptions = [
  { label: 'LOF 基金', value: 'lof' },
  { label: '封闭基金', value: 'closed' },
  { label: 'QDII 基金', value: 'qdii' },
]
function openAddModal() {
  addForm.name = ''
  addForm.code = ''
  addForm.type = 'lof'
  showAddModal.value = true
}
function submitAdd() {
  if (!addForm.name.trim() || !addForm.code.trim()) {
    message.warning('请填写基金名称和代码')
    return
  }
  if (!funds.value) return
  if (funds.value.some(f => f.code === addForm.code.trim())) {
    message.error(`代码 ${addForm.code.trim()} 已存在`)
    return
  }
  funds.value.push({
    name: addForm.name.trim(),
    code: addForm.code.trim(),
    type: addForm.type,
    price: 1.0,
    iopv: 1.0,
    premium_pct: 0,
    premium_percentile: 50,
    net_arbitrage_yield: 0,
    volume: 0,
  })
  message.success(`已添加: ${addForm.name.trim()} (${addForm.code.trim()})`)
  showAddModal.value = false
}

const tabs = [
  { key: 'index', label: '指数' },
  { key: 'lof', label: 'LOF基金' },
  { key: 'closed', label: '封闭基金' },
  { key: 'cb', label: '可转债' },
]

function exportPortfolio() {
  const headers = ['标的名称', '代码', '价格', '折溢价率', '年化收益', '到期收益', '百分位', '成交量']
  const rows = displayFunds.value.map(f => [
    f.name, f.code, f.price.toFixed(3), f.premium_pct, f.annualized ?? '',
    f.est_ytm ?? '', f.premium_percentile, f.volume,
  ])
  exportToCSV(`portfolio_${activeTab.value}_${new Date().toISOString().slice(0, 10)}`, headers, rows)
  message.success(`已导出 ${rows.length} 条 ${tabs.find(t => t.key === activeTab.value)?.label || ''} 数据`)
}

const displayFunds = computed(() => {
  if (!funds.value) return []
  if (activeTab.value === 'closed') return funds.value.filter(f => f.type === 'closed')
  if (activeTab.value === 'lof') return funds.value.filter(f => f.type === 'lof' || f.type === 'qdii')
  return funds.value.slice(0, 4)
})

const columns = computed(() => [
  {
    title: '基金名称',
    key: 'name',
    render: (row: FundItem) => h('span', { class: 'fund-name' }, row.name),
  },
  {
    title: '价格',
    key: 'price',
    align: 'right' as const,
    render: (row: FundItem) => row.price.toFixed(3),
  },
  {
    title: titleWithHelp(activeTab.value === 'closed' ? '折价率' : '溢价率', 'premium_pct'),
    key: 'premium_pct',
    align: 'right' as const,
    render: (row: FundItem) => {
      const color = row.premium_pct >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
      const text = `${row.premium_pct >= 0 ? '+' : ''}${row.premium_pct}%`
      return h('span', { style: { color } }, text)
    },
  },
  {
    title: '年化收益',
    key: 'annualized',
    align: 'right' as const,
    render: (row: FundItem) => `${(row.annualized || 0).toFixed(1)}%`,
  },
  {
    title: titleWithHelp('到期收益', 'ytm'),
    key: 'est_ytm',
    align: 'right' as const,
    render: (row: FundItem) => h(
      'span',
      { style: { color: 'var(--color-primary)', fontWeight: 700 } },
      `${(row.est_ytm || 0).toFixed(1)}%`,
    ),
  },
  {
    title: '到期日',
    key: 'maturity',
    render: (row: FundItem) => {
      if (row.maturity && row.premium_pct < -10) {
        return h('span', { class: 'maturity-badge' }, row.maturity)
      }
      return h('span', null, row.maturity || '-')
    },
  },
  {
    title: titleWithHelp('百分位', 'premium_percentile'),
    key: 'premium_percentile',
    align: 'center' as const,
    render: (row: FundItem) => h('div', { class: 'perc-bar' }, [
      h('div', { class: 'perc-fill', style: { width: row.premium_percentile + '%' } }),
    ]),
  },
])

const summaryStats = {
  totalPnl: 1.24,
  pnlToday: 2.4,
  volatility: 14.2,
  beta: 0.85,
  maxDrawdown: -8.4,
  avgDiscount: 12.5,
}

// ============================================================
// ECharts options — replace static SVG donut + sparkline
// ============================================================

// Asset allocation donut chart
const allocationChartOption = computed(() => ({
  tooltip: {
    trigger: 'item',
    formatter: '{b}: {c} ({d}%)',
  },
  legend: { show: false },
  series: [
    {
      type: 'pie',
      radius: ['55%', '78%'],
      avoidLabelOverlap: false,
      label: { show: false },
      labelLine: { show: false },
      itemStyle: {
        borderColor: 'transparent',
        borderWidth: 2,
      },
      data: [
        { value: 45, name: 'LOF基金', itemStyle: { color: '#005ea1' } },
        { value: 30, name: '封闭基金', itemStyle: { color: '#585e6c' } },
        { value: 15, name: '可转债', itemStyle: { color: '#864f00' } },
        { value: 10, name: 'REITs', itemStyle: { color: '#2178c3' } },
      ],
    },
  ],
}))

// Discount convergence trend — line chart with area gradient
const convergenceData = [75, 60, 80, 55, 85, 95]
const convergenceChartOption = computed(() => ({
  tooltip: { trigger: 'axis', formatter: (p: any) => `第${p[0].index + 1}期: ${p[0].value}%` },
  grid: { top: 8, right: 8, bottom: 8, left: 24 },
  xAxis: {
    type: 'category',
    show: false,
    data: convergenceData.map((_, i) => i + 1),
  },
  yAxis: {
    type: 'value',
    show: true,
    axisLabel: { fontSize: 9, formatter: '{value}%' },
    splitLine: { lineStyle: { type: 'dashed', opacity: 0.3 } },
  },
  series: [
    {
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      showSymbol: true,
      data: convergenceData,
      lineStyle: { width: 2, color: '#005ea1' },
      itemStyle: { color: '#005ea1' },
      areaStyle: {
        opacity: 0.15,
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(0, 94, 161, 0.4)' },
            { offset: 1, color: 'rgba(0, 94, 161, 0)' },
          ],
        },
      },
    },
  ],
}))
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    :min-height="520"
    text="正在加载投资组合数据..."
    @retry="refetch"
  >
    <div v-if="funds" class="watchlist-page">
    <!-- Header -->
    <PageHeader title="投资组合看板" :subtitle="`监控 ${mockFunds.length} 个高置信度资产，覆盖4个资产类别`" help-key="portfolioWatchlist">
      <template #actions>
        <n-button size="small" @click="openAddModal">
          <template #icon><n-icon :component="Add" /></template>
          添加
        </n-button>
        <n-button size="small" @click="exportPortfolio">
          <template #icon><n-icon :component="Download" /></template>
          导出
        </n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="portfolioWatchlist" />

    <!-- Bento Grid -->
    <div class="stat-grid wide-first">
      <!-- Allocation Card -->
      <div class="bento-card">
        <h3 class="bento-title">资产配置</h3>
        <div class="donut-container">
          <BaseChart :option="allocationChartOption" :height="140" />
          <div class="donut-center">
            <span class="donut-total">14</span>
            <span class="donut-label">总计</span>
          </div>
        </div>
        <div class="allocation-legend">
          <div class="legend-item"><span class="legend-dot" style="background: var(--color-primary)" />LOF基金 (45%)</div>
          <div class="legend-item"><span class="legend-dot" style="background:#585e6c" />封闭基金 (30%)</div>
          <div class="legend-item"><span class="legend-dot" style="background:#864f00" />可转债 (15%)</div>
          <div class="legend-item"><span class="legend-dot" style="background: var(--color-primary-hover)" />REITs (10%)</div>
        </div>
      </div>

      <!-- Performance Cards -->
      <div class="bento-card">
        <span class="bento-label">总盈亏</span>
        <span class="bento-value" style="color: var(--color-success)">+¥1.24M</span>
        <div class="bento-trend">
          <n-icon :component="TrendingUpOutline" size="16" />
          2.4% 今日
        </div>
        <div class="progress-bar"><div class="progress-fill success" style="width:75%" /></div>
      </div>

      <StatCard label="波动率" value="14.2%" sub="Beta: 0.85">
        <div class="progress-bar"><div class="progress-fill" style="width:70%" /></div>
      </StatCard>

      <StatCard label="最大回撤" value="-8.4%" sub="近12月恢复期: 12天">
        <div class="progress-bar"><div class="progress-fill blue" style="width:25%" /></div>
      </StatCard>

      <StatCard label="平均折价" value="12.5%" color="#864f00" sub="目标: 15%" :tip="getFieldTip('discount_pct')">
        <div class="progress-bar"><div class="progress-fill" style="width:60%; background:#864f00" /></div>
      </StatCard>
    </div>

    <!-- Tabs + Table -->
    <DataPanel>
      <template #actions>
        <TabBar v-model="activeTab" :tabs="tabs" />
        <div class="panel-info">
          <span>自动刷新: 5秒</span>
          <n-icon :component="FilterOutline" size="16" />
        </div>
      </template>
      <n-data-table
        :columns="columns"
        :data="displayFunds"
        :row-key="(row: any) => row.code"
        :bordered="false"
        :single-line="false"
        size="small"
        :row-props="(row: any) => ({ onClick: () => message.info(row.name) })"
      />
    </DataPanel>

    <!-- Risk Indicators -->
    <div class="bottom-grid">
      <div class="risk-panel">
        <h4>折价收敛趋势</h4>
        <BaseChart :option="convergenceChartOption" :height="160" />
      </div>
      <div class="risk-panel">
        <h4>相关性矩阵</h4>
        <div class="corr-grid">
          <div /><div class="corr-label-sm">LOF</div><div class="corr-label-sm">CLS</div><div class="corr-label-sm">BND</div><div class="corr-label-sm">IDX</div>
          <div class="corr-label-sm">LOF</div>
          <div class="corr-cell" style="opacity:0.9" /><div class="corr-cell" style="opacity:0.6" /><div class="corr-cell" style="opacity:0.2" /><div class="corr-cell" style="opacity:0.4" />
          <div class="corr-label-sm">CLS</div>
          <div class="corr-cell" style="opacity:0.6" /><div class="corr-cell" style="opacity:0.9" /><div class="corr-cell" style="opacity:0.3" /><div class="corr-cell" style="opacity:0.1" />
        </div>
      </div>
    </div>
    </div>

    <!-- 添加标的弹窗 -->
    <n-modal v-model:show="showAddModal" preset="card" title="添加标的到组合" style="width: 420px; max-width: 92vw;" :bordered="false">
      <div style="display: flex; flex-direction: column; gap: 12px;">
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; font-weight: 700; color: var(--text-muted);">标的名称</label>
          <n-input v-model:value="addForm.name" placeholder="例如：科创50ETF" />
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; font-weight: 700; color: var(--text-muted);">标的代码</label>
          <n-input v-model:value="addForm.code" placeholder="例如：588000.SH" />
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; font-weight: 700; color: var(--text-muted);">类型</label>
          <n-select v-model:value="addForm.type" :options="typeOptions" />
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px;">
          <n-button size="small" @click="showAddModal = false">取消</n-button>
          <n-button size="small" type="primary" @click="submitAdd">添加</n-button>
        </div>
      </template>
    </n-modal>
  </LoadingState>
</template>

<!-- Non-scoped styles for h()-rendered NDataTable cells -->
<style>
.fund-name {
  font-family: 'Work Sans', sans-serif;
  font-weight: 600;
  color: var(--text-primary);
}

.maturity-badge {
  display: inline-block;
  padding: 2px 8px;
  background: #ffdad6;
  color: #93000a;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
}

.perc-bar {
  width: 60px;
  height: 4px;
  background: var(--border-default);
  border-radius: 2px;
  overflow: hidden;
  margin: 0 auto;
}
.perc-fill {
  height: 100%;
  background: var(--color-primary);
  border-radius: 2px;
  transition: width 0.3s;
}
</style>

<style scoped>
.watchlist-page { display: flex; flex-direction: column; gap: 12px; }

/* Kept: allocation card (complex SVG donut + legend) and 总盈亏 card (trend indicator) */
.bento-card {
  background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px; padding: 16px;
  display: flex; flex-direction: column; gap: 8px;
}

.bento-title { font-family: 'Work Sans', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); margin: 0; }
.bento-label { font-family: 'Work Sans', sans-serif; font-size: 10px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); }
.bento-value { font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 600; color: var(--text-primary); }
.bento-trend { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--color-success); }
.bento-trend .n-icon { font-size: 16px; }

.progress-bar { height: 6px; background: var(--border-default); border-radius: 3px; overflow: hidden; margin-top: auto; }
.progress-fill { height: 100%; border-radius: 3px; background: var(--color-primary); transition: width 0.3s; }
.progress-fill.success { background: var(--color-success); }
.progress-fill.blue { background: var(--color-primary); }

.donut-container { display: flex; justify-content: center; align-items: center; position: relative; height: 140px; }
.donut-center { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; pointer-events: none; }
.donut-total { display: block; font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 700; color: var(--text-primary); line-height: 1; }
.donut-label { font-size: 10px; color: var(--text-muted); font-weight: 700; letter-spacing: 0.05em; }

.allocation-legend { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; border-top: 1px solid var(--border-default); padding-top: 10px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-secondary); }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

.panel-info { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-muted); }
.panel-info .n-icon { font-size: 18px; cursor: pointer; }

/* Bottom Grid */
.bottom-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; height: 200px; }
.risk-panel { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px; padding: 16px; display: flex; flex-direction: column; }
.risk-panel h4 { font-family: 'Work Sans', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); margin: 0 0 12px; }

.corr-grid { display: grid; grid-template-columns: 28px repeat(4, 1fr); gap: 2px; flex: 1; align-content: start; }
.corr-label-sm { font-size: 9px; font-weight: 700; color: var(--text-muted); display: flex; align-items: center; justify-content: center; }
.corr-cell { background: var(--color-primary); border-radius: 2px; aspect-ratio: 1; }

/* Responsive: collapse multi-column grids on smaller screens */
@media (max-width: 768px) {
  .bottom-grid { grid-template-columns: 1fr; height: auto; }
  .allocation-legend { grid-template-columns: 1fr; }
}
</style>
