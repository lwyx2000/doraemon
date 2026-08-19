<script setup lang="ts">
// 分区级兜底：加载失败（带重试）/ 加载成功但无数据（空态）
import { NIcon, NButton } from 'naive-ui'
import { AlertCircleOutline, RefreshOutline } from '@vicons/ionicons5'

withDefaults(
  defineProps<{
    /** 失败信息；为空表示“加载成功但无数据” */
    error?: string | null
    /** 最小高度（px），让兜底区域与正常内容高度接近，避免布局跳动 */
    minHeight?: number
    /** 空态文案 */
    emptyText?: string
  }>(),
  {
    error: null,
    minHeight: 160,
    emptyText: '暂无数据',
  },
)

const emit = defineEmits<{ (e: 'retry'): void }>()
</script>

<template>
  <div class="section-fallback" :style="{ minHeight: `${minHeight}px` }">
    <template v-if="error">
      <n-icon :component="AlertCircleOutline" size="28" class="sf-icon" />
      <span class="sf-text">{{ error }}</span>
      <n-button size="small" type="primary" ghost @click="emit('retry')">
        <template #icon><n-icon :component="RefreshOutline" /></template>
        重试
      </n-button>
    </template>
    <template v-else>
      <span class="sf-text sf-empty">{{ emptyText }}</span>
    </template>
  </div>
</template>

<style scoped>
.section-fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  box-shadow: var(--shadow-card);
}

.sf-icon {
  color: var(--color-danger);
}

.sf-text {
  font-family: 'Work Sans', sans-serif;
  font-size: 13px;
  color: var(--text-secondary);
  text-align: center;
  max-width: 320px;
}

.sf-empty {
  color: var(--text-muted);
}
</style>
