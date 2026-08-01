import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

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
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
export { routes }
