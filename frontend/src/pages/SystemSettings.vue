<script setup lang="ts">
defineOptions({ name: 'SystemSettings' })
import { ref, reactive, computed, onMounted, watch } from 'vue'
import {
  NIcon, NButton, NInput, NInputNumber, NSelect, NSwitch, NSlider,
  NTag, useMessage,
} from 'naive-ui'
import {
  ServerOutline,
  CloudDownloadOutline,
  HardwareChipOutline,
  PulseOutline,
  MoonOutline,
  SunnyOutline,
  InformationCircleOutline,
  CheckmarkCircleOutline,
  CloseCircleOutline,
  SaveOutline,
  RefreshOutline,
  EyeOutline,
  EyeOffOutline,
  SpeedometerOutline,
  NotificationsOutline,
  SendOutline,
} from '@vicons/ionicons5'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import StatCard from '../components/StatCard.vue'
import LoadingState from '../components/LoadingState.vue'
import { api } from '../utils/api'
import { useDarkMode } from '../composables/useDarkMode'
import type { AiConfig, DataSourceStatus, CacheConfig, MonitorDashboard, NotificationConfig } from '../types'

const message = useMessage()
// 展示用：默认与 api.ts 保持一致，走当前页面同源（nginx 反代 /api），不写死 localhost:8001
const apiBase = import.meta.env.VITE_API_BASE || (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8001')
const deployMode = import.meta.env.MODE
const { isDark, toggle: toggleDarkMode } = useDarkMode()

// ============================================================
// 加载状态
// ============================================================
const loading = ref(true)

// ============================================================
// AI 模型配置
// ============================================================
const aiConfig = reactive<AiConfig>({
  provider: 'openai',
  apiKey: '',
  endpoint: '',
  temperature: 0.7,
  cronExpression: '0 8 * * 1-5',
  enabled: false,
  model: '',
})
const aiConfigLoading = ref(false)
const showApiKey = ref(false)
const aiConfigChanged = ref(false)

const providerOptions = [
  { label: 'OpenAI (GPT-4o / GPT-4o-mini)', value: 'openai' },
  { label: 'Anthropic (Claude 3.5 Sonnet)', value: 'anthropic' },
  { label: 'DeepSeek (deepseek-chat)', value: 'deepseek' },
  { label: '通义千问 (qwen-max)', value: 'qwen' },
  { label: '自定义 OpenAI 兼容接口', value: 'custom' },
]

const modelOptions = computed(() => {
  switch (aiConfig.provider) {
    case 'openai':
      return [
        { label: 'GPT-4o', value: 'gpt-4o' },
        { label: 'GPT-4o mini', value: 'gpt-4o-mini' },
        { label: 'GPT-4 Turbo', value: 'gpt-4-turbo' },
      ]
    case 'anthropic':
      return [
        { label: 'Claude 3.5 Sonnet', value: 'claude-3-5-sonnet-20241022' },
        { label: 'Claude 3 Opus', value: 'claude-3-opus-20240229' },
      ]
    case 'deepseek':
      return [
        { label: 'DeepSeek Chat', value: 'deepseek-chat' },
        { label: 'DeepSeek Coder', value: 'deepseek-coder' },
      ]
    case 'qwen':
      return [
        { label: 'Qwen-Max', value: 'qwen-max' },
        { label: 'Qwen-Plus', value: 'qwen-plus' },
      ]
    default:
      return []
  }
})

watch(aiConfig, () => { aiConfigChanged.value = true }, { deep: true })

async function loadAiConfig() {
  try {
    const cfg = await api.getAiConfig()
    Object.assign(aiConfig, cfg)
    aiConfigChanged.value = false
  } catch (e: any) {
    message.error('加载 AI 配置失败: ' + (e?.message || e))
  }
}

async function saveAiConfig() {
  aiConfigLoading.value = true
  try {
    const saved = await api.saveAiConfig(aiConfig)
    Object.assign(aiConfig, saved)
    aiConfigChanged.value = false
    message.success('AI 配置已保存')
  } catch (e: any) {
    message.error('保存 AI 配置失败: ' + (e?.message || e))
  } finally {
    aiConfigLoading.value = false
  }
}

// ============================================================
// 数据源状态
// ============================================================
const dataSourceStatus = ref<DataSourceStatus | null>(null)
const dataSourceLoading = ref(false)

async function loadDataSourceStatus() {
  dataSourceLoading.value = true
  try {
    const res = await api.getDataSourceStatus()
    dataSourceStatus.value = res.data
  } catch {
    dataSourceStatus.value = null
  } finally {
    dataSourceLoading.value = false
  }
}

// ============================================================
// 缓存配置
// ============================================================
const cacheConfig = reactive<CacheConfig>({
  enabled: true,
  ttl_seconds: 300,
  max_size: 1000,
})
const cacheLoading = ref(false)
const cacheChanged = ref(false)

watch(cacheConfig, () => { cacheChanged.value = true }, { deep: true })

async function loadCacheConfig() {
  try {
    const cfg = await api.getCacheConfig()
    Object.assign(cacheConfig, cfg)
    cacheChanged.value = false
  } catch {
    // 接口可能不存在，保持默认值
  }
}

async function saveCacheConfig() {
  cacheLoading.value = true
  try {
    const cfg = await api.saveCacheConfig({
      enabled: cacheConfig.enabled,
      ttl_seconds: cacheConfig.ttl_seconds,
      max_size: cacheConfig.max_size,
    })
    Object.assign(cacheConfig, cfg)
    cacheChanged.value = false
    message.success('缓存配置已保存')
  } catch (e: any) {
    message.error('保存缓存配置失败: ' + (e?.message || e))
  } finally {
    cacheLoading.value = false
  }
}

// ============================================================
// 系统监控
// ============================================================
const monitorData = ref<MonitorDashboard | null>(null)
const monitorLoading = ref(false)

async function loadMonitorData() {
  monitorLoading.value = true
  try {
    monitorData.value = await api.getMonitorDashboard()
  } catch {
    monitorData.value = null
  } finally {
    monitorLoading.value = false
  }
}

// ============================================================
// 通知渠道配置
// ============================================================
const notifConfig = reactive<NotificationConfig>({
  wecom_webhook_url: '',
  dingtalk_webhook_url: '',
  email_smtp_host: '',
  email_smtp_port: 465,
  email_username: '',
  email_password: '',
  email_from: '',
  email_to: '',
})
const notifLoading = ref(false)
const notifChanged = ref(false)
const testingChannel = ref<string | null>(null)

watch(notifConfig, () => { notifChanged.value = true }, { deep: true })

async function loadNotificationConfig() {
  try {
    const cfg = await api.getNotificationConfig()
    Object.assign(notifConfig, cfg)
    notifChanged.value = false
  } catch {
    // 接口可能不存在，保持默认值
  }
}

async function saveNotificationConfig() {
  notifLoading.value = true
  try {
    const cfg = await api.saveNotificationConfig(notifConfig)
    Object.assign(notifConfig, cfg)
    notifChanged.value = false
    message.success('通知渠道配置已保存')
  } catch (e: any) {
    message.error('保存通知配置失败: ' + (e?.message || e))
  } finally {
    notifLoading.value = false
  }
}

async function testNotification(channel: 'wechat' | 'dingtalk') {
  testingChannel.value = channel
  try {
    const res = await api.testNotification(channel)
    if (res.sent) {
      message.success(`${channel === 'wechat' ? '企业微信' : '钉钉'}测试消息已发送`)
    } else {
      message.warning(`${channel === 'wechat' ? '企业微信' : '钉钉'}测试消息发送失败，请检查 Webhook URL`)
    }
  } catch (e: any) {
    message.error('测试失败: ' + (e?.message || e))
  } finally {
    testingChannel.value = null
  }
}

function statusColor(status: string) {
  switch (status) {
    case 'healthy': return { bg: 'var(--tag-green-bg)', color: 'var(--tag-green-text)', label: '正常' }
    case 'degraded': return { bg: 'var(--tag-orange-bg)', color: 'var(--tag-orange-text)', label: '降级' }
    case 'down': return { bg: 'var(--tag-red-bg)', color: 'var(--tag-red-text)', label: '异常' }
    default: return { bg: 'var(--bg-hover)', color: 'var(--text-muted)', label: status }
  }
}

// ============================================================
// 侧栏导航
// ============================================================
const activeSection = ref('ai')

const sections = [
  { key: 'ai', label: 'AI 模型配置', icon: HardwareChipOutline },
  { key: 'datasource', label: '数据源状态', icon: ServerOutline },
  { key: 'notification', label: '通知渠道', icon: NotificationsOutline },
  { key: 'cache', label: '缓存配置', icon: CloudDownloadOutline },
  { key: 'monitor', label: '系统监控', icon: PulseOutline },
  { key: 'appearance', label: '主题与外观', icon: MoonOutline },
  { key: 'about', label: '关于', icon: InformationCircleOutline },
]

function scrollToSection(key: string) {
  activeSection.value = key
  const el = document.getElementById(`section-${key}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

// ============================================================
// 初始化
// ============================================================
onMounted(async () => {
  loading.value = true
  // 数据源状态为网络探测（可能较慢），单独异步加载，不阻塞整页渲染
  loadDataSourceStatus()
  await Promise.allSettled([
    loadAiConfig(),
    loadCacheConfig(),
    loadMonitorData(),
    loadNotificationConfig(),
  ])
  loading.value = false
})
</script>

<template>
  <LoadingState
    :loading="loading"
    skeleton
    :min-height="480"
    text="正在加载系统设置..."
  >
    <div class="settings-page">
      <PageHeader title="系统设置" subtitle="配置 AI 模型、数据源、缓存及系统监控" />

      <div class="settings-layout">
        <!-- 左侧导航 -->
        <aside class="settings-nav">
          <button
            v-for="s in sections"
            :key="s.key"
            :class="['settings-nav-item', { active: activeSection === s.key }]"
            @click="scrollToSection(s.key)"
          >
            <n-icon :component="s.icon" size="18" />
            <span>{{ s.label }}</span>
          </button>
        </aside>

        <!-- 右侧内容 -->
        <div class="settings-content">
          <!-- ============================================================ -->
          <!-- AI 模型配置 -->
          <!-- ============================================================ -->
          <div id="section-ai" class="settings-section">
            <DataPanel title="AI 模型配置">
              <template #actions>
                <n-button
                  size="small"
                  type="primary"
                  :loading="aiConfigLoading"
                  :disabled="!aiConfigChanged"
                  @click="saveAiConfig"
                >
                  <template #icon><n-icon :component="SaveOutline" /></template>
                  保存
                </n-button>
              </template>
              <div class="panel-body-content">
                <!-- 启用开关 -->
                <div class="setting-row">
                  <div class="setting-info">
                    <span class="setting-label">启用 AI 决策</span>
                    <span class="setting-desc">开启后，AI 决策中心将按定时任务自动生成分析报告</span>
                  </div>
                  <n-switch v-model:value="aiConfig.enabled" />
                </div>

                <div class="divider" />

                <!-- 模型提供商 -->
                <div class="form-row">
                  <label class="form-label">模型提供商</label>
                  <n-select
                    v-model:value="aiConfig.provider"
                    :options="providerOptions"
                    placeholder="选择模型提供商"
                  />
                </div>

                <!-- 模型 -->
                <div class="form-row" v-if="modelOptions.length > 0">
                  <label class="form-label">模型</label>
                  <n-select
                    v-model:value="aiConfig.model"
                    :options="modelOptions"
                    placeholder="选择模型"
                    clearable
                  />
                </div>
                <div class="form-row" v-else>
                  <label class="form-label">模型名称</label>
                  <n-input
                    v-model:value="aiConfig.model"
                    placeholder="输入模型名称（如 gpt-4o）"
                  />
                </div>

                <!-- API Key -->
                <div class="form-row">
                  <label class="form-label">API Key</label>
                  <n-input
                    v-model:value="aiConfig.apiKey"
                    :type="showApiKey ? 'text' : 'password'"
                    placeholder="输入 API Key"
                  >
                    <template #suffix>
                      <n-button text @click="showApiKey = !showApiKey" aria-label="显示/隐藏 API Key">
                        <n-icon :component="showApiKey ? EyeOffOutline : EyeOutline" size="18" />
                      </n-button>
                    </template>
                  </n-input>
                </div>

                <!-- Endpoint -->
                <div class="form-row">
                  <label class="form-label">API Endpoint</label>
                  <n-input
                    v-model:value="aiConfig.endpoint"
                    placeholder="留空使用默认地址，或输入自定义接口地址"
                  />
                </div>

                <!-- Temperature -->
                <div class="form-row">
                  <label class="form-label">
                    温度 (Temperature)
                    <span class="form-value">{{ aiConfig.temperature.toFixed(2) }}</span>
                  </label>
                  <n-slider
                    v-model:value="aiConfig.temperature"
                    :min="0"
                    :max="2"
                    :step="0.05"
                    :marks="{ 0: '精确', 1: '平衡', 2: '创造' }"
                  />
                </div>

                <!-- 定时任务 -->
                <div class="form-row">
                  <label class="form-label">定时任务 (Cron)</label>
                  <n-input
                    v-model:value="aiConfig.cronExpression"
                    placeholder="如：0 8 * * 1-5（工作日8点）"
                  />
                </div>

                <!-- 说明 -->
                <div class="setting-hint">
                  <n-icon :component="InformationCircleOutline" size="14" />
                  <span>Cron 表达式格式：分 时 日 月 周。常见配置：<code>0 8 * * 1-5</code>（工作日8:00）、<code>0 */2 * * *</code>（每2小时）</span>
                </div>
              </div>
            </DataPanel>
          </div>

          <!-- ============================================================ -->
          <!-- 数据源状态 -->
          <!-- ============================================================ -->
          <div id="section-datasource" class="settings-section">
            <DataPanel title="数据源状态">
              <template #actions>
                <n-button size="small" quaternary :loading="dataSourceLoading" @click="loadDataSourceStatus">
                  <template #icon><n-icon :component="RefreshOutline" /></template>
                  刷新
                </n-button>
              </template>
              <div class="panel-body-content">
                <div class="ds-status-grid">
                  <!-- AkShare -->
                  <div class="ds-status-card">
                    <div class="ds-status-header">
                      <n-icon :component="ServerOutline" size="20" class="ds-icon" />
                      <span class="ds-name">AkShare WebAPI</span>
                    </div>
                    <div class="ds-status-body">
                      <n-tag
                        size="small"
                        :bordered="false"
                        :style="dataSourceStatus?.akshareConnected
                          ? { background: 'var(--tag-green-bg)', color: 'var(--tag-green-text)' }
                          : { background: 'var(--tag-red-bg)', color: 'var(--tag-red-text)' }"
                      >
                        {{ dataSourceStatus?.akshareConnected ? '已连接' : '未连接' }}
                      </n-tag>
                      <span class="ds-endpoint">{{ apiBase }}</span>
                    </div>
                  </div>

                  <!-- 集思录 -->
                  <div class="ds-status-card">
                    <div class="ds-status-header">
                      <n-icon :component="CloudDownloadOutline" size="20" class="ds-icon" />
                      <span class="ds-name">集思录</span>
                    </div>
                    <div class="ds-status-body">
                      <n-tag
                        size="small"
                        :bordered="false"
                        :style="dataSourceStatus?.jisiluLoggedIn
                          ? { background: 'var(--tag-green-bg)', color: 'var(--tag-green-text)' }
                          : { background: 'var(--tag-red-bg)', color: 'var(--tag-red-text)' }"
                      >
                        {{ dataSourceStatus?.jisiluLoggedIn ? '已登录' : '未登录' }}
                      </n-tag>
                      <span class="ds-endpoint">可转债 YTM / 溢价率数据源</span>
                    </div>
                  </div>
                </div>

                <div v-if="dataSourceStatus?.timestamp" class="ds-timestamp">
                  最后检测时间：{{ dataSourceStatus.timestamp }}
                </div>
                <div v-else-if="dataSourceLoading" class="ds-timestamp">
                  正在检测数据源连接...
                </div>

                <div class="setting-hint">
                  <n-icon :component="InformationCircleOutline" size="14" />
                  <span>AkShare 为主要行情数据源（指数/ETF/LOF/基金排行等）。集思录用于获取可转债到期收益率等深度数据，需在服务器配置登录 Cookie。</span>
                </div>
              </div>
            </DataPanel>
          </div>

          <!-- ============================================================ -->
          <!-- 通知渠道配置 -->
          <!-- ============================================================ -->
          <div id="section-notification" class="settings-section">
            <DataPanel title="通知渠道配置">
              <template #actions>
                <n-button
                  size="small"
                  type="primary"
                  :loading="notifLoading"
                  :disabled="!notifChanged"
                  @click="saveNotificationConfig"
                >
                  <template #icon><n-icon :component="SaveOutline" /></template>
                  保存
                </n-button>
              </template>
              <div class="panel-body-content">
                <!-- 企业微信 -->
                <div class="notif-channel-block">
                  <div class="notif-channel-header">
                    <n-icon :component="NotificationsOutline" size="18" class="notif-channel-icon" />
                    <span class="notif-channel-title">企业微信群机器人</span>
                  </div>
                  <div class="form-row">
                    <label class="form-label">Webhook URL</label>
                    <n-input
                      v-model:value="notifConfig.wecom_webhook_url"
                      placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx"
                    />
                  </div>
                  <div class="notif-test-row">
                    <n-button
                      size="small"
                      :loading="testingChannel === 'wechat'"
                      :disabled="!notifConfig.wecom_webhook_url"
                      @click="testNotification('wechat')"
                    >
                      <template #icon><n-icon :component="SendOutline" /></template>
                      发送测试消息
                    </n-button>
                  </div>
                </div>

                <div class="divider" />

                <!-- 钉钉机器人 -->
                <div class="notif-channel-block">
                  <div class="notif-channel-header">
                    <n-icon :component="NotificationsOutline" size="18" class="notif-channel-icon" />
                    <span class="notif-channel-title">钉钉群机器人</span>
                  </div>
                  <div class="form-row">
                    <label class="form-label">Webhook URL</label>
                    <n-input
                      v-model:value="notifConfig.dingtalk_webhook_url"
                      placeholder="https://oapi.dingtalk.com/robot/send?access_token=xxxxxxxx"
                    />
                  </div>
                  <div class="notif-test-row">
                    <n-button
                      size="small"
                      :loading="testingChannel === 'dingtalk'"
                      :disabled="!notifConfig.dingtalk_webhook_url"
                      @click="testNotification('dingtalk')"
                    >
                      <template #icon><n-icon :component="SendOutline" /></template>
                      发送测试消息
                    </n-button>
                  </div>
                </div>

                <div class="divider" />

                <!-- 邮件（预留） -->
                <div class="notif-channel-block">
                  <div class="notif-channel-header">
                    <n-icon :component="NotificationsOutline" size="18" class="notif-channel-icon" />
                    <span class="notif-channel-title">邮件通知</span>
                    <span class="notif-channel-tag">预留</span>
                  </div>
                  <div class="form-row-grid-2">
                    <div class="form-row">
                      <label class="form-label">SMTP 服务器</label>
                      <n-input
                        v-model:value="notifConfig.email_smtp_host"
                        placeholder="smtp.example.com"
                      />
                    </div>
                    <div class="form-row">
                      <label class="form-label">端口</label>
                      <n-input-number
                        v-model:value="notifConfig.email_smtp_port"
                        :min="1"
                        :max="65535"
                        style="width: 100%"
                      />
                    </div>
                  </div>
                  <div class="form-row-grid-2">
                    <div class="form-row">
                      <label class="form-label">用户名</label>
                      <n-input
                        v-model:value="notifConfig.email_username"
                        placeholder="user@example.com"
                      />
                    </div>
                    <div class="form-row">
                      <label class="form-label">密码</label>
                      <n-input
                        v-model:value="notifConfig.email_password"
                        type="password"
                        placeholder="SMTP 密码/授权码"
                      />
                    </div>
                  </div>
                  <div class="form-row-grid-2">
                    <div class="form-row">
                      <label class="form-label">发件人地址</label>
                      <n-input
                        v-model:value="notifConfig.email_from"
                        placeholder="from@example.com"
                      />
                    </div>
                    <div class="form-row">
                      <label class="form-label">收件人地址</label>
                      <n-input
                        v-model:value="notifConfig.email_to"
                        placeholder="to@example.com"
                      />
                    </div>
                  </div>
                </div>

                <!-- 使用说明 -->
                <div class="notif-guide">
                  <div class="notif-guide-title">
                    <n-icon :component="InformationCircleOutline" size="16" />
                    <span>使用说明</span>
                  </div>
                  <div class="notif-guide-sections">
                    <!-- 企业微信 -->
                    <div class="guide-section">
                      <h4>企业微信群机器人配置</h4>
                      <ol class="guide-steps">
                        <li>打开企业微信 PC 端或手机端，进入一个群聊</li>
                        <li>点击群聊右上角的 <code>···</code> → 选择「群机器人」</li>
                        <li>点击「添加机器人」→ 选择「自定义机器人」</li>
                        <li>设置机器人名称（如「量化预警」），选择消息发送范围</li>
                        <li>点击「完成」，复制生成的 <strong>Webhook 地址</strong></li>
                        <li>将 Webhook 地址粘贴到上方输入框，点击「保存」</li>
                        <li>点击「发送测试消息」，检查群内是否收到测试通知</li>
                      </ol>
                      <div class="guide-note">
                        <span class="guide-note-label">注意</span>
                        <span>Webhook 地址格式为 <code>https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx</code>，请勿泄露。频率限制：每个机器人发送消息不能超过 20 条/分钟，且不同消息类型有不同限制（文本 20 条/分钟，图文/文件/模板卡片 10 条/分钟，图片/语音 15 条/分钟）。预警扫描不宜过于频繁，建议间隔 ≥ 1 分钟。</span>
                      </div>
                    </div>
                    <!-- 钉钉 -->
                    <div class="guide-section">
                      <h4>钉钉群机器人配置</h4>
                      <ol class="guide-steps">
                        <li>打开钉钉 PC 端，进入一个群聊</li>
                        <li>点击群设置 → 「智能群助手」→「添加机器人」</li>
                        <li>选择「自定义」机器人，设置名称</li>
                        <li>安全设置选择「加签」或「关键字」，复制生成的 <strong>Webhook 地址</strong></li>
                        <li>将 Webhook 地址粘贴到上方输入框，点击「保存」</li>
                        <li>点击「发送测试消息」验证</li>
                      </ol>
                    </div>
                    <!-- 预警流程 -->
                    <div class="guide-section">
                      <h4>预警触发流程</h4>
                      <ol class="guide-steps">
                        <li>在「预警中心」创建预警规则，选择通知渠道（企业微信/钉钉）</li>
                        <li>启用规则后，在预警中心点击「扫描」按钮手动触发检测</li>
                        <li>系统获取实时行情数据，逐条匹配规则条件</li>
                        <li>满足条件的标的自动记录为预警事件，并按规则配置的渠道发送通知</li>
                        <li>预警事件可在「预警历史」表格中查看详情，支持标记已读</li>
                      </ol>
                    </div>
                  </div>
                </div>
              </div>
            </DataPanel>
          </div>

          <!-- ============================================================ -->
          <!-- 缓存配置 -->
          <!-- ============================================================ -->
          <div id="section-cache" class="settings-section">
            <DataPanel title="缓存配置">
              <template #actions>
                <n-button
                  size="small"
                  type="primary"
                  :loading="cacheLoading"
                  :disabled="!cacheChanged"
                  @click="saveCacheConfig"
                >
                  <template #icon><n-icon :component="SaveOutline" /></template>
                  保存
                </n-button>
              </template>
              <div class="panel-body-content">
                <div class="setting-row">
                  <div class="setting-info">
                    <span class="setting-label">启用缓存</span>
                    <span class="setting-desc">缓存 API 响应数据以减少重复请求，提升页面加载速度</span>
                  </div>
                  <n-switch v-model:value="cacheConfig.enabled" />
                </div>

                <div class="divider" />

                <div class="form-row">
                  <label class="form-label">
                    缓存有效期 (秒)
                    <span class="form-value">{{ cacheConfig.ttl_seconds }}s</span>
                  </label>
                  <n-input-number
                    v-model:value="cacheConfig.ttl_seconds"
                    :min="30"
                    :max="3600"
                    :step="30"
                    style="width: 100%"
                  />
                </div>

                <div class="form-row">
                  <label class="form-label">
                    最大缓存条目数
                    <span class="form-value">{{ cacheConfig.max_size }}</span>
                  </label>
                  <n-input-number
                    v-model:value="cacheConfig.max_size"
                    :min="100"
                    :max="10000"
                    :step="100"
                    style="width: 100%"
                  />
                </div>

                <div class="setting-hint">
                  <n-icon :component="InformationCircleOutline" size="14" />
                  <span>建议：日频数据 TTL 设为 300 秒（5分钟），实时数据 TTL 设为 30-60 秒。缓存过大会占用过多内存。</span>
                </div>
              </div>
            </DataPanel>
          </div>

          <!-- ============================================================ -->
          <!-- 系统监控 -->
          <!-- ============================================================ -->
          <div id="section-monitor" class="settings-section">
            <DataPanel title="系统监控">
              <template #actions>
                <n-button size="small" quaternary :loading="monitorLoading" @click="loadMonitorData">
                  <template #icon><n-icon :component="RefreshOutline" /></template>
                  刷新
                </n-button>
              </template>
              <div class="panel-body-content">
                <div v-if="monitorData" class="monitor-grid">
                  <StatCard label="系统运行时间" :value="monitorData.system_uptime" sub="自上次重启" />
                  <StatCard label="今日 API 调用" :value="monitorData.api_calls_today.toLocaleString()" sub="请求次数" />
                  <StatCard label="缓存命中率" :value="monitorData.cache_hit_rate + '%'" sub="缓存效率" />
                  <StatCard label="活跃连接" :value="monitorData.active_connections" sub="当前连接数" />
                </div>

                <div v-if="monitorData?.last_error" class="monitor-error">
                  <n-icon :component="CloseCircleOutline" size="16" />
                  <span>最近错误：{{ monitorData.last_error }}</span>
                </div>

                <div v-if="monitorData?.services?.length" class="services-list">
                  <div class="services-title">
                    <n-icon :component="PulseOutline" size="16" />
                    <span>服务状态</span>
                  </div>
                  <div class="services-grid">
                    <div
                      v-for="svc in monitorData.services"
                      :key="svc.name"
                      class="service-card"
                    >
                      <div class="service-header">
                        <span class="service-name">{{ svc.name }}</span>
                        <n-tag
                          size="tiny"
                          :bordered="false"
                          :style="{
                            background: statusColor(svc.status).bg,
                            color: statusColor(svc.status).color,
                          }"
                        >
                          {{ statusColor(svc.status).label }}
                        </n-tag>
                      </div>
                      <div class="service-latency">
                        <n-icon :component="SpeedometerOutline" size="14" />
                        <span>{{ svc.latency_ms }}ms</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div v-if="!monitorData" class="empty-state">
                  <n-icon :component="InformationCircleOutline" size="24" />
                  <span>暂无监控数据</span>
                </div>
              </div>
            </DataPanel>
          </div>

          <!-- ============================================================ -->
          <!-- 主题与外观 -->
          <!-- ============================================================ -->
          <div id="section-appearance" class="settings-section">
            <DataPanel title="主题与外观">
              <div class="panel-body-content">
                <div class="setting-row">
                  <div class="setting-info">
                    <span class="setting-label">深色模式</span>
                    <span class="setting-desc">切换深色/浅色主题，减少眼睛疲劳</span>
                  </div>
                  <n-switch
                    :value="isDark"
                    @update:value="toggleDarkMode"
                  >
                    <template #checked-icon>
                      <n-icon :component="MoonOutline" />
                    </template>
                    <template #unchecked-icon>
                      <n-icon :component="SunnyOutline" />
                    </template>
                  </n-switch>
                </div>

                <div class="divider" />

                <div class="theme-preview">
                  <div
                    :class="['theme-card', { active: !isDark }]"
                    @click="isDark && toggleDarkMode()"
                  >
                    <div class="theme-preview-light" />
                    <span>浅色</span>
                    <n-icon v-if="!isDark" :component="CheckmarkCircleOutline" size="16" class="theme-check" />
                  </div>
                  <div
                    :class="['theme-card', { active: isDark }]"
                    @click="!isDark && toggleDarkMode()"
                  >
                    <div class="theme-preview-dark" />
                    <span>深色</span>
                    <n-icon v-if="isDark" :component="CheckmarkCircleOutline" size="16" class="theme-check" />
                  </div>
                </div>
              </div>
            </DataPanel>
          </div>

          <!-- ============================================================ -->
          <!-- 关于 -->
          <!-- ============================================================ -->
          <div id="section-about" class="settings-section">
            <DataPanel title="关于">
              <div class="panel-body-content">
                <div class="about-grid">
                  <div class="about-item">
                    <span class="about-label">应用名称</span>
                    <span class="about-value">QuantTerminal Pro</span>
                  </div>
                  <div class="about-item">
                    <span class="about-label">版本</span>
                    <span class="about-value">v1.0.0</span>
                  </div>
                  <div class="about-item">
                    <span class="about-label">前端框架</span>
                    <span class="about-value">Vue 3 + Vite + Naive UI</span>
                  </div>
                  <div class="about-item">
                    <span class="about-label">后端框架</span>
                    <span class="about-value">FastAPI + DuckDB</span>
                  </div>
                  <div class="about-item">
                    <span class="about-label">数据源</span>
                    <span class="about-value">AkShare / 集思录</span>
                  </div>
                  <div class="about-item">
                    <span class="about-label">部署环境</span>
                    <span class="about-value">{{ deployMode }}</span>
                  </div>
                </div>

                <div class="setting-hint">
                  <n-icon :component="InformationCircleOutline" size="14" />
                  <span>QuantTerminal Pro 是一个面向个人投资者的量化分析终端，覆盖指数估值、ETF/LOF套利、可转债、REITs等品种，提供策略管理和 AI 辅助决策能力。</span>
                </div>
              </div>
            </DataPanel>
          </div>
        </div>
      </div>
    </div>
  </LoadingState>
</template>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.settings-layout {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

/* 左侧导航 */
.settings-nav {
  position: sticky;
  top: 66px;
  width: 200px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.settings-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: 'Work Sans', sans-serif;
  font-size: 13px;
  font-weight: 600;
  text-align: left;
  width: 100%;
}

.settings-nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.settings-nav-item.active {
  background: var(--bg-active);
  color: var(--color-primary);
}

/* 右侧内容 */
.settings-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.settings-section {
  scroll-margin-top: 66px;
}

/* 面板内容通用 */
.panel-body-content {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 设置行 */
.setting-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.setting-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.setting-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.setting-desc {
  font-size: 12px;
  color: var(--text-muted);
}

.divider {
  height: 1px;
  background: var(--border-default);
  margin: 0;
}

/* 表单行 */
.form-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.form-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary);
}

/* 提示信息 */
.setting-hint {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 10px 12px;
  background: var(--bg-subtle);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.setting-hint code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: var(--bg-hover);
  padding: 2px 6px;
  border-radius: 3px;
  color: var(--color-primary);
}

/* 数据源状态 */
.ds-status-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}

.ds-status-card {
  background: var(--bg-subtle);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ds-status-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ds-icon {
  color: var(--color-primary);
}

.ds-name {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.ds-status-body {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ds-endpoint {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-muted);
}

.ds-timestamp {
  font-size: 12px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

/* 监控 */
.monitor-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.monitor-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: var(--tag-red-bg);
  border-radius: 6px;
  font-size: 13px;
  color: var(--tag-red-text);
}

.services-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.services-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.services-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.service-card {
  background: var(--bg-subtle);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  padding: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.service-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.service-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.service-latency {
  display: flex;
  align-items: center;
  gap: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--text-muted);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px;
  color: var(--text-muted);
}

/* 主题预览 */
.theme-preview {
  display: flex;
  gap: 16px;
}

.theme-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  border: 2px solid var(--border-default);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.2s ease;
  min-width: 120px;
}

.theme-card:hover {
  border-color: var(--border-hover);
}

.theme-card.active {
  border-color: var(--color-primary);
}

.theme-check {
  position: absolute;
  top: 8px;
  right: 8px;
  color: var(--color-primary);
}

.theme-preview-light {
  width: 100%;
  height: 60px;
  background: linear-gradient(135deg, #ffffff 0%, #f0f0f0 100%);
  border-radius: 6px;
  border: 1px solid #e0e0e0;
}

.theme-preview-dark {
  width: 100%;
  height: 60px;
  background: linear-gradient(135deg, #1a1d21 0%, #2a2d31 100%);
  border-radius: 6px;
  border: 1px solid #3a3d41;
}

.theme-card span {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

/* 关于 */
.about-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0;
}

.about-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-default);
}

.about-item:nth-child(odd) {
  padding-right: 16px;
}

.about-item:nth-child(even) {
  padding-left: 16px;
  border-left: 1px solid var(--border-default);
}

.about-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.about-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

/* Responsive */
@media (max-width: 1024px) {
  .settings-layout {
    flex-direction: column;
  }
  .settings-nav {
    position: static;
    width: 100%;
    flex-direction: row;
    overflow-x: auto;
    overflow-y: hidden;
  }
  .settings-nav-item {
    white-space: nowrap;
  }
  .monitor-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .ds-status-grid {
    grid-template-columns: 1fr;
  }
  .services-grid {
    grid-template-columns: 1fr;
  }
  .about-grid {
    grid-template-columns: 1fr;
  }
  .about-item:nth-child(even) {
    padding-left: 0;
    border-left: none;
  }
  .about-item:nth-child(odd) {
    padding-right: 0;
  }
  .theme-preview {
    flex-direction: column;
  }
  .form-row-grid-2 {
    grid-template-columns: 1fr !important;
  }
}

/* 通知渠道配置 */
.notif-channel-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.notif-channel-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.notif-channel-icon {
  color: var(--color-primary);
}
.notif-channel-title {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}
.notif-channel-tag {
  font-size: 10px;
  padding: 1px 6px;
  background: var(--tag-gray-bg);
  color: var(--tag-gray-text);
  border-radius: 2px;
  font-weight: 700;
}
.notif-test-row {
  display: flex;
  justify-content: flex-end;
}
.form-row-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

/* 通知渠道使用说明 */
.notif-guide {
  margin-top: 16px;
  padding: 14px 16px;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 6px;
}
.notif-guide-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-bottom: 12px;
}
.notif-guide-sections {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.guide-section h4 {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-primary);
  margin: 0 0 6px 0;
}
.guide-steps {
  margin: 0 0 6px 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-secondary);
}
.guide-steps li {
  margin-bottom: 2px;
}
.guide-steps code,
.guide-note code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  padding: 1px 4px;
  background: var(--tag-gray-bg);
  color: var(--text-primary);
  border-radius: 2px;
}
.guide-note {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 6px 10px;
  background: rgba(255, 153, 0, 0.08);
  border-left: 2px solid #f90;
  border-radius: 0 4px 4px 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.guide-note-label {
  flex-shrink: 0;
  font-weight: 700;
  color: #f90;
}
</style>
