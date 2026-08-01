<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NInput, NButton, NIcon, NBadge, NAvatar, useMessage } from 'naive-ui'
import {
  Search,
  TimeOutline,
  SyncOutline,
  NotificationsOutline,
  SettingsOutline,
  SunnyOutline,
  MoonOutline,
  MenuOutline,
} from '@vicons/ionicons5'
import { useDarkMode } from '../composables/useDarkMode'
import { useSidebar } from '../composables/useSidebar'

const router = useRouter()
const message = useMessage()
const searchQuery = ref('')
const refreshing = ref(false)
const { isDark, toggle: toggleDarkMode } = useDarkMode()
const { toggleMobile } = useSidebar()

function handleSearch() {
  if (searchQuery.value.trim()) {
    message.info(`搜索: ${searchQuery.value}`)
  }
}

function refreshAll() {
  refreshing.value = true
  message.loading('正在刷新全站数据...', { duration: 1500 })
  setTimeout(() => {
    refreshing.value = false
    message.success('全站数据已刷新')
  }, 1500)
}
</script>

<template>
  <header class="app-header">
    <div class="header-left">
      <n-button text class="menu-toggle" aria-label="打开菜单" @click="toggleMobile">
        <n-icon :component="MenuOutline" size="22" />
      </n-button>
      <span class="brand-title">QuantTerminal Pro</span>
      <div class="search-box">
        <n-input
          v-model:value="searchQuery"
          placeholder="搜索标的、指数或分析模块..."
          :bordered="false"
          size="small"
          clearable
          @keyup.enter="handleSearch"
        >
          <template #prefix>
            <n-icon :component="Search" size="18" class="search-icon" />
          </template>
        </n-input>
      </div>
    </div>
    <div class="header-right">
      <n-button text class="header-btn" @click="router.push('/strategy-center')" aria-label="定时任务">
        <n-icon :component="TimeOutline" size="20" />
      </n-button>
      <n-button text class="header-btn" :loading="refreshing" @click="refreshAll" aria-label="刷新数据">
        <n-icon :component="SyncOutline" size="20" />
      </n-button>
      <n-badge :value="3" :max="99" dot>
        <n-button text class="header-btn" @click="router.push('/alert-center')" aria-label="预警中心">
          <n-icon :component="NotificationsOutline" size="20" />
        </n-button>
      </n-badge>
      <n-button text class="header-btn" @click="message.info('系统设置 (开发中)')" aria-label="系统设置">
        <n-icon :component="SettingsOutline" size="20" />
      </n-button>
      <n-button text class="header-btn" @click="toggleDarkMode" :aria-label="isDark ? '切换到浅色模式' : '切换到深色模式'">
        <n-icon :component="isDark ? SunnyOutline : MoonOutline" size="20" />
      </n-button>
      <div class="header-divider" />
      <n-avatar round size="small" style="background: #2178c3; color: white; font-weight: 700; font-size: 12px;">
        JD
      </n-avatar>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 48px;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  background: var(--bg-header);
  border-bottom: 1px solid var(--border-default);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 24px;
}

/* Hamburger toggle — hidden on desktop, visible on mobile */
.menu-toggle {
  display: none;
  color: var(--text-secondary);
  padding: 4px;
  border-radius: 4px;
}

.menu-toggle:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.brand-title {
  font-family: 'Work Sans', sans-serif;
  font-size: 18px;
  font-weight: 700;
  line-height: 24px;
  color: var(--text-brand);
  letter-spacing: -0.02em;
}

.search-box {
  width: 320px;
}

.search-box :deep(.n-input) {
  background: var(--bg-hover);
  border-radius: 4px;
  border: 1px solid var(--border-default);
  height: 32px;
}

.search-box :deep(.n-input .n-input__input-el) {
  font-size: 13px;
}

.search-icon {
  color: var(--text-muted);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.header-btn {
  color: var(--text-secondary);
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s;
}

.header-btn:hover {
  color: var(--color-primary);
  background: var(--bg-hover);
}

.header-divider {
  width: 1px;
  height: 24px;
  background: var(--border-default);
  margin: 0 8px;
}

/* Tablet: shrink search box */
@media (max-width: 1024px) {
  .search-box {
    width: 220px;
  }
  .header-left {
    gap: 16px;
  }
}

/* Mobile: show hamburger, hide search box + secondary buttons */
@media (max-width: 768px) {
  .menu-toggle {
    display: inline-flex;
  }
  .search-box {
    display: none;
  }
  .brand-title {
    font-size: 15px;
  }
  .header-right .header-btn:not(:last-of-type) {
    display: none;
  }
  .header-divider {
    display: none;
  }
}
</style>
