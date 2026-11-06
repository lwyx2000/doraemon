<script setup lang="ts">
defineOptions({ name: 'TradingLedgerPanel' })
import { ref, computed, h, watch, onMounted } from 'vue'
import {
  NButton, NInput, NSelect, NRadioGroup, NRadioButton, NTabs, NTabPane,
  NDataTable, NStatistic, NCard, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useAsyncData } from '../composables/useApi'
import { api } from '../utils/api'
import { exportToCSV } from '../utils/export'
import LoadingState from '../components/LoadingState.vue'
import type {
  SettlementRow, SettlementList, SettlementImportFailedRow, SettlementImportResult,
  DailySummary, TradeRow, DailyTradeList,
  ClosedRound, RebuiltPosition, ClosedRoundList,
} from '../types'

const message = useMessage()

// ---------- 格式化（金额 ¥ + 千分位；无数据显示 —）----------
function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `¥${fmtNum(v)}`
}
// A股惯例：盈利红（--color-danger，红涨）、亏损绿（--color-success，绿跌）
function pnlColor(v: number | null | undefined): string | undefined {
  if (v === null || v === undefined || Number.isNaN(v)) return undefined
  return v >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
}
function pnlCell(v: number | null | undefined) {
  const color = pnlColor(v)
  return h('span', { class: 'mono', style: color ? `color:${color}` : undefined }, fmtMoney(v))
}
function moneyCell(v: number | null | undefined) {
  return h('span', { class: 'mono' }, fmtMoney(v))
}
function numCell(v: number | null | undefined, digits = 2) {
  return h('span', { class: 'mono' }, fmtNum(v, digits))
}
function pctCell(v: number | null | undefined) {
  const color = pnlColor(v)
  const text = v === null || v === undefined || Number.isNaN(v)
    ? '—' : `${v >= 0 ? '+' : ''}${fmtNum(v)}%`
  return h('span', { class: 'mono', style: color ? `color:${color}` : undefined }, text)
}
function textCell(v: string | null | undefined) {
  return h('span', { class: 'mono' }, v || '—')
}

const DIR_LABELS: Record<string, string> = {
  buy: '买入', sell: '卖出', cash_in: '资金转入', cash_out: '资金转出',
  dividend: '分红', interest: '利息', other: '其他',
}
function dirLabel(d: string | null | undefined): string {
  return (d && DIR_LABELS[d]) || d || '—'
}
function dirCell(d: string | null | undefined) {
  const color = d === 'buy' ? 'var(--color-danger)' : d === 'sell' ? 'var(--color-success)' : undefined
  return h('span', { style: color ? `color:${color}` : undefined }, dirLabel(d))
}
const directionOptions: Array<{ label: string; value: string }> = [
  { label: '全部方向', value: '' },
  { label: '买入', value: 'buy' },
  { label: '卖出', value: 'sell' },
  { label: '资金转入', value: 'cash_in' },
  { label: '资金转出', value: 'cash_out' },
  { label: '分红', value: 'dividend' },
  { label: '利息', value: 'interest' },
  { label: '其他', value: 'other' },
]

// ---------- 子区 / 筛选 ----------
const ledgerTab = ref<'daily' | 'settlement' | 'closed' | 'import'>('daily')

const dailyFrom = ref('')
const dailyTo = ref('')
const dailyCode = ref('')

const settleFrom = ref('')
const settleTo = ref('')
const settleCode = ref('')
const settleDirection = ref<string>('')
const SETTLE_LIMIT = 5000

// ---------- 数据（useAsyncData：业务数据本身，加载/错误由 request 统一处理）----------
const { data: dailyData, loading: dailyLoading, error: dailyError, refresh: refreshDaily } =
  useAsyncData<DailyTradeList>(() => api.getDailyTrades({
    from: dailyFrom.value, to: dailyTo.value, code: dailyCode.value,
  }))
