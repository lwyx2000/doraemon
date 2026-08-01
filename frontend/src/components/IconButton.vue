<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  icon: Component
  size?: number
  label?: string
}>()
</script>

<template>
  <button class="icon-btn" :aria-label="label">
    <n-icon :component="icon" :size="size || 18" />
  </button>
</template>
