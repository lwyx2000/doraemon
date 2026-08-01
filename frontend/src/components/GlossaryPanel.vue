<script setup lang="ts">
/**
 * 缩写词典面板
 *
 * 可折叠区域，默认隐藏。点击标题栏展开/收起。
 * 根据 pageKey 自动从 glossaryByPage 字典获取本页面相关缩写列表。
 */
import { ref, computed } from 'vue'
import { NIcon, NCollapseTransition } from 'naive-ui'
import { BookOutline, ChevronDownOutline, ChevronUpOutline } from '@vicons/ionicons5'
import { glossaryByPage } from '../composables/glossaryContent'

const props = defineProps<{
  /** 页面 key，对应 glossaryByPage 字典 */
  pageKey: string
}>()

const expanded = ref(false)

const items = computed(() => glossaryByPage[props.pageKey] ?? [])
</script>

<template>
  <div v-if="items.length" class="glossary-panel">
    <button class="glossary-toggle" @click="expanded = !expanded">
      <span class="toggle-left">
        <NIcon :component="BookOutline" size="14" />
        <span class="toggle-text">缩写词典</span>
        <span class="toggle-count">{{ items.length }}</span>
      </span>
      <NIcon :component="expanded ? ChevronUpOutline : ChevronDownOutline" size="16" class="toggle-arrow" />
    </button>

    <NCollapseTransition :show="expanded">
      <div class="glossary-body">
        <div v-for="item in items" :key="item.abbr" class="glossary-item">
          <span class="g-abbr">{{ item.abbr }}</span>
          <span class="g-full">{{ item.full }}</span>
          <span class="g-cn">{{ item.cn }}</span>
        </div>
      </div>
    </NCollapseTransition>
  </div>
</template>

<style scoped>
.glossary-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 16px;
}

.glossary-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 10px 16px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background 0.15s ease, color 0.15s ease;
}
.glossary-toggle:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.toggle-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toggle-text {
  font-family: 'Work Sans', sans-serif;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.03em;
}
.toggle-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--bg-hover);
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}
.toggle-arrow {
  color: var(--text-muted);
  transition: transform 0.2s ease;
}

.glossary-body {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px;
  padding: 4px 16px 14px;
  border-top: 1px solid var(--border-default);
}

.glossary-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: var(--bg-hover);
  flex-wrap: wrap;
}

.g-abbr {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 700;
  color: var(--color-primary);
  flex-shrink: 0;
  min-width: 48px;
}
.g-full {
  font-family: 'Work Sans', sans-serif;
  font-size: 10px;
  color: var(--text-muted);
  font-style: italic;
}
.g-cn {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
  flex: 1;
  min-width: 120px;
}

@media (max-width: 768px) {
  .glossary-body {
    grid-template-columns: 1fr;
  }
}
</style>