const { data: settleData, loading: settleLoading, error: settleError, refresh: refreshSettle } =
  useAsyncData<SettlementList>(() => api.getSettlements({
    from: settleFrom.value, to: settleTo.value, code: settleCode.value, limit: SETTLE_LIMIT,
  }))
const { data: closedData, loading: closedLoading, error: closedError, refresh: refreshClosed } =
  useAsyncData<ClosedRoundList>(() => api.getClosedRounds())

watch(dailyError, (v) => { if (v) message.error(`每日成交加载失败：${v}`) })
watch(settleError, (v) => { if (v) message.error(`交割单加载失败：${v}`) })
watch(closedError, (v) => { if (v) message.error(`已清仓数据加载失败：${v}`) })

function loadActive() {
  if (ledgerTab.value === 'daily') refreshDaily()
  else if (ledgerTab.value === 'settlement') refreshSettle()
  else if (ledgerTab.value === 'closed') refreshClosed()
}
watch(ledgerTab, () => loadActive())
onMounted(() => { loadActive() })

function refreshAll() {
  refreshDaily()
  refreshSettle()
  refreshClosed()
}

// 模板中统一使用带空值的计算属性，避免 v-else 分支里对可空 ref 直接取属性
const dailyDays = computed<DailySummary[]>(() => dailyData.value?.days ?? [])
const dailyItems = computed<TradeRow[]>(() => dailyData.value?.items ?? [])
const settleTotal = computed(() => settleData.value?.total ?? 0)
const closedItems = computed<ClosedRound[]>(() => closedData.value?.items ?? [])
const openPositions = computed<RebuiltPosition[]>(() => closedData.value?.open_positions ?? [])
const importFailed = computed<SettlementImportFailedRow[]>(() => importResult.value?.failed ?? [])
const importBrokersText = computed(() => {
  const b = importResult.value?.brokers
  return b && b.length ? b.join('、') : '—'
})

// ---------- 每日成交 ----------
const dailyTotals = computed(() => {
  const days = dailyData.value?.days ?? []
  const sum = (key: 'buy_amount' | 'sell_amount' | 'fee_total' | 'net_amount' | 't_net_pnl') =>
    days.reduce((acc, d) => acc + (d[key] ?? 0), 0)
  return {
    trade_count: days.reduce((acc, d) => acc + (d.trade_count ?? 0), 0),
    buy_amount: sum('buy_amount'),
    sell_amount: sum('sell_amount'),
    fee_total: sum('fee_total'),
  }
})
const dailyStats = computed(() => [
  { label: '成交笔数', value: String(dailyTotals.value.trade_count) },
  { label: '买入额', value: fmtMoney(dailyTotals.value.buy_amount) },
  { label: '卖出额', value: fmtMoney(dailyTotals.value.sell_amount) },
  { label: '费用', value: fmtMoney(dailyTotals.value.fee_total) },
])

