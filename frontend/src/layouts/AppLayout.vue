<script setup lang="ts">
import { computed } from 'vue'
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import AppHeader from './AppHeader.vue'
import AppSidebar from './AppSidebar.vue'
import { useDarkMode } from '../composables/useDarkMode'

const { isDark } = useDarkMode()

const lightOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#005ea1',
    primaryColorHover: '#2178c3',
    primaryColorPressed: '#004880',
    primaryColorSuppl: '#005ea1',
    primaryColorOpacity1: 'rgba(0, 94, 161, 0.1)',
    primaryColorOpacity2: 'rgba(0, 94, 161, 0.2)',
    primaryColorOpacity3: 'rgba(0, 94, 161, 0.3)',
    primaryColorOpacity4: 'rgba(0, 94, 161, 0.4)',
    primaryColorOpacity5: 'rgba(0, 94, 161, 0.5)',
    infoColor: '#005ea1',
    successColor: '#16a34a',
    warningColor: '#f97316',
    errorColor: '#ba1a1a',
  },
  Button: {
    color: '#005ea1',
    colorHover: '#2178c3',
    colorPressed: '#004880',
    colorFocus: '#2178c3',
    textColor: '#ffffff',
    textColorHover: '#ffffff',
    textColorPressed: '#ffffff',
    textColorFocus: '#ffffff',
  },
  Select: {
    peers: {
      InternalSelection: {
        border: '1px solid #e2e8f0',
        borderHover: '1px solid #005ea1',
        borderFocus: '1px solid #005ea1',
        boxShadowFocus: '0 0 0 2px rgba(0, 94, 161, 0.1)',
        placeholderColor: '#c1c6d7',
        color: '#ffffff',
      },
    },
  },
  Input: {
    border: '1px solid #e2e8f0',
    borderHover: '1px solid #005ea1',
    borderFocus: '1px solid #005ea1',
    boxShadowFocus: '0 0 0 2px rgba(0, 94, 161, 0.1)',
    placeholderColor: '#c1c6d7',
    color: '#ffffff',
    textColor: '#181c21',
  },
  Switch: {
    railColorActive: '#005ea1',
  },
  Message: {
    color: '#1a1a1a',
    textColor: '#ffffff',
  },
}

const darkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#4a9eda',
    primaryColorHover: '#6ab0ec',
    primaryColorPressed: '#3a8eca',
    primaryColorSuppl: '#4a9eda',
    primaryColorOpacity1: 'rgba(74, 158, 218, 0.1)',
    primaryColorOpacity2: 'rgba(74, 158, 218, 0.2)',
    primaryColorOpacity3: 'rgba(74, 158, 218, 0.3)',
    primaryColorOpacity4: 'rgba(74, 158, 218, 0.4)',
    primaryColorOpacity5: 'rgba(74, 158, 218, 0.5)',
    infoColor: '#4a9eda',
    successColor: '#4ade80',
    warningColor: '#fb923c',
    errorColor: '#f87171',
    bodyColor: '#0f1419',
    cardColor: '#1a1f26',
    modalColor: '#1a1f26',
    popoverColor: '#1a1f26',
    borderColor: '#2a3140',
    inputColor: '#1a1f26',
    tableColor: '#1a1f26',
    tableHeaderColor: '#1f2530',
  },
  Button: {
    color: '#4a9eda',
    colorHover: '#6ab0ec',
    colorPressed: '#3a8eca',
    colorFocus: '#6ab0ec',
    textColor: '#ffffff',
    textColorHover: '#ffffff',
    textColorPressed: '#ffffff',
    textColorFocus: '#ffffff',
  },
  Select: {
    peers: {
      InternalSelection: {
        border: '1px solid #2a3140',
        borderHover: '1px solid #4a9eda',
        borderFocus: '1px solid #4a9eda',
        boxShadowFocus: '0 0 0 2px rgba(74, 158, 218, 0.15)',
        placeholderColor: '#5a6070',
        color: '#1a1f26',
      },
    },
  },
  Input: {
    border: '1px solid #2a3140',
    borderHover: '1px solid #4a9eda',
    borderFocus: '1px solid #4a9eda',
    boxShadowFocus: '0 0 0 2px rgba(74, 158, 218, 0.15)',
    placeholderColor: '#5a6070',
    color: '#1a1f26',
    textColor: '#e4e7ec',
  },
  Switch: {
    railColorActive: '#4a9eda',
  },
  DataTable: {
    thColor: '#1f2530',
    thColorHover: '#252b35',
    tdColor: '#1a1f26',
    tdColorHover: '#252b35',
    borderColor: '#2a3140',
  },
}

const themeOverrides = computed(() => (isDark.value ? darkOverrides : lightOverrides))
const theme = computed(() => (isDark.value ? darkTheme : null))
</script>

<template>
  <n-config-provider :theme="theme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <div class="app-layout">
          <AppHeader />
          <AppSidebar />
          <main class="app-main">
            <router-view />
          </main>
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style scoped>
.app-layout {
  min-height: 100vh;
  background: var(--bg-page);
}

.app-main {
  margin-left: 240px;
  margin-top: 48px;
  padding: 16px;
  height: calc(100vh - 48px);
  overflow-y: auto;
}

/* Tablet: narrower sidebar → narrower main margin */
@media (max-width: 1024px) {
  .app-main {
    margin-left: 200px;
    padding: 12px;
  }
}

/* Mobile: sidebar hidden → main takes full width */
@media (max-width: 768px) {
  .app-main {
    margin-left: 0;
    padding: 10px;
  }
}
</style>
