<script setup lang="ts">
import { ref } from 'vue'
import { NModal, NCard, NForm, NFormItem, NInput, NButton, useMessage } from 'naive-ui'
import { useAuth } from '../composables/useAuth'

const { changePassword } = useAuth()
const message = useMessage()
const newPassword = ref('')
const confirmPassword = ref('')
const saving = ref(false)

async function onSubmit() {
  if (newPassword.value.length < 6) {
    message.warning('新密码至少 6 位')
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    message.warning('两次输入的新密码不一致')
    return
  }
  saving.value = true
  try {
    await changePassword(undefined, newPassword.value)
    message.success('密码已设置，请妥善保管')
    newPassword.value = ''
    confirmPassword.value = ''
    // forceChange 在 changePassword 内被清除 → 父级 v-if 自动隐藏本弹窗
  } catch (e: any) {
    message.error('设置失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <n-modal
    :show="true"
    :mask-closable="false"
    :close-on-esc="false"
    :closable="false"
    transform-origin="center"
  >
    <n-card title="请设置新密码" :bordered="false" style="width: 420px; max-width: 92vw;">
      <p class="force-tip">您的密码已被管理员重置，首次登录需设置新密码后方可继续使用。</p>
      <n-form @submit.prevent="onSubmit">
        <n-form-item label="新密码">
          <n-input
            v-model:value="newPassword"
            type="password"
            placeholder="至少 6 位"
            show-password-on="click"
            @keyup.enter="onSubmit"
          />
        </n-form-item>
        <n-form-item label="确认新密码">
          <n-input
            v-model:value="confirmPassword"
            type="password"
            placeholder="再次输入新密码"
            show-password-on="click"
            @keyup.enter="onSubmit"
          />
        </n-form-item>
        <n-button type="primary" block :loading="saving" @click="onSubmit">确认设置</n-button>
      </n-form>
    </n-card>
  </n-modal>
</template>

<style scoped>
.force-tip {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0 0 16px;
  line-height: 1.5;
}
</style>
