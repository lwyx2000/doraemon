<script setup lang="ts">
withDefaults(defineProps<{
  value: number
  width?: number
}>(), {
  width: 80,
})
</script>

<template>
  <div class="perc-cell">
    <div class="perc-track" :style="{ width: width + 'px' }">
      <div class="perc-needle" :style="{ left: value + '%' }" />
    </div>
    <span class="perc-label">{{ value }}%</span>
  </div>
</template>
