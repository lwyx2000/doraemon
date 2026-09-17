<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import {
  NCard,
  NDataTable,
  NButton,
  NInput,
  NModal,
  NTag,
  NSpace,
  useMessage,
} from 'naive-ui'
import { api } from '../utils/api'
import type { AdminUserItem } from '../types'
import PageHeader from '../components/PageHeader.vue'

defineOptions({ name: 'AdminUsers' })
const message = useMessage()
const users = ref<AdminUserItem[]>([])
const loading = ref(false)

async function loadUsers() {
  loading.value = true
  try {
    const res = await api.adminListUsers()
    users.value = res.users
  } catch (e: any) {
    message.error('获取用户列表失败：' + (e?.data?.detail || e?.message || ''))
  } finally {
    loading.value = false
  }
}

// ---- 重置密码 ----
const showResetModal = ref(false)
const resetTarget = ref('')
const resetPassword = ref('')
const resetResult = ref<string | null>(null)
const resetting = ref(false)

function openReset(username: string) {
  resetTarget.value = username
  resetPassword.value = ''
  resetResult.value = null
  showResetModal.value = true
}

async function confirmReset() {
  resetting.value = true
  try {
    const res = await api.adminResetPassword(resetTarget.value, resetPassword.value || undefined)
    resetResult.value = res.new_password
    message.success(`已重置 ${res.username} 的密码`)
    await loadUsers()
  } catch (e: any) {
    message.error('重置失败：' + (e?.data?.detail || e?.message || ''))
  } finally {
    resetting.value = false
  }
}

function closeReset() {
  showResetModal.value = false
  resetResult.value = null
}

function copyPassword() {
  if (resetResult.value) {
    navigator.clipboard?.writeText(resetResult.value)
    message.success('已复制临时密码')
  }
}

const columns = [
  { title: '用户名', key: 'username', width: 160 },
  {
    title: '角色',
    key: 'is_admin',
    width: 110,
    render: (row: AdminUserItem) =>
      row.is_admin
        ? h(NTag, { type: 'warning', size: 'small', bordered: false }, { default: () => '管理员' })
        : h(NTag, { type: 'default', size: 'small', bordered: false }, { default: () => '普通用户' }),
  },
  {
    title: '状态',
    key: 'must_change_password',
    width: 120,
    render: (row: AdminUserItem) =>
      row.must_change_password
        ? h(NTag, { type: 'error', size: 'small', bordered: false }, { default: () => '需改密' })
        : h(NTag, { type: 'success', size: 'small', bordered: false }, { default: () => '正常' }),
  },
  {
    title: '操作',
    key: 'actions',
    render: (row: AdminUserItem) =>
      h(
        NButton,
        { size: 'small', type: 'primary', secondary: true, onClick: () => openReset(row.username) },
        { default: () => '重置密码' },
      ),
  },
]

onMounted(loadUsers)
</script>

<template>
  <div class="admin-users-page">
    <PageHeader title="账号管理" subtitle="管理员：重置用户密码、查看账号状态（仅管理员可用）" />
    <n-card :bordered="false" class="admin-card">
      <n-data-table
        :columns="columns"
        :data="users"
        :loading="loading"
        :row-key="(row: AdminUserItem) => row.pk_user"
        :pagination="{ pageSize: 20 }"
        size="small"
      />
    </n-card>

    <n-modal
      v-model:show="showResetModal"
      preset="card"
      :title="`重置密码 — ${resetTarget}`"
      style="width: 440px; max-width: 92vw;"
      :mask-closable="false"
    >
      <div v-if="resetResult === null">
        <p class="reset-tip">重置后该用户需在下一次登录时修改密码，且其旧登录态会立即失效。</p>
        <n-input
          v-model:value="resetPassword"
          type="password"
          show-password-on="click"
          placeholder="留空则自动生成高强度临时密码"
        />
        <n-space justify="end" style="margin-top: 16px;">
          <n-button @click="closeReset">取消</n-button>
          <n-button type="primary" :loading="resetting" @click="confirmReset">确认重置</n-button>
        </n-space>
      </div>
      <div v-else>
        <n-space vertical :size="12">
          <p class="reset-tip">密码已重置成功，请将以下临时密码转交用户：</p>
          <n-input :value="resetResult" readonly />
          <n-space justify="end">
            <n-button @click="copyPassword">复制</n-button>
            <n-button type="primary" @click="closeReset">关闭</n-button>
          </n-space>
        </n-space>
      </div>
    </n-modal>
  </div>
</template>

<style scoped>
.admin-users-page { display: flex; flex-direction: column; gap: 14px; }
.admin-card { border-radius: 10px; }
.reset-tip { font-size: 13px; color: var(--text-muted); margin: 0 0 8px; }
</style>
