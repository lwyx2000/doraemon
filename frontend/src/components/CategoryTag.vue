<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  type: 'undervalued' | 'normal' | 'overvalued' | 'opportunity'
  label?: string
}>()

const displayLabel = computed(() => {
  if (props.label) return props.label
  const map: Record<string, string> = {
    undervalued: '低估',
    normal: '正常',
    overvalued: '高估',
    opportunity: '机会',
  }
  return map[props.type] || props.type
})
</script>

<template>
  <span :class="['cat-tag', type]">{{ displayLabel }}</span>
</template>
