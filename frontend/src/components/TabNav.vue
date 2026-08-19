<script setup lang="ts">
import { NIcon } from 'naive-ui'
import { CloseOutline, RefreshOutline, CloseCircleOutline } from '@vicons/ionicons5'
import { useTabs } from '../composables/useTabs'

const { tabs, activePath, switchTab, closeTab, closeOthers, closeAll, refreshTab } = useTabs()
</script>

<template>
  <div class="tab-nav">
    <div class="tab-nav-scroll">
      <div class="tab-list">
        <div
          v-for="tab in tabs"
          :key="tab.path"
          :class="['tab-item', { active: tab.path === activePath }]"
          @click="switchTab(tab.path)"
        >
          <span class="tab-dot" v-if="tab.path === activePath" />
          <span class="tab-title">{{ tab.title }}</span>
          <button
            v-if="tab.closable"
            class="tab-close"
            @click.stop="closeTab(tab.path)"
            :aria-label="`关闭 ${tab.title}`"
          >
            <n-icon :component="CloseOutline" size="14" />
          </button>
        </div>
      </div>
    </div>
    <div class="tab-actions">
      <button
        class="tab-action-btn"
        title="刷新当前标签"
        @click="refreshTab(activePath)"
      >
        <n-icon :component="RefreshOutline" size="16" />
      </button>
      <button
        class="tab-action-btn"
        title="关闭其他标签"
        @click="activePath && closeOthers(activePath)"
      >
        <n-icon :component="CloseCircleOutline" size="16" />
      </button>
      <button
        class="tab-action-btn"
        title="关闭所有标签"
        @click="closeAll"
      >
        <n-icon :component="CloseOutline" size="16" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.tab-nav {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-default);
  padding: 0 12px;
  flex-shrink: 0;
  position: relative;
  z-index: 10;
}

.tab-nav-scroll {
  flex: 1;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}

.tab-nav-scroll::-webkit-scrollbar {
  height: 2px;
}

.tab-list {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 100%;
}

.tab-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  height: 28px;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  font-family: 'Work Sans', sans-serif;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  transition: all 0.15s ease;
  position: relative;
  flex-shrink: 0;
}

.tab-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tab-item.active {
  background: var(--bg-active);
  color: var(--color-primary);
}

.tab-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
  flex-shrink: 0;
}

.tab-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: none;
  background: transparent;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-muted);
  padding: 0;
  margin-left: 2px;
  transition: all 0.15s;
  flex-shrink: 0;
}

.tab-close:hover {
  background: var(--color-danger);
  color: white;
}

.tab-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding-left: 8px;
  border-left: 1px solid var(--border-default);
}

.tab-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-muted);
  transition: all 0.15s;
}

.tab-action-btn:hover {
  background: var(--bg-hover);
  color: var(--color-primary);
}

.tab-action-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

/* Mobile: hide action buttons */
@media (max-width: 768px) {
  .tab-actions {
    display: none;
  }
  .tab-nav {
    padding: 0 8px;
  }
  .tab-item {
    padding: 5px 8px;
    font-size: 12px;
  }
}
</style>
