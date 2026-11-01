<script setup lang="ts">
defineOptions({ name: 'HoldingsAnalysis' })
import { ref, computed, h, reactive, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton, NIcon, NDataTable, NModal, NInput, NInputNumber, NSelect, NTag,
  NRadioGroup, NRadioButton, NPopover, NCheckbox, NSwitch, NTooltip,
  NTabs, NTabPane, NCard, NAlert, NCollapse, NCollapseItem,
  useMessage, useDialog,
} from 'naive-ui'
import type { PaginationProps } from 'naive-ui'
import { CloudUploadOutline, RefreshOutline, CameraOutline, ClipboardOutline, SettingsOutline, FilterOutline, DocumentTextOutline } from '@vicons/ionicons5'
import { useAsyncData } from '../composables/useApi'
import { api } from '../utils/api'
import { useAuth } from '../composables/useAuth'
import type { Holding, HoldingsView, HoldingSnapshot, HoldingSummary, Terminal, Broker, AccountName, HoldingHistory, ImportLog } from '../types'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import DataPanel from '../components/DataPanel.vue'
import LoadingState from '../components/LoadingState.vue'
import BaseChart from '../components/BaseChart.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'

const message = useMessage()
const dialog = useDialog()
const router = useRouter()
const { username: authUsername } = useAuth()

const TYPE_LABELS: Record<string, string> = {
  stock: '股票',
  etf: '场内基金',
  fund_otc: '场外基金',
  option: '期权',
  future: '期货',
  hk_stock: '港股',
}

// 各类型标签配色（浅底深字，避免刺眼）
const TYPE_COLORS: Record<string, { bg: string; fg: string; border: string }> = {
  stock: { bg: 'rgba(0,94,161,0.12)', fg: '#005ea1', border: 'rgba(0,94,161,0.35)' },
  etf: { bg: 'rgba(61,122,74,0.12)', fg: '#2f7d44', border: 'rgba(61,122,74,0.35)' },
  fund_otc: { bg: 'rgba(124,68,156,0.12)', fg: '#7c449c', border: 'rgba(124,68,156,0.35)' },
  option: { bg: 'rgba(214,124,0,0.14)', fg: '#b86a00', border: 'rgba(214,124,0,0.4)' },
  future: { bg: 'rgba(180,40,50,0.12)', fg: '#b42832', border: 'rgba(180,40,50,0.35)' },
  hk_stock: { bg: 'rgba(176,130,0,0.14)', fg: '#9a7200', border: 'rgba(176,130,0,0.4)' },
}
function typeColor(type: string) {
  return TYPE_COLORS[type] ?? { bg: 'rgba(88,94,108,0.12)', fg: '#585e6c', border: 'rgba(88,94,108,0.3)' }
}

const { data: view, loading, error, refresh } = useAsyncData<HoldingsView>(() => api.getHoldings())
const { data: snapshots, refresh: refreshSnapshots } = useAsyncData<HoldingSnapshot[]>(() => api.getHoldingSnapshots())
const { data: history, loading: historyLoading, refresh: refreshHistory } = useAsyncData<HoldingHistory[]>(() => api.getHoldingHistory())
const activeTab = ref<'current' | 'history' | 'brokers' | 'imports'>('current')

// 表格分页：每页默认 20 行，客户端分页
const pagination = ref<PaginationProps>({
  page: 1,
  pageSize: 20,
  showSizePicker: true,
  pageSizes: [10, 20, 50, 100],
  onChange: (page: number) => { pagination.value.page = page },
  onUpdatePageSize: (pageSize: number) => {
    pagination.value.pageSize = pageSize
    pagination.value.page = 1
  },
})
// 个人中心配置的终端列表（每个终端含多个券商；加载与维护见下方「终端管理」区块）
const terminals = ref<Terminal[]>([])
// 个人中心配置的账户名列表（独立表，筛选/导入选用）
const accountNames = ref<AccountName[]>([])
async function loadAccountNames() {
  try {
    accountNames.value = await api.getAccountNames()
  } catch {
    accountNames.value = []
  }
}
onMounted(() => { refresh(); refreshSnapshots(); refreshHistory(); loadTerminals(); loadAccountNames() })

// 展平所有券商（跨终端），用于编辑弹窗 / 导入下拉
const allBrokers = computed<Broker[]>(() =>
  terminals.value.flatMap(t => t.brokers ?? []),
)
// 编辑弹窗：券商下拉选项（value=券商 name，用于填写持仓的 broker 字段；来自终端管理配置 + 持仓数据中已有的，去重）
const editBrokerOptions = computed(() => {
  const brokers = new Set<string>(allBrokers.value.map(b => b.name).filter(Boolean))
  view.value?.items.forEach(i => { if (i.broker) brokers.add(i.broker) })
  return [...brokers].map(b => ({ label: b, value: b }))
})
// 编辑弹窗：账户下拉选项（来自独立表 biz_account_names + 持仓数据中已有的，去重）
const editAccountOptions = computed(() => {
  const accounts = new Set<string>(accountNames.value.map(a => a.name).filter(Boolean))
  view.value?.items.forEach(i => { if (i.account) accounts.add(i.account) })
  return [...accounts].map(a => ({ label: a, value: a }))
})

function refreshAll() { refresh(); refreshSnapshots() }

const summary = computed<HoldingSummary | null>(() => view.value?.summary ?? null)

// ============================================================
// 筛选（表格展示层过滤，汇总统计始终全量）
// ============================================================
const filterType = ref<string | null>(null)
const filterBroker = ref<string | null>(null)
const filterAccount = ref<string | null>(null)
const filterLossOnly = ref(false)
const filterAlertOnly = ref(false)

// 实际生效的筛选条件（点「过滤」后才同步）
const appliedType = ref<string | null>(null)
const appliedBroker = ref<string | null>(null)
const appliedAccount = ref<string | null>(null)
const appliedLossOnly = ref(false)
const appliedAlertOnly = ref(false)

// 筛选条件是否有变化（用于「过滤」按钮高亮提示）
const filterDirty = computed(() =>
  filterType.value !== appliedType.value ||
  filterBroker.value !== appliedBroker.value ||
  filterAccount.value !== appliedAccount.value ||
  filterLossOnly.value !== appliedLossOnly.value ||
  filterAlertOnly.value !== appliedAlertOnly.value,
)

function applyFilter() {
  appliedType.value = filterType.value
  appliedBroker.value = filterBroker.value
  appliedAccount.value = filterAccount.value
  appliedLossOnly.value = filterLossOnly.value
  appliedAlertOnly.value = filterAlertOnly.value
}

function resetFilter() {
  filterType.value = null
  filterBroker.value = null
  filterAccount.value = null
  filterLossOnly.value = false
  filterAlertOnly.value = false
  applyFilter()
}
const typeFilterOptions = [
  ...Object.entries(TYPE_LABELS).map(([value, label]) => ({ label, value })),
]
// 筛选选项 = 终端管理配置的券商名 ∪ 持仓数据中已有的券商
const brokerFilterOptions = computed(() => {
  const brokers = new Set<string>(allBrokers.value.map(b => b.name).filter(Boolean))
  view.value?.items.forEach(i => brokers.add(i.broker || '未分组'))
  return [...brokers].map(b => ({ label: b, value: b }))
})
// 筛选选项 = 独立表账户名 ∪ 持仓数据中已有的账户
const accountFilterOptions = computed(() => {
  const accounts = new Set<string>(accountNames.value.map(a => a.name).filter(Boolean))
  view.value?.items.forEach(i => accounts.add(i.account || '未分组'))
  return [...accounts].map(a => ({ label: a, value: a }))
})
const displayItems = computed(() => {
  if (!view.value) return []
  let items = view.value.items
  if (appliedType.value) items = items.filter(i => i.type === appliedType.value)
  if (appliedBroker.value) items = items.filter(i => (i.broker || '未分组') === appliedBroker.value)
  if (appliedAccount.value) items = items.filter(i => (i.account || '未分组') === appliedAccount.value)
  if (appliedLossOnly.value) items = items.filter(i => i.pnl_pct !== null && i.pnl_pct < 0)
  if (appliedAlertOnly.value) items = items.filter(i => i.alert_status !== null)
  return items
})

// 过滤后的汇总行数据
const filterSummary = computed(() => {
  const items = displayItems.value
  if (!items.length) return null
  const totalMv = items.reduce((s, i) => s + (i.market_value ?? 0), 0)
  const totalCost = items.reduce((s, i) => s + i.cost_price * i.quantity, 0)
  const totalPnl = items.reduce((s, i) => s + (i.pnl ?? 0), 0)
  const totalDailyPnl = items.reduce((s, i) => s + (i.daily_pnl ?? 0), 0)
  const pricedCount = items.filter(i => i.price !== null).length
  const avgPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : null
  return { count: items.length, pricedCount, totalMv, totalCost, totalPnl, totalDailyPnl, avgPnlPct }
})

// ============================================================
// 格式化
// ============================================================
function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
function fmtMoney(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `¥${fmtNum(v)}`
}
function pnlColor(v: number | null | undefined): string | undefined {
  if (v === null || v === undefined) return undefined
  return v >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
}

// ============================================================
// 表格列
// ============================================================
// 总市值（权重占比用）
const totalMv = computed(() => summary.value?.total_market_value ?? 0)

// 价格闪烁：刷新后对比新旧现价，标记涨跌方向
const prevPrices = new Map<string, number>()
const flash = reactive<Record<string, 'up' | 'down' | ''>>({})
watch(
  () => view.value?.items,
  (items) => {
    if (!items) return
    for (const it of items) {
      const prev = prevPrices.get(it.id)
      if (prev !== undefined && it.price !== null && prev !== 0 && it.price !== prev) {
        const dir = it.price > prev ? 'up' : 'down'
        flash[it.id] = dir
        window.setTimeout(() => { if (flash[it.id] === dir) flash[it.id] = '' }, 900)
      }
      if (it.price !== null) prevPrices.set(it.id, it.price)
    }
  },
)

// 自动刷新
const autoRefresh = ref(false)
let autoTimer: number | null = null
function toggleAutoRefresh(v: boolean) {
  autoRefresh.value = v
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null }
  if (v) autoTimer = window.setInterval(() => refreshAll(), 30000)
}
onBeforeUnmount(() => { if (autoTimer) clearInterval(autoTimer) })

// 建议止损线（单票）
function suggestStopLoss(row: Holding): number {
  const pct = row.pnl_pct
  if (pct == null || pct >= 0) return -8
  if (pct > -8) return -8
  return Math.max(Math.round(pct / 5) * 5, -50)
}
async function applySuggestedStop(row: Holding) {
  const sl = suggestStopLoss(row)
  try {
    await api.updateHolding(row.id, { stop_loss_pct: sl })
    message.success(`已为 ${row.name} 设置建议止损线 ${sl}%`)
    refresh()
  } catch (e: any) {
    message.error(e.message || '设置失败')
  }
}

function weightOf(row: Holding): number | null {
  if (row.market_value == null || !totalMv.value) return null
  return row.market_value / totalMv.value * 100
}
function beRiseOf(row: Holding): number {
  if (row.price === null || row.price === 0 || row.cost_price == null) return -Infinity
  return (row.cost_price - row.price) / row.price * 100
}

