import { ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationNormalized } from 'vue-router'

export interface TabItem {
  path: string
  title: string
  name: string
  closable: boolean
}

// 全局状态：打开的标签页列表和当前激活标签
const tabs = ref<TabItem[]>([])
const activePath = ref<string>('')

// 防止多个组件调用 useTabs() 时重复注册 watch
let watchRegistered = false

// 固定标签（不可关闭的首页标签）
const HOME_TAB: TabItem = {
  path: '/dashboard',
  title: '宏观看板',
  name: 'Dashboard',
  closable: false,
}

/**
 * 多标签页管理 composable。
 *
 * - 侧边栏点击菜单时调用 openTab(path)
 * - 标签栏点击切换时调用 switchTab(path)
 * - 标签栏点击关闭时调用 closeTab(path)
 * - 路由变化时自动同步
 */
export function useTabs() {
  const route = useRoute()
  const router = useRouter()

  /** 初始化首页标签 */
  function ensureHome() {
    if (!tabs.value.find(t => t.path === HOME_TAB.path)) {
      tabs.value.push({ ...HOME_TAB })
    }
  }

  /** 规范化路径：'/' → '/dashboard' */
  function normalizePath(p: string): string {
    return p === '/' ? HOME_TAB.path : p
  }

  /** 根据路由元信息构建 TabItem */
  function routeToTab(r: RouteLocationNormalized): TabItem {
    const isHome = r.path === HOME_TAB.path || r.path === '/'
    return {
      path: isHome ? HOME_TAB.path : r.path,
      title: isHome ? HOME_TAB.title : ((r.meta?.title as string) || r.name as string || r.path),
      name: isHome ? HOME_TAB.name : ((r.name as string) || ''),
      closable: !isHome,
    }
  }

  /** 打开一个新标签页（如果已存在则切换到它） */
  function openTab(path: string) {
    const normPath = normalizePath(path)
    ensureHome()
    const existing = tabs.value.find(t => t.path === normPath)
    if (existing) {
      activePath.value = normPath
    } else {
      // 从路由表中查找 meta.title
      const matched = router.getRoutes().find(r => r.path === normPath)
      const title = matched?.meta?.title as string || normPath
      const name = matched?.name as string || ''
      tabs.value.push({
        path: normPath,
        title,
        name,
        closable: normPath !== HOME_TAB.path,
      })
      activePath.value = normPath
    }
  }

  /** 切换到指定标签页 */
  function switchTab(path: string) {
    activePath.value = path
    router.push(path)
  }

  /** 关闭指定标签页 */
  function closeTab(path: string) {
    const idx = tabs.value.findIndex(t => t.path === path)
    if (idx === -1) return
    const tab = tabs.value[idx]
    if (!tab.closable) return // 首页不可关闭

    tabs.value.splice(idx, 1)

    // 如果关闭的是当前激活标签，切换到相邻标签
    if (activePath.value === path) {
      const next = tabs.value[idx] || tabs.value[idx - 1] || tabs.value[tabs.value.length - 1]
      if (next) {
        switchTab(next.path)
      }
    }
  }

  /** 关闭其他标签页（保留指定标签和首页） */
  function closeOthers(path: string) {
    tabs.value = tabs.value.filter(t => t.path === path || !t.closable)
    switchTab(path)
  }

  /** 关闭所有可关闭标签（回到首页） */
  function closeAll() {
    tabs.value = tabs.value.filter(t => !t.closable)
    switchTab(HOME_TAB.path)
  }

  /** 刷新指定标签（临时从缓存中移除再加回来触发组件重建） */
  function refreshTab(path: string) {
    const idx = tabs.value.findIndex(t => t.path === path)
    if (idx === -1) return
    // 临时将 name 置空，使 keep-alive include 不匹配 → 组件被销毁
    const originalName = tabs.value[idx].name
    tabs.value[idx].name = ''
    // 下一帧恢复 name，组件重新挂载
    setTimeout(() => {
      tabs.value[idx].name = originalName
      activePath.value = path
    }, 50)
  }

  // 监听路由变化，自动同步标签状态（只注册一次）
  if (!watchRegistered) {
    watchRegistered = true
    watch(() => route.path, (newPath) => {
      if (!newPath) return
      const normPath = normalizePath(newPath)
      ensureHome()
      // 查找是否已有该路径的 tab（用规范化路径匹配）
      const existing = tabs.value.find(t => t.path === normPath)
      if (!existing) {
        // 只有当 tabs 中完全没有这个路径时才添加
        // 但要防止重复添加：先检查再 push
        if (!tabs.value.find(t => t.path === normPath)) {
          tabs.value.push(routeToTab(route))
        }
      } else if (existing.path === HOME_TAB.path) {
        existing.closable = false
      }
      activePath.value = normPath
    }, { immediate: true })
  }

  return {
    tabs,
    activePath,
    openTab,
    switchTab,
    closeTab,
    closeOthers,
    closeAll,
    refreshTab,
  }
}
