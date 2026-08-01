<script setup lang="ts">
import type { Component } from 'vue'

interface TabItem {
  key: string
  label: string
  icon?: Component
}

defineProps<{
  tabs: TabItem[]
  modelValue: string
}>()

defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <div class="tab-bar">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      :class="['tab-btn', { active: modelValue === tab.key }]"
      @click="$emit('update:modelValue', tab.key)"
    >
      <n-icon v-if="tab.icon" :component="tab.icon" size="16" />
      {{ tab.label }}
    </button>
  </div>
</template>
