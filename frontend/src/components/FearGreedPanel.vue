<script setup lang="ts">
/**
 * 宏观看板嵌入式「贪婪恐惧指数」紧凑面板。
 * 左：恐贪总值 + 档位；右：近 90 日迷你走势；下：6 分项得分条。
 * 完整口径说明/可交互历史曲线/手动采集回填见详情页 /fear-greed。
 */
import { computed } from 'vue'
import { NTag, NButton, NText } from 'naive-ui'
import { useRouter } from 'vue-router'
import BaseChart from './BaseChart.vue'
import { buildFearGreedMetrics, labelType, scoreColor } from '../utils/fearGreedDisplay'
import type { FearGreedLatest, FearGreedPoint } from '../types'

interface Props {
  latest: FearGreedLatest | null
  history?: FearGreedPoint[]
  title?: string
}

const props = withDefaults(defineProps<Props>(), {
  history: () => [],
  title: '贪婪恐惧指数',
})

const router = useRouter()

const metrics = computed(() => (props.latest ? buildFearGreedMetrics(props.latest) : []))

const totalText = computed(() => {
  const v = props.latest?.totalScore
  return v == null ? '—' : v.toFixed(1)
})

const partialText = computed(() => {
  const l = props.latest
  if (!l) return ''
  return l.componentsUsed < 6 ? `${l.componentsUsed}/6 分项·近似` : '6/6 分项'
})

// 迷你走势：仅总值线 + 10/50/90 虚线参考，无坐标轴（紧凑）
const sparkOption = computed(() => ({
  grid: { left: 6, right: 6, top: 8, bottom: 6 },
  tooltip: {
    trigger: 'axis',
    formatter: (params: any[]) =>
      params.length
        ? `${params[0].axisValue}<br/>恐贪值 <b>${params[0].value == null ? '—' : Number(params[0].value).toFixed(1)}</b>`
        : '',
  },
  xAxis: { type: 'category', data: props.history.map((h) => h.date), show: false, boundaryGap: false },
  yAxis: { type: 'value', min: 0, max: 100, show: false },
  series: [
    {
      name: '恐贪值',
      type: 'line',
      data: props.history.map((h) => h.totalScore),
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 2, color: '#8b5cf6' },
      areaStyle: { color: '#8b5cf6', opacity: 0.12 },
      markLine: {
        symbol: 'none',
        silent: true,
        label: { show: false },
        lineStyle: { type: 'dashed', opacity: 0.35 },
        data: [{ yAxis: 10 }, { yAxis: 50 }, { yAxis: 90 }],
      },
    },
  ],
}))
</script>

<template>
  <div class="fear-greed-panel">
    <div class="panel-header">
      <h3 class="panel-title">
        {{ title }}
        <span class="panel-subtitle">0 恐慌 ↔ 100 贪婪</span>
      </h3>
      <div class="header-right">
        <n-text v-if="latest?.date" depth="3" class="panel-date">{{ latest.date }}</n-text>
        <n-button text size="small" @click="router.push('/fear-greed')">详情 →</n-button>
      </div>
    </div>

    <div class="fg-body">
      <div class="fg-score">
        <div class="fg-score-value" :style="{ color: scoreColor(latest?.totalScore) }">
          {{ totalText }}
        </div>
        <div class="fg-score-tags">
          <n-tag :type="labelType(latest?.label)" round size="small">
            {{ latest?.label ?? '—' }}
          </n-tag>
          <span class="fg-partial" :class="{ full: latest?.componentsUsed === 6 }">{{ partialText }}</span>
        </div>
      </div>
      <div class="fg-spark">
        <BaseChart v-if="history.length > 1" :option="sparkOption" :height="84" />
        <div v-else class="fg-spark-empty">暂无历史走势</div>
      </div>
    </div>

    <div class="fg-metrics">
      <div v-for="m in metrics" :key="m.key" class="fg-metric" :title="m.tip">
        <div class="fg-metric-head">
          <span class="fg-metric-name">{{ m.name }}</span>
          <span class="fg-metric-weight">{{ m.weight }}</span>
        </div>
        <div class="fg-metric-body">
          <span class="fg-metric-score" :style="{ color: scoreColor(m.score) }">
            {{ m.score == null ? '—' : m.score.toFixed(1) }}
          </span>
          <span class="fg-metric-raw">{{ m.raw }}</span>
        </div>
        <div class="fg-metric-track">
          <div
            class="fg-metric-fill"
            :style="{ width: `${m.score == null ? 0 : Math.round(m.score)}%`, background: scoreColor(m.score) }"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fear-greed-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 16px;
  box-shadow: var(--shadow-card);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
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

.panel-subtitle {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-date {
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
}

.fg-body {
  display: grid;
  grid-template-columns: 168px 1fr;
  gap: 16px;
  align-items: center;
}

.fg-score {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.fg-score-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 40px;
  font-weight: 700;
  line-height: 1;
}

.fg-score-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}

.fg-partial {
  font-size: 11px;
  color: var(--text-muted);
}

.fg-partial.full {
  color: var(--text-secondary);
}

.fg-spark {
  min-width: 0;
}

.fg-spark-empty {
  height: 84px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--text-muted);
  background: var(--bg-subtle, rgba(127, 127, 127, 0.05));
  border-radius: 8px;
}

.fg-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px 20px;
  margin-top: 14px;
}

.fg-metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: help;
}

.fg-metric-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.fg-metric-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.fg-metric-weight {
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}

.fg-metric-body {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.fg-metric-score {
  font-family: 'JetBrains Mono', monospace;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.1;
}

.fg-metric-raw {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}

.fg-metric-track {
  height: 4px;
  border-radius: 2px;
  background: rgba(127, 127, 127, 0.15);
  overflow: hidden;
}

.fg-metric-fill {
  height: 100%;
  border-radius: 2px;
}

@media (max-width: 1280px) {
  .fg-metrics { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 720px) {
  .fg-body { grid-template-columns: 1fr; }
  .fg-metrics { grid-template-columns: 1fr; }
}
</style>