const dayColumns: DataTableColumns<DailySummary> = [
  { title: '交易日', key: 'trade_date', width: 120, render: (row) => textCell(row.trade_date) },
  { title: '成交笔数', key: 'trade_count', width: 100, align: 'right', render: (row) => numCell(row.trade_count, 0) },
  { title: '买入额', key: 'buy_amount', width: 140, align: 'right', render: (row) => moneyCell(row.buy_amount) },
  { title: '卖出额', key: 'sell_amount', width: 140, align: 'right', render: (row) => moneyCell(row.sell_amount) },
  { title: '净额', key: 'net_amount', width: 140, align: 'right', render: (row) => pnlCell(row.net_amount) },
  { title: '费用', key: 'fee_total', width: 120, align: 'right', render: (row) => moneyCell(row.fee_total) },
  { title: '做T净收益', key: 't_net_pnl', width: 140, align: 'right', render: (row) => pnlCell(row.t_net_pnl) },
]
const tradeColumns: DataTableColumns<TradeRow> = [
  { title: '交易日', key: 'trade_date', width: 120, render: (row) => textCell(row.trade_date) },
  { title: '成交时间', key: 'trade_time', width: 100, render: (row) => textCell(row.trade_time) },
  { title: '代码', key: 'code', width: 100, render: (row) => textCell(row.code) },
  { title: '名称', key: 'name', width: 110, render: (row) => textCell(row.name) },
  { title: '方向', key: 'direction', width: 90, render: (row) => dirCell(row.direction) },
  { title: '价格', key: 'price', width: 100, align: 'right', render: (row) => numCell(row.price, 3) },
  { title: '数量', key: 'quantity', width: 100, align: 'right', render: (row) => numCell(row.quantity, 0) },
  { title: '成交额', key: 'amount', width: 140, align: 'right', render: (row) => moneyCell(row.amount) },
  { title: '费用合计', key: 'fee_total', width: 120, align: 'right', render: (row) => moneyCell(row.fee_total) },
  { title: '账户', key: 'account', width: 130, render: (row) => textCell(row.account) },
  { title: '来源', key: 'source', width: 110, render: (row) => textCell(row.source) },
]

// ---------- 交割单 ----------
const filteredSettleRows = computed<SettlementRow[]>(() => {
  const items = settleData.value?.items ?? []
  if (!settleDirection.value) return items
  return items.filter(r => r.direction === settleDirection.value)
})
const settlePagination = { pageSize: 20, showSizePicker: true, pageSizes: [10, 20, 50, 100] }
const settleColumns: DataTableColumns<SettlementRow> = [
  { title: '成交日期', key: 'trade_date', width: 120, render: (row) => textCell(row.trade_date) },
  { title: '成交时间', key: 'trade_time', width: 100, render: (row) => textCell(row.trade_time) },
  { title: '代码', key: 'code', width: 100, render: (row) => textCell(row.code) },
  { title: '名称', key: 'name', width: 110, render: (row) => textCell(row.name) },
  { title: '方向', key: 'direction', width: 100, render: (row) => dirCell(row.direction) },
  { title: '价格', key: 'price', width: 100, align: 'right', render: (row) => numCell(row.price, 3) },
  { title: '数量', key: 'quantity', width: 100, align: 'right', render: (row) => numCell(row.quantity, 0) },
  { title: '成交额', key: 'amount', width: 140, align: 'right', render: (row) => moneyCell(row.amount) },
  { title: '佣金', key: 'commission', width: 110, align: 'right', render: (row) => moneyCell(row.commission) },
  { title: '印花税', key: 'stamp_tax', width: 110, align: 'right', render: (row) => moneyCell(row.stamp_tax) },
  { title: '过户费', key: 'transfer_fee', width: 110, align: 'right', render: (row) => moneyCell(row.transfer_fee) },
  { title: '费用合计', key: 'fee_total', width: 120, align: 'right', render: (row) => moneyCell(row.fee_total) },
  { title: '发生金额', key: 'net_amount', width: 140, align: 'right', render: (row) => pnlCell(row.net_amount) },
  { title: '成交编号', key: 'trade_id', width: 150, render: (row) => textCell(row.trade_id) },
  { title: '账户', key: 'account', width: 130, render: (row) => textCell(row.account) },
]
function exportSettlements() {
  const rows = filteredSettleRows.value
  if (!rows.length) { message.warning('没有可导出的交割单数据'); return }
  const headers = [
    '成交日期', '成交时间', '代码', '名称', '方向', '价格', '数量', '成交额',
    '佣金', '印花税', '过户费', '其他费用', '费用合计', '发生金额', '成交编号', '账户', '币种', '来源',
  ]
  const data = rows.map(r => [
    r.trade_date, r.trade_time, r.code, r.name, dirLabel(r.direction), r.price, r.quantity, r.amount,
    r.commission, r.stamp_tax, r.transfer_fee, r.other_fee, r.fee_total, r.net_amount,
    r.trade_id, r.account, r.currency, r.source,
  ])
  exportToCSV('交割单', headers, data)
  message.success(`已导出 ${rows.length} 条交割单`)
}

