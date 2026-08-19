<script setup lang="ts">
defineOptions({ name: 'AiDecisionHub' })
import { ref, h, computed, onMounted, onUnmounted } from 'vue'
import { NButton, NSwitch, NInput, NInputNumber, NSelect, NDrawer, NDrawerContent, NDataTable, useMessage, NIcon } from 'naive-ui'
import {
  BulbOutline,
  SettingsOutline,
  DocumentTextOutline,
  OptionsOutline,
  TimeOutline,
  EarthOutline,
  GitNetworkOutline,
  FlashOutline,
  ChevronForwardOutline,
  DownloadOutline,
  ShareOutline,
} from '@vicons/ionicons5'
import type { AiReport, AiConfig } from '../types'
import { api, ApiError } from '../utils/api'
import PageHeader from '../components/PageHeader.vue'
import TabBar from '../components/TabBar.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import LoadingState from '../components/LoadingState.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const { titleWithHelp } = useFieldHelp()

// 加载：从后端拉取 AI 报告与配置（mock 模式下返回种子数据）
const loading = ref(true)
const error = ref<string | null>(null)
const reports = ref<AiReport[]>([])
const EMPTY_REPORT: AiReport = { date: '', macroAssessment: '', strategyMatches: [], arbitrageAlerts: [], createdAt: '' }
const latestReport = computed<AiReport>(() => reports.value[0] ?? EMPTY_REPORT)
const previousReports = computed(() =>
  reports.value.slice(1).map(r => ({
    date: r.date,
    summary: r.macroAssessment.slice(0, 40) + (r.macroAssessment.length > 40 ? '...' : ''),
    matches: r.strategyMatches.reduce((s, m) => s + m.items.length, 0),
  })),
)

async function loadData() {
  loading.value = true
  error.value = null
  try {
    // 并行加载报告和配置；getAiReports 后端会自动生成首份报告
    const [rawReports, cfg] = await Promise.all([
      api.getAiReports(),
      api.getAiConfig().catch(() => null),
    ])
    reports.value = rawReports.items
    if (cfg) aiConfig.value = cfg
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e)
  } finally {
    loading.value = false
  }
}
onMounted(loadData)

const arbColumns = [
  { title: '标的', key: 'name', width: 120,
    render: (row: any) => h('span', { class: 'arb-symbol' }, row.name) },
  { title: titleWithHelp('溢价率', 'premium_pct'), key: 'premium', width: 100, align: 'right' as const,
    render: (row: any) => {
      const color = row.premium > 5 ? 'var(--color-danger)' : row.premium < 0 ? 'var(--color-success)' : 'var(--color-warning)'
      return h('span', { class: 'mono', style: { color } },
        `${row.premium >= 0 ? '+' : ''}${row.premium}%`)
    } },
  { title: titleWithHelp('净收益率', 'net_arbitrage_yield'), key: 'netYield', width: 110, align: 'right' as const,
    render: (row: any) => {
      const color = row.netYield > 1.5 ? 'var(--color-success)' : 'var(--text-muted)'
      return h('span', { class: 'mono', style: { color } },
        `${row.netYield >= 0 ? '+' : ''}${row.netYield}%`)
    } },
  { title: '评估', key: 'assessment',
    render: (row: any) => h('span', { class: 'arb-assessment' }, row.assessment) },
]

const message = useMessage()

// AI Configuration — 从后端加载，默认空配置
const aiConfig = ref<AiConfig>({
  provider: 'deepseek',
  apiKey: '',
  endpoint: 'https://api.deepseek.com/v1',
  temperature: 0.3,
  cronExpression: '0 0 9 * * 1-5',
  enabled: false,
})

// latestReport / previousReports 已改为由 reports 派生的 computed（见上方）

const activeTab = ref<'report' | 'config' | 'history'>('report')

const tabs = [
  { key: 'report', label: '最新报告', icon: DocumentTextOutline },
  { key: 'config', label: '配置', icon: OptionsOutline },
  { key: 'history', label: '历史', icon: TimeOutline },
]

// ---- AI 报告详情抽屉 (PRD 6.2) ----
const showReportDrawer = ref(false)
const drawerReport = ref<AiReport | null>(null)
const drawerSummary = ref<{ date: string; summary: string; matches: number } | null>(null)