// 列定义（含显隐与排序）
interface ColDef {
  key: string
  title: string
  width?: number
  minWidth?: number
  align?: 'right'
  fixed?: 'left' | 'right'
  always?: boolean
  defaultOn?: boolean
  help?: string
  sorter?: (a: Holding, b: Holding) => number
  render: (row: Holding) => any
}
const columnDefs: ColDef[] = [
  { key: 'code', title: '代码', width: 100, always: true, fixed: 'left' as const, render: (row: Holding) => h('span', { class: 'mono' }, row.code) },
  { key: 'name', title: '名称', minWidth: 120, always: true, fixed: 'left' as const, render: (row: Holding) => h('span', { class: 'holding-name' }, row.name) },
  {
    key: 'type_label', title: '类型', width: 100, always: true,
    render: (row: Holding) => {
      const c = typeColor(row.type)
      return h(NTag, { size: 'small', bordered: false, color: { color: c.bg, textColor: c.fg, borderColor: c.border } }, { default: () => row.type_label })
    },
  },
  { key: 'broker', title: '券商', width: 110, defaultOn: false, render: (row: Holding) => row.broker || '未分组' },
  { key: 'account', title: '账户', width: 100, defaultOn: false, render: (row: Holding) => row.account || '未分组' },
  { key: 'quantity', title: '数量', align: 'right' as const, width: 100, sorter: (a, b) => a.quantity - b.quantity, render: (row: Holding) => fmtNum(row.quantity) },
  { key: 'cost_price', title: '成本价', align: 'right' as const, width: 100, sorter: (a, b) => (a.cost_price ?? 0) - (b.cost_price ?? 0), render: (row: Holding) => h('span', { class: 'mono' }, fmtNum(row.cost_price, 3)) },
  {
    key: 'price', title: '现价', align: 'right' as const, width: 110, sorter: (a, b) => (a.price ?? -Infinity) - (b.price ?? -Infinity),
    render: (row: Holding) => {
      if (row.price === null) {
        return h(NButton, { size: 'tiny', dashed: true, onClick: () => openEdit(row) }, { default: () => '手动填价' })
      }
      return h('span', { class: `mono flash-${flash[row.id] || ''}`, style: { borderRadius: '3px', padding: '0 2px' } }, [
        fmtNum(row.price, 3),
        h('span', { class: 'price-src' }, row.price_source === 'manual' ? '手' : '自动'),
      ])
    },
  },
  { key: 'market_value', title: '市值', align: 'right' as const, width: 120, sorter: (a, b) => (a.market_value ?? -Infinity) - (b.market_value ?? -Infinity), render: (row: Holding) => h('span', { class: 'mono' }, fmtMoney(row.market_value)) },
  {
    key: 'pnl', title: '浮动盈亏', align: 'right' as const, width: 120, sorter: (a, b) => (a.pnl ?? -Infinity) - (b.pnl ?? -Infinity),
    help: '现价相对成本价计算的浮动盈亏金额（尚未卖出，不计交易税费）。',
    render: (row: Holding) => h('span', { class: `mono flash-${flash[row.id] || ''}`, style: { color: pnlColor(row.pnl), fontWeight: 600, borderRadius: '3px', padding: '0 2px' } }, fmtMoney(row.pnl)),
  },
  {
    key: 'pnl_pct', title: '收益率', align: 'right' as const, width: 90, sorter: (a, b) => (a.pnl_pct ?? -Infinity) - (b.pnl_pct ?? -Infinity),
    help: '浮动盈亏 ÷ 成本价，即（现价 − 成本价）÷ 成本价 × 100%。',
    render: (row: Holding) => row.pnl_pct === null
      ? '—'
      : h('span', { style: { color: pnlColor(row.pnl_pct), fontWeight: 600 } }, `${row.pnl_pct >= 0 ? '+' : ''}${fmtNum(row.pnl_pct)}%`),
  },
  {
    key: 'daily_pnl', title: '当日盈亏', align: 'right' as const, width: 110, defaultOn: true, sorter: (a, b) => (a.daily_pnl ?? -Infinity) - (b.daily_pnl ?? -Infinity),
    help: '今天这一天的盈亏变化 = 数量 ×（现价 − 昨收价），无昨收价的不计入。',
    render: (row: Holding) => h('span', { class: 'mono', style: { color: pnlColor(row.daily_pnl) } }, fmtMoney(row.daily_pnl)),
  },
  {
    key: 'daily_pct', title: '当日涨跌幅', align: 'right' as const, width: 100, defaultOn: true, sorter: (a, b) => (a.daily_pct ?? -Infinity) - (b.daily_pct ?? -Infinity),
    help: '今天相对昨收价的涨跌幅 =（现价 − 昨收价）÷ 昨收价 × 100%。',
    render: (row: Holding) => row.daily_pct === null
      ? '—'
      : h('span', { class: 'mono', style: { color: pnlColor(row.daily_pct), fontWeight: 600 } }, `${row.daily_pct >= 0 ? '+' : ''}${fmtNum(row.daily_pct)}%`),
  },
  {
    key: 'weight', title: '权重%', align: 'right' as const, width: 90, sorter: (a, b) => (weightOf(a) ?? -Infinity) - (weightOf(b) ?? -Infinity),
    help: '该标的市值占全部持仓总市值的比例。>30% 代表单票过于集中，是判断要不要减仓、控制风险的关键指标。',
    render: (row: Holding) => {
      const w = weightOf(row)
      return h('span', { class: 'mono', style: { color: w != null && w > 30 ? 'var(--color-danger)' : 'var(--text-secondary)', fontWeight: w != null && w > 30 ? 600 : 400 } }, w == null ? '—' : `${w.toFixed(1)}%`)
    },
  },
  {
    key: 'breakeven', title: '回本', align: 'right' as const, width: 130, sorter: (a, b) => beRiseOf(a) - beRiseOf(b),
    help: '想回到成本价还需要涨多少。显示「盈利」说明现价已高于成本；否则显示回本价及还需上涨的百分比。',
    render: (row: Holding) => {
      if (row.price === null || row.price === 0 || row.cost_price == null) return h('span', { style: { color: 'var(--text-muted)', fontSize: '11px' } }, '—')
      const rise = (row.cost_price - row.price) / row.price * 100
      if (rise <= 0) return h('span', { style: { color: 'var(--color-success)', fontSize: '11px', fontWeight: 600 } }, '盈利')
      return h('span', { class: 'mono', style: { color: 'var(--color-danger)', fontSize: '11px' } }, `¥${fmtNum(row.cost_price, 3)} +${fmtNum(rise, 1)}%`)
    },
  },
  {
    key: 'valuation', title: '估值', align: 'right' as const, width: 130, sorter: (a, b) => (a.val_pct ?? -Infinity) - (b.val_pct ?? -Infinity),
    help: '你填的合理价 vs 现价。现价比合理价高 >10% 标「偏高·考虑卖」；低 >10% 标「偏低·考虑买」；中间为「合理」。这是系统的第一条「买卖原持仓提示」。',
    render: (row: Holding) => {
      if (row.valuation == null) return h('span', { style: { color: 'var(--text-muted)', fontSize: '11px' } }, '—')
      const tagMap = {
        over: { type: 'warning', text: `偏高 ${row.val_pct != null ? fmtNum(row.val_pct, 0) : ''}%` },
        under: { type: 'success', text: `偏低 ${row.val_pct != null ? '+' + fmtNum(row.val_pct, 0) : ''}%` },
        fair: { type: 'default', text: `合理 ${row.val_pct != null ? (row.val_pct >= 0 ? '+' : '') + fmtNum(row.val_pct, 0) : ''}%` },
      } as const
      const t = tagMap[row.valuation]
      return h(NTag, { size: 'small', type: t.type, bordered: false }, { default: () => t.text })
    },
  },
  {
    key: 'grid', title: '网格', align: 'right' as const, width: 140, sorter: (a, b) => (a.grid_pos_pct ?? -Infinity) - (b.grid_pos_pct ?? -Infinity),
    help: '你设定的网格区间 [下限, 上限]，按间距自动切成多条买卖网格线。现价触及下沿提示买入、触及上沿提示卖出——这是系统的第二条「买卖原持仓提示」。需在编辑持仓里先填网格参数。',
    render: (row: Holding) => {
      if (row.grid_signal == null) return h('span', { style: { color: 'var(--text-muted)', fontSize: '11px' } }, '—')
      const map = {
        buy: { type: 'warning', text: '触下沿·可买' },
        sell: { type: 'success', text: '触上沿·可卖' },
        hold: { type: 'default', text: `第${(row.grid_level ?? 0) + 1}/${row.grid_total ?? '—'}格` },
      } as const
      const m = map[row.grid_signal]
      return h(NTag, { size: 'small', type: m.type, bordered: false }, { default: () => m.text })
    },
  },
  {
    key: 'alert', title: '预警', width: 140, always: true,
    help: '止损/止盈触发状态。未设置时点击「建议止损」一键填入；触发后整行高亮并在顶部预警条提示。',
    render: (row: Holding) => {
      const sl = row.stop_loss_pct
      const tp = row.take_profit_pct
      if (row.alert_status === null && sl === null && tp === null) {
        return h(NButton, { size: 'tiny', quaternary: true, onClick: () => applySuggestedStop(row) }, { default: () => '建议止损' })
      }
      const tags: any[] = []
      if (row.alert_status === 'stop_loss') {
        tags.push(h(NTag, { size: 'small', type: 'error', bordered: false }, { default: () => `止损 ${sl}%` }))
      } else if (row.alert_status === 'take_profit') {
        tags.push(h(NTag, { size: 'small', type: 'success', bordered: false }, { default: () => `止盈 ${tp}%` }))
      } else {
        if (sl !== null) tags.push(h(NTag, { size: 'small', type: 'warning', bordered: false, style: { opacity: 0.65 } }, { default: () => `止损 ${sl}%` }))
        if (tp !== null) tags.push(h(NTag, { size: 'small', type: 'info', bordered: false, style: { opacity: 0.65 } }, { default: () => `止盈 ${tp}%` }))
      }
      return h('div', { style: { display: 'flex', gap: '4px', flexWrap: 'wrap' } }, tags)
    },
  },
  {
    key: 'actions', title: '操作', width: 150, fixed: 'right' as const, always: true,
    render: (row: Holding) => h('div', { class: 'row-actions' }, [
      h(NButton, { size: 'tiny', secondary: true, type: 'primary', onClick: () => openAdd(row) }, { default: () => '加仓' }),
      h(NButton, { size: 'tiny', secondary: true, type: 'default', onClick: () => openEdit(row) }, { default: () => '编辑' }),
      h(NButton, { size: 'tiny', secondary: true, type: 'error', onClick: () => confirmDelete(row) }, { default: () => '平仓' }),
    ]),
  },
]

// 列显隐（localStorage 持久化）
const COL_STORAGE_KEY = 'holdings_visible_cols'
function defaultVisibleKeys(): string[] {
  return columnDefs.filter(d => !d.always && d.defaultOn !== false).map(d => d.key)
}
function loadVisible(): Set<string> {
  try {
    const raw = localStorage.getItem(COL_STORAGE_KEY)
    if (raw) return new Set(JSON.parse(raw))
  } catch { /* ignore */ }
  return new Set(defaultVisibleKeys())
}
const visibleCols = ref<Set<string>>(loadVisible())
function isColOn(key: string): boolean {
  const d = columnDefs.find(x => x.key === key)
  if (d?.always) return true
  return visibleCols.value.has(key)
}
function setCol(key: string, on: boolean) {
  const s = new Set(visibleCols.value)
  if (on) s.add(key); else s.delete(key)
  visibleCols.value = s
  try { localStorage.setItem(COL_STORAGE_KEY, JSON.stringify([...visibleCols.value])) } catch { /* ignore */ }
}
const toggleableCols = columnDefs.filter(d => !d.always).map(d => ({ key: d.key, title: d.title }))
function resetCols() {
  visibleCols.value = new Set(defaultVisibleKeys())
  try { localStorage.setItem(COL_STORAGE_KEY, JSON.stringify([...visibleCols.value])) } catch { /* ignore */ }
}

const columns = computed(() => columnDefs
  .filter(d => d.always || visibleCols.value.has(d.key))
  .map((d) => {
    const title = d.help
      ? () => h('span', { class: 'col-title-with-help' }, [
          d.title,
          h(NTooltip, { placement: 'top' }, {
            trigger: () => h('span', { class: 'col-help-mark' }, '?'),
            default: () => d.help as string,
          }),
        ])
      : d.title
    return {
      title, key: d.key, width: d.width, minWidth: d.minWidth,
      align: d.align, fixed: d.fixed, sorter: d.sorter, render: d.render,
    }
  })
)

// ============================================================
// JSON 批量导入
// ============================================================
const IMPORT_TEMPLATE = `[
  { "code": "600519", "name": "贵州茅台", "type": "stock", "broker": "华泰证券", "account": "普通", "quantity": 100, "cost_price": 1700.5, "open_date": "2025-01-15" },
  { "code": "510300", "name": "沪深300ETF", "type": "etf", "broker": "华泰证券", "account": "普通", "quantity": 1000, "cost_price": 3.85 },
  { "code": "110011", "name": "易方达优质精选", "type": "fund_otc", "broker": "天天基金", "account": "普通", "quantity": 5000, "cost_price": 4.2 },
  { "code": "10007620", "name": "IO2603-C-4000", "type": "option", "broker": "中信期货", "account": "普通", "quantity": 2, "cost_price": 220 },
  { "code": "rb2605", "name": "螺纹钢2605", "type": "future", "broker": "中信期货", "account": "普通", "quantity": 1, "cost_price": 3350 },
  { "code": "00700", "name": "腾讯控股", "type": "hk_stock", "broker": "富途证券", "account": "普通", "quantity": 200, "cost_price": 380.5, "currency": "HKD" }
]`

const showImportModal = ref(false)
const importMode = ref<'json' | 'csv' | 'trades'>('json')
const importText = ref('')
const importErrors = ref<string[]>([])
const importValidCount = ref(0)
const importing = ref(false)
const csvFile = ref<File | null>(null)
const csvBroker = ref('')
const csvAccount = ref('')