// ---------- 已清仓 ----------
const closedStats = computed(() => {
  const s = closedData.value?.summary
  return [
    { label: '已清仓回合', value: s ? String(s.round_count) : '—' },
    { label: '盈利回合', value: s ? String(s.win_count) : '—' },
    { label: '胜率', value: s && s.win_rate !== null ? `${fmtNum(s.win_rate)}%` : '—' },
    { label: '累计已实现盈亏', value: fmtMoney(s?.total_realized_pnl) },
    { label: '总费用', value: fmtMoney(s?.total_fee) },
    { label: '平均持有天数', value: fmtNum(s?.avg_holding_days) },
  ]
})
const closedColumns: DataTableColumns<ClosedRound> = [
  { title: '代码', key: 'code', width: 100, render: (row) => textCell(row.code) },
  { title: '名称', key: 'name', width: 110, render: (row) => textCell(row.name) },
  { title: '数量', key: 'quantity', width: 100, align: 'right', render: (row) => numCell(row.quantity, 0) },
  { title: '买入均价', key: 'buy_avg_price', width: 120, align: 'right', render: (row) => numCell(row.buy_avg_price, 3) },
  { title: '卖出均价', key: 'sell_avg_price', width: 120, align: 'right', render: (row) => numCell(row.sell_avg_price, 3) },
  { title: '持有天数', key: 'holding_days', width: 110, align: 'right', render: (row) => numCell(row.holding_days, 0) },
  { title: '毛盈亏', key: 'gross_pnl', width: 140, align: 'right', render: (row) => pnlCell(row.gross_pnl) },
  { title: '费用', key: 'fee_total', width: 120, align: 'right', render: (row) => moneyCell(row.fee_total) },
  { title: '净盈亏', key: 'realized_pnl', width: 140, align: 'right', render: (row) => pnlCell(row.realized_pnl) },
  { title: '收益率', key: 'return_pct', width: 120, align: 'right', render: (row) => pctCell(row.return_pct) },
]
const positionColumns: DataTableColumns<RebuiltPosition> = [
  { title: '代码', key: 'code', width: 110, render: (row) => textCell(row.code) },
  { title: '名称', key: 'name', width: 120, render: (row) => textCell(row.name) },
  { title: '数量', key: 'quantity', width: 110, align: 'right', render: (row) => numCell(row.quantity, 0) },
  { title: '成本价', key: 'cost_price', width: 120, align: 'right', render: (row) => numCell(row.cost_price, 3) },
  { title: '首次买入', key: 'first_buy_date', width: 140, render: (row) => textCell(row.first_buy_date) },
  { title: '成本内费用', key: 'fee_in_cost', width: 130, align: 'right', render: (row) => moneyCell(row.fee_in_cost) },
]
const failedColumns: DataTableColumns<SettlementImportFailedRow> = [
  { title: '行号', key: 'row', width: 100, render: (row) => numCell(row.row, 0) },
  { title: '代码', key: 'code', width: 150, render: (row) => textCell(row.code) },
  { title: '失败原因', key: 'reason', render: (row) => textCell(row.reason) },
]

// ---------- 导入交割单 ----------
const importFile = ref<File | null>(null)
const importBroker = ref('')
const importAccount = ref('')
const importMode = ref<'merge' | 'replace'>('merge')
const importing = ref(false)
const importResult = ref<SettlementImportResult | null>(null)
function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  importFile.value = input.files?.[0] ?? null
}
async function doImport() {
  if (!importFile.value) { message.warning('请先选择交割单文件'); return }
  importing.value = true
  try {
    const res = await api.importSettlementFile(
      importFile.value,
      importBroker.value || undefined,
      importAccount.value || undefined,
      importMode.value,
    )
    importResult.value = res
    message.success(`导入完成：新增 ${res.inserted} 条，重复跳过 ${res.duplicates} 条`)
    refreshAll()
  } catch (e) {
    message.error(e instanceof Error ? e.message : String(e))
  } finally {
    importing.value = false
  }
}

