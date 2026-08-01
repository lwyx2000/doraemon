<script setup lang="ts">
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import {
  StatsChartOutline,
  Analytics,
  WalletOutline,
  LockClosedOutline,
  CashOutline,
  SwapHorizontalOutline,
  Star,
  Notifications,
  OptionsOutline,
  BulbOutline,
  Wallet,
  CloseOutline,
  ServerOutline,
} from '@vicons/ionicons5'
import { useSidebar } from '../composables/useSidebar'

const route = useRoute()
const router = useRouter()
const { mobileOpen, closeMobile } = useSidebar()

interface NavItem {
  name: string
  path: string
  icon: any
  label: string
}

const navItems: NavItem[] = [
  { name: 'Dashboard', path: '/dashboard', icon: StatsChartOutline, label: '宏观看板' },
  { name: 'IndexAnalysis', path: '/index-analysis', icon: Analytics, label: '指数分析' },
  { name: 'LofFunds', path: '/lof-funds', icon: WalletOutline, label: 'LOF基金' },
  { name: 'ClosedFunds', path: '/closed-funds', icon: LockClosedOutline, label: '封闭基金' },
  { name: 'ConvertibleBonds', path: '/convertible-bonds', icon: CashOutline, label: '可转债' },
  { name: 'EtfFunds', path: '/etf-funds', icon: SwapHorizontalOutline, label: 'ETF基金' },
  { name: 'Reits', path: '/reits', icon: Wallet, label: '公募REITs' },
  { name: 'PortfolioWatchlist', path: '/portfolio-watchlist', icon: Star, label: '投资组合' },
  { name: 'StrategyCenter', path: '/strategy-center', icon: OptionsOutline, label: '策略中心' },
  { name: 'AiDecisionHub', path: '/ai-decision', icon: BulbOutline, label: 'AI决策' },
  { name: 'AlertCenter', path: '/alert-center', icon: Notifications, label: '预警中心' },
  { name: 'DataSources', path: '/data-sources', icon: ServerOutline, label: '数据来源' },
]

const isActive = (path: string) => route.path === path

function navigate(path: string) {
  router.push(path)
  closeMobile()
}

// Close mobile sidebar on route change
watch(() => route.path, () => {
  if (mobileOpen.value) closeMobile()
})

// Close mobile sidebar on Escape key
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && mobileOpen.value) closeMobile()
}
if (typeof window !== 'undefined') {
  window.addEventListener('keydown', onKeydown)
}
</script>

<template>
  <!-- Mobile backdrop -->
  <div
    v-if="mobileOpen"
    class="sidebar-backdrop"
    aria-hidden="true"
    @click="closeMobile"
  />
  <aside :class="['app-sidebar', { 'mobile-open': mobileOpen }]">
    <button class="sidebar-close" aria-label="关闭菜单" @click="closeMobile">
      <n-icon :component="CloseOutline" size="20" />
    </button>
    <div class="sidebar-brand">
      <div class="brand-icon">
        <n-icon :component="Wallet" size="20" />
      </div>
      <div class="brand-text">
        <span class="brand-name">QuantTerminal</span>
        <span class="brand-subtitle">量化投资终端</span>
      </div>
    </div>
    <nav class="sidebar-nav" aria-label="主导航">
      <a
        v-for="item in navItems"
        :key="item.path"
        :class="['nav-item', { active: isActive(item.path) }]"
        :aria-current="isActive(item.path) ? 'page' : undefined"
        :aria-label="item.label"
        tabindex="0"
        @click="navigate(item.path)"
        @keyup.enter="navigate(item.path)"
      >
        <n-icon :component="item.icon" size="20" aria-hidden="true" />
        <span class="nav-label">{{ item.label }}</span>
      </a>
    </nav>
    <div class="sidebar-footer">
      <div class="market-status">
        <span class="status-dot" />
        <span class="status-text">已连接</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar {
  position: fixed;
  left: 0;
  top: 48px;
  width: 240px;
  height: calc(100vh - 48px);
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  padding: 16px 0;
  z-index: 50;
  overflow-y: auto;
  transition: transform 0.25s ease;
}

.sidebar-close {
  display: none;
  position: absolute;
  top: 12px;
  right: 12px;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 4px;
  align-items: center;
  justify-content: center;
}
.sidebar-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.sidebar-close:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.sidebar-backdrop {
  display: none;
  position: fixed;
  inset: 48px 0 0 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 40;
  backdrop-filter: blur(2px);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px 16px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--border-default);
}

.brand-icon {
  width: 36px;
  height: 36px;
  background: var(--color-primary);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.brand-text {
  display: flex;
  flex-direction: column;
}

.brand-name {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-brand);
  line-height: 1.2;
}

.brand-subtitle {
  font-size: 10px;
  color: var(--text-muted);
}

.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
  text-decoration: none;
  font-family: 'Work Sans', sans-serif;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--bg-active);
  color: var(--color-primary);
  border-right: 2px solid var(--color-primary);
}

.nav-item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: -2px;
}

.nav-label {
  line-height: 1;
}

.sidebar-footer {
  padding: 12px 16px;
  margin-top: auto;
  border-top: 1px solid var(--border-default);
}

.market-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-hover);
  border-radius: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-success);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
}

/* Tablet: shrink sidebar */
@media (max-width: 1024px) {
  .app-sidebar {
    width: 200px;
  }
}

/* Mobile: sidebar becomes off-canvas overlay */
@media (max-width: 768px) {
  .app-sidebar {
    transform: translateX(-100%);
    box-shadow: 2px 0 12px rgba(0, 0, 0, 0.2);
    z-index: 60;
  }
  .app-sidebar.mobile-open {
    transform: translateX(0);
  }
  .sidebar-close {
    display: inline-flex;
  }
  .sidebar-backdrop {
    display: block;
  }
}
</style>
