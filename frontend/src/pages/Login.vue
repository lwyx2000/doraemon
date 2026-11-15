<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NCard, NForm, NFormItem, NInput, NButton, NCheckbox, NAlert, useMessage,
} from 'naive-ui'
import { useAuth } from '../composables/useAuth'
import { bootstrapSession } from '../utils/api'
import AuthBackground from '../components/AuthBackground.vue'

defineOptions({ name: 'Login' })
const router = useRouter()
const route = useRoute()
const message = useMessage()
const { login, isAdmin, isLoggedIn } = useAuth()

const username = ref('')
const password = ref('')
const loading = ref(false)
const restoring = ref(false)

// 偏好单独持久化：退出登录会清掉登录态，但保留「是否勾选自动登录」这个选择
const AUTO_PREF_KEY = 'qt_auto_login_pref'
const pref = localStorage.getItem(AUTO_PREF_KEY)
const auto = ref<boolean>(pref === null ? true : pref === '1')
const expired = ref(route.query.expired === '1')

async function onSubmit() {
  if (!username.value.trim() || !password.value) {
    message.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    localStorage.setItem(AUTO_PREF_KEY, auto.value ? '1' : '0')
    await login(username.value.trim(), password.value, auto.value)
    message.success(auto.value ? '登录成功，已开启自动登录' : '登录成功')
    const redirect = (route.query.redirect as string) || (isAdmin.value ? '/admin/users' : '/dashboard')
    router.push(redirect)
  } catch (e: any) {
    message.error('登录失败：' + (e?.data?.detail || e?.message || '用户名或密码错误'))
  } finally {
    loading.value = false
  }
}

// 自动登录：长效凭证还在但 access token 已丢失时（如手工清了 token / 重启浏览器），
// 打开登录页即静默续期并直接进入系统，无需再输密码。
onMounted(async () => {
  if (isLoggedIn.value || localStorage.getItem('qt_auto_login') !== '1') return
  if (!localStorage.getItem('qt_refresh_token')) return
  restoring.value = true
  try {
    if (await bootstrapSession()) {
      message.success('已自动登录')
      const redirect = (route.query.redirect as string) || (isAdmin.value ? '/admin/users' : '/dashboard')
      router.push(redirect)
    }
  } finally {
    restoring.value = false
  }
})
</script>

<template>
  <div class="auth-wrap">
    <AuthBackground />
    <n-card class="auth-card" :bordered="false">
      <div class="auth-brand">QuantTerminal Pro</div>
      <h2 class="auth-title">登录</h2>
      <n-alert v-if="expired" type="warning" :bordered="false" class="auth-alert">
        登录状态已过期，请重新登录
      </n-alert>
      <n-form @submit.prevent="onSubmit">
        <n-form-item label="用户名">
          <n-input v-model:value="username" placeholder="如 trader" size="large" clearable @keyup.enter="onSubmit" />
        </n-form-item>
        <n-form-item label="密码">
          <n-input
            v-model:value="password"
            type="password"
            placeholder="请输入密码"
            size="large"
            show-password-on="click"
            @keyup.enter="onSubmit"
          />
        </n-form-item>
        <div class="auth-auto">
          <n-checkbox v-model:checked="auto" size="small">
            自动登录（本机记住 30 天）
          </n-checkbox>
          <div class="auth-auto-hint">勾选后 access token 过期会自动续期；退出登录或管理员重置密码后立即失效。</div>
        </div>
        <n-button type="primary" block size="large" :loading="loading || restoring" @click="onSubmit">登录</n-button>
      </n-form>
      <div class="auth-foot">
        还没有账号？<router-link to="/register">立即注册</router-link>
      </div>
      <div class="auth-foot">
        <router-link to="/external-api-docs">外部上传接口文档（免登录）</router-link>
      </div>
    </n-card>
  </div>
</template>

<style scoped>
.auth-wrap {
  position: relative;
  overflow: hidden;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-subtle);
  padding: 24px;
}
.auth-card {
  position: relative;
  z-index: 1;
  width: 380px;
  max-width: 92vw;
  border-radius: 12px;
  box-shadow: var(--shadow-card);
}
.auth-brand {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--text-brand);
  text-align: center;
  margin-bottom: 4px;
}
.auth-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  text-align: center;
  margin: 0 0 20px;
}
.auth-alert {
  margin-bottom: 16px;
}
.auth-auto {
  margin: -4px 0 16px;
}
.auth-auto-hint {
  margin-top: 6px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-muted);
}
.auth-foot {
  margin-top: 16px;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
}
.auth-foot a {
  color: var(--color-primary);
  font-weight: 600;
  text-decoration: none;
}
</style>
