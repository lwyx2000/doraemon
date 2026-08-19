<script setup lang="ts">
import { NSkeleton } from 'naive-ui'

withDefaults(
  defineProps<{
    /** 骨架屏形态 */
    variant?: 'page' | 'overview' | 'card' | 'flow' | 'metric' | 'table'
    /** 列表/表格行数 */
    rows?: number
  }>(),
  {
    variant: 'card',
    rows: 5,
  },
)
</script>

<template>
  <div class="section-skeleton" :class="`skeleton-${variant}`">
    <!-- 整页骨架（LoadingState 使用） -->
    <template v-if="variant === 'page'">
      <div class="sk-page-header">
        <div class="sk-page-title">
          <n-skeleton :width="180" :height="18" />
          <n-skeleton :width="240" :height="12" />
        </div>
        <n-skeleton :width="72" :height="28" round />
      </div>
      <div class="sk-page-cards">
        <div v-for="i in 4" :key="i" class="sk-page-card">
          <n-skeleton :width="80" :height="13" />
          <n-skeleton :width="'100%'" :height="11" />
          <n-skeleton :width="'82%'" :height="11" />
          <n-skeleton :width="'60%'" :height="11" />
        </div>
      </div>
      <div class="sk-page-table">
        <n-skeleton :width="'40%'" :height="13" />
        <n-skeleton v-for="i in 4" :key="i" :width="'100%'" :height="30" />
      </div>
    </template>

    <!-- 市场概况 -->
    <template v-else-if="variant === 'overview'">
      <div class="sk-head">
        <n-skeleton :width="110" :height="26" round />
        <n-skeleton :width="130" :height="12" />
      </div>
      <div class="sk-indices">
        <div v-for="i in 6" :key="i" class="sk-index">
          <n-skeleton :width="44" :height="11" />
          <n-skeleton :width="64" :height="17" />
          <n-skeleton :width="52" :height="10" />
        </div>
      </div>
      <n-skeleton :width="'100%'" :height="7" round />
      <div class="sk-foot">
        <n-skeleton :width="150" :height="13" />
        <n-skeleton :width="130" :height="13" />
      </div>
    </template>

    <!-- 卡片列表（板块涨幅 / 基金排行 / 涨跌停） -->
    <template v-else-if="variant === 'card'">
      <div class="sk-head">
        <n-skeleton :width="90" :height="15" />
        <n-skeleton :width="84" :height="22" round />
      </div>
      <div v-for="i in rows" :key="i" class="sk-row">
        <n-skeleton :width="22" :height="22" round />
        <div class="sk-row-info">
          <n-skeleton :width="110" :height="13" />
          <n-skeleton :width="150" :height="10" />
        </div>
        <n-skeleton :width="54" :height="13" />
      </div>
    </template>

    <!-- 资金流向 -->
    <template v-else-if="variant === 'flow'">
      <div class="sk-head">
        <n-skeleton :width="80" :height="15" />
        <n-skeleton :width="56" :height="11" />
      </div>
      <div class="sk-main">
        <n-skeleton :width="96" :height="11" />
        <n-skeleton :width="140" :height="26" />
      </div>
      <div v-for="i in 5" :key="i" class="sk-flow">
        <n-skeleton :width="68" :height="11" />
        <div class="sk-flow-bar">
          <n-skeleton :width="`${35 + i * 7}%`" :height="7" round />
        </div>
        <n-skeleton :width="58" :height="11" />
      </div>
    </template>

    <!-- 指标卡（ERP / DR007 / GC001） -->
    <template v-else-if="variant === 'metric'">
      <div class="sk-metrics">
        <div v-for="i in 4" :key="i" class="sk-metric">
          <n-skeleton :width="64" :height="11" />
          <n-skeleton :width="110" :height="24" />
          <n-skeleton :width="86" :height="9" />
        </div>
      </div>
    </template>

    <!-- 数据表格 -->
    <template v-else>
      <div class="sk-table">
        <div class="sk-table-row sk-table-head">
          <n-skeleton v-for="i in 6" :key="i" :width="56" :height="11" />
        </div>
        <div v-for="i in rows" :key="i" class="sk-table-row">
          <n-skeleton v-for="j in 6" :key="j" :width="56" :height="11" />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.section-skeleton {
  width: 100%;
}

/* 面板容器：与真实面板保持一致的视觉 */
.skeleton-overview,
.skeleton-card,
.skeleton-flow,
.skeleton-table {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 16px;
  box-shadow: var(--shadow-card);
}

.sk-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.sk-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.sk-row:last-child {
  border-bottom: none;
}

.sk-row-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* overview */
.sk-indices {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

.sk-index {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 12px 8px;
  background: var(--bg-subtle);
  border-radius: 8px;
}

.sk-foot {
  display: flex;
  justify-content: space-between;
  padding-top: 16px;
  margin-top: 16px;
  border-top: 1px solid var(--border-subtle);
}

/* flow */
.sk-main {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  background: var(--bg-subtle);
  border-radius: 8px;
  margin-bottom: 16px;
}

.sk-flow {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.sk-flow:last-child {
  margin-bottom: 0;
}

.sk-flow-bar {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: var(--border-subtle);
  display: flex;
  align-items: center;
}

/* metric：放置在 .metric-grid 网格中时跨满整行 */
.skeleton-metric {
  grid-column: 1 / -1;
}

.sk-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.sk-metric {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: var(--shadow-card);
}

/* table */
.sk-table-row {
  display: flex;
  gap: 24px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.sk-table-row:last-child {
  border-bottom: none;
}

.sk-table-head {
  padding: 6px 0 12px;
}

/* page */
.sk-page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.sk-page-title {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sk-page-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}

.sk-page-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: var(--shadow-card);
}

.sk-page-table {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: var(--shadow-card);
}

@media (max-width: 1280px) {
  .sk-metrics { grid-template-columns: repeat(2, 1fr); }
  .sk-page-cards { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .sk-metrics { grid-template-columns: 1fr; }
  .sk-page-cards { grid-template-columns: 1fr; }
  .sk-indices { grid-template-columns: repeat(2, 1fr); }
}
</style>
