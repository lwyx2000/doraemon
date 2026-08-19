<script setup lang="ts">
defineOptions({ name: 'AlertCenter' })
import { ref, reactive, h, computed, onMounted } from 'vue'
import { NButton, NSwitch, NIcon, NModal, NDrawer, NDrawerContent, NInput, NInputNumber, NSelect, NCheckboxGroup, NCheckbox, NDataTable, useMessage, useDialog } from 'naive-ui'
import {
  AddCircleOutline,
  WarningOutline,
  NotificationsOutline,
  InformationOutline,
  SettingsOutline,
  TrashOutline,
  EyeOutline,
  SearchOutline,
  RefreshOutline,
} from '@vicons/ionicons5'
import type { ConvertibleBond, FundItem, ReitItem, AlertEvent } from '../types'
import { useAsyncData } from '../composables/useApi'
import { api } from '../utils/api'
import { analyzeArbitrageBatch } from '../utils/arbitrage'
import { analyzeConversionBatch, analyzeVolatilityBatch } from '../utils/convertibleBond'
import { analyzeClosedFundBatch } from '../utils/closedFund'
import { analyzeReitsBatch } from '../utils/reits'
import type { AlertRule } from '../types'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import DataPanel from '../components/DataPanel.vue'
import LoadingState from '../components/LoadingState.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'

const message = useMessage()
const dialog = useDialog()
const { data: alertRules, loading, error, refresh: refetch } = useAsyncData<AlertRule[]>(() => api.getAlertRules())
// 实时信号基于 53 上 AkShare 的真实数据（可转债 / 基金 / REITs），不再使用前端 mock
const { data: bonds, execute: executeBonds } = useAsyncData<ConvertibleBond[]>(() => api.getConvertibleBonds())
const { data: funds, execute: executeFunds } = useAsyncData<FundItem[]>(() => api.getFunds())
const { data: reits, execute: executeReits } = useAsyncData<ReitItem[]>(() => api.getReits())
onMounted(() => {
  refetch()
  executeBonds()
  executeFunds()
  executeReits()
  loadAlertEvents()
})

// ---- 预警历史（从后端 /alerts/events 加载，不再写死）----
const alertEvents = ref<AlertEvent[]>([])
const eventsLoading = ref(false)
const scanning = ref(false)

async function loadAlertEvents() {
  eventsLoading.value = true
  try {
    const res = await api.getAlertEvents({ page: 1, page_size: 50 })
    alertEvents.value = res.items
  } catch {
    alertEvents.value = []
  } finally {
    eventsLoading.value = false
  }
}

async function runScan() {
  scanning.value = true
  try {
    const result = await api.scanAlerts()
    message.success(`扫描完成：检查 ${result.scanned_rules} 条规则，触发 ${result.triggered_events} 个预警`)
    // 刷新事件列表
    await loadAlertEvents()
  } catch (e: any) {
    message.error('扫描失败: ' + (e?.message || e))
  } finally {
    scanning.value = false
  }
}

// 将 AlertEvent 转换为表格展示格式
interface HistoryItem {
  id: string
  rule: string
  target: string
  value: string
  triggered: string
  status: 'active' | 'resolved'
  rawEvent: AlertEvent
}

const alertHistory = computed<HistoryItem[]>(() => {
  return alertEvents.value.map(ev => ({
    id: String(ev.id),
    rule: getRuleName(ev.rule_id),
    target: ev.target_name || ev.target_code || '-',
    value: ev.actual_value != null ? String(ev.actual_value) : '-',
    triggered: formatTime(ev.triggered_at),
    status: ev.is_read ? 'resolved' as const : 'active' as const,
    rawEvent: ev,
  }))
})

