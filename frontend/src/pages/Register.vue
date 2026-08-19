<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NForm, NFormItem, NInput, NButton, useMessage } from 'naive-ui'
import { useAuth } from '../composables/useAuth'
import AuthBackground from '../components/AuthBackground.vue'

defineOptions({ name: 'Register' })
const router = useRouter()
const message = useMessage()
const { register } = useAuth()

const username = ref('')
const password = ref('')
const confirm = ref('')
const loading = ref(false)

async function onSubmit() {
  if (!username.value.trim() && !username.value) {
    message.warning('请输入用户名')
    return
  }
  if (username.value.trim().length < 3) {
    message.warning('用户名至少 3 个字符')
    return
  }
  if (password.value.length < 6) {
    message.warning('密码至少 6 位')
    return
  }
  if (password.value !== confirm.value) {
    message.warning('两次输入的密码不一致')
    return
  }
  loading.value = true
  try {
    await register(username.value.trim(), password.value)
    message.success('注册成功，已自动登录')
    router.push('/dashboard')
  } catch (e: any) {
    message.error('注册失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
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
      <h2 class="auth-title">注册账号</h2>
      <n-form @submit.prevent="onSubmit">
        <n-form-item label="用户名">
          <n-input v-model:value="username" placeholder="至少 3 个字符" size="large" clearable @keyup.enter="onSubmit" />
        </n-form-item>
        <n-form-item label="密码">
          <n-input
            v-model:value="password"
            type="password"
            placeholder="至少 6 位"
            size="large"
            show-password-on="click"
            @keyup.enter="onSubmit"
          />
        </n-form-item>
        <n-form-item label="确认密码">
          <n-input
            v-model:value="confirm"
            type="password"
            placeholder="再次输入密码"
            size="large"
            show-password-on="click"
            @keyup.enter="onSubmit"
          />
        </n-form-item>
        <n-button type="primary" block size="large" :loading="loading" @click="onSubmit">注册</n-button>
      </n-form>
      <div class="auth-foot">
        已有账号？<router-link to="/login">返回登录</router-link>
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