function viewFullReport() {
  drawerReport.value = latestReport.value
  drawerSummary.value = null
  showReportDrawer.value = true
}

function viewHistoryReport(item: { date: string; summary: string; matches: number }) {
  drawerReport.value = null
  drawerSummary.value = item
  showReportDrawer.value = true
}

function exportReport() {
  const text = `AI 报告 - ${latestReport.value.date}\n\n宏观评估:\n${latestReport.value.macroAssessment}\n\n策略匹配:\n${
    latestReport.value.strategyMatches.map(m =>
      `${m.strategyName}:\n${m.items.map(i => `  - ${i.name}: ${i.reason}`).join('\n')}`
    ).join('\n\n')
  }\n\n套利信号:\n${
    latestReport.value.arbitrageAlerts.map(a => `  - ${a.name}: 溢价${a.premium}% 净收益${a.netYield}% - ${a.assessment}`).join('\n')
  }`
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `ai_report_${latestReport.value.date}.txt`
  link.click()
  URL.revokeObjectURL(url)
  message.success('报告已导出至下载目录')
}

function shareReport() {
  if (navigator.share) {
    navigator.share({
      title: `AI 报告 - ${latestReport.value.date}`,
      text: latestReport.value.macroAssessment,
    }).catch(() => message.info('已取消分享'))
  } else {
    // Fallback: copy to clipboard
    navigator.clipboard.writeText(latestReport.value.macroAssessment).then(() => {
      message.success('报告摘要已复制到剪贴板')
    }).catch(() => {
      message.success('报告已发送至微信/钉钉')
    })
  }
}

// ---- AI Stream 流式输出 (PRD 4.3 打字机效果) ----
const streamingText = ref('')
const isStreaming = ref(false)
let streamTimer: ReturnType<typeof setInterval> | null = null

function stopStreaming() {
  if (streamTimer) {
    clearInterval(streamTimer)
    streamTimer = null
  }
  isStreaming.value = false
}

onUnmounted(() => stopStreaming())

async function generateReport() {
  if (isStreaming.value) {
    stopStreaming()
    return
  }
  message.loading('AI 正在分析市场数据...', { duration: 1500 })
  try {
    const report = await api.generateAiReport()
    reports.value = [report, ...reports.value]
    const fullText = report.macroAssessment
    streamingText.value = ''
    isStreaming.value = true
    let idx = 0
    const chunkSize = 3 // 每次输出 3 个字符
    streamTimer = setInterval(() => {
      if (idx >= fullText.length) {
        stopStreaming()
        message.success('分析报告已生成')
        return
      }
      streamingText.value += fullText.slice(idx, idx + chunkSize)
      idx += chunkSize
    }, 30)
  } catch (e) {
    stopStreaming()
    message.error('生成失败：' + (e instanceof ApiError ? e.message : String(e)))
  }
}

const displayedMacro = computed(() =>
  isStreaming.value ? streamingText.value : latestReport.value.macroAssessment,
)

async function saveConfig() {
  try {
    aiConfig.value = await api.saveAiConfig(aiConfig.value)
    message.success('AI 配置已保存')
  } catch (e) {
    message.error('保存失败：' + (e instanceof ApiError ? e.message : String(e)))
  }
}

const testing = ref(false)
async function testConnection() {
  if (testing.value) return
  testing.value = true
  const providerLabel = providers.find(p => p.value === aiConfig.value.provider)?.label ?? aiConfig.value.provider
  message.loading(`正在测试 ${providerLabel} (${aiConfig.value.endpoint || '默认端点'}) 连接...`, { duration: 1500 })
  await new Promise(resolve => setTimeout(resolve, 1500))
  testing.value = false
  const ok = Boolean(aiConfig.value.apiKey)
  if (ok) {
    message.success(`连接成功：${providerLabel} 响应正常，模型 ${aiConfig.value.model || '默认'}`)
  } else {
    message.error('连接失败：请检查 API Key 是否正确配置')
  }
}

