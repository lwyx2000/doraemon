<script setup lang="ts">
import { computed, type PropType } from 'vue'
import { VChart } from '../utils/echarts'
import { useDarkMode } from '../composables/useDarkMode'

type EChartsOption = Record<string, any>

const props = defineProps({
  option: {
    type: Object as PropType<EChartsOption>,
    required: true,
  },
  /** Chart height in px (default 240). */
  height: {
    type: Number,
    default: 240,
  },
  /** Auto-resize on window resize (default true). */
  autoresize: {
    type: Boolean,
    default: true,
  },
})

const { isDark } = useDarkMode()

// Inject theme-aware text color into every option
const mergedOption = computed<EChartsOption>(() => {
  const textColor = isDark.value ? '#b4bac4' : '#414751'
  const mutedColor = isDark.value ? '#8b919e' : '#717782'
  const borderColor = isDark.value ? '#2a3140' : '#e2e8f0'
  return {
    textStyle: { color: textColor, fontFamily: 'Work Sans, sans-serif' },
    ...props.option,
    // Deep-merge common tooltip/legend defaults without overriding user values
    tooltip: {
      textStyle: { color: textColor },
      backgroundColor: isDark.value ? '#1a1f26' : '#ffffff',
      borderColor,
      borderWidth: 1,
      ...(props.option.tooltip || {}),
    },
    legend: {
      textStyle: { color: mutedColor },
      ...(props.option.legend || {}),
    },
  }
})

const chartHeight = computed(() => `${props.height}px`)
</script>

<template>
  <div class="base-chart" :style="{ height: chartHeight }">
    <v-chart
      :option="mergedOption"
      :autoresize="autoresize"
      :loading="false"
      class="chart-canvas"
    />
  </div>
</template>

<style scoped>
.base-chart {
  width: 100%;
  position: relative;
}

.chart-canvas {
  width: 100%;
  height: 100%;
}
</style>
