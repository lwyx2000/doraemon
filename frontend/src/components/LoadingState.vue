<script setup lang="ts">
import { NSpin, NIcon, NButton } from 'naive-ui'
import { AlertCircleOutline, RefreshOutline } from '@vicons/ionicons5'

withDefaults(
  defineProps<{
    loading?: boolean
    error?: string | null
    /** Min height of the placeholder area, in px. */
    minHeight?: number
    /** Loading text shown below the spinner. */
    text?: string
  }>(),
  {
    loading: false,
    error: null,
    minHeight: 240,
    text: '加载中...',
  },
)

const emit = defineEmits<{ (e: 'retry'): void }>()
</script>

<template>
  <div
    v-if="loading || error"
    class="loading-state"
    :style="{ minHeight: `${minHeight}px` }"
    role="status"
    :aria-live="error ? 'assertive' : 'polite'"
  >
    <template v-if="loading">
      <n-spin size="medium" />
      <span class="ls-text">{{ text }}</span>
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
