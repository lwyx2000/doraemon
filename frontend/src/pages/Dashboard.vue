<script setup lang="ts">
import { ref, computed, h } from 'vue'
import { NDataTable, NButton, NIcon, useMessage } from 'naive-ui'
import { TrendingUp } from '@vicons/ionicons5'
import { mockMacroData } from '../composables/useMockData'
import { useAsyncMock } from '../composables/useApi'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import LoadingState from '../components/LoadingState.vue'
import FieldHelp from '../components/FieldHelp.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: macro, loading, error, refresh: refetch } = useAsyncMock(mockMacroData)
const refreshing = ref(false)

function refresh() {
  refreshing.value = true
  message.loading('正在刷新宏观数据...', { duration: 1200 })
  refetch().finally(() => {
    refreshing.value = false
    if (macro.value) {
      message.success(`已刷新 ${macro.value.indices.length} 个指数数据`)
    }
  })
}

const erpColor = computed(() => {
  if (!macro.value) return 'var(--color-danger)'
  if (macro.value.erp_percentile_3y > 80) return 'var(--color-success)'
  if (macro.value.erp_percentile_3y > 50) return 'var(--color-warning)'
  return 'var(--color-danger)'
})

const columns = [
  { title: 'INDEX NAME', key: 'name', width: 160, render: (row: any) => row.name },
  { title: 'LEVEL', key: 'level', width: 100, align: 'right' as const,
    render: (row: any) => row.level.toLocaleString() },
  { title: 'CHG%', key: 'change_pct', width: 90, align: 'right' as const,
    render: (row: any) => {
      const color = row.change_pct >= 0 ? 'var(--color-success)' : 'var(--color-danger)'
      return h('span', { style: { color } },
        `${row.change_pct >= 0 ? '+' : ''}${row.change_pct}%`)
    },
  },
  { title: titleWithHelp('PE PERCENTILE', 'pe_percentile'), key: 'pe_percentile', width: 130, align: 'center' as const,
    render: (row: any) =>
      h('div', { class: 'percentile-cell' }, [
        h('div', { class: 'percentile-track' }, [
          h('div', { class: 'percentile-needle', style: { left: `${row.pe_percentile}%` } }),
        ]),
        h('span', { class: 'percentile-label' }, `${row.pe_percentile}%`),
      ]),
  },
  { title: titleWithHelp('PB PERCENTILE', 'pb_percentile'), key: 'pb_percentile', width: 130, align: 'center' as const,
    render: (row: any) =>
      h('div', { class: 'percentile-cell' }, [
        h('div', { class: 'percentile-track' }, [
          h('div', { class: 'percentile-needle', style: { left: `${row.pb_percentile}%` } }),
        ]),
        h('span', { class: 'percentile-label' }, `${row.pb_percentile}%`),
      ]),
  },
  { title: 'CATEGORY', key: 'category', width: 120,
    render: (row: any) => h('span', { class: ['category-tag', row.category] }, row.category.toUpperCase()),
  },
  { title: '3M Δ%', key: 'change_3m_pct', width: 90, align: 'right' as const,
    render: (row: any) => {
      const color = row.change_3m_pct >= 0 ? 'var(--color-success)' : 'var(--color-danger)'
      return h('span', { style: { color } },
        `${row.change_3m_pct >= 0 ? '+' : ''}${row.change_3m_pct}%`)
    },
  },
  { title: titleWithHelp('WIN RATE', 'win_rate'), key: 'win_rate', width: 90, align: 'right' as const,
    render: (row: any) => `${row.win_rate}%` },
]