// 成交记录导入（复用无鉴权 POST /api/v1/trades/import，body 带当前 username）
const TRADE_TEMPLATE = `{
  "trade_date": "2026-10-22",
  "items": [
    { "code": "600519", "name": "贵州茅台", "type": "stock", "account": "普通", "direction": "buy", "price": 1700.5, "quantity": 100, "fee": 5.5 },
    { "code": "510300", "name": "沪深300ETF", "type": "etf", "account": "普通", "direction": "sell", "price": 3.95, "quantity": 1000, "fee": 1.2 },
    { "code": "00700", "name": "腾讯控股", "type": "hk_stock", "account": "普通", "direction": "buy", "price": 420, "quantity": 200, "currency": "HKD", "fee": 18 }
  ]
}`
const tradeDate = ref('')
const tradeDateTs = ref<number | null>(null)
const tradeAccount = ref('')
const tradeText = ref('')
const tradeErrors = ref<string[]>([])
const tradeValidCount = ref(0)
// 券商下拉（value=券商 account，作为成交上传的 account 主标识）
const tradeBrokerOptions = computed(() =>
  allBrokers.value.map(b => ({ label: `${b.name} · ${b.account}`, value: b.account })),
)
function fmtTradeDate(v: number | null): string {
  if (!v) return ''
  const d = new Date(v)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

function parseImportText(): { items: Array<Record<string, unknown>>; errors: string[] } {
  const errors: string[] = []
  let parsed: unknown
  try {
    parsed = JSON.parse(importText.value)
  } catch (e) {
    return { items: [], errors: [`JSON 解析失败：${String(e)}`] }
  }
  if (!Array.isArray(parsed)) return { items: [], errors: ['顶层必须是 JSON 数组 [ ... ]'] }
  const items: Array<Record<string, unknown>> = []
  parsed.forEach((raw, i) => {
    const line = `第 ${i + 1} 条`
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) { errors.push(`${line}：必须是对象`); return }
    const r = raw as Record<string, unknown>
    if (!r.code || !r.name) { errors.push(`${line}：缺少 code 或 name`); return }
    if (!TYPE_LABELS[r.type as string]) {
      errors.push(`${line}：未知 type "${String(r.type)}"（可选：${Object.keys(TYPE_LABELS).join(' / ')}）`)
      return
    }
    if (typeof r.quantity !== 'number' || r.quantity === 0) { errors.push(`${line}：quantity 必须为非零数字`); return }
    if (typeof r.cost_price !== 'number') { errors.push(`${line}：cost_price 必须为数字`); return }
    items.push(r)
  })
  return { items, errors }
}

function previewImport() {
  const { items, errors } = parseImportText()
  importErrors.value = errors
  importValidCount.value = items.length
}

// 成交记录 JSON 解析（顶层 { trade_date, items }）
function parseTradeText(): { items: Array<Record<string, unknown>>; errors: string[] } {
  const errors: string[] = []
  if (!tradeDate.value) errors.push('请先填写「交易日期」（YYYY-MM-DD）')
  if (!tradeAccount.value) errors.push('请先选择「券商」（决定 account，整批必传）')
  if (errors.length) return { items: [], errors }
  let parsed: unknown
  try {
    parsed = JSON.parse(tradeText.value)
  } catch (e) {
    return { items: [], errors: [`JSON 解析失败：${String(e)}`] }
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { items: [], errors: ['顶层必须是一个 JSON 对象 { "trade_date": "...", "items": [ ... ] }'] }
  }
  const obj = parsed as Record<string, unknown>
  const arr = obj.items
  if (!Array.isArray(arr)) return { items: [], errors: ['缺少 items 数组字段'] }
  const items: Array<Record<string, unknown>> = []
  arr.forEach((raw, i) => {
    const line = `第 ${i + 1} 条`
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) { errors.push(`${line}：必须是对象`); return }
    const r = raw as Record<string, unknown>
    if (!r.code || !r.name) { errors.push(`${line}：缺少 code 或 name`); return }
    if (!TYPE_LABELS[r.type as string]) {
      errors.push(`${line}：未知 type "${String(r.type)}"（可选：${Object.keys(TYPE_LABELS).join(' / ')}）`)
      return
    }
    if (r.direction !== 'buy' && r.direction !== 'sell') {
      errors.push(`${line}：direction 必须为 "buy" 或 "sell"`); return
    }
    if (typeof r.quantity !== 'number' || r.quantity === 0) { errors.push(`${line}：quantity 必须为非零数字`); return }
    if (typeof r.price !== 'number') { errors.push(`${line}：price 必须为数字`); return }
    items.push(r)
  })
  return { items, errors }
}

function previewTrade() {
  const { items, errors } = parseTradeText()
  tradeErrors.value = errors
  tradeValidCount.value = items.length
}

async function submitImport() {
  if (importMode.value === 'trades') {
    const { items, errors } = parseTradeText()
    tradeErrors.value = errors
    tradeValidCount.value = items.length
    if (items.length === 0) {
      message.warning('没有可导入的有效成交条目，请检查格式')
      return
    }
    importing.value = true
    try {
      const result = await api.importTrades({
        username: authUsername.value || '',
        source: 'web',
        account: tradeAccount.value,
        trade_date: tradeDate.value,
        items,
      })
      let msg = `导入完成：新增 ${result.inserted}`
      if (result.deleted) msg += `（覆盖删除 ${result.deleted}）`
      if (result.failed.length) msg += `，失败 ${result.failed.length}（${result.failed[0].reason}…）`
      message.success(msg)
      showImportModal.value = false
      tradeText.value = ''
      tradeErrors.value = []
      refreshAll()
    } catch (e: any) {
      message.error(e.message || '成交导入失败')
    } finally {
      importing.value = false
    }
    return
  }
  if (importMode.value === 'json') {
    const { items, errors } = parseImportText()
    importErrors.value = errors
    importValidCount.value = items.length
    if (items.length === 0) {
      message.warning('没有可导入的有效条目，请检查格式')
      return
    }
    importing.value = true
    try {
      const result = await api.importHoldings(items)
      let msg = `导入完成：新增 ${result.added}，更新 ${result.updated}`
      if (result.failed.length) msg += `，失败 ${result.failed.length}（${result.failed[0].reason}…）`
      message.success(msg)
      showImportModal.value = false
      importText.value = ''
      importErrors.value = []
      refreshAll()
    } catch (e: any) {
      message.error(e.message || '导入失败')
    } finally {
      importing.value = false
    }
  } else {
    if (!csvFile.value) {
      message.warning('请选择 CSV 文件')
      return
    }
    importing.value = true
    try {
      const result = await api.importHoldingsCsv(csvFile.value, csvBroker.value, csvAccount.value)
      let msg = `导入完成：新增 ${result.added}，更新 ${result.updated}`
      if (result.failed.length) msg += `，失败 ${result.failed.length}（${result.failed[0].reason}…）`
      message.success(msg)
      showImportModal.value = false
      csvFile.value = null
      refreshAll()
    } catch (e: any) {
      message.error(e.message || 'CSV 导入失败')
    } finally {
      importing.value = false
    }
  }
}

function copyTemplate() {
  if (importMode.value === 'trades') {
    tradeText.value = TRADE_TEMPLATE
    previewTrade()
    navigator.clipboard.writeText(TRADE_TEMPLATE).then(
      () => message.success('示例已填入输入框并复制到剪贴板'),
      () => message.success('示例已填入输入框'),
    )
    return
  }
  importText.value = IMPORT_TEMPLATE
  previewImport()
  navigator.clipboard.writeText(IMPORT_TEMPLATE).then(
    () => message.success('示例已填入输入框并复制到剪贴板'),
    () => message.success('示例已填入输入框'),
  )
}

// ============================================================
// 手动编辑 / 删除
// ============================================================
const showEditModal = ref(false)
const editSaving = ref(false)
const editForm = reactive({
  id: '', code: '', name: '',
  quantity: 0, cost_price: 0,
  manual_price: null as number | null,
  stop_loss_pct: null as number | null,
  take_profit_pct: null as number | null,
  fair_value: null as number | null,
  grid_lower: null as number | null,
  grid_upper: null as number | null,
  grid_step: null as number | null,
  broker: '', account: '',
})

function openEdit(row: Holding) {
  Object.assign(editForm, {
    id: row.id, code: row.code, name: row.name,
    quantity: row.quantity, cost_price: row.cost_price,
    manual_price: row.manual_price,
    stop_loss_pct: row.stop_loss_pct,
    take_profit_pct: row.take_profit_pct,
    fair_value: row.fair_value,
    grid_lower: row.grid_lower,
    grid_upper: row.grid_upper,
    grid_step: row.grid_step,
    broker: row.broker, account: row.account,
  })
  showEditModal.value = true
}

async function submitEdit() {
  if (editForm.quantity === 0) {
    message.warning('数量不能为 0（如需删除请使用删除操作）')
    return
  }
  editSaving.value = true
  try {
    await api.updateHolding(editForm.id, {
      quantity: editForm.quantity,
      cost_price: editForm.cost_price,
      manual_price: editForm.manual_price,
      stop_loss_pct: editForm.stop_loss_pct,
      take_profit_pct: editForm.take_profit_pct,
      fair_value: editForm.fair_value,
      grid_lower: editForm.grid_lower,
      grid_upper: editForm.grid_upper,
      grid_step: editForm.grid_step,
      broker: editForm.broker,
      account: editForm.account,
    })
    message.success('持仓已更新')
    showEditModal.value = false
    refresh()
  } catch (e: any) {
    message.error(e.message || '更新失败')
  } finally {
    editSaving.value = false
  }
}

function confirmDelete(row: Holding) {
  dialog.warning({
    title: '平仓持仓',
    content: `确定平仓 ${row.name}（${row.code}）吗？平仓后该标的会归档到「历史持仓」标签。`,
    positiveText: '平仓',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.deleteHolding(row.id)
        message.success('已平仓，归档到历史持仓')
        refresh()
        refreshHistory()
      } catch (e: any) {
        message.error(e.message || '平仓失败')
      }
    },
  })
}

// ============================================================
// 加仓模拟器
// ============================================================
const showAddModal = ref(false)
const addApplying = ref(false)
const addRow = ref<Holding | null>(null)
const addForm = reactive({
  addQty: 0,
  addPrice: null as number | null,
})

function openAdd(row: Holding) {
  addRow.value = row
  addForm.addQty = 0
  addForm.addPrice = row.price
  showAddModal.value = true
}

const addSim = computed(() => {
  const row = addRow.value
  if (!row || row.price === null) return null
  const price = row.price as number
  const qty = row.quantity
  const cost = row.cost_price
  const addQty = addForm.addQty
  const addPrice = addForm.addPrice
  if (!addPrice || addQty <= 0) return null
  const addAmount = addQty * addPrice
  const newQty = qty + addQty
  const newCost = cost * qty + addPrice * addQty
  const newAvg = newCost / newQty
  const oldPnl = (price - cost) * qty
  const newPnl = (price - newAvg) * newQty
  const breakEvenRise = (newAvg - price) / price * 100
  const costDelta = newAvg - cost
  return {
    price, qty, cost, addQty, addPrice, addAmount, newQty, newCost, newAvg,
    oldPnl, newPnl, breakEvenRise, costDelta,
  }
})

async function applyAdd() {
  const row = addRow.value
  const sim = addSim.value
  if (!row || !sim) {
    message.warning('请先填入有效的加仓数量与价格')
    return
  }
  if (sim.addQty <= 0) {
    message.warning('加仓数量必须大于 0')
    return
  }
  addApplying.value = true
  try {
    await api.updateHolding(row.id, {
      quantity: sim.newQty,
      cost_price: Number(sim.newAvg.toFixed(4)),
    })
    message.success('加仓已应用：数量与成本价已按加权重算')
    showAddModal.value = false
    refresh()
  } catch (e: any) {
    message.error(e.message || '应用失败')
  } finally {
    addApplying.value = false
  }
}

// ============================================================
// 手动快照
// ============================================================
const snapping = ref(false)
async function takeSnapshot() {
  snapping.value = true
  try {
    await api.takeHoldingSnapshot()
    message.success('已生成当日快照')
    refreshSnapshots()
  } catch (e: any) {
    message.error(e.message || '快照生成失败')
  } finally {
    snapping.value = false
  }
}

// ============================================================
// 图表
// ============================================================
const PALETTE = ['#005ea1', '#2178c3', '#585e6c', '#864f00', '#3d7a4a', '#9c4d9c']

const allocationOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: (p: any) => `${p.name}: ¥${Number(p.value).toLocaleString()} (${p.percent}%)` },
  legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 11 } },
  series: [{
    type: 'pie',
    radius: ['52%', '74%'],
    center: ['50%', '44%'],
    label: { show: false },
    labelLine: { show: false },
    data: (summary.value?.allocation_by_type ?? []).map((a, i) => ({
      value: a.market_value,
      name: a.label,
      itemStyle: { color: PALETTE[i % PALETTE.length] },
    })),
  }],
}))