function getRuleName(ruleId: string): string {
  const rule = (alertRules.value ?? []).find(r => r.id === ruleId)
  return rule?.name || '未知规则'
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

interface SignalItem {
  id: string
  type: string
  title: string
  desc: string
  severity: 'high' | 'medium' | 'low'
  time: string
}

// ---- 动态信号生成：基于 53 AkShare 真实数据分析结果计算实时信号 ----
const realtimeSignals = computed<SignalItem[]>(() => {
  const signals: SignalItem[] = []
  let idx = 0

  // 递增时间戳生成器：格式 14:2X:XX
  const add = (type: string, title: string, desc: string, severity: 'high' | 'medium' | 'low') => {
    const sec = idx % 60
    const min = 20 + Math.floor(idx / 60)
    signals.push({
      id: `sig-${idx}`,
      type,
      title,
      desc,
      severity,
      time: `14:${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}`,
    })
    idx++
  }

  // a) ETF/LOF 套利信号（排除封闭基金，封闭基金由专项分析覆盖）
  const arbitrageFunds = (funds.value ?? []).filter(f => f.type !== 'closed')
  const arbResults = analyzeArbitrageBatch(arbitrageFunds)
  arbitrageFunds.forEach(fund => {
    const a = arbResults.get(fund.code)
    if (!a) return
    if (a.feasibility === 'infeasible') {
      add(
        'arbitrage',
        `${fund.name} 套利不可行`,
        a.traps.length ? a.traps.join('；') : `资金容量${a.capitalLabel}，套利收益归零`,
        'high',
      )
    } else if (a.feasibility === 'risky') {
      add(
        'arbitrage',
        `${fund.name} 套利有风险`,
        `T+${a.holdingDays}敞口${a.riskExposure}%，调整收益${a.adjustedYieldLow}%~${a.adjustedYieldHigh}%`,
        'medium',
      )
    } else if (a.feasibility === 'feasible' && Math.abs(fund.premium_pct) > 0.5) {
      add(
        'arbitrage',
        `${fund.name} 套利机会`,
        `折溢价${fund.premium_pct}%，净套利收益${fund.net_arbitrage_yield}%`,
        'low',
      )
    }
  })

  // b) 可转债信号（转股套利 + 波动率）
  const convResults = analyzeConversionBatch(bonds.value ?? [])
  const volResults = analyzeVolatilityBatch(bonds.value ?? [])
  ;(bonds.value ?? []).forEach(bond => {
    const conv = convResults.get(bond.code)
    const vol = volResults.get(bond.code)
    if (conv) {
      if (conv.feasibility === 'feasible') {
        add(
          'conversion',
          `${bond.name} 转股套利可行`,
          `理论收益率${conv.theoreticalYield}%，T+1敞口${conv.overnightRisk}%`,
          'low',
        )
      } else if (conv.feasibility === 'infeasible') {
        add(
          'conversion',
          `${bond.name} 转股套利陷阱`,
          conv.blockers.length ? conv.blockers.join('；') : '负溢价但存在阻碍',
          'high',
        )
      }
    }
    if (vol) {
      if (vol.signal === 'undervalued') {
        add(
          'volatility',
          `${bond.name} IV低估`,
          `IV=${vol.iv}% HV=${vol.hv}%，价差${vol.spread}%，Delta对冲买入信号`,
          'medium',
        )
      } else if (vol.signal === 'overvalued') {
        add(
          'volatility',
          `${bond.name} IV高估`,
          `IV=${vol.iv}% HV=${vol.hv}%，价差${vol.spread}%，期权部分被高估`,
          'medium',
        )
      }
    }
  })

  // c) 封闭基金信号（折价收敛 / 流动性 / 信用风险）
  const closedFunds = (funds.value ?? []).filter(f => f.type === 'closed')
  const closedResults = analyzeClosedFundBatch(closedFunds)
  closedFunds.forEach(fund => {
    const c = closedResults.get(fund.code)
    if (!c) return
    if (c.convergence === 'uncertain') {
      add(
        'convergence',
        `${fund.name} 折价收敛不确定`,
        `不转LOF且剩余${c.remainingDays}天，折价${c.discountPct}%`,
        'high',
      )
    }
    if (c.liquidity === 'illiquid') {
      add(
        'liquidity',
        `${fund.name} 流动性极差`,
        `日成交${c.volume}手，换手${c.turnoverEstimate}%`,
        'medium',
      )
    }
    if (c.creditRisk === 'risky') {
      add(
        'credit',
        `${fund.name} 信用风险`,
        `评级${c.creditRating}，底层${c.underlyingType}`,
        'high',
      )
    }
  })

  // d) REITs 信号（NAV折溢价 / 分红可持续性 / 流动性）
  const reitsResults = analyzeReitsBatch(reits.value ?? [])
  ;(reits.value ?? []).forEach(reit => {
    const r = reitsResults.get(reit.code)
    if (!r) return
    if (r.navLevel === 'premium') {
      add(
        'nav',
        `${reit.name} NAV溢价${r.navPremiumPct}%`,
        r.safetyMargin,
        'medium',
      )
    }
    if (r.sustainability === 'at_risk') {
      add(
        'sustainability',
        `${reit.name} 分红可持续性差`,
        `DSCR=${r.dscr}，出租率趋势${r.occupancyTrend}%，杠杆率${r.leverageRatio}%`,
        'high',
      )
    }
    if (r.liquidity === 'illiquid') {
      add(
        'liquidity',
        `${reit.name} 流动性极差`,
        `日成交${r.volume}手`,
        'low',
      )
    }
  })

  return signals
})

// ---- 信号严重级别统计 ----
const highSignalCount = computed(() => realtimeSignals.value.filter(s => s.severity === 'high').length)
const mediumSignalCount = computed(() => realtimeSignals.value.filter(s => s.severity === 'medium').length)
const lowSignalCount = computed(() => realtimeSignals.value.filter(s => s.severity === 'low').length)

// ---- 信号筛选 ----
const signalFilter = ref<'all' | 'high' | 'medium' | 'low'>('all')
const filteredSignals = computed(() => {
  if (signalFilter.value === 'all') return realtimeSignals.value
  return realtimeSignals.value.filter(s => s.severity === signalFilter.value)
})

// ---- 预警规则创建弹窗 (PRD 页七) ----
const showRuleModal = ref(false)
const ruleForm = reactive<{ name: string; type: AlertRule['type']; target: string; condition: AlertRule['condition']; value: number | null; channels: AlertRule['channels'] }>({
  name: '', type: 'premium', target: '', condition: 'above', value: null, channels: ['popup'],
})

const typeOptions = [
  { label: '价格', value: 'price' },
  { label: '溢价率', value: 'premium' },
  { label: '折价率', value: 'discount' },
  { label: 'YTM', value: 'ytm' },
]

const conditionOptions = [
  { label: '高于', value: 'above' },
  { label: '低于', value: 'below' },
  { label: '穿越', value: 'crosses' },
]

const channelOptions = [
  { label: '系统弹窗', value: 'popup' },
  { label: '钉钉机器人', value: 'dingtalk' },
  { label: '企业微信', value: 'wechat' },
  { label: '邮件', value: 'email' },
]

function openRuleModal() {
  ruleForm.name = ''
  ruleForm.type = 'premium'
  ruleForm.target = ''
  ruleForm.condition = 'above'
  ruleForm.value = null
  ruleForm.channels = ['popup']
  showRuleModal.value = true
}

async function saveRule() {
  if (!ruleForm.name.trim()) { message.warning('请输入规则名称'); return }
  if (!ruleForm.target.trim()) { message.warning('请输入监控标的'); return }
  if (ruleForm.value === null) { message.warning('请输入触发阈值'); return }
  if (ruleForm.channels.length === 0) { message.warning('请至少选择一个通知渠道'); return }
  const created = await api.createAlertRule({
    name: ruleForm.name.trim(),
    type: ruleForm.type,
    target: ruleForm.target.trim(),
    condition: ruleForm.condition,
    value: ruleForm.value,
    channels: [...ruleForm.channels],
  })
  alertRules.value?.push(created)
  message.success(`已创建: ${ruleForm.name}`)
  showRuleModal.value = false
}

// ---- 规则模板库 ----
const showRuleTemplates = ref(false)
interface RuleTemplate { name: string; type: AlertRule['type']; target: string; condition: AlertRule['condition']; value: number; channels: AlertRule['channels']; desc: string }
const ruleTemplates: RuleTemplate[] = [
  { name: '溢价率突破 5%', type: 'premium', target: '', condition: 'above', value: 5, channels: ['popup', 'dingtalk'], desc: '监控标的溢价率超过 5% 触发' },
  { name: '折价率低于 -10%', type: 'discount', target: '', condition: 'below', value: -10, channels: ['popup'], desc: '封闭基金折价加深至 -10% 触发' },
  { name: '转债价格破 120', type: 'price', target: '', condition: 'below', value: 120, channels: ['popup', 'wechat'], desc: '可转债价格低于 120 触发买入提醒' },
  { name: 'YTM 高于 4%', type: 'ytm', target: '', condition: 'above', value: 4, channels: ['popup', 'email'], desc: '到期收益率高于 4% 触发配置价值提醒' },
]
async function importRuleTemplate(tpl: RuleTemplate) {
  const created = await api.createAlertRule({
    name: tpl.name + ' (副本)',
    type: tpl.type,
    target: tpl.target || '全部标的',
    condition: tpl.condition,
    value: tpl.value,
    channels: [...tpl.channels],
  })
  alertRules.value?.push(created)
  message.success(`已导入模板: ${tpl.name}`)
  showRuleTemplates.value = false
}

// ---- 历史详情抽屉 ----
const showDetailDrawer = ref(false)
const detailItem = ref<HistoryItem | null>(null)

function viewHistoryDetail(item: HistoryItem) {
  detailItem.value = item
  showDetailDrawer.value = true
  // 标记为已读
  if (!item.rawEvent.is_read) {
    api.markAlertEventRead(item.rawEvent.id).then(() => {
      loadAlertEvents()
    }).catch(() => {})
  }
}

function toggleRule(rule: AlertRule) {
  const next = !rule.active
  rule.active = next
  api.updateAlertRule(rule.id, { active: next }).catch(() => {
    rule.active = !next
    message.error('更新状态失败')
  })
  message.success(`${rule.name}: ${next ? '已启用' : '已禁用'}`)
}

function deleteRule(rule: AlertRule) {
  dialog.warning({
    title: '删除规则',
    content: `确定删除「${rule.name}」吗？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      const idx = alertRules.value?.findIndex(r => r.id === rule.id)
      if (idx !== undefined && idx > -1) alertRules.value!.splice(idx, 1)
      try {
        await api.deleteAlertRule(rule.id)
        message.success(`已删除: ${rule.name}`)
      } catch {
        message.error(`删除失败: ${rule.name}`)
      }
    },
  })
}

function clearAllResolved() {
  // 将所有已读事件标记为已解决（前端过滤显示）
  alertEvents.value = alertEvents.value.filter(ev => ev.is_read === false)
  message.success('已清除所有已解决通知')
}

const severityConfig = {
  high: { color: 'var(--tag-red-text)', bg: 'var(--tag-red-bg)', icon: WarningOutline },
  medium: { color: 'var(--tag-orange-text)', bg: 'var(--tag-orange-bg)', icon: NotificationsOutline },
  low: { color: 'var(--tag-blue-text)', bg: 'var(--tag-blue-bg)', icon: InformationOutline },
} as const

const typeConfig: Record<string, { label: string; color: string; bg: string }> = {
  premium: { label: '溢价预警', color: 'var(--tag-red-text)', bg: 'var(--tag-red-bg)' },
  discount: { label: '折价机会', color: 'var(--tag-blue-text)', bg: 'var(--tag-blue-bg)' },
  redemption: { label: '强赎风险', color: 'var(--tag-red-text)', bg: 'var(--tag-red-bg)' },
  info: { label: '信息提示', color: 'var(--tag-gray-text)', bg: 'var(--tag-gray-bg)' },
  arbitrage: { label: '套利信号', color: 'var(--tag-blue-text)', bg: 'var(--tag-blue-bg)' },
  conversion: { label: '转股套利', color: 'var(--tag-green-text)', bg: 'var(--tag-green-bg)' },
  volatility: { label: '波动率', color: 'var(--tag-orange-text)', bg: 'var(--tag-orange-bg)' },
  convergence: { label: '折价收敛', color: 'var(--tag-blue-text)', bg: 'var(--tag-blue-bg)' },
  nav: { label: 'NAV折溢价', color: 'var(--tag-blue-text)', bg: 'var(--tag-blue-bg)' },
  sustainability: { label: '可持续性', color: 'var(--tag-red-text)', bg: 'var(--tag-red-bg)' },
  liquidity: { label: '流动性', color: 'var(--tag-orange-text)', bg: 'var(--tag-orange-bg)' },
  credit: { label: '信用风险', color: 'var(--tag-red-text)', bg: 'var(--tag-red-bg)' },
}

const historyColumns = [
  { title: '规则', key: 'rule', render: (row: HistoryItem) => h('span', { class: 'rule-cell' }, row.rule) },
  { title: '标的', key: 'target', render: (row: HistoryItem) => h('span', { class: 'target-cell' }, row.target) },
  { title: '触发值', key: 'value', align: 'right' as const, render: (row: HistoryItem) => h('span', { class: 'mono' }, row.value) },
  { title: '触发时间', key: 'triggered', render: (row: HistoryItem) => h('span', { class: 'mono' }, row.triggered) },
  {
    title: '状态', key: 'status', align: 'center' as const,
    render: (row: HistoryItem) => h('span', { class: ['status-badge', row.status] },
      row.status === 'active' ? '活跃中' : '已解决'),
  },
  {
    title: '操作', key: 'actions', align: 'center' as const,
    render: (row: HistoryItem) => h('button', {
      class: 'action-btn',
      onClick: (e: Event) => { e.stopPropagation(); viewHistoryDetail(row) },
    }, [h(NIcon, { component: EyeOutline, size: 16 })]),
  },
]

const historyRowProps = (row: HistoryItem) => ({
  style: 'cursor: pointer',
  onClick: () => viewHistoryDetail(row),
})

const historyFilter = ref<'all' | 'today' | 'week'>('all')

const filteredHistory = computed(() => {
  if (historyFilter.value === 'all') return alertHistory.value
  if (historyFilter.value === 'today') {
    const today = new Date().toDateString()
    return alertHistory.value.filter(h => new Date(h.rawEvent.triggered_at).toDateString() === today)
  }
  if (historyFilter.value === 'week') {
    const now = new Date()
    const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
    return alertHistory.value.filter(h => new Date(h.rawEvent.triggered_at) >= weekAgo)
  }
  return alertHistory.value
})
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    skeleton
    :min-height="520"
    text="正在加载预警数据..."
    @retry="refetch"
  >
    <div v-if="alertRules" class="alert-page">
    <!-- Page Header -->
    <PageHeader title="预警与信号中心" subtitle="实时预警监控与规则管理 — 跟踪折溢价异动、强赎风险和套利机会" helpKey="alertCenter">
      <template #actions>
        <n-button size="small" :loading="scanning" @click="runScan">
          <template #icon><n-icon :component="RefreshOutline" /></template>
          扫描
        </n-button>
        <n-button size="small" @click="clearAllResolved">清除已解决</n-button>
        <n-button size="small" type="primary" @click="openRuleModal">
          <template #icon>
            <n-icon :component="AddCircleOutline" />
          </template>
          新建规则
        </n-button>
      </template>
    </PageHeader>
    <GlossaryPanel page-key="alertCenter" />

    <!-- Top Row: Summary Stats -->
    <div class="stat-grid stat-grid-signals">
      <StatCard label="高危信号" :value="highSignalCount" sub="需立即关注" color="#ba1a1a" />
      <StatCard label="中危信号" :value="mediumSignalCount" sub="风险提示" color="#c47a00" />
      <StatCard label="套利机会" :value="lowSignalCount" sub="低优先级机会" color="#005ea1" tip="综合可行性判定：可行=资金充足且敞口可控；有风险=敞口可能吞噬收益；不可行=限购或停牌导致无法执行。" />
      <StatCard label="活跃规则" :value="alertRules?.filter(r => r.active).length ?? 0" :sub="`规则总数: ${alertRules?.length ?? 0}`" color="#005ea1" />
      <StatCard label="未读预警" :value="alertEvents.filter(e => !e.is_read).length" :sub="`总事件: ${alertEvents.length}`" />
      <StatCard label="通知渠道" :value="(alertRules ?? []).flatMap(r => r.channels).filter((v, i, a) => a.indexOf(v) === i).length" sub="已配置渠道数" />
    </div>

    <!-- Main Content Grid -->
    <div class="main-grid">
      <!-- Left: Real-time Signal Feed -->
      <DataPanel title="实时信号" class="signal-panel">
        <template #actions>
          <span class="live-badge">
            <span class="live-dot" />直播
          </span>
        </template>
        <div class="signal-filters">
          <button
            v-for="opt in [{k:'all',l:'全部'},{k:'high',l:'高危'},{k:'medium',l:'中危'},{k:'low',l:'机会'}]"
            :key="opt.k"
            :class="['signal-filter-btn', { active: signalFilter === opt.k }]"
            @click="signalFilter = opt.k as 'all' | 'high' | 'medium' | 'low'"
          >{{ opt.l }}</button>
        </div>
        <div class="signal-feed">
          <div
            v-for="signal in filteredSignals"
            :key="signal.id"
            class="signal-item"
            @click="message.info(signal.title)"
          >
            <div class="signal-icon" :style="{ background: severityConfig[signal.severity].bg }">
              <n-icon
                :component="severityConfig[signal.severity].icon"
                size="18"
                :style="{ color: severityConfig[signal.severity].color }"
              />
            </div>
            <div class="signal-content">
              <div class="signal-top">
                <span class="signal-title">{{ signal.title }}</span>
                <span class="signal-time">{{ signal.time }}</span>
              </div>
              <span class="signal-desc">{{ signal.desc }}</span>
              <div class="signal-tags">
                <span class="signal-type-tag" :style="{ background: typeConfig[signal.type]?.bg, color: typeConfig[signal.type]?.color }">
                  {{ typeConfig[signal.type]?.label || signal.type }}
                </span>
                <span :class="['severity-tag', signal.severity]">{{ signal.severity === 'high' ? '高' : signal.severity === 'medium' ? '中' : '低' }}</span>
              </div>
            </div>
          </div>
        </div>
      </DataPanel>

      <!-- Right: Rules Management -->
      <DataPanel title="预警规则" class="rules-panel">
        <template #actions>
          <n-button size="tiny" text @click="showRuleTemplates = true">
            <n-icon :component="SettingsOutline" size="16" />
          </n-button>
        </template>
        <div class="rules-list">
          <div v-for="rule in (alertRules ?? [])" :key="rule.id" class="rule-item">
            <div class="rule-main">
              <div class="rule-info">
                <span class="rule-name">{{ rule.name }}</span>
                <div class="rule-meta">
                  <span class="rule-target">{{ rule.target }}</span>
                  <span class="rule-condition">{{ rule.condition === 'above' ? '>' : '<' }} {{ rule.value }}</span>
                </div>
              </div>
              <div class="rule-controls">
                <n-switch :value="rule.active" size="small" :aria-label="`${rule.name} 启用开关`" @update:value="() => toggleRule(rule)" />
                <button class="rule-delete" aria-label="删除规则" @click.stop="deleteRule(rule)">
                  <n-icon :component="TrashOutline" size="16" />
                </button>
              </div>
            </div>
            <div class="rule-channels">
              <span v-for="ch in rule.channels" :key="ch" class="ch-tag">{{ ch }}</span>
            </div>
          </div>
        </div>
        <div class="add-rule-bar" @click="openRuleModal">
          <n-icon :component="AddCircleOutline" size="18" />
          <span>新增预警规则</span>
        </div>
      </DataPanel>
    </div>

    <!-- Alert History Table -->
    <DataPanel title="预警历史">
      <template #actions>
        <div class="history-filters">
          <button
            v-for="opt in [{k:'all',l:'全部'},{k:'today',l:'今日'},{k:'week',l:'本周'}]"
            :key="opt.k"
            :class="['filter-btn', { active: historyFilter === opt.k }]"
            @click="historyFilter = opt.k as 'all' | 'today' | 'week'"
          >{{ opt.l }}</button>
          <n-icon :component="SearchOutline" size="18" class="filter-search-icon" />
        </div>
      </template>
      <n-data-table
        :columns="historyColumns"
        :data="filteredHistory"
        :row-key="(row: HistoryItem) => row.id"
        :bordered="false"
        :single-line="false"
        size="small"
        :row-props="historyRowProps"
      />
    </DataPanel>

    <!-- 预警规则创建弹窗 (PRD 页七) -->
    <n-modal v-model:show="showRuleModal" preset="card" title="新建预警规则" style="width: 520px; max-width: 92vw;" :bordered="false">
      <div class="rule-builder-body">
        <div class="rule-builder-field">
          <label class="rule-builder-label">规则名称</label>
          <n-input v-model:value="ruleForm.name" placeholder="例如：溢价率异动预警" />
        </div>
        <div class="rule-builder-field">
          <label class="rule-builder-label">监控类型</label>
          <n-select v-model:value="ruleForm.type" :options="typeOptions" />
        </div>
        <div class="rule-builder-field">
          <label class="rule-builder-label">监控标的</label>
          <n-input v-model:value="ruleForm.target" placeholder="例如：LOF基金 / 161129.SZ / TechGrowth CB" />
        </div>
        <div class="rule-builder-row">
          <div class="rule-builder-field">
            <label class="rule-builder-label">触发条件</label>
            <n-select v-model:value="ruleForm.condition" :options="conditionOptions" />
          </div>
          <div class="rule-builder-field">
            <label class="rule-builder-label">触发阈值</label>
            <n-input-number v-model:value="ruleForm.value" placeholder="数值" style="width: 100%;" />
          </div>
        </div>
        <div class="rule-builder-field">
          <label class="rule-builder-label">通知渠道</label>
          <n-checkbox-group v-model:value="ruleForm.channels">
            <n-checkbox v-for="ch in channelOptions" :key="ch.value" :value="ch.value" :label="ch.label" />
          </n-checkbox-group>
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px;">
          <n-button size="small" @click="showRuleModal = false">取消</n-button>
          <n-button size="small" type="primary" @click="saveRule">创建规则</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 历史详情抽屉 -->
    <n-drawer v-model:show="showDetailDrawer" :width="420" placement="right">
      <n-drawer-content title="预警详情" closable>
        <div v-if="detailItem" class="detail-body">
          <div class="detail-row">
            <span class="detail-label">关联规则</span>
            <span class="detail-value">{{ detailItem.rule }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">触发标的</span>
            <span class="detail-value mono">{{ detailItem.target }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">触发数值</span>
            <span class="detail-value mono detail-value-highlight">{{ detailItem.value }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">触发时间</span>
            <span class="detail-value mono">{{ detailItem.triggered }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">当前状态</span>
            <span class="detail-value">
              <span :class="['detail-status', detailItem.status]">{{ detailItem.status === 'active' ? '活跃中' : '已解决' }}</span>
            </span>
          </div>
        </div>
      </n-drawer-content>
    </n-drawer>

    <!-- 规则模板库弹窗 -->
    <n-modal v-model:show="showRuleTemplates" preset="card" title="规则模板库" style="width: 520px; max-width: 92vw;" :bordered="false">
      <div style="display: flex; flex-direction: column; gap: 10px;">
        <div v-for="tpl in ruleTemplates" :key="tpl.name" style="display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px; border: 1px solid var(--border-default); border-radius: 8px;">
          <div style="flex: 1; min-width: 0;">
            <div style="font-family: 'Work Sans', sans-serif; font-size: 14px; font-weight: 600; color: var(--text-primary);">{{ tpl.name }}</div>
            <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">{{ tpl.desc }}</div>
            <div style="margin-top: 6px; font-size: 11px; color: var(--text-secondary); font-family: 'JetBrains Mono', monospace;">
              {{ typeOptions.find(o => o.value === tpl.type)?.label }} {{ conditionOptions.find(o => o.value === tpl.condition)?.label }} {{ tpl.value }}
            </div>
          </div>
          <n-button size="small" type="primary" @click="importRuleTemplate(tpl)">导入</n-button>
        </div>
      </div>
    </n-modal>
    </div>
  </LoadingState>
</template>

<style scoped>
.alert-page { display: flex; flex-direction: column; gap: 14px; }

/* Stat grid override for 6 severity/summary cards */
.stat-grid-signals { grid-template-columns: repeat(6, 1fr); }
@media (max-width: 1280px) { .stat-grid-signals { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 768px) { .stat-grid-signals { grid-template-columns: 1fr; } }

/* Summary extras */
.notif-channels { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; }
.channel-badge { padding: 2px 8px; background: var(--tag-gray-bg); color: var(--tag-gray-text); border-radius: 4px; font-size: 11px; font-weight: 600; }

/* Main Grid */
.main-grid { display: grid; grid-template-columns: 1.5fr 1fr; gap: 14px; height: 420px; }

/* Signal Panel */
.signal-panel { display: flex; flex-direction: column; }
.signal-panel :deep(.panel-body) { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.signal-feed { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 4px; }

/* Signal severity filters */
.signal-filters { display: flex; align-items: center; gap: 6px; padding: 8px 12px 4px; border-bottom: 1px solid var(--border-default); }
.signal-filter-btn { padding: 2px 10px; border: 1px solid var(--border-default); border-radius: 4px; background: var(--bg-card); cursor: pointer; font-size: 11px; font-weight: 700; color: var(--text-muted); transition: all 0.15s; }
.signal-filter-btn.active { background: var(--color-primary); color: white; border-color: var(--color-primary); }
.signal-filter-btn:hover:not(.active) { background: var(--bg-hover); }

.signal-item {
  display: flex; gap: 12px; padding: 12px; border-radius: 6px;
  cursor: pointer; transition: background 0.15s; border: 1px solid transparent;
}
.signal-item:hover { background: var(--bg-overlay); border-color: var(--border-default); }

.signal-icon {
  width: 36px; height: 36px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}

.signal-content { flex: 1; min-width: 0; }
.signal-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.signal-title { font-weight: 600; font-size: 14px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.signal-time { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-muted); white-space: nowrap; }
.signal-desc { display: block; font-size: 13px; color: var(--text-muted); margin-top: 2px; }
.signal-tags { display: flex; gap: 4px; margin-top: 6px; }
.signal-type-tag { padding: 1px 6px; border-radius: 2px; font-size: 9px; font-weight: 700; }
.severity-tag { padding: 1px 6px; border-radius: 2px; font-size: 9px; font-weight: 700; }
.severity-tag.high { background: var(--tag-red-bg); color: var(--tag-red-text); }
.severity-tag.medium { background: var(--tag-orange-bg); color: var(--tag-orange-text); }
.severity-tag.low { background: var(--tag-blue-bg); color: var(--tag-blue-text); }

.live-badge {
  display: flex; align-items: center; gap: 4px; padding: 2px 8px;
  background: var(--tag-red-bg); color: var(--tag-red-text); border-radius: 4px;
  font-size: 11px; font-weight: 700; letter-spacing: 0.05em;
}
.live-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--color-danger); animation: pulse 1.5s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

/* Rules Panel */
.rules-panel { display: flex; flex-direction: column; }
.rules-panel :deep(.panel-body) { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.rules-list { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 4px; }

.rule-item { padding: 10px 12px; border-radius: 6px; border: 1px solid var(--border-default); transition: all 0.15s; }
.rule-item:hover { border-color: var(--border-hover); background: var(--bg-hover); }

.rule-main { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.rule-info { flex: 1; min-width: 0; }
.rule-name { font-weight: 600; font-size: 13px; color: var(--text-primary); display: block; }
.rule-meta { display: flex; gap: 8px; margin-top: 4px; }
.rule-target { font-size: 11px; color: var(--text-muted); background: var(--bg-hover); padding: 1px 6px; border-radius: 2px; }
.rule-condition { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--color-primary); font-weight: 700; }

.rule-controls { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.rule-delete { display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; border: none; background: transparent; border-radius: 4px; cursor: pointer; color: var(--text-placeholder); transition: all 0.15s; }
.rule-delete:hover { background: var(--tag-red-bg); color: var(--tag-red-text); }

.rule-channels { display: flex; gap: 4px; margin-top: 6px; }
.ch-tag { padding: 1px 6px; font-size: 9px; background: var(--tag-blue-bg); color: var(--tag-blue-text); border-radius: 2px; font-weight: 600; }

.add-rule-bar {
  display: flex; align-items: center; gap: 8px; padding: 12px 16px;
  border-top: 1px dashed var(--border-default); cursor: pointer; color: var(--text-muted);
  font-size: 13px; font-weight: 600; transition: all 0.15s;
}
.add-rule-bar:hover { background: var(--bg-overlay); color: var(--color-primary); }

.history-filters { display: flex; align-items: center; gap: 8px; }
.filter-btn { padding: 2px 10px; border: 1px solid var(--border-default); border-radius: 4px; background: var(--bg-card); cursor: pointer; font-size: 11px; font-weight: 700; color: var(--text-muted); transition: all 0.15s; }
.filter-btn.active { background: var(--color-primary); color: white; border-color: var(--color-primary); }
.filter-btn:hover:not(.active) { background: var(--bg-hover); }
.filter-search-icon { color: var(--text-muted); cursor: pointer; }

.rule-cell { font-weight: 600; color: var(--text-primary); }
.target-cell { font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--text-secondary); }

.status-badge { display: inline-block; padding: 2px 8px; border-radius: 2px; font-size: 11px; font-weight: 700; }
.status-badge.active { background: var(--tag-red-bg); color: var(--tag-red-text); }
.status-badge.resolved { background: var(--tag-green-bg); color: var(--tag-green-text); }

.action-btn { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border: none; background: transparent; border-radius: 4px; cursor: pointer; color: var(--text-muted); transition: all 0.15s; }
.action-btn:hover { background: var(--bg-hover); color: var(--color-primary); }

/* 规则创建弹窗 */
.rule-builder-body { display: flex; flex-direction: column; gap: 14px; }
.rule-builder-field { display: flex; flex-direction: column; gap: 6px; flex: 1; }
.rule-builder-row { display: flex; gap: 12px; }
.rule-builder-label { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-secondary); }

/* 详情抽屉 */
.detail-body { display: flex; flex-direction: column; gap: 16px; }
.detail-row { display: flex; flex-direction: column; gap: 4px; }
.detail-label { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); }
.detail-value { font-size: 15px; color: var(--text-primary); }
.detail-value-highlight { color: var(--color-primary); font-weight: 600; }
.detail-status { display: inline-block; padding: 2px 10px; border-radius: 2px; font-size: 12px; font-weight: 700; }
.detail-status.active { background: var(--tag-red-bg); color: var(--tag-red-text); }
.detail-status.resolved { background: var(--tag-green-bg); color: var(--tag-green-text); }

/* Responsive: collapse multi-column grids on smaller screens */
@media (max-width: 768px) {
  .main-grid { grid-template-columns: 1fr; height: auto; }
  .history-filters { flex-wrap: wrap; }
  .rule-builder-row { flex-direction: column; }
}
</style>