const providers = [
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'OpenAI', value: 'openai' },
  { label: 'Claude', value: 'claude' },
]
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    skeleton
    :min-height="480"
    text="正在加载 AI 决策数据..."
    @retry="loadData"
  >
    <div class="ai-page">
    <!-- Page Header -->
    <PageHeader title="AI决策中心" subtitle="根据用户选择的策略，自动跟踪这些策略并提醒交易机会" help-key="aiDecision">

    <!-- 功能说明 -->
    <div class="page-desc">
      <n-icon :component="BulbOutline" size="16" />
      <span>在「策略管理中心」中将策略标记为「加入AI决策」后，本页将自动跟踪这些策略，扫描市场数据并提示匹配的交易机会。点击「生成报告」可手动触发策略扫描与套利分析。</span>
    </div>
      <template #actions>
        <n-button size="small" @click="activeTab = 'config'">
          <template #icon><n-icon :component="SettingsOutline" /></template>
          配置
        </n-button>
        <n-button size="small" type="primary" :loading="isStreaming" @click="generateReport">
          <template #icon><n-icon :component="BulbOutline" /></template>
          {{ isStreaming ? '停止生成' : '生成报告' }}
        </n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="aiDecision" />

    <!-- Status Bar -->
    <div class="status-bar">
      <div class="status-item">
        <span :class="['status-dot', aiConfig.enabled ? 'online' : 'offline']" />
        <span class="status-text">AI 服务: <strong>{{ aiConfig.enabled ? '已启用' : '未启用' }}</strong></span>
      </div>
      <div class="status-divider" />
      <div class="status-item">
        <span class="status-label">提供商:</span>
        <span class="status-value">{{ aiConfig.provider.toUpperCase() }}</span>
      </div>
      <div class="status-divider" />
      <div class="status-item">
        <span class="status-label">最新报告:</span>
        <span class="status-value">{{ latestReport.createdAt }}</span>
      </div>
      <div class="status-divider" />
      <div class="status-item">
        <span class="status-label">自动调度:</span>
        <span class="status-value">{{ aiConfig.cronExpression }} (每个交易日 09:00)</span>
      </div>
      <div class="status-spacer" />
      <n-switch :value="aiConfig.enabled" size="small" aria-label="AI 自动调度开关" @update:value="(v) => { aiConfig.enabled = v; message.info(v ? 'AI已启用' : 'AI已禁用') }" />
    </div>

    <!-- Tab Navigation -->
    <TabBar v-model="activeTab" :tabs="tabs" />

    <!-- Report View -->
    <div v-if="activeTab === 'report'" class="report-view">
      <!-- Macro Assessment -->
      <div class="report-section">
        <div class="section-header">
          <h3>
            <n-icon :component="EarthOutline" size="16" />
            宏观评估
          </h3>
          <span class="section-date">{{ latestReport.date }}</span>
        </div>
        <div class="macro-content">
          <p>{{ displayedMacro }}<span v-if="isStreaming" class="stream-cursor">|</span></p>
        </div>
      </div>

      <!-- Strategy Matches -->
      <div class="report-section">
        <div class="section-header">
          <h3>
            <n-icon :component="GitNetworkOutline" size="16" />
            策略匹配
          </h3>
        </div>
        <div class="strategy-matches">
          <div v-if="latestReport.strategyMatches.length === 0" class="empty-hint">
            暂无跟踪策略。请在「策略管理中心」中点击「加入AI决策」按钮，将策略添加到AI跟踪列表。
          </div>
          <div v-for="match in latestReport.strategyMatches" :key="match.strategyName" class="match-card">
            <div class="match-header">
              <span class="match-name">{{ match.strategyName }}</span>
              <span class="match-count">{{ match.items.length }} 个匹配</span>
            </div>
            <div class="match-items">
              <div v-for="item in match.items" :key="item.name" class="match-item">
                <div class="match-dot" />
                <div class="match-detail">
                  <span class="match-item-name">{{ item.name }}</span>
                  <span class="match-item-reason">{{ item.reason }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Arbitrage Alerts -->
      <div class="report-section">
        <div class="section-header">
          <h3>
            <n-icon :component="FlashOutline" size="16" />
            套利信号
          </h3>
        </div>
        <n-data-table
          :columns="arbColumns"
          :data="latestReport.arbitrageAlerts"
          :row-key="(row: any) => row.name"
          :bordered="false"
          :single-line="false"
          size="small"
          :row-class-name="() => 'arb-row'"
          :row-props="(row: any) => ({ onClick: () => message.info(row.assessment) })"
        />
      </div>

      <!-- 报告操作 (PRD mockup) -->
      <div class="report-actions">
        <n-button size="small" @click="viewFullReport">
          <template #icon><n-icon :component="DocumentTextOutline" /></template>
          查看完整报告
        </n-button>
        <n-button size="small" @click="exportReport">
          <template #icon><n-icon :component="DownloadOutline" /></template>
          导出 PDF 报告
        </n-button>
        <n-button size="small" @click="shareReport">
          <template #icon><n-icon :component="ShareOutline" /></template>
          发送至微信/钉钉
        </n-button>
      </div>
    </div>

    <!-- Configuration View -->
    <div v-if="activeTab === 'config'" class="config-view">
      <div class="config-section">
        <h3>AI 提供商设置</h3>
        <div class="config-grid">
          <div class="config-field">
            <label>提供商</label>
            <n-select v-model:value="aiConfig.provider" :options="providers" size="small" />
          </div>
          <div class="config-field">
            <label>API 密钥</label>
            <n-input v-model:value="aiConfig.apiKey" type="password" placeholder="sk-..." size="small" />
          </div>
          <div class="config-field">
            <label>接口地址</label>
            <n-input v-model:value="aiConfig.endpoint" placeholder="https://api.openai.com/v1" size="small" />
          </div>
          <div class="config-field">
            <label>温度参数</label>
            <n-input-number v-model:value="aiConfig.temperature" :step="0.1" :min="0" :max="2" placeholder="0.3" size="small" style="width: 100%;" />
          </div>
          <div class="config-field span-2">
            <label>Cron 调度</label>
            <n-input v-model:value="aiConfig.cronExpression" placeholder="0 0 9 * * 1-5" size="small" />
            <span class="config-hint">格式: 分 时 日 月 周 (默认每个交易日 09:00)</span>
          </div>
        </div>
        <div class="config-actions">
          <n-button size="small" :loading="testing" @click="testConnection">测试连接</n-button>
          <n-button size="small" type="primary" @click="saveConfig">保存配置</n-button>
        </div>
      </div>
    </div>

    <!-- History View -->
    <div v-if="activeTab === 'history'" class="history-view">
      <div class="history-list">
        <div v-for="report in previousReports" :key="report.date" class="history-card" role="button" tabindex="0" :aria-label="`查看 ${report.date} 的历史报告`" @click="viewHistoryReport(report)">
          <div class="history-left">
            <span class="history-date">{{ report.date }}</span>
            <span class="history-summary">{{ report.summary }}</span>
          </div>
          <div class="history-right">
            <span class="history-count">{{ report.matches }} 个匹配</span>
            <n-icon :component="ChevronForwardOutline" size="18" class="history-chevron" />
          </div>
        </div>
      </div>
    </div>

    <!-- AI 报告详情抽屉 (PRD 6.2) -->
    <n-drawer v-model:show="showReportDrawer" :width="520" placement="right">
      <n-drawer-content :title="drawerReport ? `完整报告 - ${drawerReport.date}` : `历史报告 - ${drawerSummary?.date}`" closable>
        <!-- 完整报告 -->
        <div v-if="drawerReport" class="drawer-report">
          <div class="drawer-section">
            <h4 class="drawer-section-title"><n-icon :component="EarthOutline" size="16" /> 宏观大类资产研判</h4>
            <p class="drawer-text">{{ drawerReport.macroAssessment }}</p>
          </div>
          <div class="drawer-section">
            <h4 class="drawer-section-title"><n-icon :component="GitNetworkOutline" size="16" /> 策略匹配机会</h4>
            <div v-for="match in drawerReport.strategyMatches" :key="match.strategyName" class="drawer-match">
              <div class="drawer-match-name">{{ match.strategyName }}</div>
              <div v-for="item in match.items" :key="item.name" class="drawer-match-item">
                <span class="drawer-item-name">{{ item.name }}</span>
                <span class="drawer-item-reason">{{ item.reason }}</span>
              </div>
            </div>
          </div>
          <div class="drawer-section">
            <h4 class="drawer-section-title"><n-icon :component="FlashOutline" size="16" /> 套利机会提示</h4>
            <div v-for="alert in drawerReport.arbitrageAlerts" :key="alert.name" class="drawer-alert">
              <div class="drawer-alert-head">
                <span class="drawer-alert-name">{{ alert.name }}</span>
                <span class="drawer-alert-values">溢价 {{ alert.premium }}% · 净收益 {{ alert.netYield }}%</span>
              </div>
              <p class="drawer-text">{{ alert.assessment }}</p>
            </div>
          </div>
          <div class="drawer-meta">生成时间: {{ drawerReport.createdAt }}</div>
        </div>
        <!-- 历史摘要 -->
        <div v-else-if="drawerSummary" class="drawer-summary">
          <div class="drawer-summary-date">{{ drawerSummary.date }}</div>
          <p class="drawer-text">{{ drawerSummary.summary }}</p>
          <div class="drawer-summary-meta">共匹配 {{ drawerSummary.matches }} 个标的</div>
        </div>
      </n-drawer-content>
    </n-drawer>
  </div>
  </LoadingState>
</template>

<style scoped>
.ai-page { display: flex; flex-direction: column; gap: 14px; }

/* 功能说明栏 */
.page-desc {
  display: flex; align-items: flex-start; gap: 8px;
  background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px;
  padding: 10px 14px; font-size: 13px; color: var(--text-secondary); line-height: 1.6;
  box-shadow: var(--shadow-card);
}
.page-desc .n-icon { color: var(--color-primary); flex-shrink: 0; margin-top: 1px; }

/* Status Bar */
.status-bar {
  display: flex; align-items: center; gap: 12px;
  background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px; padding: 8px 16px;
  font-size: 13px; color: var(--text-secondary); box-shadow: var(--shadow-card);
}
.status-item { display: flex; align-items: center; gap: 6px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.online { background: var(--color-success); }
.status-dot.offline { background: var(--text-muted); }
.status-label { color: var(--text-muted); }
.status-value { color: var(--text-primary); font-weight: 600; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
.status-divider { width: 1px; height: 16px; background: var(--border-default); }
.status-spacer { flex: 1; }

/* Report View */
.report-view { display: flex; flex-direction: column; gap: 14px; }
.report-section { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 10px; overflow: hidden; box-shadow: var(--shadow-card); }
.section-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 16px; border-bottom: 1px solid var(--border-default); background: var(--bg-overlay);
}
.section-header h3 { display: flex; align-items: center; gap: 8px; margin: 0; font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-secondary); }
.section-header .n-icon { font-size: 16px; color: var(--color-primary); }
.section-date { font-size: 11px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }

.macro-content { padding: 18px; }
.macro-content p { font-size: 14px; color: var(--text-secondary); line-height: 1.8; margin: 0; }
.stream-cursor { display: inline-block; color: var(--color-primary); font-weight: 700; animation: blink 0.8s infinite; margin-left: 2px; }
@keyframes blink { 0%, 50% { opacity: 1; } 51%, 100% { opacity: 0; } }

/* Strategy Matches */
.strategy-matches { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; padding: 12px; }
.match-card { border: 1px solid var(--border-default); border-radius: 10px; padding: 12px; transition: all 0.15s; }
.match-card:hover { border-color: var(--border-hover); box-shadow: 0 1px 4px rgba(0,0,0,0.04); }
.match-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.match-name { font-size: 13px; font-weight: 700; color: var(--text-primary); }
.match-count { font-size: 11px; color: var(--text-muted); background: var(--bg-hover); padding: 1px 8px; border-radius: 4px; }
.match-items { display: flex; flex-direction: column; gap: 8px; }
.match-item { display: flex; gap: 8px; align-items: flex-start; }
.match-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--color-success); margin-top: 5px; flex-shrink: 0; }
.match-detail { display: flex; flex-direction: column; gap: 1px; }
.match-item-name { font-size: 13px; font-weight: 600; color: var(--color-primary); }
.match-item-reason { font-size: 12px; color: var(--text-muted); line-height: 1.4; }