const brokerOption = computed(() => {
  const alloc = summary.value?.allocation_by_broker ?? []
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (p: any) => `${p[0].name}: ¥${Number(p[0].value).toLocaleString()}`,
    },
    grid: { top: 8, left: 8, right: 24, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { fontSize: 10, formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(0)}万` : String(v)) },
      splitLine: { lineStyle: { type: 'dashed', opacity: 0.3 } },
    },
    yAxis: { type: 'category', data: alloc.map(a => a.label), axisLabel: { fontSize: 11 } },
    series: [{
      type: 'bar',
      barWidth: 12,
      itemStyle: { color: '#005ea1', borderRadius: 3 },
      data: alloc.map(a => a.market_value),
    }],
  }
})

const accountOption = computed(() => {
  const alloc = summary.value?.allocation_by_account ?? []
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => `${p.name}: ¥${Number(p.value).toLocaleString()} (${p.percent}%)`,
    },
    legend: { bottom: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 4, textStyle: { fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '46%'],
      label: { show: true, formatter: '{b}\n{d}%', fontSize: 10 },
      data: alloc.map(a => ({ name: a.label, value: a.market_value })),
    }],
  }
})

const historyOption = computed(() => {
  const snaps = snapshots.value ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 4, data: ['总市值', '累计盈亏', '收益率'] },
    grid: { top: 16, left: 8, right: 8, bottom: 36, containLabel: true },
    xAxis: { type: 'category', data: snaps.map(s => s.snap_date), axisLabel: { fontSize: 10 } },
    yAxis: [
      {
        type: 'value',
        axisLabel: { fontSize: 10, formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(0)}万` : String(v)) },
        splitLine: { lineStyle: { type: 'dashed', opacity: 0.3 } },
      },
      { type: 'value', splitLine: { show: false }, axisLabel: { fontSize: 10 } },
      { type: 'value', splitLine: { show: false }, axisLabel: { fontSize: 10, formatter: (v: number) => `${v}%` } },
    ],
    series: [
      { name: '总市值', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, data: snaps.map(s => s.total_market_value), lineStyle: { width: 2, color: '#005ea1' }, itemStyle: { color: '#005ea1' } },
      { name: '累计盈亏', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'circle', symbolSize: 5, data: snaps.map(s => s.total_pnl), lineStyle: { width: 2, color: '#864f00' }, itemStyle: { color: '#864f00' } },
      { name: '收益率', type: 'line', yAxisIndex: 2, smooth: true, symbol: 'circle', symbolSize: 4, data: snaps.map(s => s.total_pnl_pct), lineStyle: { width: 1.5, type: 'dashed', color: '#3d7a4a' }, itemStyle: { color: '#3d7a4a' } },
    ],
  }
})

const snapshotColumns = [
  { title: '日期', key: 'snap_date', width: 110 },
  { title: '总市值', key: 'total_market_value', align: 'right' as const, render: (row: HoldingSnapshot) => fmtMoney(row.total_market_value) },
  { title: '总成本', key: 'total_cost', align: 'right' as const, render: (row: HoldingSnapshot) => fmtMoney(row.total_cost) },
  {
    title: '累计盈亏', key: 'total_pnl', align: 'right' as const,
    render: (row: HoldingSnapshot) => h('span', { style: { color: pnlColor(row.total_pnl), fontWeight: 600 } }, fmtMoney(row.total_pnl)),
  },
  {
    title: '收益率', key: 'total_pnl_pct', align: 'right' as const,
    render: (row: HoldingSnapshot) => h('span', { style: { color: pnlColor(row.total_pnl_pct) } }, `${row.total_pnl_pct >= 0 ? '+' : ''}${fmtNum(row.total_pnl_pct)}%`),
  },
  { title: '当日盈亏', key: 'daily_pnl', align: 'right' as const, render: (row: HoldingSnapshot) => h('span', { style: { color: pnlColor(row.daily_pnl) } }, fmtMoney(row.daily_pnl)) },
  { title: '标的数', key: 'holding_count', align: 'center' as const, render: (row: HoldingSnapshot) => `${row.priced_count}/${row.holding_count}` },
]

// 历史持仓（已平仓）列定义
function typeLabel(t: string): string {
  return TYPE_LABELS[t] ?? t
}
const historyColumns = [
  { title: '代码', key: 'code', width: 100, render: (row: HoldingHistory) => h('span', { class: 'mono' }, row.code) },
  { title: '名称', key: 'name', minWidth: 120 },
  { title: '类型', key: 'type', width: 90, render: (row: HoldingHistory) => h('span', {}, typeLabel(row.type)) },
  { title: '券商', key: 'broker', width: 120, render: (row: HoldingHistory) => row.broker || '—' },
  { title: '账户', key: 'account', width: 100, render: (row: HoldingHistory) => row.account || '—' },
  { title: '数量', key: 'quantity', align: 'right' as const, render: (row: HoldingHistory) => fmtNum(row.quantity) },
  { title: '成本价', key: 'cost_price', align: 'right' as const, render: (row: HoldingHistory) => fmtMoney(row.cost_price) },
  { title: '平仓价', key: 'close_price', align: 'right' as const, render: (row: HoldingHistory) => fmtMoney(row.close_price) },
  { title: '已实现盈亏', key: 'realized_pnl', align: 'right' as const, render: (row: HoldingHistory) => h('span', { style: { color: pnlColor(row.realized_pnl) } }, fmtMoney(row.realized_pnl)) },
  { title: '平仓时间', key: 'closed_at', width: 170, render: (row: HoldingHistory) => row.closed_at ? new Date(row.closed_at).toLocaleString('zh-CN') : '—' },
]
const historySummary = computed(() => {
  const items = history.value ?? []
  if (!items.length) return null
  const totalRealized = items.reduce((s, i) => s + (i.realized_pnl ?? 0), 0)
  return { count: items.length, totalRealized }
})

// ============ 终端管理（持仓页 tab：终端管理） ============
// 一个终端可含多个券商；券商 account 由客户端自传作为主标识
const terminalsLoading = ref(false)
const terminalsLoaded = ref(false)
const tmSaving = ref(false)

async function loadTerminals() {
  if (terminalsLoading.value) return
  terminalsLoading.value = true
  try {
    terminals.value = await api.getTerminals()
    terminalsLoaded.value = true
  } catch (e: any) {
    message.error('加载终端失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  } finally {
    terminalsLoading.value = false
  }
}

// ---- 终端 CRUD ----
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
    message.error('添加失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  } finally {
    tmSaving.value = false
  }
}

const showTerminalModal = ref(false)
const terminalForm = reactive({ id: '', name: '', remark: '' })

function openEditTerminal(t: Terminal) {
  terminalForm.id = t.id
  terminalForm.name = t.name
  terminalForm.remark = t.remark
  showTerminalModal.value = true
}