// 按日期清空重导
const clearDate = ref('')
const clearing = ref(false)
async function clearByDate() {
  if (!clearDate.value) { message.warning('请输入要清空的成交日期（YYYY-MM-DD）'); return }
  clearing.value = true
  try {
    const res = await api.clearSettlements(clearDate.value)
    message.success(`已清空 ${clearDate.value} 的 ${res.deleted} 条交割单`)
    refreshAll()
  } catch (e) {
    message.error(e instanceof Error ? e.message : String(e))
  } finally {
    clearing.value = false
  }
}

// 可选：粘贴 JSON 导入每日成交
const dailyTradeDate = ref('')
const dailyJsonText = ref('')
const dailyImporting = ref(false)
async function importDailyJson() {
  if (!dailyTradeDate.value) { message.warning('请输入交易日期'); return }
  let parsed: unknown
  try {
    parsed = JSON.parse(dailyJsonText.value)
  } catch {
    message.error('JSON 解析失败，请检查格式'); return
  }
  if (!Array.isArray(parsed)) { message.error('请输入每日成交的 JSON 数组'); return }
  dailyImporting.value = true
  try {
    const res = await api.importDailyTrades({
      trade_date: dailyTradeDate.value,
      items: parsed as Array<Record<string, unknown>>,
      source: 'manual-paste',
    })
    message.success(`每日成交导入：覆盖删除 ${res.deleted} 条，插入 ${res.inserted} 条`)
    refreshDaily()
  } catch (e) {
    message.error(e instanceof Error ? e.message : String(e))
  } finally {
    dailyImporting.value = false
  }
}
</script>

