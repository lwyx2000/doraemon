import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('../pages/Dashboard.vue'),
    meta: { title: '大类资产配置看板', icon: 'dashboard' },
  },
  {
    path: '/index-analysis',
    name: 'IndexAnalysis',
    component: () => import('../pages/IndexAnalysis.vue'),
    meta: { title: '指数估值分析', icon: 'analytics' },
  },
  {
    path: '/index-valuation',
    name: 'IndexValuation',
    component: () => import('../pages/IndexValuation.vue'),
    meta: { title: '宽基估值分位', icon: 'trending_up' },
  },
  {
    path: '/lof-funds',
    name: 'LofFunds',
    component: () => import('../pages/LofFunds.vue'),
    meta: { title: 'LOF基金套利扫描', icon: 'account_balance' },
  },
  {
    path: '/closed-funds',
    name: 'ClosedFunds',
    component: () => import('../pages/ClosedFunds.vue'),
    meta: { title: '封闭基金', icon: 'lock' },
  },
  {
    path: '/convertible-bonds',
    name: 'ConvertibleBonds',
    component: () => import('../pages/ConvertibleBonds.vue'),
    meta: { title: '可转债扫描', icon: 'currency_exchange' },
  },
  {
    path: '/etf-funds',
    name: 'EtfFunds',
    component: () => import('../pages/EtfFunds.vue'),
    meta: { title: 'ETF基金策略', icon: 'swap_horiz' },
  },
  {
    path: '/portfolio-watchlist',
    name: 'PortfolioWatchlist',
    component: () => import('../pages/PortfolioWatchlist.vue'),
    meta: { title: '投资组合自选', icon: 'star' },
  },
  {
    path: '/holdings',
    name: 'HoldingsAnalysis',
    component: () => import('../pages/HoldingsAnalysis.vue'),
    meta: { title: '持仓分析', icon: 'briefcase' },
  },
  {
    path: '/reits',
    name: 'Reits',
    component: () => import('../pages/Reits.vue'),
    meta: { title: '公募REITs分析', icon: 'account_balance' },
  },
  {
    path: '/alert-center',
    name: 'AlertCenter',
    component: () => import('../pages/AlertCenter.vue'),
    meta: { title: '预警中心', icon: 'notifications' },
  },
  {
    path: '/strategy-center',
    name: 'StrategyCenter',
    component: () => import('../pages/StrategyCenter.vue'),
    meta: { title: '策略管理中心', icon: 'tune' },
  },
  {
    path: '/signal-lab',
    name: 'SignalLab',
    component: () => import('../pages/SignalLab.vue'),
    meta: { title: '信号实验室', icon: 'flash' },
  },
  {
    path: '/ai-decision',
    name: 'AiDecisionHub',
    component: () => import('../pages/AiDecisionHub.vue'),
    meta: { title: 'AI决策中心', icon: 'psychology' },
  },
  {
    path: '/data-sources',
    name: 'DataSources',
    component: () => import('../pages/DataSources.vue'),
    meta: { title: '数据来源', icon: 'server' },
  },
  {
    path: '/precious-metals',
    name: 'PreciousMetals',
    component: () => import('../pages/PreciousMetals.vue'),
    meta: { title: '贵金属', icon: 'diamond' },
  },
  {
    path: '/system-settings',
    name: 'SystemSettings',
    component: () => import('../pages/SystemSettings.vue'),
    meta: { title: '系统设置', icon: 'settings' },
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../pages/Login.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../pages/Register.vue'),
    meta: { title: '注册', public: true },
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('../pages/Profile.vue'),
    meta: { title: '个人中心', icon: 'person' },
  },
  {
    path: '/admin/users',
    name: 'AdminUsers',
    component: () => import('../pages/AdminUsers.vue'),
    meta: { title: '账号管理', icon: 'people', admin: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局路由守卫：未登录访问非公开页面时跳转登录页，登录后回跳原页面
router.beforeEach((to) => {
  const { isLoggedIn, isAdmin } = useAuth()
  if (!to.meta.public && !isLoggedIn.value) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  // 已登录用户访问登录/注册页时回首页（管理员回账号管理页）
  if (to.meta.public && isLoggedIn.value && (to.path === '/login' || to.path === '/register')) {
    return { path: isAdmin.value ? '/admin/users' : '/' }
  }
  // 管理员仅允许访问账号管理页，其余一律重定向
  if (isLoggedIn.value && isAdmin.value && !(to.meta.admin || to.path === '/admin/users')) {
    return { path: '/admin/users' }
  }
  // 非管理员访问管理员页则回看板
  if (isLoggedIn.value && !isAdmin.value && to.meta.admin) {
    return { path: '/dashboard' }
  }
  return true
})

export default router
export { routes }
