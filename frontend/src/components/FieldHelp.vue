<script setup lang="ts">
/**
 * 字段说明提示组件
 *
 * 在字段名旁渲染一个"?"图标，鼠标悬浮显示字段含义。
 * 用法：<FieldHelp field="premium_pct" /> 或 <FieldHelp tip="自定义说明文本" />
 */
import { computed } from 'vue'
import { NIcon, NTooltip } from 'naive-ui'
import { HelpCircleOutline } from '@vicons/ionicons5'
import { getFieldTip } from '../composables/helpContent'

const props = defineProps<{
  /** 字段 key，从 fieldTips 字典自动获取说明 */
  field?: string
  /** 自定义说明文本（优先级高于 field） */
  tip?: string
  /** 图标大小 */
  size?: number
}>()

const tooltipText = computed(() => {
  if (props.tip) return props.tip
  if (props.field) return getFieldTip(props.field)
  return ''
})
</script>

<template>
  <NTooltip v-if="tooltipText" trigger="hover" placement="top" :style="{ maxWidth: '360px' }">
    <template #trigger>
      <span class="field-help-icon" @click.stop>
        <NIcon :component="HelpCircleOutline" :size="size ?? 13" />
      </span>
    </template>
    <span class="field-help-text">{{ tooltipText }}</span>
  </NTooltip>
</template>

<style scoped>
.field-help-icon {
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
  margin-left: 4px;
  color: var(--text-muted);
  cursor: help;
  transition: color 0.15s ease;
}
.field-help-icon:hover {
  color: var(--color-primary);
}
</style>