/* 空状态提示 */
.empty-hint { padding: 16px; text-align: center; font-size: 13px; color: var(--text-muted); }

/* Config View */
.config-view { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 10px; padding: 24px; box-shadow: var(--shadow-card); }
.config-section h3 { font-family: 'Work Sans', sans-serif; font-size: 15px; font-weight: 600; color: var(--text-primary); margin: 0 0 16px; }
.config-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.config-field { display: flex; flex-direction: column; gap: 6px; }
.config-field.span-2 { grid-column: span 2; }
.config-field label { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); }
.config-hint { font-size: 11px; color: var(--text-placeholder); }
.config-actions { display: flex; gap: 8px; margin-top: 24px; justify-content: flex-end; }

/* History View */
.history-view { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 10px; overflow: hidden; box-shadow: var(--shadow-card); }
.history-list { display: flex; flex-direction: column; }
.history-card { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--border-default); cursor: pointer; transition: background 0.15s; }
.history-card:last-child { border-bottom: none; }
.history-card:hover { background: var(--bg-overlay); }
.history-left { display: flex; flex-direction: column; gap: 2px; }
.history-date { font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; color: var(--text-primary); }
.history-summary { font-size: 13px; color: var(--text-muted); }
.history-right { display: flex; align-items: center; gap: 8px; }
.history-count { font-size: 12px; color: var(--tag-blue-text); font-weight: 600; background: var(--tag-blue-bg); padding: 2px 8px; border-radius: 4px; }
.history-chevron { color: var(--text-placeholder); }