async function saveTerminal() {
  const name = terminalForm.name.trim()
  if (!name) { message.warning('请输入终端名称'); return }
  tmSaving.value = true
  try {
    await api.updateTerminal(terminalForm.id, name, terminalForm.remark.trim())
    message.success('终端已更新')
    showTerminalModal.value = false
    await loadTerminals()
  } catch (e: any) {
    message.error('保存失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
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

// ---- 券商 CRUD（隶属于某终端） ----
const newBrokerTerminalId = ref('')
const newBrokerName = ref('')
const newBrokerAccount = ref('')
const newBrokerRemark = ref('')

async function addBroker() {
  const terminalId = newBrokerTerminalId.value
  const name = newBrokerName.value.trim()
  const account = newBrokerAccount.value.trim()
  if (!terminalId) { message.warning('请选择所属终端'); return }
  if (!name) { message.warning('请输入券商名称'); return }
  if (!account) { message.warning('请输入券商账号（account）'); return }
  tmSaving.value = true
  try {
    await api.createBroker(terminalId, name, account, newBrokerRemark.value.trim())
    message.success('券商已添加')
    newBrokerName.value = ''
    newBrokerAccount.value = ''
    newBrokerRemark.value = ''
    await loadTerminals()
  } catch (e: any) {
    message.error('添加失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  } finally {
    tmSaving.value = false
  }
}

const showBrokerModal = ref(false)
const brokerForm = reactive({ terminalId: '', id: '', name: '', account: '', remark: '' })

function openEditBroker(t: Terminal, b: Broker) {
  brokerForm.terminalId = t.id
  brokerForm.id = b.id
  brokerForm.name = b.name
  brokerForm.account = b.account
  brokerForm.remark = b.remark
  showBrokerModal.value = true
}

async function saveBroker() {
  const name = brokerForm.name.trim()
  const account = brokerForm.account.trim()
  if (!name) { message.warning('请输入券商名称'); return }
  if (!account) { message.warning('请输入券商账号（account）'); return }
  tmSaving.value = true
  try {
    await api.updateBroker(brokerForm.terminalId, brokerForm.id, {
      name, account, remark: brokerForm.remark.trim(),
    })
    message.success('券商已更新')
    showBrokerModal.value = false
    await loadTerminals()
  } catch (e: any) {
    message.error('保存失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  } finally {
    tmSaving.value = false
  }
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

// ============ 上传记录（持仓页 tab：上传记录） ============
// 展示外部上传接口（持仓/成交导入）每次调用的留痕日志，便于核对导入结果
const importLogs = ref<ImportLog[]>([])
const importLogsLoading = ref(false)
const importLogsLoaded = ref(false)

async function loadImportLogs() {
  if (importLogsLoading.value) return
  importLogsLoading.value = true
  try {
    importLogs.value = await api.getImportLogs(100)
    importLogsLoaded.value = true
  } catch (e: any) {
    message.error('加载上传记录失败：' + (e?.data?.detail || e?.message || '请稍后重试'))
  } finally {
    importLogsLoading.value = false
  }
}

function parseFailDetail(row: ImportLog): Array<{ index: number; code: string; reason: string }> {
  try {
    const arr = JSON.parse(row.fail_detail || '[]')
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

const importLogColumns = [
  {
    type: 'expand' as const,
    renderExpand: (row: ImportLog) => {
      const fails = parseFailDetail(row)
      if (!fails.length) return h('div', { class: 'import-fail-empty' }, '本次导入无失败条目')
      return h(
        'div',
        { class: 'import-fail-list' },
        fails.map((f) =>
          h(
            'div',
            { class: 'import-fail-item' },
            [
              h('span', { class: 'mono import-fail-idx' }, `#${f.index}`),
              h('span', { class: 'mono import-fail-code' }, f.code || '—'),
              h('span', { class: 'import-fail-reason' }, f.reason),
            ],
          ),
        ),
      )
    },
  },
  { title: '时间', key: 'created_at', width: 165, render: (row: ImportLog) => row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '—' },
  { title: '接口', key: 'endpoint', width: 90, render: (row: ImportLog) => row.endpoint === 'holdings' ? '持仓' : row.endpoint === 'trades' ? '成交' : row.endpoint },
  { title: '来源', key: 'source', width: 110, render: (row: ImportLog) => row.source || '—' },
  { title: '券商code', key: 'broker_code', width: 130, render: (row: ImportLog) => h('span', { class: 'mono' }, row.broker_code || '—') },
  { title: '券商', key: 'broker', width: 100, render: (row: ImportLog) => row.broker || '—' },
  { title: '总条数', key: 'total', width: 80, align: 'right' as const },
  { title: '新增', key: 'added', width: 70, align: 'right' as const, render: (row: ImportLog) => h('span', { style: row.added ? { color: 'var(--color-success)' } : {} }, String(row.added)) },
  { title: '更新', key: 'updated', width: 70, align: 'right' as const },
  { title: '插入', key: 'inserted', width: 70, align: 'right' as const },
  { title: '删除', key: 'deleted', width: 70, align: 'right' as const },
  { title: '失败', key: 'failed', width: 70, align: 'right' as const, render: (row: ImportLog) => h('span', { style: row.failed ? { color: 'var(--color-danger)', fontWeight: 600 } : {} }, String(row.failed)) },
]

// 切换 tab 时按需加载（券商管理 / 上传记录）
watch(activeTab, (tab) => {
  if (tab === 'brokers') loadTerminals()
  if (tab === 'imports') loadImportLogs()
})
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    skeleton
    :min-height="520"
    text="正在加载持仓数据..."
    @retry="refresh"
  >
    <div v-if="view" class="holdings-page">
      <!-- Header -->
      <PageHeader
        title="持仓分析"
        :subtitle="`跨券商统一持仓：${summary?.holding_count ?? 0} 个标的，${summary?.priced_count ?? 0} 个已取得行情 · 支持 JSON 批量导入、手动变更与历史快照`"
        help-key="holdingsAnalysis"
      >
        <template #actions>
          <n-button size="small" @click="showImportModal = true">
            <template #icon><n-icon :component="CloudUploadOutline" /></template>
            导入持仓
          </n-button>
          <n-button size="small" @click="refreshAll">
            <template #icon><n-icon :component="RefreshOutline" /></template>
            刷新
          </n-button>
          <n-button size="small" @click="router.push('/external-api-docs')" title="外部上传接口文档（免登录，可分享给其它项目）">
            <template #icon><n-icon :component="DocumentTextOutline" /></template>
            接口文档
          </n-button>
        </template>
      </PageHeader>

      <GlossaryPanel page-key="holdingsAnalysis" />

      <n-tabs type="line" v-model:value="activeTab" class="holdings-tabs">
        <n-tab-pane name="current" tab="当前持仓">
      <div class="current-section">
      <!-- 风险预警条 -->
      <div v-if="summary && summary.warnings.length" class="warnings-strip">
        <div v-for="(w, i) in summary.warnings" :key="i" :class="['warning-item', w.level]">
          {{ w.text }}
        </div>
      </div>

      <!-- 概览统计卡 -->
      <div class="stat-grid">
        <StatCard label="总资产" :value="fmtMoney(summary?.total_market_value)" :sub="`总成本 ${fmtMoney(summary?.total_cost)}`" />
        <StatCard label="当日盈亏" :value="fmtMoney(summary?.daily_pnl)" :color="pnlColor(summary?.daily_pnl) || 'var(--text-muted)'" sub="Σ数量×(现价-昨收)，无昨收不计入" />
        <StatCard label="累计盈亏" :value="fmtMoney(summary?.total_pnl)" :color="pnlColor(summary?.total_pnl) || 'var(--text-muted)'" sub="现价相对成本的浮动盈亏" />
        <StatCard label="总收益率" :value="summary ? `${summary.total_pnl_pct >= 0 ? '+' : ''}${fmtNum(summary.total_pnl_pct)}%` : '—'" :color="pnlColor(summary?.total_pnl_pct) || 'var(--text-muted)'" />
        <StatCard label="持仓数" :value="String(summary?.holding_count ?? 0)" :sub="`${summary?.priced_count ?? 0} 个已取得行情`" />
      </div>

      <!-- 资产配置图表 -->
      <div class="chart-grid">
        <DataPanel title="资产配置（按类型）">
          <BaseChart :option="allocationOption" :height="200" />
        </DataPanel>
        <DataPanel title="券商分布（市值）">
          <BaseChart :option="brokerOption" :height="200" />
        </DataPanel>
        <DataPanel title="账户分布（市值）">
          <BaseChart :option="accountOption" :height="260" />
        </DataPanel>
      </div>

      <!-- 持仓明细表 -->
      <DataPanel title="持仓明细">
        <template #actions>
          <n-select v-model:value="filterType" :options="typeFilterOptions" placeholder="全部类型" clearable size="small" style="width: 110px;" />
          <n-select v-model:value="filterBroker" :options="brokerFilterOptions" placeholder="全部券商" clearable size="small" style="width: 110px;" />
          <n-select v-model:value="filterAccount" :options="accountFilterOptions" placeholder="全部账户" clearable size="small" style="width: 110px;" />
          <n-button size="small" :type="filterLossOnly ? 'primary' : 'default'" @click="filterLossOnly = !filterLossOnly">只看浮亏</n-button>
          <n-button size="small" :type="filterAlertOnly ? 'primary' : 'default'" @click="filterAlertOnly = !filterAlertOnly">只看已触预警</n-button>
          <n-button size="small" type="info" :ghost="!filterDirty" @click="applyFilter">
            <template #icon><n-icon :component="FilterOutline" /></template>
            过滤
          </n-button>
          <n-button size="small" quaternary @click="resetFilter" v-if="appliedType || appliedBroker || appliedAccount || appliedLossOnly || appliedAlertOnly">重置</n-button>
          <n-popover trigger="click" placement="bottom-end">
            <template #trigger>
              <n-button size="small">
                <template #icon><n-icon :component="SettingsOutline" /></template>
                列设置
              </n-button>
            </template>
            <div class="col-set">
              <div class="col-set-title">显示列（点击切换）</div>
              <div v-for="c in toggleableCols" :key="c.key" class="col-set-item">
                <n-checkbox :checked="isColOn(c.key)" @update:checked="(e: boolean) => setCol(c.key, e)">{{ c.title }}</n-checkbox>
              </div>
              <n-button size="tiny" quaternary block @click="resetCols">恢复默认</n-button>
            </div>
          </n-popover>
          <n-tooltip trigger="hover">
            <template #trigger>
              <n-switch v-model:value="autoRefresh" @update:value="toggleAutoRefresh" size="small">
                <template #checked>自动刷新</template>
                <template #unchecked>手动刷新</template>
              </n-switch>
            </template>
            每 30 秒自动刷新行情，价格变动会以绿涨红跌闪烁
          </n-tooltip>
          <n-button text size="small" @click="router.push('/profile')">
            <template #icon><n-icon :component="SettingsOutline" /></template>
            管理券商/账户名
          </n-button>
          <span class="panel-info">{{ summary?.quote_time ? `行情时间: ${new Date(summary.quote_time).toLocaleTimeString('zh-CN')}` : '暂无行情' }}</span>
        </template>
      <n-data-table
        :columns="columns"
        :data="displayItems"
        :row-key="(row: Holding) => row.id"
        :row-class-name="(row: Holding) => row.alert_status === 'stop_loss' ? 'row-alert-stop-loss' : row.alert_status === 'take_profit' ? 'row-alert-take-profit' : ''"
        :bordered="false"
        :single-line="false"
        size="small"
        :pagination="pagination"
        :scroll-x="1700"
          max-height="480"
        />
        <!-- 过滤后汇总行 -->
        <div v-if="filterSummary" class="filter-summary-row">
          <div class="summary-cell summary-label">
            <span class="summary-count">汇总（{{ filterSummary.count }} 个标的，{{ filterSummary.pricedCount }} 个已获行情）</span>
          </div>
          <div class="summary-cell summary-stat">
            <span class="summary-sub-label">总市值</span>
            <span class="summary-value mono">{{ fmtMoney(filterSummary.totalMv) }}</span>
          </div>
          <div class="summary-cell summary-stat">
            <span class="summary-sub-label">总成本</span>
            <span class="summary-value mono">{{ fmtMoney(filterSummary.totalCost) }}</span>
          </div>
          <div class="summary-cell summary-stat">
            <span class="summary-sub-label">浮动盈亏</span>
            <span class="summary-value mono" :style="{ color: pnlColor(filterSummary.totalPnl), fontWeight: 600 }">{{ fmtMoney(filterSummary.totalPnl) }}</span>
          </div>
          <div class="summary-cell summary-stat">
            <span class="summary-sub-label">平均收益率</span>
            <span class="summary-value mono" :style="{ color: pnlColor(filterSummary.avgPnlPct), fontWeight: 600 }">{{ filterSummary.avgPnlPct === null ? '—' : (filterSummary.avgPnlPct >= 0 ? '+' : '') + fmtNum(filterSummary.avgPnlPct) + '%' }}</span>
          </div>
          <div class="summary-cell summary-stat">
            <span class="summary-sub-label">当日盈亏</span>
            <span class="summary-value mono" :style="{ color: pnlColor(filterSummary.totalDailyPnl), fontWeight: 600 }">{{ fmtMoney(filterSummary.totalDailyPnl) }}</span>
          </div>
        </div>
      </DataPanel>

      <!-- 净值走势曲线 -->
      <DataPanel title="净值走势曲线">
        <template #actions>
          <n-button size="small" :loading="snapping" @click="takeSnapshot">
            <template #icon><n-icon :component="CameraOutline" /></template>
            立即快照
          </n-button>
        </template>
        <BaseChart :option="historyOption" :height="220" />
        <n-data-table
          :columns="snapshotColumns"
          :data="[...(snapshots ?? [])].reverse()"
          :row-key="(row: HoldingSnapshot) => row.id"
          :bordered="false"
          :single-line="false"
          size="small"
          max-height="260"
        />
      </DataPanel>
      </div>
        </n-tab-pane>

        <n-tab-pane name="history" tab="历史持仓">
          <div v-if="historySummary" class="history-summary">
            历史持仓 <b>{{ historySummary.count }}</b> 笔 · 已实现盈亏合计
            <b :style="{ color: pnlColor(historySummary.totalRealized) }">{{ fmtMoney(historySummary.totalRealized) }}</b>
          </div>
          <DataPanel title="历史持仓（已平仓）">
            <n-data-table
              :columns="historyColumns"
              :data="history ?? []"
              :row-key="(row: HoldingHistory) => row.id"
              :bordered="false"
              :single-line="false"
              size="small"
              max-height="520"
            />
          <div v-if="!historyLoading && (!history || !history.length)" class="history-empty">
            暂无历史持仓。在「当前持仓」中平仓某标的即会归档到此。
          </div>
        </DataPanel>
        </n-tab-pane>

        <n-tab-pane name="brokers" tab="终端管理">
          <n-card :bordered="false" class="broker-mgmt-card">
            <template #header>终端与券商</template>
            <template #header-extra>
              <n-button size="small" :loading="terminalsLoading" @click="loadTerminals">刷新</n-button>
            </template>

            <!-- 添加终端 -->
            <div class="broker-form">
              <n-input v-model:value="newTerminalName" placeholder="终端名称（如 电脑A / 手机B）" clearable @keyup.enter="addTerminal" />
              <n-input v-model:value="newTerminalRemark" placeholder="备注（可选）" clearable @keyup.enter="addTerminal" />
              <n-button type="primary" :loading="tmSaving" @click="addTerminal">添加终端</n-button>
            </div>

            <!-- 添加券商（选择所属终端） -->
            <div class="broker-form">
              <n-select
                v-model:value="newBrokerTerminalId"
                :options="terminals.map(t => ({ label: t.name, value: t.id }))"
                placeholder="选择所属终端"
                clearable
                filterable
                style="min-width: 160px;"
              />
              <n-input v-model:value="newBrokerName" placeholder="券商名称（如 华泰证券）" clearable @keyup.enter="addBroker" />
              <n-input v-model:value="newBrokerAccount" placeholder="券商账号 account（必填）" clearable @keyup.enter="addBroker" />
              <n-input v-model:value="newBrokerRemark" placeholder="备注（可选）" clearable @keyup.enter="addBroker" />
              <n-button type="primary" :loading="tmSaving" @click="addBroker">添加券商</n-button>
            </div>

            <n-alert type="info" :show-icon="false" class="broker-hint">
              一个终端可包含多个券商。券商 <b>account</b> 由客户端自传作为主标识（不再自动生成 code）；外部上传接口（持仓 / 成交导入）报文中需传入对应 <span class="mono">account</span>。
            </n-alert>

            <!-- 终端列表 + 各自券商 -->
            <div class="broker-list broker-list-scroll">
              <div v-for="t in terminals" :key="t.id" class="terminal-block">
                <div class="terminal-head">
                  <div class="terminal-title">
                    <span class="terminal-name">{{ t.name }}</span>
                    <span v-if="t.remark" class="terminal-remark">{{ t.remark }}</span>
                  </div>
                  <div class="terminal-actions">
                    <n-button text size="small" type="primary" @click="openEditTerminal(t)">编辑</n-button>
                    <n-button text size="small" type="error" @click="deleteTerminal(t)">删除</n-button>
                  </div>
                </div>
                <div class="broker-sublist">
                  <div v-for="b in (t.brokers || [])" :key="b.id" class="broker-item">
                    <div class="broker-item-main">
                      <span class="broker-item-name">{{ b.name }}</span>
                      <span class="broker-item-account mono">{{ b.account }}</span>
                      <span v-if="b.remark" class="broker-item-remark">{{ b.remark }}</span>
                    </div>
                    <div class="broker-actions">
                      <n-button text size="small" type="primary" @click="openEditBroker(t, b)">编辑</n-button>
                      <n-button text size="small" type="error" @click="deleteBroker(t, b)">删除</n-button>
                    </div>
                  </div>
                  <div v-if="!t.brokers || !t.brokers.length" class="broker-empty">
                    该终端下暂无券商
                  </div>
                </div>
              </div>
              <div v-if="terminalsLoaded && !terminals.length" class="broker-empty">
                尚未配置终端，添加终端后即可在其下添加券商
              </div>
            </div>
          </n-card>

          <!-- 终端编辑弹窗 -->
          <n-modal v-model:show="showTerminalModal" preset="card" title="编辑终端" style="width: 480px; max-width: 94vw;" :bordered="false">
            <div class="edit-field">
              <label>终端名称</label>
              <n-input v-model:value="terminalForm.name" placeholder="终端名称" clearable />
            </div>
            <div class="edit-field">
              <label>备注</label>
              <n-input v-model:value="terminalForm.remark" placeholder="备注（可选）" clearable />
            </div>
            <template #footer>
              <div class="modal-footer">
                <n-button @click="showTerminalModal = false">取消</n-button>
                <n-button type="primary" :loading="tmSaving" @click="saveTerminal">保存</n-button>
              </div>
            </template>
          </n-modal>

          <!-- 券商编辑弹窗 -->
          <n-modal v-model:show="showBrokerModal" preset="card" title="编辑券商" style="width: 520px; max-width: 94vw;" :bordered="false">
            <div class="edit-field">
              <label>券商名称</label>
              <n-input v-model:value="brokerForm.name" placeholder="券商名称（如 华泰证券）" clearable />
            </div>
            <div class="edit-field">
              <label>券商账号 account（主标识）</label>
              <n-input v-model:value="brokerForm.account" placeholder="券商账号（客户端自传，唯一）" clearable />
            </div>
            <div class="edit-field">
              <label>备注</label>
              <n-input v-model:value="brokerForm.remark" placeholder="备注（可选）" clearable />
            </div>
            <template #footer>
              <div class="modal-footer">
                <n-button @click="showBrokerModal = false">取消</n-button>
                <n-button type="primary" :loading="tmSaving" @click="saveBroker">保存</n-button>
              </div>
            </template>
          </n-modal>
        </n-tab-pane>

        <n-tab-pane name="imports" tab="上传记录">
          <DataPanel title="上传留痕记录">
            <template #actions>
              <n-button size="small" :loading="importLogsLoading" @click="loadImportLogs">刷新</n-button>
            </template>
            <n-data-table
              :columns="importLogColumns"
              :data="importLogs"
              :row-key="(row: ImportLog) => row.id"
              :bordered="false"
              :single-line="false"
              size="small"
              :scroll-x="1100"
              max-height="520"
            />
            <div v-if="importLogsLoaded && !importLogs.length" class="import-empty">
              暂无上传记录。通过外部上传接口（持仓 / 成交导入）导入数据后即会出现在此。
            </div>
          </DataPanel>
        </n-tab-pane>
      </n-tabs>

    </div>

    <!-- 导入弹窗 -->
    <n-modal v-model:show="showImportModal" preset="card" title="批量导入数据" style="width: 760px; max-width: 94vw;" :bordered="false">
      <n-radio-group v-model:value="importMode" size="small" style="margin-bottom: 12px;">
        <n-radio-button value="json">持仓 · JSON</n-radio-button>
        <n-radio-button value="csv">持仓 · CSV</n-radio-button>
        <n-radio-button value="trades">成交记录</n-radio-button>
      </n-radio-group>

      <!-- ================= 成交记录导入 ================= -->
      <template v-if="importMode === 'trades'">
        <!-- 顶部参数：交易日期 + 券商账户 -->
        <div class="trade-params">
          <div class="edit-field" style="flex: 1; min-width: 160px;">
            <label>交易日期（必填，YYYY-MM-DD）</label>
            <n-date-picker
              v-model:value="tradeDateTs"
              type="date"
              clearable
              style="width: 100%;"
              @update:value="(v: number | null) => { tradeDate = fmtTradeDate(v); previewTrade() }"
            />
          </div>
          <div class="edit-field" style="flex: 1; min-width: 160px;">
            <label>券商（决定 account，整批必传）</label>
            <n-select
              v-model:value="tradeAccount"
              :options="tradeBrokerOptions"
              placeholder="选择券商"
              clearable
              filterable
              @update:value="previewTrade"
            />
          </div>
        </div>
        <div v-if="!tradeBrokerOptions.length" class="import-errors" style="margin-bottom: 14px;">
          尚未配置券商，请先到「终端管理」或「个人中心」添加终端与券商（券商 account 为上传主标识）后再上传成交。
        </div>

        <!-- 字段说明表 -->
        <div class="import-field-docs">
          <div class="import-docs-header">
            <h4>字段说明</h4>
            <n-button size="tiny" quaternary @click="copyTemplate">
              <template #icon><n-icon :component="ClipboardOutline" /></template>
              复制示例
            </n-button>
          </div>
          <table class="import-field-table">
            <thead>
              <tr><th>字段</th><th>类型</th><th>必填</th><th>说明</th></tr>
            </thead>
            <tbody>
              <tr><td class="ft-field">trade_date</td><td class="ft-type">string</td><td class="ft-req">是*</td><td class="ft-desc">交易日期（YYYY-MM-DD），也可在上方日期选择器填写；按 (用户, 交易日) 覆盖上传</td></tr>
              <tr><td class="ft-field">items</td><td class="ft-type">array</td><td class="ft-req">是</td><td class="ft-desc">成交明细数组，每条为一个成交对象（见下）</td></tr>
              <tr><td class="ft-field">items[].code</td><td class="ft-type">string</td><td class="ft-req">是</td><td class="ft-desc">证券代码（如 600519 / 510300 / 00700）</td></tr>
              <tr><td class="ft-field">items[].name</td><td class="ft-type">string</td><td class="ft-req">是</td><td class="ft-desc">证券名称（如 贵州茅台）</td></tr>
              <tr><td class="ft-field">items[].type</td><td class="ft-type">enum</td><td class="ft-req">是</td><td class="ft-desc">持仓类型：stock / etf / fund_otc / option / future / hk_stock</td></tr>
              <tr><td class="ft-field">items[].direction</td><td class="ft-type">enum</td><td class="ft-req">是</td><td class="ft-desc">买卖方向：buy（买入） / sell（卖出）</td></tr>
              <tr><td class="ft-field">items[].price</td><td class="ft-type">number</td><td class="ft-req">是</td><td class="ft-desc">成交价格，单位与 currency 一致</td></tr>
              <tr><td class="ft-field">items[].quantity</td><td class="ft-type">number</td><td class="ft-req">是</td><td class="ft-desc">成交数量（股数/份数/张数，不能为0）</td></tr>
              <tr><td class="ft-field">items[].account</td><td class="ft-type">string</td><td class="ft-opt">否</td><td class="ft-desc">子账户（如 普通 / 两融）</td></tr>
              <tr><td class="ft-field">items[].amount</td><td class="ft-type">number</td><td class="ft-opt">否</td><td class="ft-desc">成交金额，缺省自动 = price × quantity</td></tr>
              <tr><td class="ft-field">items[].fee</td><td class="ft-type">number</td><td class="ft-opt">否</td><td class="ft-desc">手续费 / 佣金，单位与 currency 一致</td></tr>
              <tr><td class="ft-field">items[].currency</td><td class="ft-type">string</td><td class="ft-opt">否</td><td class="ft-desc">币种，默认 CNY；港股可填 HKD</td></tr>
              <tr><td class="ft-field">items[].trade_time</td><td class="ft-type">string</td><td class="ft-opt">否</td><td class="ft-desc">成交时间（HH:MM:SS，可选）</td></tr>
            </tbody>
          </table>
        </div>

        <!-- JSON 示例 -->
        <div class="import-example">
          <div class="import-example-header">
            <h4>JSON 示例</h4>
            <span class="import-example-hint">点击「复制示例」按钮可将示例填入输入框</span>
          </div>
          <div class="import-example-block">
            <pre class="import-example-pre">{{ TRADE_TEMPLATE }}</pre>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="import-input-section">
          <label class="import-input-label">粘贴您的成交记录 JSON（含 trade_date 与 items 数组）</label>
          <n-input
            v-model:value="tradeText"
            type="textarea"
            placeholder='{ "trade_date": "2026-10-22", "items": [ { "code": "600519", "name": "贵州茅台", "type": "stock", "direction": "buy", "price": 1700.5, "quantity": 100 } ] }'
            :autosize="{ minRows: 6, maxRows: 14 }"
            class="mono"
            @input="previewTrade"
          />
        </div>

        <!-- 校验结果 -->
        <div v-if="tradeErrors.length" class="import-errors">
          <div v-for="(e, i) in tradeErrors" :key="i">{{ e }}</div>
        </div>
        <div v-else-if="tradeValidCount > 0" class="import-ok">
          解析成功：{{ tradeValidCount }} 条有效成交
        </div>
      </template>

      <!-- ================= 持仓导入（JSON / CSV） ================= -->
      <template v-else>
        <!-- 字段说明表 -->
        <div class="import-field-docs">
          <div class="import-docs-header">
            <h4>字段说明</h4>
            <n-button size="tiny" quaternary @click="copyTemplate">
              <template #icon><n-icon :component="ClipboardOutline" /></template>
              复制示例
            </n-button>
          </div>
          <table class="import-field-table">
            <thead>
              <tr><th>字段</th><th>类型</th><th>必填</th><th>说明</th></tr>
            </thead>
            <tbody>
              <tr><td class="ft-field">code</td><td class="ft-type">string</td><td class="ft-req">是</td><td class="ft-desc">证券代码（如 600519 / 510300 / 00700）</td></tr>
              <tr><td class="ft-field">name</td><td class="ft-type">string</td><td class="ft-req">是</td><td class="ft-desc">证券名称（如 贵州茅台）</td></tr>
              <tr><td class="ft-field">type</td><td class="ft-type">enum</td><td class="ft-req">是</td><td class="ft-desc">持仓类型：stock(股票) / etf(场内基金) / fund_otc(场外基金) / option(期权) / future(期货) / hk_stock(港股)</td></tr>
              <tr><td class="ft-field">quantity</td><td class="ft-type">number</td><td class="ft-req">是</td><td class="ft-desc">持仓数量（股数/份数/张数，不能为0）</td></tr>
              <tr><td class="ft-field">cost_price</td><td class="ft-type">number</td><td class="ft-req">是</td><td class="ft-desc">成本价（买入均价），单位与 currency 一致</td></tr>
              <tr><td class="ft-field">broker</td><td class="ft-type">string</td><td class="ft-opt">否</td><td class="ft-desc">券商/渠道名称（如 华泰证券、天天基金）</td></tr>
              <tr><td class="ft-field">account</td><td class="ft-type">string</td><td class="ft-opt">否</td><td class="ft-desc">子账户（如 普通 / 两融），用于分账户统计与筛选</td></tr>
              <tr><td class="ft-field">open_date</td><td class="ft-type">string</td><td class="ft-opt">否</td><td class="ft-desc">建仓日期（YYYY-MM-DD）</td></tr>
              <tr><td class="ft-field">currency</td><td class="ft-type">string</td><td class="ft-opt">否</td><td class="ft-desc">币种，默认 CNY（人民币）。港股可填 HKD</td></tr>
              <tr><td class="ft-field">stop_loss_pct</td><td class="ft-type">number</td><td class="ft-opt">否</td><td class="ft-desc">止损线（收益率 %，负值如 -8），触发后顶部预警条与表格高亮提示</td></tr>
              <tr><td class="ft-field">take_profit_pct</td><td class="ft-type">number</td><td class="ft-opt">否</td><td class="ft-desc">止盈线（收益率 %，正值如 20），触发后顶部预警条与表格高亮提示</td></tr>
            </tbody>
          </table>
        </div>

        <template v-if="importMode === 'json'">
          <!-- JSON 示例 -->
          <div class="import-example">
            <div class="import-example-header">
              <h4>JSON 示例</h4>
              <span class="import-example-hint">点击「复制示例」按钮可将示例填入输入框</span>
            </div>
            <div class="import-example-block">
              <pre class="import-example-pre">{{ IMPORT_TEMPLATE }}</pre>
            </div>
          </div>

          <!-- 输入区 -->
          <div class="import-input-section">
            <label class="import-input-label">粘贴您的持仓 JSON</label>
            <n-input
              v-model:value="importText"
              type="textarea"
              placeholder='[{ "code": "600519", "name": "贵州茅台", "type": "stock", "broker": "华泰证券", "quantity": 100, "cost_price": 1700.5 }]'
              :autosize="{ minRows: 6, maxRows: 14 }"
              class="mono"
              @input="previewImport"
            />
          </div>

          <!-- 校验结果 -->
          <div v-if="importErrors.length" class="import-errors">
            <div v-for="(e, i) in importErrors" :key="i">{{ e }}</div>
          </div>
          <div v-else-if="importValidCount > 0" class="import-ok">
            解析成功：{{ importValidCount }} 条有效持仓
          </div>
        </template>

        <template v-else>
          <div class="import-input-section">
            <label class="import-input-label">上传 CSV 文件（支持华泰 PC 客户端导出的持仓表，或 Excel 另存为 CSV）</label>
            <input type="file" accept=".csv,.txt" @change="e => csvFile = (e.target as HTMLInputElement).files?.[0] ?? null" />
            <div style="font-size: 12px; color: var(--text-muted); margin-top: 6px;">
              列头可包含：证券代码、证券名称、持仓数量、成本价、账户 等；未识别的代码将按 6 位代码推断为股票或场内基金。
            </div>
          </div>
          <div class="edit-form" style="margin-top: 12px;">
<div class="edit-field">
<label>默认券商</label>
<n-select v-model:value="csvBroker" :options="editBrokerOptions" placeholder="选择券商" clearable filterable />
</div>
<div class="edit-field">
<label>默认账户</label>
<n-select v-model:value="csvAccount" :options="editAccountOptions" placeholder="选择账户" clearable filterable />
</div>
          </div>
        </template>
      </template>

      <!-- 上传接口说明面板：报文格式 / 接口地址 / curl 示例 -->
      <n-collapse class="import-api-docs" :default-expanded-names="[]">
        <n-collapse-item title="上传接口说明（报文格式 · 接口地址 · curl 示例）" name="api">
          <div class="api-docs">
            <h5>通用约定</h5>
            <ul class="api-notes">
              <li><b>接口前缀</b>：<span class="mono">/api/v1</span>（前端经 nginx <span class="mono">:9080</span> 反代；机器直连后端 <span class="mono">:8001</span>）</li>
              <li><b>无鉴权</b>：机器 / 程序直接调用，无需 JWT。请求体用 <span class="mono">user_id</span> 或 <span class="mono">username</span> 指明归属用户（缺失或不存在 → 400）。</li>
              <li><b>account 整批必传</b>：请求体<b>顶层</b>传一个 <span class="mono">account</span>（券商账号，由客户端自传作为主标识，如 <span class="mono">huatai-12345678</span>），整批统一归属该券商；逐条传的 <span class="mono">broker</span> 会被忽略，实际券商名由后端解析回填。首见该 account 时按 <span class="mono">broker_name</span> / <span class="mono">remark</span> 自动建券商（落默认终端或指定 <span class="mono">terminal</span>）。缺失 → 整批进入 failed，不入库。兼容旧字段 <span class="mono">broker_code</span>（等同于 account）。</li>
              <li><b>source</b>：来源标记（任意字符串），写入上传记录便于追溯，缺省 <span class="mono">"api"</span>。</li>
              <li><b>响应结构</b>：<span class="mono">{ "code": 0, "message": "ok", "data": {...} }</span></li>
            </ul>

            <h5>接口地址</h5>
            <table class="import-field-table">
              <thead><tr><th>用途</th><th>方法 &amp; 路径</th><th>说明</th></tr></thead>
              <tbody>
                <tr><td class="ft-desc">持仓上传（增量合并）</td><td class="ft-field">POST /api/v1/holdings/import/api</td><td class="ft-desc">按 code+type+account 去重；已存在覆盖更新，新增插入；覆盖前旧行入历史表</td></tr>
                <tr><td class="ft-desc">成交上传（按日覆盖）</td><td class="ft-field">POST /api/v1/trades/import</td><td class="ft-desc">按 (用户, trade_date) 全量覆盖；新 trade_date 直接新增</td></tr>
                <tr><td class="ft-desc">查询成交</td><td class="ft-field">GET /api/v1/trades</td><td class="ft-desc">按 user_id/username + 可选 trade_date 过滤</td></tr>
                <tr><td class="ft-desc">成交交易日列表</td><td class="ft-field">GET /api/v1/trades/dates</td><td class="ft-desc">返回该用户所有有成交的交易日（升序）</td></tr>
                <tr><td class="ft-desc">上传记录留痕（需登录）</td><td class="ft-field">GET /api/v1/import-logs</td><td class="ft-desc">本页「上传记录」tab 展示，可用于对账</td></tr>
              </tbody>
            </table>

            <h5>持仓上传报文示例（curl）</h5>
            <div class="import-example-block">
              <pre class="import-example-pre">curl -X POST 'http://192.168.3.53:9080/api/v1/holdings/import/api' \
  -H 'Content-Type: application/json' \
  -d '{
    "username": "sos",
    "source": "my_bot",
    "account": "huatai-12345678",
    "broker_name": "华泰证券",
    "items": [
      { "code": "510300", "name": "沪深300ETF", "type": "etf",
        "account": "普通", "quantity": 10000, "cost_price": 3.85 }
    ]
  }'</pre>
            </div>

            <h5>成交上传报文示例（curl）</h5>
            <div class="import-example-block">
              <pre class="import-example-pre">curl -X POST 'http://192.168.3.53:9080/api/v1/trades/import' \
  -H 'Content-Type: application/json' \
  -d '{
    "username": "sos",
    "source": "my_bot",
    "account": "huatai-12345678",
    "broker_name": "华泰证券",
    "trade_date": "2026-10-28",
    "items": [
      { "code": "510300", "name": "沪深300ETF", "type": "etf",
        "account": "普通", "direction": "buy",
        "price": 3.92, "quantity": 5000 }
    ]
  }'</pre>
            </div>
          </div>
        </n-collapse-item>
      </n-collapse>

      <template #footer>
        <div class="modal-footer">
          <n-button size="small" @click="showImportModal = false">取消</n-button>
          <n-button size="small" type="primary" :loading="importing" @click="submitImport">确认导入</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 编辑持仓弹窗 -->
    <n-modal v-model:show="showEditModal" preset="card" :title="`编辑持仓：${editForm.name}（${editForm.code}）`" style="width: 460px; max-width: 92vw;" :bordered="false">
      <div class="edit-form">
        <div class="edit-field">
          <label>数量</label>
          <n-input-number v-model:value="editForm.quantity" :show-button="false" style="width: 100%;" />
        </div>
        <div class="edit-field">
          <label>成本价</label>
          <n-input-number v-model:value="editForm.cost_price" :show-button="false" :precision="4" style="width: 100%;" />
        </div>
        <div class="edit-field">
          <label>手动现价（留空则使用自动行情）</label>
          <n-input-number v-model:value="editForm.manual_price" :show-button="false" :precision="4" placeholder="期权/场外基金等抓不到行情时手填" style="width: 100%;" />
        </div>
        <div class="edit-field">
          <label>止损线（收益率 %，如 -8 表示亏 8% 预警；留空关闭）</label>
          <div class="alert-input-row">
            <n-input-number v-model:value="editForm.stop_loss_pct" :show-button="false" :precision="2" placeholder="如 -8" style="width: 100%;" />
            <n-button size="tiny" secondary @click="editForm.stop_loss_pct = suggestStopLoss(editForm as any)">建议</n-button>
            <div class="preset-tags">
              <n-button size="tiny" quaternary v-for="p in [-5, -8, -10, -15]" :key="p" @click="editForm.stop_loss_pct = p">{{ p }}%</n-button>
            </div>
          </div>
        </div>
        <div class="edit-field">
          <label>止盈线（收益率 %，如 20 表示赚 20% 预警；留空关闭）</label>
          <div class="alert-input-row">
            <n-input-number v-model:value="editForm.take_profit_pct" :show-button="false" :precision="2" placeholder="如 20" style="width: 100%;" />
            <div class="preset-tags">
              <n-button size="tiny" quaternary v-for="p in [20, 30, 50, 100]" :key="p" @click="editForm.take_profit_pct = p">+{{ p }}%</n-button>
            </div>
          </div>
        </div>
        <div class="edit-field">
          <label>合理价（估值参考，留空关闭估值提示）</label>
          <n-input-number v-model:value="editForm.fair_value" :show-button="false" :precision="4" placeholder="你认为的合理价值，用于估值偏高/偏低提示" style="width: 100%;" />
        </div>
        <div class="edit-field">
          <label>网格下限（留空关闭网格提示）</label>
          <n-input-number v-model:value="editForm.grid_lower" :show-button="false" :precision="4" placeholder="如 3.0，网格最低买入线" style="width: 100%;" />
        </div>
        <div class="edit-field">
          <label>网格上限（需大于下限）</label>
          <n-input-number v-model:value="editForm.grid_upper" :show-button="false" :precision="4" placeholder="如 4.0，网格最高卖出线" style="width: 100%;" />
        </div>
        <div class="edit-field">
          <label>网格间距（相邻买卖线间隔）</label>
          <n-input-number v-model:value="editForm.grid_step" :show-button="false" :precision="4" :min="0" placeholder="如 0.2，自动切成多格" style="width: 100%;" />
        </div>
<div class="edit-field">
<label>券商</label>
<n-select v-model:value="editForm.broker" :options="editBrokerOptions" placeholder="选择券商" clearable filterable />
</div>
<div class="edit-field">
<label>账户</label>
<n-select v-model:value="editForm.account" :options="editAccountOptions" placeholder="选择账户" clearable filterable />
</div>
      </div>
      <template #footer>
        <div class="modal-footer">
          <n-button size="small" @click="showEditModal = false">取消</n-button>
          <n-button size="small" type="primary" :loading="editSaving" @click="submitEdit">保存</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 加仓模拟器弹窗 -->
    <n-modal v-model:show="showAddModal" preset="card" :title="`加仓模拟：${addRow?.name}（${addRow?.code}）`" style="width: 520px; max-width: 94vw;" :bordered="false">
      <div v-if="addRow" class="add-sim">
        <div class="add-sim-current">
          <div class="add-sim-cur-item"><span>现价</span><b class="mono">{{ fmtNum(addRow.price, 3) }}</b></div>
          <div class="add-sim-cur-item"><span>持仓量</span><b class="mono">{{ fmtNum(addRow.quantity) }}</b></div>
          <div class="add-sim-cur-item"><span>成本价</span><b class="mono">{{ fmtNum(addRow.cost_price, 3) }}</b></div>
          <div class="add-sim-cur-item"><span>当前收益率</span><b class="mono" :style="{ color: pnlColor(addRow.pnl_pct) }">{{ addRow.pnl_pct === null ? '—' : (addRow.pnl_pct >= 0 ? '+' : '') + fmtNum(addRow.pnl_pct) + '%' }}</b></div>
        </div>

        <div class="edit-form" style="margin-top: 4px;">
          <div class="edit-field">
            <label>拟加仓数量</label>
            <n-input-number v-model:value="addForm.addQty" :show-button="false" :min="0" placeholder="例如 100" style="width: 100%;" />
          </div>
          <div class="edit-field">
            <label>拟加仓价格（默认现价）</label>
            <n-input-number v-model:value="addForm.addPrice" :show-button="false" :precision="3" :min="0" placeholder="留空则按现价估算" style="width: 100%;" />
          </div>
        </div>

        <div v-if="addSim" class="add-sim-result">
          <div class="add-sim-row">
            <span>加仓金额</span><b class="mono">{{ fmtMoney(addSim.addAmount) }}</b>
          </div>
          <div class="add-sim-row">
            <span>加仓后数量</span><b class="mono">{{ fmtNum(addSim.newQty) }}</b>
          </div>
          <div class="add-sim-row">
            <span>加仓后成本价</span>
            <b class="mono" :style="{ color: addSim.costDelta > 0 ? 'var(--color-danger)' : 'var(--color-success)' }">
              {{ fmtNum(addSim.newAvg, 3) }}
              <i class="add-sim-delta">{{ addSim.costDelta >= 0 ? '+' : '' }}{{ fmtNum(addSim.costDelta, 3) }}</i>
            </b>
          </div>
          <div class="add-sim-row">
            <span>回本所需涨幅</span>
            <b class="mono" :style="{ color: addSim.breakEvenRise > 0 ? 'var(--color-danger)' : 'var(--color-success)' }">
              {{ addSim.breakEvenRise >= 0 ? '+' : '' }}{{ fmtNum(addSim.breakEvenRise) }}%
            </b>
          </div>
          <div class="add-sim-row">
            <span>现价下浮盈亏</span>
            <b class="mono" :style="{ color: pnlColor(addSim.newPnl) }">{{ fmtMoney(addSim.newPnl) }}</b>
            <i class="add-sim-delta" :style="{ color: pnlColor(addSim.newPnl - addSim.oldPnl) }">
              较当前 {{ (addSim.newPnl - addSim.oldPnl) >= 0 ? '+' : '' }}{{ fmtMoney(addSim.newPnl - addSim.oldPnl) }}
            </i>
          </div>
          <div class="add-sim-hint" v-if="addRow.pnl_pct !== null && addRow.pnl_pct < 0 && addSim.costDelta < 0">
            加仓后成本摊低 {{ fmtNum(-addSim.costDelta, 3) }}，回本所需涨幅缩小，但总浮亏金额扩大，请确认现金与风险承受。
          </div>
          <div class="add-sim-hint warn" v-else-if="addSim.costDelta > 0">
            本次加仓价格高于原成本，会抬高成本价，回本难度增加。
          </div>
        </div>
        <div v-else class="add-sim-empty">填写加仓数量后，实时计算加仓后的成本价、回本涨幅与盈亏变化。</div>
      </div>
      <template #footer>
        <div class="modal-footer">
          <n-button size="small" @click="showAddModal = false">取消</n-button>
          <n-button size="small" type="primary" :loading="addApplying" :disabled="!addSim" @click="applyAdd">应用到持仓</n-button>
        </div>
      </template>
    </n-modal>
  </LoadingState>
</template>

<style>
.holdings-page .holding-name { font-weight: 600; color: var(--text-primary); }
.holdings-page .mono, .import-errors .mono { font-family: 'JetBrains Mono', monospace; }
.holdings-page .price-src { margin-left: 4px; font-size: 9px; color: var(--text-muted); border: 1px solid var(--border-default); border-radius: 3px; padding: 0 3px; }
.holdings-page .row-actions { display: flex; gap: 4px; }
.holdings-page .row-actions .n-button { font-weight: 500; border-radius: 4px; padding: 0 6px; }
</style>

<style scoped>
.holdings-page { display: flex; flex-direction: column; gap: 20px; }

/* 当前持仓 tab 内各区域（预警条 / 概览卡 / 图表 / 明细表 / 走势曲线）纵向间距 */
.current-section { display: flex; flex-direction: column; gap: 24px; }

.warnings-strip { display: flex; flex-wrap: wrap; gap: 8px; }
.warning-item {
  font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 6px; border: 1px solid;
}
.warning-item.warn { background: rgba(134, 79, 0, 0.1); color: #864f00; border-color: rgba(134, 79, 0, 0.3); }
.warning-item.danger { background: rgba(147, 0, 10, 0.08); color: #93000a; border-color: rgba(147, 0, 10, 0.28); }

.stat-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; }
.chart-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }

.panel-info { font-size: 12px; color: var(--text-muted); white-space: nowrap; }

/* 导入弹窗：字段说明表 */
.import-field-docs { margin-bottom: 16px; }
.import-docs-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.import-docs-header h4 { font-family: 'Work Sans', sans-serif; font-size: 13px; font-weight: 700; color: var(--text-primary); margin: 0; }
.import-field-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.import-field-table th { text-align: left; padding: 6px 10px; background: var(--bg-overlay); border: 1px solid var(--border-default); font-weight: 700; color: var(--text-muted); font-size: 11px; }
.import-field-table td { padding: 6px 10px; border: 1px solid var(--border-default); vertical-align: top; }
.ft-req { color: var(--color-danger); font-weight: 700; text-align: center; }
.ft-opt { color: var(--text-muted); text-align: center; }

/* 导入弹窗：JSON 示例 */
.import-example { margin-bottom: 16px; }
.import-example-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.import-example-header h4 { font-family: 'Work Sans', sans-serif; font-size: 13px; font-weight: 700; color: var(--text-primary); margin: 0; }
.import-example-hint { font-size: 11px; color: var(--text-muted); }
.import-example-block { background: var(--bg-overlay); border: 1px solid var(--border-default); border-radius: 6px; max-height: 220px; overflow-y: auto; }
.import-example-pre { margin: 0; padding: 12px; font-family: 'JetBrains Mono', monospace; font-size: 11px; line-height: 1.5; color: var(--text-primary); white-space: pre-wrap; word-break: break-all; }

/* 导入弹窗：输入区 */
.import-input-section { margin-bottom: 12px; }
.import-input-label { display: block; font-size: 12px; font-weight: 700; color: var(--text-muted); margin-bottom: 6px; }
.import-errors { margin-top: 10px; padding: 10px 12px; background: rgba(147, 0, 10, 0.06); border: 1px solid rgba(147, 0, 10, 0.2); border-radius: 6px; color: #93000a; font-size: 12px; display: flex; flex-direction: column; gap: 4px; max-height: 140px; overflow-y: auto; }
.import-ok { margin-top: 10px; font-size: 12px; color: var(--color-success); font-weight: 600; }

/* 成交导入：顶部参数行（日期 + 券商账户） */
.trade-params { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 14px; }

/* 上传接口说明面板 */
.import-api-docs { margin-top: 8px; }
.import-api-docs :deep(.n-collapse-item__header) { font-size: 12px; font-weight: 700; color: var(--text-primary); }
.api-docs { display: flex; flex-direction: column; gap: 10px; padding-top: 4px; }
.api-docs h5 { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; color: var(--text-primary); margin: 4px 0 0; }
.api-notes { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: var(--text-secondary); line-height: 1.6; }
.api-notes li { line-height: 1.6; }
.api-notes b { color: var(--text-primary); }

.edit-form { display: flex; flex-direction: column; gap: 12px; }
.edit-field { display: flex; flex-direction: column; gap: 4px; }
.edit-field label { font-size: 11px; font-weight: 700; color: var(--text-muted); }

/* 编辑弹窗：止损/止盈快捷预设 */
.alert-input-row { display: flex; flex-direction: column; gap: 6px; }
.preset-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.preset-tags .n-button { font-size: 10px; padding: 0 6px; }

/* 持仓表：预警触发行高亮 */
.holdings-page .n-data-table .row-alert-stop-loss td {
  background: rgba(147, 0, 10, 0.10) !important;
}
.holdings-page .n-data-table .row-alert-take-profit td {
  background: rgba(61, 122, 74, 0.10) !important;
}

/* 加仓模拟器 */
.add-sim { display: flex; flex-direction: column; gap: 14px; }
.add-sim-current { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; background: var(--bg-overlay); border: 1px solid var(--border-default); border-radius: 6px; padding: 10px 12px; }
.add-sim-cur-item { display: flex; flex-direction: column; gap: 2px; }
.add-sim-cur-item span { font-size: 10px; color: var(--text-muted); }
.add-sim-cur-item b { font-size: 13px; color: var(--text-primary); }
.add-sim-result { display: flex; flex-direction: column; gap: 8px; border: 1px solid var(--border-default); border-radius: 6px; padding: 12px; background: var(--bg-subtle); }
.add-sim-row { display: flex; align-items: baseline; gap: 8px; font-size: 12px; }
.add-sim-row span { color: var(--text-muted); min-width: 110px; }
.add-sim-row b { font-size: 14px; }
.add-sim-delta { font-style: normal; font-size: 11px; margin-left: 4px; opacity: 0.85; }
.add-sim-hint { font-size: 11px; line-height: 1.6; color: var(--color-success); background: rgba(61,122,74,0.08); border-radius: 5px; padding: 6px 10px; }
.add-sim-hint.warn { color: var(--color-danger); background: rgba(147,0,10,0.06); }
.add-sim-empty { font-size: 12px; color: var(--text-muted); text-align: center; padding: 18px 0; }

.modal-footer { display: flex; justify-content: flex-end; gap: 8px; }

/* AI 分析数据面板 */
.ai-panel { display: flex; flex-direction: column; gap: 12px; }
.ai-desc { font-size: 12px; color: var(--text-secondary); line-height: 1.6; background: var(--bg-overlay); border-radius: 6px; padding: 8px 12px; }
.ai-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ai-json-block { background: var(--bg-overlay); border: 1px solid var(--border-default); border-radius: 6px; max-height: 400px; overflow-y: auto; }
.ai-json-pre { margin: 0; padding: 12px; font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.5; color: var(--text-primary); white-space: pre-wrap; word-break: break-all; }
.ai-field-docs h4 { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); margin: 0 0 8px; }
.field-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.field-table th { text-align: left; padding: 6px 10px; background: var(--bg-overlay); border-bottom: 1px solid var(--border-default); font-weight: 700; color: var(--text-muted); font-size: 11px; letter-spacing: 0.03em; }
.field-table td { padding: 6px 10px; border-bottom: 1px solid var(--bg-subtle); vertical-align: top; }
.field-table tr:hover td { background: var(--bg-overlay); }
.ft-path { color: var(--text-muted); font-family: 'JetBrains Mono', monospace; font-size: 11px; white-space: nowrap; }
.ft-field { color: var(--color-primary); font-family: 'JetBrains Mono', monospace; font-weight: 600; }
.ft-type { color: var(--text-muted); font-family: 'JetBrains Mono', monospace; font-size: 11px; white-space: nowrap; }
.ft-desc { color: var(--text-secondary); line-height: 1.5; }

/* 历史持仓 Tab */
.holdings-tabs { margin-top: 4px; }
.history-summary { font-size: 13px; color: var(--text-secondary); margin: 4px 0 10px; padding: 8px 12px; background: var(--bg-subtle); border: 1px solid var(--border-default); border-radius: 6px; }
.history-summary b { color: var(--text-primary); font-family: 'JetBrains Mono', monospace; }
.history-empty { padding: 24px; text-align: center; font-size: 12px; color: var(--text-muted); background: var(--bg-subtle); border-radius: 6px; }

/* 券商管理 Tab */
.broker-mgmt-card { border-radius: 10px; }
.broker-form { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.broker-form .n-input { flex: 1; min-width: 160px; }
.broker-hint { margin-bottom: 12px; font-size: 12px; line-height: 1.6; }
.broker-hint .mono { font-family: 'JetBrains Mono', monospace; color: var(--color-primary); }
.broker-list { display: flex; flex-direction: column; gap: 6px; }
.broker-list-scroll { max-height: 360px; overflow-y: auto; }
.broker-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 6px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-default);
}
.broker-item-main { display: flex; align-items: baseline; gap: 8px; flex: 1; min-width: 0; }
.broker-item-name { font-weight: 600; font-size: 14px; color: var(--text-primary); }
.broker-item-account { font-size: 12px; color: var(--text-muted); }
.broker-item-code { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.broker-code-text { font-size: 13px; color: var(--color-primary); font-weight: 600; }
.broker-empty { padding: 16px; text-align: center; font-size: 12px; color: var(--text-muted); background: var(--bg-subtle); border-radius: 6px; }

/* 终端管理：二级结构 */
.terminal-block {
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--bg-subtle);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.terminal-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.terminal-title { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.terminal-name { font-weight: 700; font-size: 15px; color: var(--text-primary); }
.terminal-remark { font-size: 12px; color: var(--text-muted); }
.terminal-actions { display: flex; gap: 10px; flex-shrink: 0; }
.broker-sublist { display: flex; flex-direction: column; gap: 6px; padding-left: 12px; border-left: 2px solid var(--border-default); }
.broker-item-remark { font-size: 12px; color: var(--text-muted); }
.broker-actions { display: flex; gap: 10px; flex-shrink: 0; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; }


/* 上传记录 Tab */
.import-empty { padding: 24px; text-align: center; font-size: 12px; color: var(--text-muted); background: var(--bg-subtle); border-radius: 6px; margin-top: 10px; }
.import-fail-empty { padding: 8px 12px; font-size: 12px; color: var(--text-muted); }
.import-fail-list { display: flex; flex-direction: column; gap: 4px; padding: 4px 8px; }
.import-fail-item { display: flex; align-items: center; gap: 10px; font-size: 12px; padding: 4px 8px; background: var(--bg-subtle); border-radius: 4px; }
.import-fail-idx { color: var(--text-muted); }
.import-fail-code { color: var(--color-primary); }
.import-fail-reason { color: var(--color-danger); flex: 1; }
.broker-list-scroll::-webkit-scrollbar { width: 6px; }
.broker-list-scroll::-webkit-scrollbar-thumb { background: var(--border-default); border-radius: 3px; }

/* 价格闪烁（绿涨红跌） */
.holdings-page .flash-up { animation: flashUp 0.9s ease-out; }
.holdings-page .flash-down { animation: flashDown 0.9s ease-out; }
@keyframes flashUp {
  0% { background: rgba(61, 122, 74, 0.5); }
  100% { background: transparent; }
}
@keyframes flashDown {
  0% { background: rgba(180, 40, 50, 0.5); }
  100% { background: transparent; }
}

/* 列设置弹层 */
.col-set { width: 168px; }
.col-set-title { font-size: 11px; font-weight: 700; color: var(--text-muted); margin-bottom: 8px; }
.col-set-item { padding: 4px 0; }
.col-set .n-button { margin-top: 8px; }

/* 列标题帮助问号 */
.col-title-with-help { display: inline-flex; align-items: center; gap: 3px; }
.col-help-mark {
  display: inline-flex; align-items: center; justify-content: center;
  width: 13px; height: 13px; border-radius: 50%;
  font-size: 9px; font-weight: 700; line-height: 1;
  color: var(--text-muted); background: var(--bg-overlay);
  border: 1px solid var(--border-default); cursor: help;
  transition: color .15s, background .15s, border-color .15s;
}
.col-help-mark:hover {
  color: #fff; background: var(--color-primary); border-color: var(--color-primary);
}

@media (max-width: 1024px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .chart-grid { grid-template-columns: 1fr; }
}

/* 过滤后汇总行 */
.filter-summary-row {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 10px 16px;
  margin-top: 8px;
  background: var(--bg-overlay);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  flex-wrap: wrap;
}
.summary-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.summary-label {
  margin-right: auto;
}
.summary-count {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}
.summary-sub-label {
  font-size: 10px;
  color: var(--text-muted);
}
.summary-value {
  font-size: 14px;
  color: var(--text-primary);
}
</style>
