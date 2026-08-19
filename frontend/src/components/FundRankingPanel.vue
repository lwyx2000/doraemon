<script setup lang="ts">
import { ref, computed } from 'vue'
import type { FundRankingItem } from '../types'

interface Props {
  funds: FundRankingItem[]
  title?: string
  maxItems?: number
}

const props = withDefaults(defineProps<Props>(), {
  title: '基金涨跌排行',
  maxItems: 6
})

const activeTab = ref<'all' | 'ETF' | 'LOF' | 'QDII'>('all')

const filteredFunds = computed(() => {
  let filtered = props.funds
  if (activeTab.value !== 'all') {
    filtered = props.funds.filter(f => f.type === activeTab.value)
  }
  return filtered.slice(0, props.maxItems)
})

function getChangeColor(changePct: number): string {
  return changePct >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
}

function getTypeTagColor(type: string): string {
  const colors: Record<string, string> = {
    'ETF': '#005ea1',
    'LOF': '#10b981',
    'QDII': '#f59e0b',
    '场外基金': '#6b7280'
  }
  return colors[type] || '#6b7280'
}
</script>

<template>
  <div class="fund-ranking-panel">
    <div class="panel-header">
      <h3 class="panel-title">{{ title }}</h3>
      <div class="tab-switch">
        <button
          :class="['tab-btn', { active: activeTab === 'all' }]"
          @click="activeTab = 'all'"
        >
          全部
        </button>
        <button
          :class="['tab-btn', { active: activeTab === 'ETF' }]"
          @click="activeTab = 'ETF'"
        >
          ETF
        </button>
        <button
          :class="['tab-btn', { active: activeTab === 'LOF' }]"
          @click="activeTab = 'LOF'"
        >
          LOF
        </button>
        <button
          :class="['tab-btn', { active: activeTab === 'QDII' }]"
          @click="activeTab = 'QDII'"
        >
          QDII
        </button>
      </div>
    </div>

    <div class="fund-list">
      <div
        v-for="fund in filteredFunds"
        :key="fund.code"
        class="fund-item"
      >
        <div class="fund-rank">{{ fund.rank }}</div>
        <div class="fund-info">
          <div class="fund-name-row">
            <span class="fund-name">{{ fund.name }}</span>
            <span class="fund-type-tag" :style="{ background: getTypeTagColor(fund.type) }">
              {{ fund.type }}
            </span>
          </div>
          <div class="fund-code">{{ fund.code }}</div>
        </div>
        <div class="fund-data">
          <div class="fund-change" :style="{ color: getChangeColor(fund.changePct) }">
            <span class="change-pct">{{ fund.changePct >= 0 ? '+' : '' }}{{ fund.changePct.toFixed(2) }}%</span>
            <span class="change-value">{{ fund.change >= 0 ? '+' : '' }}{{ fund.change.toFixed(3) }}</span>
          </div>
          <div class="fund-nav">净值: {{ fund.nav.toFixed(3) }}</div>
          <div v-if="fund.premiumPct !== undefined && fund.premiumPct !== null" class="fund-premium" :style="{ color: getChangeColor(fund.premiumPct) }">
            溢价: {{ fund.premiumPct >= 0 ? '+' : '' }}{{ fund.premiumPct.toFixed(2) }}%
          </div>
          <div v-if="fund.volume" class="fund-volume">成交: {{ (fund.volume / 10000).toFixed(1) }}亿</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fund-ranking-panel {
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
  flex-wrap: wrap;
  gap: 12px;
}

.panel-title {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.tab-switch {
  display: flex;
  gap: 4px;
  background: var(--bg-subtle);
  border-radius: 6px;
  padding: 2px;
}

.tab-btn {
  padding: 4px 10px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 500;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-btn.active {
  background: var(--bg-card);
  color: var(--color-primary);
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.fund-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.fund-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: var(--bg-subtle);
  border-radius: 8px;
  transition: background 0.2s;
}

.fund-item:hover {
  background: var(--bg-hover);
}

.fund-rank {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  background: var(--bg-card);
  border-radius: 4px;
  flex-shrink: 0;
}

.fund-rank:first-child {
  background: var(--color-danger);
  color: white;
}

.fund-info {
  flex: 1;
  min-width: 0;
}

.fund-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.fund-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.fund-type-tag {
  font-size: 9px;
  font-weight: 600;
  color: white;
  padding: 2px 5px;
  border-radius: 3px;
  flex-shrink: 0;
}

.fund-code {
  font-size: 11px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.fund-data {
  text-align: right;
  flex-shrink: 0;
}

.fund-change {
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 2px;
}

.change-pct {
  font-size: 14px;
  font-weight: 700;
}

.change-value {
  font-size: 10px;
  opacity: 0.8;
  margin-left: 6px;
}

.fund-nav {
  font-size: 10px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.fund-premium {
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
}

.fund-volume {
  font-size: 10px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}
</style>
