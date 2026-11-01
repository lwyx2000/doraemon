<script setup lang="ts">
import { computed } from 'vue'
import { pctColor } from '../utils/percentile'

const props = withDefaults(defineProps<{
  /** 分位值（0–100）。null → 显示「—」 */
  value: number | null
  /** 可选：底层绝对值（如 PB 8.11），显示在左侧；不传则只显示分位 */
  metric?: number | null
  /** metric 小数位（默认 2） */
  metricDigits?: number
  /** 进度条宽度（px）；不传则撑满父容器 */
  width?: number
}>(), {
  metric: null,
  metricDigits: 2,
  width: undefined,
})

// 分位越高色温越高 → 红；越低 → 蓝；null → 灰（与全局标准一致）
const color = computed(() => (props.value == null ? '#8b919e' : pctColor(props.value)))

// 进度条填充宽度（钳制到 0–100，防异常值撑破容器）
const fillWidth = computed(() => {
  if (props.value == null || Number.isNaN(props.value)) return 0
  return Math.max(0, Math.min(100, props.value))
})
</script>

<template>
  <div
    class="perc-cell"
    :style="width != null ? { width: width + 'px' } : { width: '100%' }"
  >
    <template v-if="value == null">
      <span class="perc-dash">—</span>
    </template>
    <template v-else>
      <div class="perc-row">
        <span v-if="metric != null" class="perc-metric">{{ metric.toFixed(metricDigits) }}</span>
        <span class="perc-pct" :style="{ color }">{{ value.toFixed(1) }}%</span>
      </div>
      <div class="perc-track">
        <div class="perc-fill" :style="{ width: fillWidth + '%', background: color }" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.perc-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.perc-dash {
  font-size: 14px;
  color: var(--text-muted);
  text-align: center;
}

.perc-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.perc-metric {
  font-family: 'JetBrains Mono', monospace;
  font-size: 15px;
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1;
}

.perc-pct {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.perc-track {
  width: 100%;
  height: 7px;
  background: var(--bg-hover);
  border-radius: 3px;
  overflow: hidden;
}

.perc-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}
</style>
