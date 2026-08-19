// 认证状态管理（模块级单例）
import { ref, computed } from 'vue'
import { api } from '../utils/api'

const TOKEN_KEY = 'qt_token'
const USER_KEY = 'qt_user'

const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '')
const username = ref<string>(localStorage.getItem(USER_KEY) || '')

const isLoggedIn = computed(() => !!token.value)
const userInitial = computed(() => (username.value ? username.value[0].toUpperCase() : '?'))

function setAuth(t: string, u: string) {
  token.value = t
  username.value = u
  localStorage.setItem(TOKEN_KEY, t)
  localStorage.setItem(USER_KEY, u)
}

function logout() {
  token.value = ''
  username.value = ''
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

async function login(uname: string, pwd: string) {
  const res = await api.login(uname, pwd)
  setAuth(res.token, res.username)
}

async function register(uname: string, pwd: string) {
  const res = await api.register(uname, pwd)
  setAuth(res.token, res.username)
}

export function useAuth() {
  return { token, username, isLoggedIn, userInitial, login, register, logout, setAuth }
}
