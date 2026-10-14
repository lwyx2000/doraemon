<script setup lang="ts">
import { computed } from 'vue'
import { pctColor } from '../utils/percentile'

const props = withDefaults(defineProps<{
  value: number | null
  width?: number
}>(), {
  width: 80,
})

// 分位越高色温越高 → 红；越低 → 蓝；null → 灰（与全局标准一致）
const needleColor = computed(() => (props.value == null ? '#c1c6d7' : pctColor(props.value)))
</script>

<template>
  <div class="perc-cell">
    <template v-if="value == null">—</template>
    <template v-else>
      <div class="perc-track" :style="{ width: width + 'px' }">
        <div class="perc-needle" :style="{ left: value + '%', background: needleColor }" />
      </div>
      <span class="perc-label" :style="{ color: needleColor }">{{ value }}%</span>
    </template>
  </div>
</template>
