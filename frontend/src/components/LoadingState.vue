<script setup lang="ts">
import { NSpin, NIcon, NButton } from 'naive-ui'
import { AlertCircleOutline, RefreshOutline } from '@vicons/ionicons5'
import SectionSkeleton from './SectionSkeleton.vue'

withDefaults(
  defineProps<{
    loading?: boolean
    error?: string | null
    /** Min height of the placeholder area, in px. */
    minHeight?: number
    /** Loading text shown below the spinner. */
    text?: string
    /** 加载时显示整页骨架屏（默认转圈+文案） */
    skeleton?: boolean
  }>(),
  {
    loading: false,
    error: null,
    minHeight: 240,
    text: '加载中...',
    skeleton: false,
  },
)

const emit = defineEmits<{ (e: 'retry'): void }>()
</script>

<template>
  <div
    v-if="loading || error"
    class="loading-state"
    :class="{ 'ls-skeleton': skeleton }"
    :style="{ minHeight: `${minHeight}px` }"
    role="status"
    :aria-live="error ? 'assertive' : 'polite'"
  >
    <template v-if="loading">
      <SectionSkeleton v-if="skeleton" variant="page" />
      <template v-else>
        <n-spin size="medium" />
        <span class="ls-text">{{ text }}</span>
      </template>
    </template>
    <template v-else-if="error">
      <n-icon :component="AlertCircleOutline" size="32" class="ls-error-icon" />
      <span class="ls-error-text">{{ error }}</span>
      <n-button size="small" type="primary" ghost @click="emit('retry')">
        <template #icon><n-icon :component="RefreshOutline" /></template>
        重试
      </n-button>
    </template>
  </div>
  <slot v-else />
</template>

<style scoped>
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

/* 骨架屏模式下去掉包裹容器的面板样式（骨架自身带卡片） */
.loading-state.ls-skeleton {
  padding: 0;
  background: transparent;
  border: none;
  box-shadow: none;
  align-items: stretch;
  justify-content: flex-start;
}

.ls-text {
  font-size: 12px;
  color: var(--text-muted);
  font-family: 'Work Sans', sans-serif;
  letter-spacing: 0.04em;
}

.ls-error-icon {
  color: var(--color-danger);
}

.ls-error-text {
  font-size: 13px;
  color: var(--text-secondary);
  text-align: center;
  max-width: 320px;
}
</style>
