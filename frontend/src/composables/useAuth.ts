// 认证状态管理（模块级单例）
import { ref, computed } from 'vue'
import { api, resetSessionExpiredFlag } from '../utils/api'

const TOKEN_KEY = 'qt_token'
const USER_KEY = 'qt_user'
const IS_ADMIN_KEY = 'qt_is_admin'
const FORCE_CHANGE_KEY = 'qt_force_change'

const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '')
const username = ref<string>(localStorage.getItem(USER_KEY) || '')
const isAdmin = ref<boolean>(localStorage.getItem(IS_ADMIN_KEY) === '1')
const forceChange = ref<boolean>(localStorage.getItem(FORCE_CHANGE_KEY) === '1')

const isLoggedIn = computed(() => !!token.value)
const userInitial = computed(() => (username.value ? username.value[0].toUpperCase() : '?'))

function setAuth(
  t: string,
  u: string,
  authInfo?: { is_admin?: boolean; force_change?: boolean },
) {
  const isAdminVal = authInfo?.is_admin ?? false
  const forceChangeVal = authInfo?.force_change ?? false
  token.value = t
  username.value = u
  isAdmin.value = isAdminVal
  forceChange.value = forceChangeVal
  localStorage.setItem(TOKEN_KEY, t)
  localStorage.setItem(USER_KEY, u)
  localStorage.setItem(IS_ADMIN_KEY, isAdminVal ? '1' : '0')
  localStorage.setItem(FORCE_CHANGE_KEY, forceChangeVal ? '1' : '0')
  // 新会话建立：重置 api.ts 的 401 一次性开关，保证本次会话再次过期仍能跳登录页
  // （否则 Login.vue 软导航后开关保持置位，第二次过期只会裸显错误条）
  resetSessionExpiredFlag()
}

function logout() {
  token.value = ''
  username.value = ''
  isAdmin.value = false
  forceChange.value = false
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(IS_ADMIN_KEY)
  localStorage.removeItem(FORCE_CHANGE_KEY)
  // 收口跳转：清空本地状态后直接跳登录页（避免各调用点遗漏 / SPA 守卫边缘情况）。
  // 用整页导航而非 router.push，规避 useAuth 与 router 的循环依赖；
  // 未登录访问非 public 路由时守卫也会兜底 302 到 /login。
  window.location.href = '/login'
}

async function login(uname: string, pwd: string) {
  const res = await api.login(uname, pwd)
  setAuth(res.token, res.username, { is_admin: res.is_admin, force_change: res.force_change })
}

async function register(uname: string, pwd: string) {
  const res = await api.register(uname, pwd)
  setAuth(res.token, res.username, { is_admin: res.is_admin, force_change: res.force_change })
}

// 改密封装：被管理员强制改密的用户可不传 oldPassword；成功后清除本地 forceChange 标记
async function changePassword(oldPassword: string | undefined, newPassword: string) {
  const res = await api.changePassword(oldPassword, newPassword)
  forceChange.value = false
  localStorage.setItem(FORCE_CHANGE_KEY, '0')
  return res
}

export function useAuth() {
  return {
    token,
    username,
    isAdmin,
    forceChange,
    isLoggedIn,
    userInitial,
    login,
    register,
    logout,
    setAuth,
    changePassword,
  }
}
