<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import AppHeader from './AppHeader.vue'
import AppSidebar from './AppSidebar.vue'
import TabNav from '../components/TabNav.vue'
import { useDarkMode } from '../composables/useDarkMode'
import { useTabs } from '../composables/useTabs'

const { isDark } = useDarkMode()
const { tabs } = useTabs()
const route = useRoute()

// 登录/注册页全屏展示，不套用头部/侧栏/主内容布局
const isAuthPage = computed(() => route.meta.public === true)

// keep-alive 的 include 列表：按路由 name 缓存
const cachedViews = computed(() =>
  tabs.value.map(t => t.name).filter(Boolean)
)

const lightOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#005ea1',
    primaryColorHover: '#2178c3',
    primaryColorPressed: '#004880',
    primaryColorSuppl: '#005ea1',
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
    textColorText: '#005ea1',
    textColorTextHover: '#2178c3',
    textColorTextPressed: '#004880',
    textColorTextFocus: '#2178c3',
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
    textColorText: '#4a9eda',
    textColorTextHover: '#6ab0ec',
    textColorTextPressed: '#3a8eca',
    textColorTextFocus: '#6ab0ec',
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
        <div v-if="isAuthPage" class="auth-layout">
          <router-view />
        </div>
        <div v-else class="app-layout">
          <AppHeader />
          <AppSidebar />
          <main class="app-main">
            <TabNav />
            <div class="app-content">
              <router-view v-slot="{ Component }">
                <keep-alive :include="cachedViews">
                  <component :is="Component" />
                </keep-alive>
              </router-view>
            </div>
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

/* 登录/注册页：全屏无布局干扰 */
.auth-layout {
  min-height: 100vh;
  background: var(--bg-page);
}

.app-main {
  margin-left: 240px;
  margin-top: 52px;
  height: calc(100vh - 52px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.app-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

/* Tablet: narrower sidebar → narrower main margin */
@media (max-width: 1024px) {
  .app-main {
    margin-left: 200px;
  }
  .app-content {
    padding: 16px;
  }
}

/* Mobile: sidebar hidden → main takes full width */
@media (max-width: 768px) {
  .app-main {
    margin-left: 0;
  }
  .app-content {
    padding: 12px;
  }
}
</style>
