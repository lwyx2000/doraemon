<script setup lang="ts">
import { ref, h, computed, onUnmounted } from 'vue'
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
import PageHeader from '../components/PageHeader.vue'
import TabBar from '../components/TabBar.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const { titleWithHelp } = useFieldHelp()

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

// AI Configuration
const aiConfig = ref<AiConfig>({
  provider: 'deepseek',
  apiKey: 'sk-xxxxxxxxxxxxxxxx',
  endpoint: 'https://api.deepseek.com/v1',
  temperature: 0.3,
  cronExpression: '0 0 9 * * 1-5',
  enabled: true,
})

// Mock AI Report (latest)
const latestReport = ref<AiReport>({
  date: '2026-07-22',
  macroAssessment: '当前宏观环境呈现出典型的"弱复苏、低估值"特征。ERP处于近3年82%分位，表明权益资产的性价比较高。DR007维持在1.85%的低位，流动性充裕。市场热度指标仅35%，处于偏低区域。综合判断，当前是逐步增加权益配置的较好时机，建议关注沪深300和中证500的低估值机会。',
  strategyMatches: [
    {
      strategyName: '双低可转债轮动策略',
      items: [
        { name: 'Zhenghong CB 2 (113001)', reason: '双低得分 135.2，价格 124.52，溢价率 10.78%，信用评级 AAA' },
        { name: 'SolarEnergy CB (113004)', reason: '双低得分 112.4，价格 112.30，溢价率 6.54%，信用评级 AAA' },
      ],
    },
    {
      strategyName: 'QDII 溢价套利策略',
      items: [
        { name: 'Harvest Nasdaq QDII (160213)', reason: '溢价率 6.25%，净套利收益 1.82%，存在套利空间' },
        { name: 'Penghua Nasdaq QDII (501306)', reason: '溢价率 5.12%，净套利收益 1.45%，关注 QDII 额度限制' },
      ],
    },
  ],
  arbitrageAlerts: [
    { name: '161129.SZ', premium: 6.25, netYield: 1.82, assessment: '溢价率偏高，套利空间存在但需注意QDII额度限制和汇率风险' },
    { name: '501306.SH', premium: 5.12, netYield: 1.45, assessment: '适度溢价，建议分批参与套利' },
    { name: '160311.SH', premium: -2.10, netYield: 0.85, assessment: '折价状态，长期配置价值凸显' },
  ],
  createdAt: '2026-07-22 09:00:00',
})

// Previous reports
const previousReports = ref([
  { date: '2026-07-21', summary: '市场继续缩量调整，创业板估值偏高，建议控制成长仓位', matches: 4 },
  { date: '2026-07-20', summary: '沪深300估值处于历史低位，中证500出现机会信号', matches: 5 },
  { date: '2026-07-19', summary: '流动性维持宽松，REITs配置价值提升', matches: 3 },
  { date: '2026-07-18', summary: 'QDII溢价套利空间扩大，关注纳指相关LOF', matches: 6 },
])

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

function generateReport() {
  if (isStreaming.value) {
    stopStreaming()
    return
  }
  // 模拟流式输出: 逐字渲染 macroAssessment
  const fullText = latestReport.value.macroAssessment
  streamingText.value = ''
  isStreaming.value = true
  let idx = 0
  const chunkSize = 3 // 每次输出 3 个字符
  message.loading('AI 正在分析市场数据...', { duration: 1500 })
  streamTimer = setInterval(() => {
    if (idx >= fullText.length) {
      stopStreaming()
      message.success('分析报告已生成')
      return
    }
    streamingText.value += fullText.slice(idx, idx + chunkSize)
    idx += chunkSize
  }, 30)
}

const displayedMacro = computed(() =>
  isStreaming.value ? streamingText.value : latestReport.value.macroAssessment,
)

function saveConfig() {
  message.success('AI 配置已保存')
}

