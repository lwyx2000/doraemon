<script setup lang="ts">
import { ref, computed } from 'vue'
import type { BoardSector } from '../types'

interface Props {
  sectors: BoardSector[]
  title?: string
  maxItems?: number
}

const props = withDefaults(defineProps<Props>(), {
  title: '板块涨幅',
  maxItems: 6
})

const activeTab = ref<'industry' | 'concept'>('industry')

const filteredSectors = computed(() => {
  const filtered = props.sectors.filter(s => s.type === activeTab.value)
  return filtered.slice(0, props.maxItems)
})

function getChangeColor(changePct: number): string {
  return changePct >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
}
</script>

<template>
  <div class="board-sector-panel">
    <div class="panel-header">
      <h3 class="panel-title">{{ title }}</h3>
      <div class="tab-switch">
        <button
          :class="['tab-btn', { active: activeTab === 'industry' }]"
          @click="activeTab = 'industry'"
        >
          行业
        </button>
        <button
          :class="['tab-btn', { active: activeTab === 'concept' }]"
          @click="activeTab = 'concept'"
        >
          概念
        </button>
      </div>
    </div>

    <div class="sector-list">
      <div
        v-for="sector in filteredSectors"
        :key="sector.code"
        class="sector-item"
      >
        <div class="sector-rank">{{ sector.rank }}</div>
        <div class="sector-info">
          <div class="sector-name">{{ sector.name }}</div>
          <div class="sector-detail">
            <span class="up-down-count">
              <span class="up">{{ sector.upCount }}涨</span>
              <span class="down">{{ sector.downCount }}跌</span>
            </span>
            <span class="leading-stock">{{ sector.leadingStock }}</span>
          </div>
        </div>
        <div class="sector-change" :style="{ color: getChangeColor(sector.changePct) }">
          <div class="change-pct">{{ sector.changePct >= 0 ? '+' : '' }}{{ sector.changePct.toFixed(2) }}%</div>
          <div class="leading-change" :style="{ color: getChangeColor(sector.leadingStockChange) }">
            {{ sector.leadingStockChange >= 0 ? '+' : '' }}{{ sector.leadingStockChange.toFixed(2) }}%
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.board-sector-panel {
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

.tab-switch {
  display: flex;
  gap: 4px;
  background: var(--bg-subtle);
  border-radius: 6px;
  padding: 2px;
}

.tab-btn {
  padding: 4px 12px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
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

.sector-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sector-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.sector-item:last-child {
  border-bottom: none;
}

.sector-rank {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
  background: var(--bg-subtle);
  border-radius: 4px;
}

.sector-rank:first-child {
  background: var(--color-danger);
  color: white;
}

.sector-rank:nth-child(2) {
  background: rgba(220, 38, 38, 0.8);
  color: white;
}

.sector-rank:nth-child(3) {
  background: rgba(220, 38, 38, 0.6);
  color: white;
}

.sector-info {
  flex: 1;
  min-width: 0;
}

.sector-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.sector-detail {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-muted);
}

.up-down-count {
  display: flex;
  gap: 6px;
}

.up {
  color: var(--color-danger);
}

.down {
  color: var(--color-success);
}

.leading-stock {
  color: var(--text-muted);
}

.sector-change {
  text-align: right;
  font-family: 'JetBrains Mono', monospace;
}

.change-pct {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 2px;
}

.leading-change {
  font-size: 11px;
  opacity: 0.8;
}
</style>
