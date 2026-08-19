<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ZTStats, ZTStock, DTStock } from '../types'

interface Props {
  ztStats: ZTStats
  title?: string
}

const props = withDefaults(defineProps<Props>(), {
  title: '涨跌停统计'
})

const activeTab = ref<'zt' | 'dt'>('zt')

const displayList = computed(() => {
  return activeTab.value === 'zt' ? props.ztStats.ztList : props.ztStats.dtList
})

const ztDtRatio = computed(() => {
  return `${props.ztStats.ztCount} : ${props.ztStats.dtCount}`
})

function getChangeColor(changePct: number): string {
  return changePct >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
}
</script>

<template>
  <div class="zt-stats-panel">
    <div class="panel-header">
      <h3 class="panel-title">{{ title }}</h3>
      <div class="zt-dt-ratio" :style="{ color: 'var(--color-danger)' }">
        {{ ztDtRatio }}
      </div>
    </div>

    <!-- 昨日涨停表现 -->
    <div class="prev-zt-performance" v-if="ztStats.prevZTPerformance">
      <div class="performance-title">昨日涨停表现</div>
      <div class="performance-content">
        <div class="avg-change">
          <span class="label">平均涨幅</span>
          <span class="value" :style="{ color: 'var(--color-danger)' }">
            +{{ ztStats.prevZTPerformance.avgChange.toFixed(2) }}%
          </span>
        </div>
        <div class="top-performer">
          <span class="label">最强个股</span>
          <span class="stock-name">{{ ztStats.prevZTPerformance.topPerformer }}</span>
          <span class="stock-change" :style="{ color: 'var(--color-danger)' }">
            +{{ ztStats.prevZTPerformance.topPerformerChange.toFixed(2) }}%
          </span>
        </div>
      </div>
    </div>

    <!-- 今日涨跌停切换 -->
    <div class="tab-switch">
      <button
        :class="['tab-btn', { active: activeTab === 'zt' }]"
        @click="activeTab = 'zt'"
      >
        涨停 ({{ ztStats.ztCount }})
      </button>
      <button
        :class="['tab-btn', { active: activeTab === 'dt' }]"
        @click="activeTab = 'dt'"
      >
        跌停 ({{ ztStats.dtCount }})
      </button>
    </div>

    <!-- 股票列表 -->
    <div class="stock-list">
      <div
        v-for="stock in displayList"
        :key="stock.code"
        class="stock-item"
      >
        <div class="stock-header">
          <div class="stock-info">
            <span class="stock-name">{{ stock.name }}</span>
            <span class="stock-code">{{ stock.code }}</span>
          </div>
          <div class="stock-change" :style="{ color: getChangeColor(stock.changePct) }">
            {{ stock.changePct >= 0 ? '+' : '' }}{{ stock.changePct.toFixed(2) }}%
          </div>
        </div>
        <div class="stock-details">
          <div class="detail-item">
            <span class="label">价格</span>
            <span class="value">¥{{ stock.price.toFixed(2) }}</span>
          </div>
          <div class="detail-item">
            <span class="label">市值</span>
            <span class="value">{{ stock.marketCap }}亿</span>
          </div>
          <div class="detail-item" v-if="'firstZtTime' in stock">
            <span class="label">封板</span>
            <span class="value">{{ (stock as ZTStock).firstZtTime }}</span>
          </div>
          <div class="detail-item" v-if="'连板数' in stock && (stock as ZTStock).连板数 > 0">
            <span class="label">连板</span>
            <span class="value highlight">{{ (stock as ZTStock).连板数 }}连板</span>
          </div>
          <div class="detail-item" v-if="'continuousDt' in stock">
            <span class="label">连跌</span>
            <span class="value">{{ (stock as DTStock).continuousDt }}天</span>
          </div>
        </div>
        <div class="stock-industry">{{ stock.industry }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.zt-stats-panel {
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

.zt-dt-ratio {
  font-family: 'JetBrains Mono', monospace;
  font-size: 18px;
  font-weight: 700;
}

.prev-zt-performance {
  background: var(--bg-subtle);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
}

.performance-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.performance-content {
  display: flex;
  gap: 24px;
}

.avg-change, .top-performer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.label {
  font-size: 12px;
  color: var(--text-muted);
}

.value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  font-weight: 700;
}

.stock-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.stock-change {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 600;
}

.tab-switch {
  display: flex;
  gap: 4px;
  background: var(--bg-subtle);
  border-radius: 6px;
  padding: 2px;
  margin-bottom: 16px;
}

.tab-btn {
  flex: 1;
  padding: 8px 12px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 13px;
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

.stock-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
}

.stock-item {
  padding: 12px;
  background: var(--bg-subtle);
  border-radius: 8px;
}

.stock-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.stock-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stock-code {
  font-size: 11px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.stock-details {
  display: flex;
  gap: 16px;
  margin-bottom: 8px;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.detail-item .label {
  font-size: 10px;
  color: var(--text-muted);
}

.detail-item .value {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.detail-item .value.highlight {
  color: var(--color-danger);
}

.stock-industry {
  font-size: 11px;
  color: var(--text-muted);
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle);
}
</style>