const testing = ref(false)
async function testConnection() {
  if (testing.value) return
  testing.value = true
  const providerLabel = providers.find(p => p.value === aiConfig.provider)?.label ?? aiConfig.provider
  message.loading(`正在测试 ${providerLabel} (${aiConfig.endpoint || '默认端点'}) 连接...`, { duration: 1500 })
  await new Promise(resolve => setTimeout(resolve, 1500))
  testing.value = false
  const ok = Boolean(aiConfig.apiKey)
  if (ok) {
    message.success(`连接成功：${providerLabel} 响应正常，模型 ${aiConfig.model || '默认'}`)
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
  <div class="ai-page">
    <!-- Page Header -->
    <PageHeader title="AI决策中心" subtitle="AI 智能决策中心 — 宏观分析、策略匹配与套利机会挖掘" help-key="aiDecision">
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
        <span class="status-dot online" />
        <span class="status-text">AI 服务: <strong>在线</strong></span>
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
</template>

<style scoped>
.ai-page { display: flex; flex-direction: column; gap: 12px; }

/* Status Bar */
.status-bar {
  display: flex; align-items: center; gap: 12px;
  background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px; padding: 8px 16px;
  font-size: 12px; color: var(--text-secondary);
}
.status-item { display: flex; align-items: center; gap: 6px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.online { background: var(--color-success); }
.status-label { color: var(--text-muted); }
.status-value { color: var(--text-primary); font-weight: 600; font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.status-divider { width: 1px; height: 16px; background: var(--border-default); }
.status-spacer { flex: 1; }

/* Report View */
.report-view { display: flex; flex-direction: column; gap: 12px; }
.report-section { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }
.section-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 16px; border-bottom: 1px solid var(--border-default); background: var(--bg-overlay);
}
.section-header h3 { display: flex; align-items: center; gap: 8px; margin: 0; font-family: 'Work Sans', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-secondary); }
.section-header .n-icon { font-size: 16px; color: var(--color-primary); }
.section-date { font-size: 10px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }

.macro-content { padding: 16px; }
.macro-content p { font-size: 13px; color: var(--text-secondary); line-height: 1.8; margin: 0; }
.stream-cursor { display: inline-block; color: var(--color-primary); font-weight: 700; animation: blink 0.8s infinite; margin-left: 2px; }
@keyframes blink { 0%, 50% { opacity: 1; } 51%, 100% { opacity: 0; } }

/* Strategy Matches */
.strategy-matches { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 12px; }
.match-card { border: 1px solid var(--border-default); border-radius: 8px; padding: 12px; transition: all 0.15s; }
.match-card:hover { border-color: var(--border-hover); box-shadow: 0 1px 4px rgba(0,0,0,0.04); }
.match-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.match-name { font-size: 12px; font-weight: 700; color: var(--text-primary); }
.match-count { font-size: 10px; color: var(--text-muted); background: var(--bg-hover); padding: 1px 8px; border-radius: 4px; }
.match-items { display: flex; flex-direction: column; gap: 8px; }
.match-item { display: flex; gap: 8px; align-items: flex-start; }
.match-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--color-success); margin-top: 5px; flex-shrink: 0; }
.match-detail { display: flex; flex-direction: column; gap: 1px; }
.match-item-name { font-size: 12px; font-weight: 600; color: var(--color-primary); }
.match-item-reason { font-size: 11px; color: var(--text-muted); line-height: 1.4; }

/* Config View */
.config-view { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px; padding: 24px; }
.config-section h3 { font-family: 'Work Sans', sans-serif; font-size: 14px; font-weight: 600; color: var(--text-primary); margin: 0 0 16px; }
.config-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.config-field { display: flex; flex-direction: column; gap: 6px; }
.config-field.span-2 { grid-column: span 2; }
.config-field label { font-family: 'Work Sans', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); }
.config-hint { font-size: 10px; color: var(--text-placeholder); }
.config-actions { display: flex; gap: 8px; margin-top: 24px; justify-content: flex-end; }

/* History View */
.history-view { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }
.history-list { display: flex; flex-direction: column; }
.history-card { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--border-default); cursor: pointer; transition: background 0.15s; }
.history-card:last-child { border-bottom: none; }
.history-card:hover { background: var(--bg-overlay); }
.history-left { display: flex; flex-direction: column; gap: 2px; }
.history-date { font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 700; color: var(--text-primary); }
.history-summary { font-size: 12px; color: var(--text-muted); }
.history-right { display: flex; align-items: center; gap: 8px; }
.history-count { font-size: 11px; color: var(--tag-blue-text); font-weight: 600; background: var(--tag-blue-bg); padding: 2px 8px; border-radius: 4px; }
.history-chevron { color: var(--text-placeholder); }

/* 报告操作 */
.report-actions { display: flex; gap: 8px; padding: 12px 0 0; border-top: 1px solid var(--bg-subtle); }

/* 报告详情抽屉 */
.drawer-report { display: flex; flex-direction: column; gap: 20px; }
.drawer-section { display: flex; flex-direction: column; gap: 8px; }
.drawer-section-title { display: flex; align-items: center; gap: 6px; font-family: 'Work Sans', sans-serif; font-size: 13px; font-weight: 700; color: var(--color-primary); margin: 0; }
.drawer-text { font-size: 13px; line-height: 1.7; color: var(--text-secondary); margin: 0; }
.drawer-match { padding: 10px 12px; background: var(--bg-overlay); border-radius: 6px; border-left: 3px solid var(--color-primary); }
.drawer-match-name { font-size: 12px; font-weight: 700; color: var(--text-primary); margin-bottom: 6px; }
.drawer-match-item { display: flex; flex-direction: column; gap: 2px; padding: 4px 0; }
.drawer-item-name { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 600; color: var(--text-primary); }
.drawer-item-reason { font-size: 11px; color: var(--text-secondary); }
.drawer-alert { padding: 10px 12px; border: 1px solid var(--border-default); border-radius: 6px; }
.drawer-alert-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.drawer-alert-name { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700; color: var(--text-primary); }
.drawer-alert-values { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--color-primary); font-weight: 600; }
.drawer-meta { font-size: 11px; color: var(--text-placeholder); font-family: 'JetBrains Mono', monospace; padding-top: 8px; border-top: 1px solid var(--bg-subtle); }

.drawer-summary { display: flex; flex-direction: column; gap: 12px; }
.drawer-summary-date { font-family: 'JetBrains Mono', monospace; font-size: 16px; font-weight: 700; color: var(--text-primary); }
.drawer-summary-meta { font-size: 12px; color: var(--tag-blue-text); font-weight: 600; background: var(--tag-blue-bg); padding: 4px 10px; border-radius: 4px; align-self: flex-start; }

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
