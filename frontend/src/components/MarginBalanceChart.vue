<script setup lang="ts">
/**
 * 宏观看板嵌入式「融资盘余额」曲线（沪市融资余额，单位亿元）。
 * 数据来自 /api/v1/market/margin-balance（AkShare stock_margin_sse，后端 30 分钟缓存）。
 * 余额增加按 A 股习惯标红、减少标绿；网关失败时后端会带缓存陈旧提示（note）。
 */
import { computed } from 'vue'
import BaseChart from './BaseChart.vue'
import type { MarginBalancePoint } from '../types'

interface Props {
  points: MarginBalancePoint[]
  title?: string
  note?: string | null
}

const props = withDefaults(defineProps<Props>(), {
  title: '融资盘余额（沪市）',
  note: null,
})

const latest = computed(() => props.points[props.points.length - 1] ?? null)
const first = computed(() => props.points[0] ?? null)

const changeAbs = computed(() => {
  if (!first.value || !latest.value || props.points.length < 2) return null
  return latest.value.balance - first.value.balance
})

const changePct = computed(() => {
  const abs = changeAbs.value
  if (abs == null || !first.value || first.value.balance === 0) return null
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

const chartOption = computed(() => ({
  grid: { left: 58, right: 18, top: 18, bottom: 30 },
  tooltip: {
    trigger: 'axis',
    formatter: (params: any[]) =>
      params.length
        ? `${params[0].axisValue}<br/>融资余额 <b>${Number(params[0].value).toFixed(2)} 亿</b>`
        : '',
  },
  xAxis: {
    type: 'category',
    data: props.points.map(p => p.date),
    boundaryGap: false,
    axisLine: { lineStyle: { color: 'rgba(128,128,128,0.35)' } },
    axisTick: { show: false },
    axisLabel: {
      color: 'inherit',
      fontSize: 10,
      formatter: (v: string) => v.slice(5),
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
  series: [
    {
      name: '融资余额',
      type: 'line',
      data: props.points.map(p => p.balance),
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 2, color: '#2563eb' },
      itemStyle: { color: '#2563eb' },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(37, 99, 235, 0.22)' },
            { offset: 1, color: 'rgba(37, 99, 235, 0.02)' },
          ],
        },
      },
    },
  ],
}))
</script>

<template>
  <div class="margin-balance-panel">
    <div class="panel-header">
      <h3 class="panel-title">
        {{ title }}
        <span class="panel-subtitle">沪市 · 单位亿元</span>
      </h3>
      <span class="panel-date">{{ latest?.date ?? '—' }}</span>
    </div>

    <div class="mb-summary">
      <div class="mb-metric">
        <span class="mb-label">最新余额</span>
        <span class="mb-value">{{ latest ? latest.balance.toFixed(0) : '—' }}<small>亿</small></span>
      </div>
      <div class="mb-metric">
        <span class="mb-label">区间变化</span>
        <span class="mb-value" :style="{ color: changeColor }">{{ changeText }}</span>
      </div>
      <div class="mb-metric mb-range">
        <span class="mb-label">统计区间</span>
        <span class="mb-range-text">{{ rangeText }}</span>
      </div>
    </div>

    <BaseChart v-if="points.length > 1" :option="chartOption" :height="200" />
    <div v-else class="mb-empty">暂无融资余额历史数据</div>

    <div v-if="note" class="mb-note">{{ note }}</div>
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

.mb-note {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-muted);
}
</style>