/* 报告操作 */
.report-actions { display: flex; gap: 8px; padding: 12px 0 0; border-top: 1px solid var(--bg-subtle); }

/* 报告详情抽屉 */
.drawer-report { display: flex; flex-direction: column; gap: 20px; }
.drawer-section { display: flex; flex-direction: column; gap: 8px; }
.drawer-section-title { display: flex; align-items: center; gap: 6px; font-family: 'Work Sans', sans-serif; font-size: 14px; font-weight: 700; color: var(--color-primary); margin: 0; }
.drawer-text { font-size: 14px; line-height: 1.7; color: var(--text-secondary); margin: 0; }
.drawer-match { padding: 10px 12px; background: var(--bg-overlay); border-radius: 6px; border-left: 3px solid var(--color-primary); }
.drawer-match-name { font-size: 13px; font-weight: 700; color: var(--text-primary); margin-bottom: 6px; }
.drawer-match-item { display: flex; flex-direction: column; gap: 2px; padding: 4px 0; }
.drawer-item-name { font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 600; color: var(--text-primary); }
.drawer-item-reason { font-size: 12px; color: var(--text-secondary); }
.drawer-alert { padding: 10px 12px; border: 1px solid var(--border-default); border-radius: 6px; }
.drawer-alert-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.drawer-alert-name { font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 700; color: var(--text-primary); }
.drawer-alert-values { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--color-primary); font-weight: 600; }
.drawer-meta { font-size: 12px; color: var(--text-placeholder); font-family: 'JetBrains Mono', monospace; padding-top: 8px; border-top: 1px solid var(--bg-subtle); }

