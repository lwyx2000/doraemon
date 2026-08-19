<script setup lang="ts">
defineProps<{
  title?: string
  meta?: string
}>()
</script>

<template>
  <div class="data-panel">
    <div v-if="title || $slots.actions || meta" class="panel-header">
      <div class="panel-header-left">
        <h2 v-if="title" class="panel-title">{{ title }}</h2>
        <span v-if="meta" class="panel-meta">{{ meta }}</span>
      </div>
      <div v-if="$slots.actions" class="panel-actions">
        <slot name="actions" />
      </div>
    </div>
    <div class="panel-body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.data-panel { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; box-shadow: var(--shadow-card); }
.panel-header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--border-default); gap: 12px; }
.panel-header-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.panel-title { font-family: 'Work Sans', sans-serif; font-size: 15px; font-weight: 700; color: var(--text-primary); margin: 0; }
.panel-meta { font-size: 12px; color: var(--text-muted); }
.panel-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 6px 8px; min-width: 0; }
.panel-body { padding: 0; }
</style>
