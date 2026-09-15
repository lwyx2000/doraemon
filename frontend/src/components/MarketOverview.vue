<script setup lang="ts">
import { ref, computed } from 'vue'
import { NButton } from 'naive-ui'
import { ChevronDown, ChevronUp } from '@vicons/ionicons5'
import type { MarketOverview } from '../types'
import IndexKlineDialog from './IndexKlineDialog.vue'

interface Props {
  overview: MarketOverview
}

const props = defineProps<Props>()

const isExpanded = ref(false)

// K 线弹窗状态
const showKline = ref(false)
const selectedIndex = ref<{ code: string; name: string } | null>(null)

function openKline(index: { name: string; code: string }) {
  selectedIndex.value = { code: index.code, name: index.name }
  showKline.value = true
}

const weekDay = computed(() => {
  const date = new Date(props.overview.date)
  const days = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']
  return days[date.getDay()]
})

const totalCount = computed(() => {
  return props.overview.upCount + props.overview.downCount + props.overview.flatCount
})

// 默认显示前6个指数
const displayIndices = computed(() => {
  if (isExpanded.value) {
    return props.overview.indices
  }
  return props.overview.indices.slice(0, 6)
})

const hasMore = computed(() => {
  return props.overview.indices.length > 6
})
</script>

<template>
  <div class="market-overview">
    <!-- 市场状态 -->
    <div class="market-status">
      <div class="status-badge" :class="overview.status">
        <span class="status-dot"></span>
        {{ overview.status }}
      </div>
      <div class="market-date">
        {{ overview.date }} {{ weekDay }}
      </div>
    </div>

    <!-- 指数列表 -->
    <div class="indices-section">
      <div class="indices-grid" :class="{ expanded: isExpanded }">
        <div
          v-for="index in displayIndices"
          :key="index.code"
          class="index-card"
          role="button"
          tabindex="0"
          @click="openKline(index)"
          @keydown.enter="openKline(index)"
          @keydown.space.prevent="openKline(index)"
        >
          <div class="index-name">{{ index.name }}</div>
          <div class="index-price" :style="{ color: index.changePct >= 0 ? 'var(--color-danger)' : 'var(--color-success)' }">
            {{ index.price.toFixed(2) }}
          </div>
          <div class="index-change">
            <span :style="{ color: index.changePct >= 0 ? 'var(--color-danger)' : 'var(--color-success)' }">
              {{ index.change >= 0 ? '+' : '' }}{{ index.change.toFixed(2) }}
            </span>
            <span :style="{ color: index.changePct >= 0 ? 'var(--color-danger)' : 'var(--color-success)' }">
              {{ index.changePct >= 0 ? '+' : '' }}{{ index.changePct.toFixed(2) }}%
            </span>
          </div>
        </div>
      </div>
      
      <!-- 展开/收起按钮 -->
      <div v-if="hasMore" class="expand-toggle">
        <n-button text size="small" @click="isExpanded = !isExpanded">
          <template #icon>
            <component :is="isExpanded ? ChevronUp : ChevronDown" />
          </template>
          {{ isExpanded ? '收起' : `展开全部 ${overview.indices.length} 个指数` }}
        </n-button>
      </div>
    </div>

    <!-- 涨跌家数 -->
    <div class="up-down-stats">
      <div class="up-down-bar">
        <div class="down-segment" :style="{ width: `${(overview.downCount / totalCount) * 100}%` }"></div>
        <div class="flat-segment" :style="{ width: `${(overview.flatCount / totalCount) * 100}%` }"></div>
        <div class="up-segment" :style="{ width: `${(overview.upCount / totalCount) * 100}%` }"></div>
      </div>
      <div class="up-down-labels">
        <div class="down-label">
          <span class="count">跌{{ overview.downCount }}</span>
        </div>
        <div class="flat-label">
          <span class="count">平{{ overview.flatCount }}</span>
        </div>
        <div class="up-label">
          <span class="count">涨{{ overview.upCount }}</span>
        </div>
      </div>
    </div>

    <!-- 成交额 -->
    <div class="volume-stats">
      <div class="volume-item">
        <span class="label">今日实时成交额</span>
        <span class="value">{{ overview.totalVolume }}亿</span>
      </div>
      <div class="volume-change">
        <span class="label">较上一日此时</span>
        <span v-if="overview.volumeChange == null" class="value" style="color: var(--text-muted)">
          —
        </span>
        <span v-else class="value" :style="{ color: overview.volumeChange >= 0 ? 'var(--color-danger)' : 'var(--color-success)' }">
          {{ overview.volumeChange >= 0 ? '+' : '' }}{{ overview.volumeChange }}亿
        </span>
      </div>
    </div>

    <!-- 指数 K 线弹窗 -->
    <IndexKlineDialog
      :show="showKline"
      :code="selectedIndex?.code || ''"
      :name="selectedIndex?.name || ''"
      @update:show="showKline = $event"
    />
  </div>
</template>

<style scoped>
.market-overview {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 20px;
  box-shadow: var(--shadow-card);
}

.market-status {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.status-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
}

.status-badge.开盘中 {
  background: rgba(220, 38, 38, 0.1);
  color: var(--color-danger);
}

.status-badge.已收盘 {
  background: var(--bg-subtle);
  color: var(--text-muted);
}

.status-badge.休市 {
  background: var(--bg-subtle);
  color: var(--text-muted);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.market-date {
  font-size: 13px;
  color: var(--text-muted);
}

.indices-section {
  margin-bottom: 24px;
}

.indices-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  max-height: 90px; /* 只显示一行的高度 */
  overflow: hidden;
  transition: max-height 0.3s ease;
}

.indices-grid.expanded {
  max-height: none;
}

@media (max-width: 1400px) {
  .indices-grid { grid-template-columns: repeat(4, 1fr); }
}

@media (max-width: 1024px) {
  .indices-grid { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 768px) {
  .indices-grid { grid-template-columns: repeat(2, 1fr); }
}

.expand-toggle {
  display: flex;
  justify-content: center;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--border-subtle);
}

.index-card {
  text-align: center;
  padding: 12px 8px;
  background: var(--bg-subtle);
  border-radius: 8px;
  min-width: 0;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.1s ease;
}

.index-card:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.06));
}

.index-card:active {
  transform: scale(0.97);
}

.index-name {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.index-price {
  font-family: 'JetBrains Mono', monospace;
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.index-change {
  display: flex;
  justify-content: center;
  gap: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  flex-wrap: wrap;
}

.up-down-stats {
  margin-bottom: 20px;
}

.up-down-bar {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}

.down-segment {
  background: var(--color-success);
}

.flat-segment {
  background: var(--border-default);
}

.up-segment {
  background: var(--color-danger);
}

.up-down-labels {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}

.down-label .count {
  color: var(--color-success);
  font-weight: 600;
}

.up-label .count {
  color: var(--color-danger);
  font-weight: 600;
}

.flat-label .count {
  color: var(--text-muted);
}

.volume-stats {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 16px;
  border-top: 1px solid var(--border-subtle);
}

.volume-item, .volume-change {
  display: flex;
  align-items: center;
  gap: 8px;
}

.volume-item .label, .volume-change .label {
  font-size: 13px;
  color: var(--text-muted);
}

.volume-item .value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.volume-change .value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  font-weight: 600;
}

@media (max-width: 768px) {
  .indices-grid {
    grid-template-columns: 1fr;
  }
}
</style>