<template>
  <div class="ledger-panel">
    <div class="panel-head">
      <span class="panel-title">交易台账 · 券商交割单</span>
      <n-button size="small" @click="loadActive">刷新</n-button>
    </div>

    <n-tabs type="line" v-model:value="ledgerTab" size="small">
      <!-- 每日成交 -->
      <n-tab-pane name="daily" tab="每日成交">
        <LoadingState :loading="dailyLoading" :error="dailyError" @retry="refreshDaily">
          <div class="filter-bar">
            <div class="filter-item">
              <label>开始日期</label>
              <n-input v-model:value="dailyFrom" placeholder="YYYY-MM-DD" clearable size="small" />
            </div>
            <div class="filter-item">
              <label>结束日期</label>
              <n-input v-model:value="dailyTo" placeholder="YYYY-MM-DD" clearable size="small" />
            </div>
            <div class="filter-item">
              <label>标的代码 / 名称</label>
              <n-input v-model:value="dailyCode" placeholder="如 600519" clearable size="small" />
            </div>
            <n-button size="small" type="primary" @click="refreshDaily">查询</n-button>
          </div>

          <div class="stat-grid">
            <n-card v-for="s in dailyStats" :key="s.label" size="small">
              <n-statistic :label="s.label" :value="s.value" />
            </n-card>
          </div>

          <div v-if="!dailyDays.length" class="empty-hint">
            暂无每日成交数据，请先导入券商交割单。
          </div>
          <template v-else>
            <div class="section-title">按交易日汇总</div>
            <n-data-table
              :columns="dayColumns"
              :data="dailyDays"
              :bordered="false"
              :single-line="false"
              size="small"
              :scroll-x="900"
              max-height="320"
            />
            <div class="section-title">成交明细（{{ dailyItems.length }} 笔）</div>
            <n-data-table
              :columns="tradeColumns"
              :data="dailyItems"
              :bordered="false"
              :single-line="false"
              size="small"
              :scroll-x="1400"
              max-height="420"
            />
          </template>
        </LoadingState>
      </n-tab-pane>

      <!-- 交割单 -->
      <n-tab-pane name="settlement" tab="交割单">
        <LoadingState :loading="settleLoading" :error="settleError" @retry="refreshSettle">
          <div class="filter-bar">
            <div class="filter-item">
              <label>开始日期</label>
              <n-input v-model:value="settleFrom" placeholder="YYYY-MM-DD" clearable size="small" />
            </div>
            <div class="filter-item">
              <label>结束日期</label>
              <n-input v-model:value="settleTo" placeholder="YYYY-MM-DD" clearable size="small" />
            </div>
            <div class="filter-item">
              <label>标的代码</label>
              <n-input v-model:value="settleCode" placeholder="如 600519" clearable size="small" />
            </div>
            <div class="filter-item">
              <label>方向</label>
              <n-select v-model:value="settleDirection" :options="directionOptions" size="small" />
            </div>
            <n-button size="small" type="primary" @click="refreshSettle">查询</n-button>
            <n-button size="small" @click="exportSettlements">导出 CSV</n-button>
          </div>

          <div v-if="!settleData || !settleData.items.length" class="empty-hint">
            暂无交割单数据，请先导入券商交割单。
          </div>
          <n-data-table
            v-else
            :columns="settleColumns"
            :data="filteredSettleRows"
            :row-key="(row: SettlementRow) => row.id"
            :pagination="settlePagination"
            :bordered="false"
            :single-line="false"
            size="small"
            :scroll-x="1900"
            max-height="520"
          />
          <div class="table-foot">
            共 {{ settleTotal }} 条，当前筛选 {{ filteredSettleRows.length }} 条；每页 20 条。
          </div>
        </LoadingState>
      </n-tab-pane>

      <!-- 已清仓 -->
      <n-tab-pane name="closed" tab="已清仓">
        <LoadingState :loading="closedLoading" :error="closedError" @retry="refreshClosed">
          <div class="stat-grid">
            <n-card v-for="s in closedStats" :key="s.label" size="small">
              <n-statistic :label="s.label" :value="s.value" />
            </n-card>
          </div>

          <div v-if="!closedItems.length" class="empty-hint">
            暂无已清仓回合，请先导入券商交割单。
          </div>
          <template v-else>
            <div class="section-title">FIFO 已平仓回合（{{ closedItems.length }} 个）</div>
            <n-data-table
              :columns="closedColumns"
              :data="closedItems"
              :bordered="false"
              :single-line="false"
              size="small"
              :scroll-x="1200"
              max-height="420"
            />
          </template>

          <div class="section-title">
            由流水重建的当前持仓（{{ openPositions.length }} 个）
            <span class="sub-note">可与「当前持仓」对账</span>
          </div>
          <n-data-table
            :columns="positionColumns"
            :data="openPositions"
            :bordered="false"
            :single-line="false"
            size="small"
            :scroll-x="800"
            max-height="320"
          />
        </LoadingState>
      </n-tab-pane>

      <!-- 导入交割单 -->
      <n-tab-pane name="import" tab="导入交割单">
        <div class="section-title">上传券商交割单（.xlsx / .csv / .txt）</div>
        <div class="filter-bar">
          <div class="filter-item">
            <label>选择文件</label>
            <input type="file" accept=".xlsx,.csv,.txt" class="file-input" @change="onFileChange" />
          </div>
          <div class="filter-item">
            <label>券商（可选）</label>
            <n-input v-model:value="importBroker" placeholder="如 华泰证券" clearable size="small" />
          </div>
          <div class="filter-item">
            <label>账户（可选）</label>
            <n-input v-model:value="importAccount" placeholder="资金账号" clearable size="small" />
          </div>
          <div class="filter-item">
            <label>导入模式</label>
            <n-radio-group v-model:value="importMode" size="small">
              <n-radio-button value="merge">合并（merge）</n-radio-button>
              <n-radio-button value="replace">替换（replace）</n-radio-button>
            </n-radio-group>
          </div>
          <n-button size="small" type="primary" :loading="importing" @click="doImport">导入</n-button>
        </div>

        <div class="hint-box">
          支持的表头别名：成交日期 / 证券代码 / 证券名称 / 买卖标志 / 成交价格 / 成交数量 / 成交金额 /
          佣金 / 印花税 / 过户费 / 其他费用 / 成交编号 / 成交时间 / 发生金额。
          缺失的费用字段按 0 处理；同一「成交编号」重复导入会被跳过。
        </div>

        <div v-if="importResult" class="result-box">
          <div class="stat-grid">
            <n-card size="small"><n-statistic label="总行数" :value="String(importResult?.total ?? 0)" /></n-card>
            <n-card size="small"><n-statistic label="新增" :value="String(importResult?.inserted ?? 0)" /></n-card>
            <n-card size="small"><n-statistic label="重复跳过" :value="String(importResult?.duplicates ?? 0)" /></n-card>
            <n-card size="small"><n-statistic label="失败" :value="String(importFailed.length)" /></n-card>
          </div>
          <div class="meta-line">
            日期范围：{{ importResult?.date_from || '—' }} ~ {{ importResult?.date_to || '—' }}；
            识别券商：{{ importBrokersText }}
          </div>
          <div v-if="importFailed.length" class="section-title">失败明细</div>
          <n-data-table
            v-if="importFailed.length"
            :columns="failedColumns"
            :data="importFailed"
            :bordered="false"
            :single-line="false"
            size="small"
            max-height="240"
          />
        </div>

        <div class="section-title">按日期清空重导</div>
        <div class="filter-bar">
          <div class="filter-item">
            <label>成交日期（YYYY-MM-DD）</label>
            <n-input v-model:value="clearDate" placeholder="如 2026-11-05" clearable size="small" />
          </div>
          <n-button size="small" type="error" ghost :loading="clearing" @click="clearByDate">清空该日交割单</n-button>
        </div>

        <div class="section-title">可选：粘贴 JSON 导入每日成交</div>
        <div class="filter-bar">
          <div class="filter-item">
            <label>交易日期</label>
            <n-input v-model:value="dailyTradeDate" placeholder="YYYY-MM-DD" clearable size="small" />
          </div>
        </div>
        <n-input
          v-model:value="dailyJsonText"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 8 }"
          placeholder='粘贴成交明细 JSON 数组，如 [{"code":"600519","name":"贵州茅台","direction":"buy","price":1500,"quantity":100}]'
        />
        <div style="margin-top: 8px;">
          <n-button size="small" :loading="dailyImporting" @click="importDailyJson">导入每日成交</n-button>
        </div>
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<style scoped>
.ledger-panel { display: flex; flex-direction: column; gap: 8px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; }
.panel-title { font-size: 14px; font-weight: 600; color: var(--text-secondary); }
.filter-bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; margin-bottom: 14px; }
.filter-item { display: flex; flex-direction: column; gap: 4px; min-width: 160px; }
.filter-item label { font-size: 12px; color: var(--text-muted); }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 14px; }
.section-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); margin: 14px 0 8px; }
.sub-note { font-size: 12px; font-weight: 400; color: var(--text-muted); margin-left: 8px; }
.empty-hint { padding: 28px; text-align: center; color: var(--text-muted); font-size: 13px; }
.hint-box { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 8px; padding: 12px 14px; font-size: 12px; color: var(--text-secondary); line-height: 1.8; }
.result-box { margin-top: 14px; }
.meta-line { font-size: 12px; color: var(--text-muted); margin: 6px 0 10px; }
.table-foot { font-size: 12px; color: var(--text-muted); margin-top: 8px; }
.file-input { font-size: 12px; color: var(--text-secondary); }
.mono { font-variant-numeric: tabular-nums; }
</style>
