<script setup lang="ts">
withDefaults(defineProps<{
  value: number | null
  width?: number
}>(), {
  width: 80,
})
</script>

<template>
  <div class="perc-cell">
    <template v-if="value == null">—</template>
    <template v-else>
      <div class="perc-track" :style="{ width: width + 'px' }">
        <div class="perc-needle" :style="{ left: value + '%' }" />
      </div>
      <span class="perc-label">{{ value }}%</span>
    </template>
  </div>
</template>