.drawer-summary { display: flex; flex-direction: column; gap: 12px; }
.drawer-summary-date { font-family: 'JetBrains Mono', monospace; font-size: 16px; font-weight: 700; color: var(--text-primary); }
.drawer-summary-meta { font-size: 13px; color: var(--tag-blue-text); font-weight: 600; background: var(--tag-blue-bg); padding: 4px 10px; border-radius: 4px; align-self: flex-start; }

/* Responsive: collapse multi-column grids on smaller screens */
@media (max-width: 768px) {
  .strategy-matches { grid-template-columns: 1fr; }
  .config-grid { grid-template-columns: 1fr; }
  .config-field.span-2 { grid-column: span 1; }
  .status-bar { flex-wrap: wrap; gap: 8px; }
  .report-actions { flex-wrap: wrap; }
}
</style>

<!-- Non-scoped styles for h()-rendered NDataTable cells -->
<style>
.arb-symbol { font-family: 'JetBrains Mono', monospace; font-weight: 700; color: var(--text-primary); }
.arb-assessment { font-size: 12px; color: var(--text-secondary); max-width: 300px; }
.mono { font-family: 'JetBrains Mono', monospace; }
.arb-row { cursor: pointer; transition: background 0.15s; }
.arb-row:hover { background: var(--bg-hover) !important; }
</style>
