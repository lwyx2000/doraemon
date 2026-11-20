<script setup lang="ts">
/**
 * 宏观看板嵌入式「融资盘余额」面板：沪深合计 / 沪市 / 深市三个 tab。
 * 数据源 /api/v1/market/margin-balance（金十全史 + 交易所官方尾部补齐，单位亿元）。
 * 合计 tab：上方合计曲线，下方堆叠柱状图区分沪市/深市余额贡献。
 * 余额增加按 A 股习惯标红、减少标绿；后端 note 用于展示缓存/缺口提示。
 */
import { computed, ref } from 'vue'
import BaseChart from './BaseChart.vue'
import type { MarginBalanceData, MarginBalancePoint } from '../types'

type TabKey = 'total' | 'sh' | 'sz'

interface Props {
  data: MarginBalanceData
  title?: string
  note?: string | null
}

const props = withDefaults(defineProps<Props>(), {
  title: '融资盘余额（沪深）',
  note: null,
})

const activeTab = ref<TabKey>('total')
const tabs: Array<{ key: TabKey; label: string }> = [
  { key: 'total', label: '沪深合计' },
  { key: 'sh', label: '沪市' },
  { key: 'sz', label: '深市' },
]

const TOTAL_COLOR = '#7c3aed'
const SH_COLOR = '#2563eb'
const SZ_COLOR = '#f59e0b'

function isNum(v: number | null | undefined): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

function fmt(v: number | null | undefined, digits = 0): string {
  return isNum(v) ? v.toFixed(digits) : '—'
}

function lastValid(points: MarginBalancePoint[]): number | null {
  for (let i = points.length - 1; i >= 0; i -= 1) {
    if (isNum(points[i].balance)) return points[i].balance
  }
  return null
}

type ValidPoint = { date: string; balance: number }

const series = computed<MarginBalancePoint[]>(() => props.data[activeTab.value] ?? [])
const validPoints = computed<ValidPoint[]>(() =>
  series.value.filter((p): p is ValidPoint => isNum(p.balance)),
)
const latest = computed(() => validPoints.value[validPoints.value.length - 1] ?? null)
const first = computed(() => validPoints.value[0] ?? null)

const latestSh = computed(() => lastValid(props.data.sh ?? []))
const latestSz = computed(() => lastValid(props.data.sz ?? []))

const changeAbs = computed(() => {
  if (!first.value || !latest.value) return null
  return latest.value.balance - first.value.balance
})

const changePct = computed(() => {
  const abs = changeAbs.value
  if (abs == null || !first.value || !first.value.balance) return null
  return (abs / first.value.balance) * 100
})

const changeColor = computed(() => {
  if (changeAbs.value == null) return 'var(--text-muted)'
  return changeAbs.value >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
})

