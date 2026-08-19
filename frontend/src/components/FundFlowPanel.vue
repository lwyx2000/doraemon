<script setup lang="ts">
import { computed } from 'vue'
import type { FundFlows } from '../types'

interface Props {
  fundFlows: FundFlows
  title?: string
}

const props = withDefaults(defineProps<Props>(), {
  title: '资金流向'
})

const mainFlowAvailable = computed(() => props.fundFlows.mainFlowAvailable !== false)
const isProxy = computed(() => props.fundFlows.source === 'board_proxy')

const mainFlowColor = computed(() => {
  const v = props.fundFlows.mainInflow
  if (v == null) return 'var(--text-muted)'
  return v >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
})

const flowItems = computed(() => [
  { label: '主力净流入', value: props.fundFlows.mainInflow, pct: props.fundFlows.mainInflowPct },
  { label: '超大单净流入', value: props.fundFlows.superLargeInflow, pct: props.fundFlows.superLargeInflowPct },
  { label: '大单净流入', value: props.fundFlows.largeInflow, pct: props.fundFlows.largeInflowPct },
  { label: '中单净流入', value: props.fundFlows.mediumInflow, pct: props.fundFlows.mediumInflowPct },
  { label: '小单净流入', value: props.fundFlows.smallInflow, pct: props.fundFlows.smallInflowPct },
])

function formatAmount(value: number | null): string {
  if (value == null) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}亿`
}

function formatPct(value: number | null): string {
  if (value == null) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function getChangeColor(value: number | null): string {
  if (value == null) return 'var(--text-muted)'
  return value >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
}
</script>

<template>
  <div class="fund-flow-panel">
    <div class="panel-header">
      <h3 class="panel-title">{{ title }}</h3>
      <span class="panel-date">{{ fundFlows.date }}</span>
    </div>

    <div class="main-flow">
      <div class="main-flow-label">大盘资金净流入</div>
      <div class="main-flow-value" :style="{ color: mainFlowColor }">
        {{ formatAmount(fundFlows.mainInflow) }}
      </div>
      <div v-if="!mainFlowAvailable" class="main-flow-note">
        主力净流入为东财专有指标，53 东财源不可用，暂以板块涨跌幅代理
      </div>
    </div>

    <div class="flow-chart" v-if="mainFlowAvailable">
      <div
        v-for="item in flowItems"
        :key="item.label"
        class="flow-bar-item"
      >
        <div class="flow-label">{{ item.label }}</div>
        <div class="flow-bar-wrapper">
          <div
            class="flow-bar"
            :style="{
              width: `${item.pct == null ? 0 : Math.min(Math.abs(item.pct) * 10, 100)}%`,
              background: getChangeColor(item.value),
              marginLeft: item.value != null && item.value < 0 ? 'auto' : '0'
            }"
          />
        </div>
        <div class="flow-value" :style="{ color: getChangeColor(item.value) }">
          {{ formatAmount(item.value) }}
        </div>
      </div>
    </div>

    <div class="industry-flows" v-if="fundFlows.industryFlows?.length">
      <div class="industry-title">{{ isProxy ? '行业涨跌 TOP5（真实板块数据）' : '行业资金流向 TOP5' }}</div>
      <div class="industry-list">
        <div
          v-for="(industry, index) in fundFlows.industryFlows"
          :key="industry.name"
          class="industry-item"
        >
          <span class="industry-rank">{{ index + 1 }}</span>
          <span class="industry-name">{{ industry.name }}</span>
          <span v-if="industry.inflow != null" class="industry-inflow" :style="{ color: getChangeColor(industry.inflow) }">
            +{{ industry.inflow.toFixed(2) }}亿
          </span>
          <span v-else class="industry-inflow industry-inflow--na">净流入N/A</span>
          <span class="industry-change" :style="{ color: getChangeColor(industry.changePct) }">
            {{ formatPct(industry.changePct) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fund-flow-panel {
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
  margin-bottom: 16px;
}

.panel-title {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.panel-date {
  font-size: 12px;
  color: var(--text-muted);
}

.main-flow {
  text-align: center;
  padding: 16px;
  background: var(--bg-subtle);
  border-radius: 8px;
  margin-bottom: 16px;
}

.main-flow-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.main-flow-note {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 8px;
  line-height: 1.4;
}

.main-flow-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 28px;
  font-weight: 700;
}

.flow-chart {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.flow-bar-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.flow-label {
  width: 80px;
  font-size: 12px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.flow-bar-wrapper {
  flex: 1;
  height: 8px;
  background: var(--border-subtle);
  border-radius: 4px;
  overflow: hidden;
  position: relative;
}

.flow-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.flow-value {
  width: 80px;
  text-align: right;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.industry-flows {
  border-top: 1px solid var(--border-subtle);
  padding-top: 16px;
}

.industry-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.industry-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.industry-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: var(--bg-subtle);
  border-radius: 6px;
  font-size: 13px;
}

.industry-rank {
  width: 20px;
  text-align: center;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: var(--text-muted);
}

.industry-name {
  flex: 1;
  color: var(--text-primary);
}

.industry-inflow {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}

.industry-inflow--na {
  color: var(--text-muted);
  font-weight: 400;
  font-size: 12px;
}

.industry-change {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--text-muted);
}
</style>
