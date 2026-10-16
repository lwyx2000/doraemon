<script setup lang="ts">
/**
 * 页面头部组件
 *
 * 新增 helpKey 属性：传入页面 key 后自动渲染说明按钮，点击弹出页面说明弹窗。
 */
import { ref, computed } from 'vue'
import { NIcon, NModal, NButton } from 'naive-ui'
import { HelpCircleOutline, BulbOutline, AnalyticsOutline, TimeOutline } from '@vicons/ionicons5'
import { pageHelpContent } from '../composables/helpContent'

const props = defineProps<{
  title: string
  subtitle?: string
  /** 页面说明 key，对应 pageHelpContent 字典 */
  helpKey?: string
  /** 数据更新时间（ISO 字符串，后端 meta.updateTime = 取数时刻） */
  updatedAt?: string | null
  /** 数据日期（如行情快照日期），优先于 updatedAt 展示 */
  dataDate?: string | null
}>()

const showModal = ref(false)

const helpData = computed(() => {
  if (!props.helpKey) return null
  return pageHelpContent[props.helpKey] ?? null
})

// 时间 chip 文案：有数据日期时以数据日期为主，附取数时间
function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const timeChipText = computed(() => {
  const updated = props.updatedAt ? fmtTime(props.updatedAt) : ''
  const dataDate = props.dataDate?.trim() || ''
  if (dataDate && updated) return `数据日期 ${dataDate} · 更新于 ${updated}`
  if (dataDate) return `数据日期 ${dataDate}`
  if (updated) return `数据更新于 ${updated}`
  return ''
})
</script>

<template>
  <div class="page-header">
    <div class="header-left">
      <h1 class="page-title">{{ title }}</h1>
      <p v-if="subtitle" class="page-subtitle">{{ subtitle }}</p>
      <p v-if="timeChipText" class="page-updated">
        <NIcon :component="TimeOutline" size="13" />
        <span>{{ timeChipText }}</span>
      </p>
    </div>
    <div class="header-actions">
      <slot name="actions" />
      <NButton
        v-if="helpData"
        size="small"
        quaternary
        @click="showModal = true"
      >
        <template #icon><NIcon :component="HelpCircleOutline" /></template>
        说明
      </NButton>
    </div>

    <!-- 页面说明弹窗 -->
    <NModal
      v-model:show="showModal"
      preset="card"
      :title="helpData?.title"
      style="max-width: 560px"
      :bordered="false"
    >
      <div v-if="helpData" class="help-modal-body">
        <!-- 页面用途 -->
        <div class="help-section">
          <div class="help-section-title">
            <NIcon :component="BulbOutline" size="16" />
            <span>页面用途</span>
          </div>
          <p class="help-section-text">{{ helpData.purpose }}</p>
        </div>

        <!-- 策略要点 -->
        <div class="help-section">
          <div class="help-section-title">
            <NIcon :component="AnalyticsOutline" size="16" />
            <span>策略要点</span>
          </div>
          <ul class="help-strategy-list">
            <li v-for="(s, i) in helpData.strategy" :key="i">{{ s }}</li>
          </ul>
        </div>

        <!-- 数据频率 -->
        <div class="help-section">
          <div class="help-section-title">
            <NIcon :component="TimeOutline" size="16" />
            <span>数据频率</span>
          </div>
          <p class="help-section-text">{{ helpData.dataFreq }}</p>
        </div>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; margin-bottom: 4px; }
.header-left { min-width: 0; }
.page-title { font-family: 'Work Sans', sans-serif; font-size: 26px; font-weight: 600; letter-spacing: -0.02em; color: var(--text-primary); margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-muted); margin: 4px 0 0; }
.page-updated {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 12px; color: var(--text-muted); margin: 6px 0 0;
  font-variant-numeric: tabular-nums;
}
.header-actions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }

.help-modal-body { display: flex; flex-direction: column; gap: 20px; padding: 4px 0; }

.help-section { display: flex; flex-direction: column; gap: 8px; }
.help-section-title {
  display: flex; align-items: center; gap: 6px;
  font-family: 'Work Sans', sans-serif; font-size: 14px; font-weight: 700;
  color: var(--text-primary);
}
.help-section-text {
  font-size: 14px; line-height: 1.6; color: var(--text-secondary); margin: 0;
}
.help-strategy-list {
  margin: 0; padding-left: 0; list-style: none;
  display: flex; flex-direction: column; gap: 6px;
}
.help-strategy-list li {
  font-size: 14px; line-height: 1.5; color: var(--text-secondary);
  padding-left: 16px; position: relative;
}
.help-strategy-list li::before {
  content: '→'; position: absolute; left: 0; color: var(--color-primary); font-weight: 700;
}
</style>