function handleCheckedChange(keys: string[]) {
  if (keys.length === 0) return
  if (!macro.value) return
  const names = macro.value.indices
    .filter(idx => keys.includes(idx.name))
    .map(idx => idx.name)
  message.info(`已选 ${keys.length} 个指数: ${names.join(', ')}`)
}
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    :min-height="480"
    text="正在加载宏观数据..."
    @retry="refetch"
  >
    <div v-if="macro" class="dashboard-page">
    <!-- Page Header -->
    <PageHeader title="大类资产配置看板" subtitle="大类资产配置与宏观深度看板" helpKey="dashboard">
      <template #actions>
        <n-button size="small" :loading="refreshing" @click="refresh">
          <template #icon><n-icon :component="TrendingUp" /></template>
          刷新
        </n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="dashboard" />

    <!-- ERP & Rate Cards -->
    <div class="metric-grid">
      <div class="metric-card">
        <span class="metric-label">ERP (股权风险溢价)<FieldHelp field="erp" /></span>
        <div class="metric-value-row">
          <span class="metric-value" :style="{ color: erpColor }">{{ macro.erp }}%</span>
          <div class="percentile-indicator">
            <div class="percentile-bar">
              <div class="percentile-fill" :style="{ width: `${macro.erp_percentile_3y}%`, background: erpColor }" />
            </div>
            <span class="percentile-text">3Y: {{ macro.erp_percentile_3y }}%</span>
          </div>
        </div>
        <div class="metric-footnotes">
          <span>5Y: {{ macro.erp_percentile_5y }}%</span>
          <span>10Y: {{ macro.erp_percentile_10y }}%</span>
        </div>
      </div>

      <div class="metric-card">
        <span class="metric-label">DR007<FieldHelp field="dr007" /></span>
        <div class="metric-value-row">
          <span class="metric-value">{{ macro.dr007 }}%</span>
        </div>
        <div class="metric-footnotes">存款类机构7天质押式回购</div>
      </div>

      <div class="metric-card">
        <span class="metric-label">GC001<FieldHelp field="gc001" /></span>
        <div class="metric-value-row">
          <span class="metric-value">{{ macro.gc001 }}%</span>
        </div>
        <div class="metric-footnotes">上交所1天国债回购</div>
      </div>

      <div class="metric-card">
        <span class="metric-label">Market Heat</span>
        <div class="metric-value-row">
          <span class="metric-value" style="color: #005ea1">35%</span>
        </div>
        <div class="heat-track">
          <div class="heat-gradient" />
          <div class="heat-needle" style="left: 35%" />
        </div>
        <div class="metric-footnotes">偏低估值区域</div>
      </div>
    </div>

    <!-- Index Valuation Table -->
    <DataPanel title="Broad Index Universe" meta="Last update: 2026-07-22 15:00:00">
      <n-data-table
        :columns="columns"
        :data="macro.indices"
        :row-key="(row: any) => row.name"
        :bordered="false"
        :single-line="false"
        size="small"
        :row-class-name="() => 'data-row'"
        @update:checked-row-keys="handleCheckedChange"
      />
    </DataPanel>

    <!-- Bottom Stats -->
    <div class="bottom-stats">
      <div class="stat-item">
        <span class="stat-label">市场热度</span>
        <div class="heat-bar">
          <div class="heat-gradient" />
          <div class="heat-needle" style="left: 35%" />
        </div>
        <span class="stat-value">35%</span>
      </div>
      <div class="stat-divider" />
      <div class="stat-item">
        <span class="stat-label">指数总数</span>
        <span class="stat-value">1,242</span>
      </div>
      <div class="stat-divider" />
      <div class="stat-item">
        <span class="stat-label text-blue">低估</span>
        <span class="stat-value text-blue">428</span>
      </div>
      <div class="stat-divider" />
      <div class="stat-item">
        <span class="stat-label text-red">高估</span>
        <span class="stat-value text-red">112</span>
      </div>
      <div class="stat-divider" />
      <div class="stat-item right">
        <span class="stat-label">系统延迟: 12ms</span>
      </div>
    </div>
    </div>
  </LoadingState>
</template>

<!-- Global styles for h()-rendered table cells (not scoped so VNodes get the styles) -->
<style>
.percentile-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.percentile-track {
  width: 80px;
  height: 4px;
  background: var(--border-default);
  border-radius: 2px;
  position: relative;
}

.percentile-needle {
  position: absolute;
  top: -3px;
  width: 2px;
  height: 10px;
  background: var(--color-primary);
  border-radius: 1px;
  transition: left 0.3s ease;
}

.percentile-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-muted);
}

.category-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 2px;
  font-family: 'Work Sans', sans-serif;
  font-size: 10px;
  font-weight: 700;
}
.category-tag.undervalued,
.category-tag.opportunity {
  background: var(--tag-blue-bg);
  color: var(--tag-blue-text);
}
.category-tag.normal {
  background: var(--tag-gray-bg);
  color: var(--tag-gray-text);
}
.category-tag.overvalued {
  background: var(--tag-red-bg);
  color: var(--tag-red-text);
}
</style>

<style scoped>
.dashboard-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

@media (max-width: 1280px) {
  .metric-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .metric-grid { grid-template-columns: 1fr; }
  .bottom-stats { flex-wrap: wrap; gap: 8px; }
}

.metric-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  transition: box-shadow 0.2s, border-color 0.2s;
}

.metric-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  border-color: var(--border-hover);
}

.metric-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.metric-value-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.metric-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.2;
}

.percentile-indicator {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.percentile-bar {
  height: 4px;
  background: var(--border-default);
  border-radius: 2px;
  overflow: hidden;
}

.percentile-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
}

.percentile-text {
  font-size: 10px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.metric-footnotes {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-muted);
}

.heat-track {
  height: 8px;
  background: linear-gradient(to right, var(--color-primary), var(--border-default), var(--color-danger));
  border-radius: 4px;
  position: relative;
  overflow: hidden;
}

.heat-gradient {
  height: 100%;
  width: 100%;
  border-radius: 4px;
}

.heat-needle {
  position: absolute;
  top: -3px;
  width: 4px;
  height: 14px;
  background: var(--text-primary);
  border-radius: 2px;
  transform: translateX(-50%);
  transition: left 0.3s ease;
}

:deep(.data-row) {
  height: 40px;
  cursor: pointer;
  transition: background 0.12s ease;
}

:deep(.data-row:hover) {
  background: var(--bg-hover);
}

:deep(.n-data-table-th) {
  background: var(--bg-subtle) !important;
  font-family: 'Work Sans', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

:deep(.n-data-table-td) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}

.bottom-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 8px 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  transition: box-shadow 0.2s;
}

.bottom-stats:hover {
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stat-item.right {
  margin-left: auto;
}

.stat-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  text-transform: uppercase;
}

.stat-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-primary);
}

.text-blue { color: var(--color-primary) !important; }
.text-red { color: var(--color-danger) !important; }

.stat-divider {
  width: 1px;
  height: 16px;
  background: var(--border-default);
}

.heat-bar {
  width: 80px;
  height: 8px;
  border-radius: 4px;
  background: linear-gradient(to right, var(--color-primary), var(--border-default), var(--color-danger));
  position: relative;
}
</style>
