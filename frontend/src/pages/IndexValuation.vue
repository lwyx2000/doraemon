<script setup lang="ts">
defineOptions({ name: 'IndexValuation' })
import { ref, computed, onMounted } from 'vue'
import { NDataTable, NTag, NSpin, NEmpty, NModal, NButton, NAlert, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { api } from '../utils/api'
import type { BroadIndexValuation, SectionSourceMeta } from '../types'
import PageHeader from '../components/PageHeader.vue'
import PercentileIndicator from '../components/PercentileIndicator.vue'
import BaseChart from '../components/BaseChart.vue'

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

onMounted(loadData)

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
    title: '拥挤度',
    key: 'crowding',
    width: 140,
    align: 'center',
    render: (row) => h('div', { style: 'display:flex; align-items:center; justify-content:center; gap:6px;' }, [
      h(PercentileIndicator, { value: row.crowding, width: 60 }),
      h(NTag, { type: crowdingColor(row.crowding), size: 'small', bordered: false }, () => row.crowding != null ? row.crowding.toFixed(0) + '%' : '—'),
    ]),
  },
  {
    title: '操作',
    key: 'action',
    width: 80,
    align: 'center',
    render: (row) => h(NButton, { size: 'small', quaternary: true, onClick: () => openDetail(row) }, () => '详情'),
  },
]

import { h } from 'vue'

// ==================== 详情弹窗 ====================
const detailVisible = ref(false)
const selectedItem = ref<BroadIndexValuation | null>(null)

function openDetail(row: BroadIndexValuation) {
  selectedItem.value = row
  detailVisible.value = true
}

// PB 历史走势图
const pbChartOption = computed(() => {
  if (!selectedItem.value?.pb_history?.length) return null
  const hist = selectedItem.value.pb_history
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 30, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: hist.map(h => h.date), boundaryGap: false },
    yAxis: { type: 'value', name: 'PB', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 5 }],
    series: [{
      name: 'PB',
      type: 'line',
      data: hist.map(h => h.pb),
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 2, color: '#f59e0b' },
      areaStyle: { color: 'rgba(245,158,11,0.1)' },
    }],
  }
})

// 股债利差历史走势图
const spreadChartOption = computed(() => {
  if (!selectedItem.value?.spread_history?.length) return null
  const hist = selectedItem.value.spread_history
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['股债利差(%)', 'PB'] },
    grid: { left: 50, right: 50, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: hist.map(h => h.date), boundaryGap: false },
    yAxis: [
      { type: 'value', name: '利差(%)', scale: true, position: 'left' },
      { type: 'value', name: 'PB', scale: true, position: 'right' },
    ],
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 5 }],
    series: [
      {
        name: '股债利差(%)',
        type: 'line',
        yAxisIndex: 0,
        data: hist.map(h => h.spread),
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#3b82f6' },
        areaStyle: { color: 'rgba(59,130,246,0.1)' },
        markLine: {
          silent: true,
          lineStyle: { type: 'dashed', color: '#666' },
          data: [{ yAxis: 0, label: { formatter: '0%' } }],
        },
      },
      {
        name: 'PB',
        type: 'line',
        yAxisIndex: 1,
        data: hist.map(h => h.pb),
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#f59e0b', type: 'dashed' },
      },
    ],
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
    <PageHeader title="宽基指数估值分析" subtitle="股债利差估值分位 + 拥挤度" helpKey="indexValuation" />

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
        <span class="param-value">中证800 ★</span>
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
      &nbsp;&nbsp;<strong>拥挤度</strong>：指数PB / 基准PB 的历史分位，衡量相对估值。
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
        :scroll-x="850"
      />
      <n-empty v-else-if="!loading" description="暂无数据，请确保后端服务正常运行" style="padding: 60px 0" />
    </n-spin>

    <!-- 详情弹窗 -->
    <n-modal
      v-model:show="detailVisible"
      preset="card"
      :title="selectedItem ? `${selectedItem.name} · 估值历史走势` : '指数详情'"
      style="width: 900px; max-width: 95vw"
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

        <!-- PB 历史走势 -->
        <div class="detail-section">
          <h4 class="section-title">PB 历史走势</h4>
          <BaseChart v-if="pbChartOption" :option="pbChartOption" :height="280" />
          <n-empty v-else description="暂无PB历史数据" style="padding: 30px 0" />
        </div>

        <!-- 股债利差历史走势 -->
        <div class="detail-section">
          <h4 class="section-title">股债利差历史走势</h4>
          <BaseChart v-if="spreadChartOption" :option="spreadChartOption" :height="280" />
          <n-empty v-else description="暂无利差历史数据" style="padding: 30px 0" />
        </div>

        <!-- 公式说明 -->
        <div class="formula-hint">
          <n-text depth="3" style="font-size: 12px; line-height: 1.8">
            股债利差 = ROE均值(近5年) ÷ PB − 10年期国债收益率 + 0.3 × CPI同比<br>
            估值分位 = 100 − 利差在历史中的升序百分位（越小=越便宜）<br>
            拥挤度 = (指数PB ÷ 中证800PB) 在历史中的百分位（越小=相对越便宜）
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

.detail-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
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