const changeText = computed(() => {
  const abs = changeAbs.value
  const pct = changePct.value
  if (abs == null || pct == null) return '—'
  return `${abs >= 0 ? '+' : ''}${abs.toFixed(0)}亿 / ${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
})

const rangeText = computed(() => {
  if (!first.value || !latest.value) return '—'
  return `${first.value.date} ~ ${latest.value.date}`
})

function tooltipValue(params: any[], name: string): number | null {
  const hit = params.find((p) => p.seriesName === name)
  return isNum(hit?.value) ? hit.value : null
}

const totalOption = computed(() => {
  const dates = props.data.total.map((p) => p.date)
  return {
    animation: false,
    grid: [
      { left: 58, right: 18, top: 30, height: '48%' },
      { left: 58, right: 18, top: '70%', height: '18%' },
    ],
    legend: {
      top: 0,
      right: 8,
      itemWidth: 10,
      itemHeight: 10,
      data: ['合计', '沪市', '深市'],
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', link: [{ xAxisIndex: 'all' }] },
      formatter: (params: any[]) => {
        if (!params?.length) return ''
        const date = String(params[0].axisValue ?? '')
        return [
          date,
          `合计 <b>${fmt(tooltipValue(params, '合计'), 2)}</b> 亿`,
          `沪市 <b>${fmt(tooltipValue(params, '沪市'), 2)}</b> 亿`,
          `深市 <b>${fmt(tooltipValue(params, '深市'), 2)}</b> 亿`,
        ].join('<br/>')
      },
    },
    xAxis: [
      {
        type: 'category',
        gridIndex: 0,
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: 'rgba(128,128,128,0.35)' } },
        axisTick: { show: false },
        axisLabel: { show: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: 'rgba(128,128,128,0.35)' } },
        axisTick: { show: false },
        axisLabel: {
          color: 'inherit',
          fontSize: 10,
          formatter: (v: string) => v.slice(0, 7),
          hideOverlap: true,
        },
      },
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        scale: true,
        name: '亿元',
        nameTextStyle: { fontSize: 10, padding: [0, 0, 0, -20] },
        axisLabel: { color: 'inherit', fontSize: 10, formatter: (v: number) => v.toFixed(0) },
        splitLine: { lineStyle: { type: 'dashed', opacity: 0.25 } },
      },
      {
        type: 'value',
        gridIndex: 1,
        name: '沪深',
        nameTextStyle: { fontSize: 10, padding: [0, 0, 0, -14] },
        axisLabel: { color: 'inherit', fontSize: 10, formatter: (v: number) => v.toFixed(0) },
        splitLine: { lineStyle: { type: 'dashed', opacity: 0.2 } },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100, zoomOnMouseWheel: true },
    ],
    series: [
      {
        name: '合计',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: props.data.total.map((p) => p.balance),
        showSymbol: false,
        smooth: true,
        sampling: 'lttb',
        lineStyle: { width: 2, color: TOTAL_COLOR },
        itemStyle: { color: TOTAL_COLOR },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(124, 58, 237, 0.20)' },
              { offset: 1, color: 'rgba(124, 58, 237, 0.02)' },
            ],
          },
        },
      },
      {
        name: '沪市',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        stack: 'market',
        barWidth: '70%',
        data: props.data.sh.map((p) => p.balance),
        itemStyle: { color: SH_COLOR },
      },
      {
        name: '深市',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        stack: 'market',
        barWidth: '70%',
        data: props.data.sz.map((p) => p.balance),
        itemStyle: { color: SZ_COLOR },
      },
    ],
  }
})

const singleOption = computed(() => {
  const key: 'sh' | 'sz' = activeTab.value === 'sz' ? 'sz' : 'sh'
  const color = key === 'sh' ? SH_COLOR : SZ_COLOR
  const name = key === 'sh' ? '沪市' : '深市'
  const points = props.data[key] ?? []
  return {
    animation: false,
    grid: { left: 58, right: 18, top: 18, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any[]) =>
        params.length
          ? `${params[0].axisValue}<br/>${name}融资余额 <b>${fmt(params[0].value, 2)} 亿</b>`
          : '',
    },
    xAxis: {
      type: 'category',
      data: points.map((p) => p.date),
      boundaryGap: false,
      axisLine: { lineStyle: { color: 'rgba(128,128,128,0.35)' } },
      axisTick: { show: false },
      axisLabel: {
        color: 'inherit',
        fontSize: 10,
        formatter: (v: string) => v.slice(2, 7),
        hideOverlap: true,
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
      name: '亿元',
      nameTextStyle: { fontSize: 10, padding: [0, 0, 0, -20] },
      axisLabel: { color: 'inherit', fontSize: 10, formatter: (v: number) => v.toFixed(0) },
      splitLine: { lineStyle: { type: 'dashed', opacity: 0.25 } },
    },
    dataZoom: [{ type: 'inside', start: 0, end: 100, zoomOnMouseWheel: true }],
    series: [
      {
        name,
        type: 'line',
        data: points.map((p) => p.balance),
        showSymbol: false,
        smooth: true,
        sampling: 'lttb',
        lineStyle: { width: 2, color },
        itemStyle: { color },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: key === 'sh' ? 'rgba(37, 99, 235, 0.22)' : 'rgba(245, 158, 11, 0.22)' },
              { offset: 1, color: key === 'sh' ? 'rgba(37, 99, 235, 0.02)' : 'rgba(245, 158, 11, 0.02)' },
            ],
          },
        },
      },
    ],
  }
})

const chartOption = computed(() => (activeTab.value === 'total' ? totalOption.value : singleOption.value))
const chartHeight = computed(() => (activeTab.value === 'total' ? 320 : 220))
</script>

<template>
  <div class="margin-balance-panel">
    <div class="panel-header">
      <h3 class="panel-title">
        {{ title }}
        <span class="panel-subtitle">单位亿元 · 近10年</span>
      </h3>
      <span class="panel-date">{{ latest?.date ?? '—' }}</span>
    </div>

    <div class="mb-tabs" role="tablist" aria-label="融资余额市场切换">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        role="tab"
        class="mb-tab"
        :class="{ active: activeTab === tab.key }"
        :aria-selected="activeTab === tab.key"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="mb-summary">
      <div class="mb-metric">
        <span class="mb-label">{{ activeTab === 'total' ? '合计余额' : activeTab === 'sh' ? '沪市余额' : '深市余额' }}</span>
        <span class="mb-value">{{ fmt(latest?.balance) }}<small>亿</small></span>
      </div>
      <div class="mb-metric">
        <span class="mb-label">区间变化</span>
        <span class="mb-value mb-change" :style="{ color: changeColor }">{{ changeText }}</span>
      </div>
      <div v-if="activeTab === 'total'" class="mb-metric">
        <span class="mb-label">沪 / 深 最新</span>
        <span class="mb-value mb-split">
          <span :style="{ color: SH_COLOR }">{{ fmt(latestSh) }}</span>
          <span class="mb-split-sep">/</span>
          <span :style="{ color: SZ_COLOR }">{{ fmt(latestSz) }}</span>
          <small>亿</small>
        </span>
      </div>
      <div class="mb-metric mb-range">
        <span class="mb-label">统计区间</span>
        <span class="mb-range-text">{{ rangeText }}</span>
      </div>
    </div>

    <BaseChart v-if="series.length > 1" :option="chartOption" :height="chartHeight" />
    <div v-else class="mb-empty">暂无融资余额历史数据</div>

    <div v-if="note" class="mb-note">{{ note }}</div>
    <div v-else-if="activeTab === 'total'" class="mb-hint">下方堆叠柱区分沪市 / 深市余额贡献，滚轮可缩放时间轴</div>
  </div>
</template>

<style scoped>
.margin-balance-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 16px;
  box-shadow: var(--shadow-card);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.panel-title {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.panel-subtitle,
.panel-date {
  font-size: 11px;
  color: var(--text-muted);
}

.panel-date {
  font-family: 'JetBrains Mono', monospace;
}

.mb-tabs {
  display: flex;
  gap: 6px;
  margin: 10px 0 2px;
}

.mb-tab {
  border: 1px solid var(--border-default);
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.mb-tab:hover {
  color: var(--color-primary);
}

.mb-tab.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
  font-weight: 600;
}

.mb-summary {
  display: flex;
  align-items: flex-end;
  gap: 28px;
  flex-wrap: wrap;
  margin: 10px 0 4px;
}

.mb-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mb-label {
  font-size: 11px;
  color: var(--text-muted);
}

.mb-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.mb-value small {
  font-size: 11px;
  font-weight: 500;
  margin-left: 2px;
}

.mb-change {
  font-size: 15px;
}

.mb-split {
  font-size: 16px;
}

.mb-split-sep {
  color: var(--text-muted);
  margin: 0 4px;
}

.mb-range {
  margin-left: auto;
}

.mb-range-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--text-secondary);
}

.mb-empty {
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--text-muted);
}

.mb-note,
.mb-hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-muted);
}

.mb-note {
  color: var(--tag-orange-text, var(--text-muted));
}
</style>
