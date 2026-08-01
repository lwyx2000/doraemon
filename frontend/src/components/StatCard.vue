<script setup lang="ts">
/**
 * 统计卡片组件
 *
 * 新增 tip 属性：传入说明文本后，在标签旁显示"?"图标提示。
 */
import { NIcon, NTooltip } from 'naive-ui'
import { HelpCircleOutline } from '@vicons/ionicons5'

withDefaults(defineProps<{
  label: string
  value: string | number
  sub?: string
  color?: string
  /** 字段说明文本，显示在标签旁的提示图标中 */
  tip?: string
}>(), {
  color: '#181c21',
})
</script>

<template>
  <div class="stat-card">
    <div class="stat-label-row">
      <span class="stat-label">{{ label }}</span>
      <NTooltip v-if="tip" trigger="hover" placement="top" :style="{ maxWidth: '320px' }">
        <template #trigger>
          <span class="stat-tip-icon" @click.stop>
            <NIcon :component="HelpCircleOutline" size="12" />
          </span>
        </template>
        <span>{{ tip }}</span>
      </NTooltip>
    </div>
    <span class="stat-value" :style="{ color }">{{ value }}</span>
    <span v-if="sub" class="stat-sub">{{ sub }}</span>
    <slot />
  </div>
</template>

<style scoped>
.stat-card { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px; padding: 16px; display: flex; flex-direction: column; gap: 4px; }
.stat-label-row { display: flex; align-items: center; gap: 3px; }
.stat-label { font-family: 'Work Sans', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); }
.stat-tip-icon { display: inline-flex; align-items: center; color: var(--text-muted); cursor: help; transition: color 0.15s ease; }
.stat-tip-icon:hover { color: var(--color-primary); }
.stat-value { font-family: 'JetBrains Mono', monospace; font-size: 28px; font-weight: 600; line-height: 1.2; }
.stat-sub { font-size: 12px; color: var(--text-muted); }
</style>
