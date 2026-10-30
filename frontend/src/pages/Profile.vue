<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NButton, NInput, NSelect, NTabs, NTabPane, NForm, NFormItem, useMessage, useDialog } from 'naive-ui'
import { useAuth } from '../composables/useAuth'
import { api } from '../utils/api'
import type { Terminal, Broker, AccountName } from '../types'
import PageHeader from '../components/PageHeader.vue'

defineOptions({ name: 'Profile' })
const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const { username, isLoggedIn, logout } = useAuth()

function onLogout() {
  logout()
  message.success('已退出登录')
}

// ---- 修改密码 ----
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const changing = ref(false)

async function onChangePassword() {
  if (!oldPassword.value) {
    message.warning('请输入旧密码')
    return
  }
  if (newPassword.value.length < 6) {
    message.warning('新密码至少 6 位')
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    message.warning('两次输入的新密码不一致')
    return
  }
  changing.value = true
  try {
    await api.changePassword(oldPassword.value, newPassword.value)
    message.success('密码修改成功')
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } catch (e: any) {
    message.error('修改失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  } finally {
    changing.value = false
  }
}

// ---- 终端与券商（一个终端可含多个券商） ----
const terminals = ref<Terminal[]>([])
const tmSaving = ref(false)

async function loadTerminals() {
  try {
    terminals.value = await api.getTerminals()
  } catch {
    terminals.value = []
  }
}

// 添加终端
const newTerminalName = ref('')
const newTerminalRemark = ref('')
async function addTerminal() {
  const name = newTerminalName.value.trim()
  if (!name) { message.warning('请输入终端名称'); return }
  if (terminals.value.some(t => t.name === name)) { message.warning('该终端名称已存在'); return }
  tmSaving.value = true
  try {
    await api.createTerminal(name, newTerminalRemark.value.trim())
    message.success('终端已添加')
    newTerminalName.value = ''
    newTerminalRemark.value = ''
    await loadTerminals()
  } catch (e: any) {
    message.error('操作失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  } finally {
    tmSaving.value = false
  }
}

// 添加券商（选择所属终端）
const newBrokerTerminalId = ref('')
const newBrokerName = ref('')
const newBrokerAccount = ref('')
const newBrokerRemark = ref('')
async function addBroker() {
  const terminalId = newBrokerTerminalId.value
  if (!terminalId) { message.warning('请选择所属终端'); return }
  if (!newBrokerName.value.trim()) { message.warning('请输入券商名称'); return }
  if (!newBrokerAccount.value.trim()) { message.warning('请输入券商账号（account）'); return }
  tmSaving.value = true
  try {
    await api.createBroker(terminalId, newBrokerName.value.trim(), newBrokerAccount.value.trim(), newBrokerRemark.value.trim())
    message.success('券商已添加')
    newBrokerName.value = ''
    newBrokerAccount.value = ''
    newBrokerRemark.value = ''
    await loadTerminals()
  } catch (e: any) {
    message.error('操作失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  } finally {
    tmSaving.value = false
  }
}

async function deleteTerminal(t: Terminal) {
  dialog.warning({
    title: '删除终端',
    content: `确定删除终端「${t.name}」？其下 ${t.brokers?.length ?? 0} 个券商将一并删除，且不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.deleteTerminal(t.id)
        message.success('终端已删除')
        await loadTerminals()
      } catch (e: any) {
        message.error('删除失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
      }
    },
  })
}

async function deleteBroker(t: Terminal, b: Broker) {
  dialog.warning({
    title: '删除券商',
    content: `确定删除券商「${b.name}（${b.account}）」？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.deleteBroker(t.id, b.id)
        message.success('券商已删除')
        await loadTerminals()
      } catch (e: any) {
        message.error('删除失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
      }
    },
  })
}

// ---- 账户名列表（独立表 biz_account_names） ----
const accountNames = ref<AccountName[]>([])

const anSaving = ref(false)

async function loadAccountNames() {
  try {
    accountNames.value = await api.getAccountNames()
  } catch {
    accountNames.value = []
  }
}

// 添加账户名
const newAccountName = ref('')
async function addAccountName() {
  if (!newAccountName.value.trim()) {
    message.warning('请输入账户名称')
    return
  }
  if (accountNames.value.some(a => a.name === newAccountName.value.trim())) {
    message.warning('该账户名已存在')
    return
  }
  anSaving.value = true
  try {
    await api.createAccountName(newAccountName.value.trim())
    message.success('账户名已添加')
    newAccountName.value = ''
    await loadAccountNames()
  } catch (e: any) {
    message.error('操作失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  } finally {
    anSaving.value = false
  }
}

// 删除账户名
async function deleteAccountName(id: string) {
  try {
    await api.deleteAccountName(id)
    message.success('已删除')
    await loadAccountNames()
  } catch (e: any) {
    message.error('删除失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  }
}

onMounted(() => {
  if (isLoggedIn.value) {
    loadTerminals()
    loadAccountNames()
  }
})
</script>

<template>
  <div class="profile-page">
    <PageHeader title="个人中心" subtitle="账户信息与快捷入口" />
    <div class="profile-grid">
      <n-card title="账户信息" class="profile-card">
        <div class="profile-row">
          <span class="profile-label">用户名</span>
          <span class="profile-value">{{ username || '未登录' }}</span>
        </div>
        <div class="profile-row">
          <span class="profile-label">登录状态</span>
          <span
            class="profile-value"
            :style="{ color: isLoggedIn ? 'var(--color-success)' : 'var(--color-danger)' }"
          >{{ isLoggedIn ? '已登录' : '未登录' }}</span>
        </div>
        <n-button v-if="isLoggedIn" type="error" secondary block @click="onLogout">退出登录</n-button>
        <n-button v-else type="primary" block @click="router.push('/login')">去登录</n-button>
      </n-card>

      <n-card v-if="isLoggedIn" title="终端、券商与账户名" class="profile-card ba-card">
        <n-tabs type="line" size="small" class="ba-tabs">
          <!-- 终端与券商 Tab -->
          <n-tab-pane name="terminals" tab="终端与券商">
            <!-- 添加终端 -->
            <div class="ba-form">
              <n-input v-model:value="newTerminalName" placeholder="终端名称（如 电脑A / 手机B）" clearable @keyup.enter="addTerminal" />
              <n-input v-model:value="newTerminalRemark" placeholder="备注（可选）" clearable @keyup.enter="addTerminal" />
              <n-button :loading="tmSaving" @click="addTerminal">添加终端</n-button>
            </div>
            <!-- 添加券商（选择所属终端） -->
            <div class="ba-form">
              <n-select
                v-model:value="newBrokerTerminalId"
                :options="terminals.map(t => ({ label: t.name, value: t.id }))"
                placeholder="选择所属终端"
                clearable
                filterable
              />
              <n-input v-model:value="newBrokerName" placeholder="券商名称（如 华泰证券）" clearable @keyup.enter="addBroker" />
              <n-input v-model:value="newBrokerAccount" placeholder="券商账号 account（必填）" clearable @keyup.enter="addBroker" />
              <n-input v-model:value="newBrokerRemark" placeholder="备注（可选）" clearable @keyup.enter="addBroker" />
              <n-button :loading="tmSaving" @click="addBroker">添加券商</n-button>
            </div>
            <div class="ba-list ba-list-scroll">
              <div v-for="t in terminals" :key="t.id" class="terminal-block">
                <div class="terminal-head">
                  <div class="terminal-title">
                    <span class="terminal-name">{{ t.name }}</span>
                    <span v-if="t.remark" class="terminal-remark">{{ t.remark }}</span>
                  </div>
                  <div class="ba-actions">
                    <n-button text size="small" type="error" @click="deleteTerminal(t)">删除终端</n-button>
                  </div>
                </div>
                <div class="broker-sublist">
                  <div v-for="b in (t.brokers || [])" :key="b.id" class="ba-item">
                    <span class="ba-name">{{ b.name }} <span class="mono ba-account">{{ b.account }}</span><span v-if="b.remark" class="ba-remark">（{{ b.remark }}）</span></span>
                    <div class="ba-actions">
                      <n-button text size="small" type="error" @click="deleteBroker(t, b)">删除</n-button>
                    </div>
                  </div>
                  <div v-if="!t.brokers || !t.brokers.length" class="ba-empty">
                    该终端下暂无券商
                  </div>
                </div>
              </div>
              <div v-if="!terminals.length" class="ba-empty">
                尚未配置终端，添加终端后即可在其下添加券商
              </div>
            </div>
          </n-tab-pane>

          <!-- 账户名 Tab（独立表） -->
          <n-tab-pane name="accountNames" tab="账户名">
            <div class="ba-form">
              <n-input v-model:value="newAccountName" placeholder="账户名（如 普通 / 两融 / 信用）" clearable @keyup.enter="addAccountName" />
              <n-button :loading="anSaving" @click="addAccountName">添加</n-button>
            </div>
            <div class="ba-list ba-list-scroll">
              <div v-for="a in accountNames" :key="a.id" class="ba-item">
                <span class="ba-name">{{ a.name }}</span>
                <div class="ba-actions">
                  <n-button text size="small" type="error" @click="deleteAccountName(a.id)">删除</n-button>
                </div>
              </div>
              <div v-if="!accountNames.length" class="ba-empty">
                尚未配置账户名，添加后可在持仓页编辑时选用
              </div>
            </div>
          </n-tab-pane>
        </n-tabs>
      </n-card>

      <n-card v-if="isLoggedIn" title="修改密码" class="profile-card">
        <n-form @submit.prevent="onChangePassword">
          <n-form-item label="旧密码">
            <n-input
              v-model:value="oldPassword"
              type="password"
              placeholder="请输入当前密码"
              show-password-on="click"
              @keyup.enter="onChangePassword"
            />
          </n-form-item>
          <n-form-item label="新密码">
            <n-input
              v-model:value="newPassword"
              type="password"
              placeholder="至少 6 位"
              show-password-on="click"
              @keyup.enter="onChangePassword"
            />
          </n-form-item>
          <n-form-item label="确认新密码">
            <n-input
              v-model:value="confirmPassword"
              type="password"
              placeholder="再次输入新密码"
              show-password-on="click"
              @keyup.enter="onChangePassword"
            />
          </n-form-item>
          <n-button type="primary" block :loading="changing" @click="onChangePassword">确认修改</n-button>
        </n-form>
      </n-card>

      <n-card title="快捷入口" class="profile-card">
        <div class="link-list">
          <router-link to="/portfolio-watchlist" class="profile-link">投资组合自选</router-link>
          <router-link to="/convertible-bonds" class="profile-link">可转债扫描</router-link>
          <router-link to="/dashboard" class="profile-link">大类资产配置看板</router-link>
          <router-link to="/ai-decision" class="profile-link">AI 决策中心</router-link>
        </div>
      </n-card>
    </div>
  </div>
</template>

<style scoped>
.profile-page { display: flex; flex-direction: column; gap: 14px; padding: 4px; }
.profile-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.profile-card { border-radius: 10px; }
.profile-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border-default); }
.profile-row:last-of-type { border-bottom: none; }
.profile-label { font-size: 13px; color: var(--text-muted); font-weight: 600; }
.profile-value { font-size: 14px; color: var(--text-primary); font-weight: 600; font-family: 'JetBrains Mono', monospace; }
.profile-row + .n-button { margin-top: 12px; }
.link-list { display: flex; flex-direction: column; gap: 10px; }
.profile-link {
  display: block;
  padding: 10px 14px;
  border-radius: 6px;
  background: var(--bg-subtle);
  color: var(--text-primary);
  text-decoration: none;
  font-weight: 600;
  font-size: 13px;
  transition: all 0.15s;
}
.profile-link:hover { background: var(--bg-hover); color: var(--color-primary); }

/* 券商与账户名卡片 */
.ba-card { overflow: hidden; }
.ba-tabs { height: 100%; }
.ba-tabs .n-tab-pane {
  padding: 8px 0 0 0;
}

.ba-form {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.ba-form .n-input { flex: 1; }

/* 列表区域：固定高度 + 滚动条 */
.ba-list-scroll {
  max-height: 200px;
  overflow-y: auto;
}
.ba-list { display: flex; flex-direction: column; gap: 6px; }
.ba-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--bg-subtle);
}
.ba-name { font-weight: 600; font-size: 13px; color: var(--text-primary); flex: 1; }
.ba-actions { margin-left: auto; display: flex; gap: 4px; flex-shrink: 0; }
.ba-empty { padding: 12px; text-align: center; font-size: 12px; color: var(--text-muted); background: var(--bg-subtle); border-radius: 6px; }
.ba-account { font-size: 11px; color: var(--color-primary); margin-left: 4px; }
.ba-remark { font-size: 12px; color: var(--text-muted); }

/* 终端二级结构 */
.terminal-block { border: 1px solid var(--border-default); border-radius: 8px; padding: 8px 10px; background: var(--bg-subtle); display: flex; flex-direction: column; gap: 6px; }
.terminal-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.terminal-title { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.terminal-name { font-weight: 700; font-size: 14px; color: var(--text-primary); }
.terminal-remark { font-size: 12px; color: var(--text-muted); }
.broker-sublist { display: flex; flex-direction: column; gap: 6px; padding-left: 10px; border-left: 2px solid var(--border-default); }


/* 滚动条样式 */
.ba-list-scroll::-webkit-scrollbar { width: 5px; }
.ba-list-scroll::-webkit-scrollbar-track { background: transparent; }
.ba-list-scroll::-webkit-scrollbar-thumb { background: var(--border-default); border-radius: 3px; }
.ba-list-scroll::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

@media (max-width: 768px) { .profile-grid { grid-template-columns: 1fr; } }
</style>
