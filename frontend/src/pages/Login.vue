<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NCard, NForm, NFormItem, NInput, NButton, useMessage } from 'naive-ui'
import { useAuth } from '../composables/useAuth'
import AuthBackground from '../components/AuthBackground.vue'

defineOptions({ name: 'Login' })
const router = useRouter()
const route = useRoute()
const message = useMessage()
const { login, isAdmin } = useAuth()

const username = ref('')
const password = ref('')
const loading = ref(false)

async function onSubmit() {
  if (!username.value.trim() || !password.value) {
    message.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await login(username.value.trim(), password.value)
    message.success('登录成功')
    const redirect = (route.query.redirect as string) || (isAdmin.value ? '/admin/users' : '/dashboard')
    router.push(redirect)
  } catch (e: any) {
    message.error('登录失败：' + (e?.data?.detail || e?.message || '用户名或密码错误'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-wrap">
    <AuthBackground />
    <n-card class="auth-card" :bordered="false">
      <div class="auth-brand">QuantTerminal Pro</div>
      <h2 class="auth-title">登录</h2>
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
        <n-button type="primary" block size="large" :loading="loading" @click="onSubmit">登录</n-button>
      </n-form>
      <div class="auth-foot">
        还没有账号？<router-link to="/register">立即注册</router-link>
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
