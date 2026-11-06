<script setup lang="ts">
defineOptions({ name: 'TradeReviewPanel' })
import { ref, computed, h, watch, onMounted } from 'vue'
import {
  NButton, NInput, NDataTable, NStatistic, NCard, NAlert, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useAsyncData } from '../composables/useApi'
import { api } from '../utils/api'
import LoadingState from '../components/LoadingState.vue'
import type { TradingAnalysis, TTrade, GroupStat, HoldingDiff } from '../types'

const message = useMessage()

// ---------- 格式化 ----------
function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `¥${fmtNum(v)}`
}
// A股惯例：盈利红（--color-danger）、亏损绿（--color-success），切勿搞反
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
const PATTERN_LABELS: Record<string, string> = {
  sell_then_buy: '先卖后买',
  buy_then_sell: '先买后卖',
  mixed: '混合',
}

// ---------- 数据 ----------
const from = ref('')
const to = ref('')
const { data: analysis, loading, error, refresh } =
  useAsyncData<TradingAnalysis>(() => api.getTradingAnalysis({ from: from.value, to: to.value }))
watch(error, (v) => { if (v) message.error(`交易分析加载失败：${v}`) })
onMounted(() => { refresh() })

const hasData = computed(() =>
  !!analysis.value &&
  (analysis.value.meta.settlement_rows > 0 || analysis.value.meta.daily_rows > 0),
)
const metaText = computed(() => {
  const m = analysis.value?.meta
  if (!m) return ''
  return `数据范围：${m.date_from || '—'} ~ ${m.date_to || '—'} ｜ 交割单 ${m.settlement_rows} 行 / 每日成交 ${m.daily_rows} 行 / 合并 ${m.merged_rows} 行 / 估算费用 ${m.fee_estimated_rows} 行`
})

// ---------- 概览 ----------
const overview = computed(() => {
  const a = analysis.value
  if (!a) return []
  return [
    { label: '做T次数', value: String(a.t_trades.summary.count) },
    { label: '做T胜率', value: a.t_trades.summary.win_rate === null ? '—' : `${fmtNum(a.t_trades.summary.win_rate)}%` },
    { label: '做T累计净收益', value: fmtMoney(a.t_trades.summary.total_net) },
    { label: '已平仓回合胜率', value: a.rounds.summary.win_rate === null ? '—' : `${fmtNum(a.rounds.summary.win_rate)}%` },
    { label: '累计已实现盈亏', value: fmtMoney(a.rounds.summary.total_pnl) },
    { label: '总费用', value: fmtMoney(a.fees.total_fee) },
  ]
})

// ---------- 做T统计 ----------
const tStats = computed(() => {
  const s = analysis.value?.t_trades.summary
  if (!s) return []
  return [
    { label: '做T次数', value: String(s.count) },
    { label: '盈利次数', value: String(s.win_count) },
    { label: '胜率', value: s.win_rate === null ? '—' : `${fmtNum(s.win_rate)}%` },
    { label: '累计毛利', value: fmtMoney(s.total_gross) },
    { label: '累计费用', value: fmtMoney(s.total_fee) },
    { label: '累计净收益', value: fmtMoney(s.total_net) },
    { label: '平均净收益', value: fmtMoney(s.avg_net) },
    { label: '最佳单笔', value: fmtMoney(s.best_net) },
    { label: '最差单笔', value: fmtMoney(s.worst_net) },
    { label: '闭环数', value: String(s.closed_count) },
    { label: '先卖后买', value: String(s.sell_then_buy_count) },
    { label: '先买后卖', value: String(s.buy_then_sell_count) },
  ]
})
const tTradeColumns: DataTableColumns<TTrade> = [
  { title: '日期', key: 'trade_date', width: 120, render: (row) => textCell(row.trade_date) },
  { title: '标的', key: 'code', width: 170, render: (row) => h('span', {}, `${row.code}${row.name ? ' ' + row.name : ''}`) },
  { title: '做T量', key: 't_quantity', width: 100, align: 'right', render: (row) => numCell(row.t_quantity, 0) },
  { title: '买均价', key: 'buy_avg', width: 110, align: 'right', render: (row) => numCell(row.buy_avg, 3) },
  { title: '卖均价', key: 'sell_avg', width: 110, align: 'right', render: (row) => numCell(row.sell_avg, 3) },
  { title: '毛利', key: 'gross_pnl', width: 130, align: 'right', render: (row) => pnlCell(row.gross_pnl) },
  { title: '费用', key: 'fee_alloc', width: 120, align: 'right', render: (row) => moneyCell(row.fee_alloc) },
  { title: '净收益', key: 'net_pnl', width: 130, align: 'right', render: (row) => pnlCell(row.net_pnl) },
  { title: '闭环', key: 'closed', width: 80, render: (row) => h('span', {}, row.closed ? '是' : '否') },
  { title: '模式', key: 'pattern', width: 120, render: (row) => h('span', {}, PATTERN_LABELS[row.pattern] || row.pattern || '—') },
  { title: '成交笔数', key: 'trade_count', width: 110, align: 'right', render: (row) => numCell(row.trade_count, 0) },
]

// ---------- 费用摩擦 ----------
const feeStats = computed(() => {
  const f = analysis.value?.fees
  if (!f) return []
  return [
    { label: '总费用', value: fmtMoney(f.total_fee) },
    { label: '佣金', value: fmtMoney(f.commission) },
    { label: '印花税', value: fmtMoney(f.stamp_tax) },
    { label: '过户费', value: fmtMoney(f.transfer_fee) },
    { label: '其他费用', value: fmtMoney(f.other_fee) },
    { label: '未拆分费用', value: fmtMoney(f.unallocated_fee) },
    { label: '费用占毛利比', value: f.fee_to_gross_pct === null ? '—' : `${fmtNum(f.fee_to_gross_pct)}%` },
    { label: '小单笔数', value: String(f.small_order_count) },
    { label: '估算费用行数', value: String(f.estimated_fee_rows) },
  ]
})

// ---------- 已平仓回合 ----------
const roundStats = computed(() => {
  const s = analysis.value?.rounds.summary
  if (!s) return []
  return [
    { label: '回合数', value: String(s.count) },
    { label: '盈利回合', value: String(s.win_count) },
    { label: '胜率', value: s.win_rate === null ? '—' : `${fmtNum(s.win_rate)}%` },
    { label: '累计盈亏', value: fmtMoney(s.total_pnl) },
    { label: '平均盈利', value: fmtMoney(s.avg_win) },
    { label: '平均亏损', value: fmtMoney(s.avg_loss) },
    { label: '盈亏比', value: s.profit_factor === null || s.profit_factor === 0 ? '—' : fmtNum(s.profit_factor) },
    { label: '期望值', value: fmtMoney(s.expectancy) },
    { label: '最佳回合', value: fmtMoney(s.best_pnl) },
    { label: '最差回合', value: fmtMoney(s.worst_pnl) },
    { label: '平均持有天数', value: fmtNum(s.avg_holding_days) },
  ]
})
const groupColumns: DataTableColumns<GroupStat> = [
  { title: '分组', key: 'label', minWidth: 150, render: (row) => textCell(row.label || row.key) },
  { title: '次数', key: 'count', width: 100, align: 'right', render: (row) => numCell(row.count, 0) },
  { title: '净盈亏', key: 'net_pnl', width: 140, align: 'right', render: (row) => pnlCell(row.net_pnl) },
  { title: '盈利次数', key: 'win_count', width: 110, align: 'right', render: (row) => numCell(row.win_count, 0) },
  { title: '胜率', key: 'win_rate', width: 110, align: 'right', render: (row) => pctCell(row.win_rate) },
  { title: '费用', key: 'fee', width: 120, align: 'right', render: (row) => moneyCell(row.fee) },
]

// ---------- 行为与对账 ----------
const behaviorStats = computed(() => {
  const b = analysis.value?.behavior
  if (!b) return []
  return [
    { label: '盈利单平均持有天数', value: fmtNum(b.avg_hold_days_win) },
    { label: '亏损单平均持有天数', value: fmtNum(b.avg_hold_days_loss) },
    { label: '处置效应差值', value: fmtNum(b.disposition_gap) },
    { label: '交易天数', value: String(b.trade_days) },
    { label: '日均交易笔数', value: fmtNum(b.avg_trades_per_day) },
    { label: '最常交易标的', value: b.most_traded_code || '—' },
  ]
})
const reconStats = computed(() => {
  const r = analysis.value?.reconciliation
  if (!r) return []
  return [
    { label: '交割单行', value: String(r.settlement_rows) },
    { label: '每日成交行', value: String(r.daily_rows) },
    { label: '未匹配每日成交', value: String(r.unmatched_daily) },
    { label: '重复成交编号', value: String(r.duplicate_ids) },
  ]
})
const warnings = computed<string[]>(() => analysis.value?.reconciliation.warnings ?? [])
const diffColumns: DataTableColumns<HoldingDiff> = [
  { title: '代码', key: 'code', width: 120, render: (row) => textCell(row.code) },
  { title: '账户', key: 'account', width: 170, render: (row) => textCell(row.account) },
  { title: '台账数量', key: 'ledger_qty', width: 130, align: 'right', render: (row) => numCell(row.ledger_qty, 0) },
  { title: '导入持仓数量', key: 'imported_qty', width: 150, align: 'right', render: (row) => numCell(row.imported_qty, 0) },
  { title: '差异', key: 'diff', width: 120, align: 'right', render: (row) => h('span', { class: 'mono', style: row.diff !== 0 ? 'color:var(--color-danger)' : undefined }, fmtNum(row.diff, 0)) },
]
</script>

<template>
  <div class="review-panel">
    <div class="filter-bar">
      <div class="filter-item">
        <label>开始日期</label>
        <n-input v-model:value="from" placeholder="YYYY-MM-DD" clearable size="small" />
      </div>
      <div class="filter-item">
        <label>结束日期</label>
        <n-input v-model:value="to" placeholder="YYYY-MM-DD" clearable size="small" />
      </div>
      <div class="filter-item">
        <n-button size="small" type="primary" @click="refresh">查询 / 刷新</n-button>
      </div>
    </div>

    <LoadingState :loading="loading" :error="error" @retry="refresh">
      <div v-if="!hasData" class="empty-hint">暂无交易分析数据，请先导入券商交割单。</div>
      <template v-else>
        <div class="meta-line">{{ metaText }}</div>

        <div class="section-title">概览</div>
        <div class="stat-grid">
          <n-card v-for="s in overview" :key="s.label" size="small">
            <n-statistic :label="s.label" :value="s.value" />
          </n-card>
        </div>

        <div class="section-title">做T统计</div>
        <div class="stat-grid">
          <n-card v-for="s in tStats" :key="s.label" size="small">
            <n-statistic :label="s.label" :value="s.value" />
          </n-card>
        </div>
        <n-alert
          v-if="(analysis?.t_trades.summary.fee_eroded_count ?? 0) > 0"
          type="warning"
          :bordered="false"
          class="tip-alert"
        >
          有 {{ analysis?.t_trades.summary.fee_eroded_count }} 笔做T「毛利为正但净利为负」——费用侵蚀了利润，需关注小单与佣金。
        </n-alert>
        <n-data-table
          :columns="tTradeColumns"
          :data="analysis?.t_trades.items ?? []"
          :bordered="false"
          :single-line="false"
          size="small"
          :scroll-x="1400"
          max-height="440"
        />

        <div class="section-title">费用摩擦</div>
        <div class="stat-grid">
          <n-card v-for="s in feeStats" :key="s.label" size="small">
            <n-statistic :label="s.label" :value="s.value" />
          </n-card>
        </div>
        <n-alert
          v-if="(analysis?.fees.small_order_count ?? 0) > 0"
          type="warning"
          :bordered="false"
          class="tip-alert"
        >
          有 {{ analysis?.fees.small_order_count }} 笔小单成交额偏低，可能被「最低佣金」放大费用摩擦；估算费用行数 {{ analysis?.fees.estimated_fee_rows }} 行。
        </n-alert>

        <div class="section-title">已平仓回合</div>
        <div class="stat-grid">
          <n-card v-for="s in roundStats" :key="s.label" size="small">
            <n-statistic :label="s.label" :value="s.value" />
          </n-card>
        </div>
        <div class="sub-title">按标的</div>
        <n-data-table :columns="groupColumns" :data="analysis?.rounds.by_code ?? []" :bordered="false" :single-line="false" size="small" :scroll-x="700" max-height="260" />
        <div class="sub-title">按月份</div>
        <n-data-table :columns="groupColumns" :data="analysis?.rounds.by_month ?? []" :bordered="false" :single-line="false" size="small" :scroll-x="700" max-height="260" />
        <div class="sub-title">按账户</div>
        <n-data-table :columns="groupColumns" :data="analysis?.rounds.by_account ?? []" :bordered="false" :single-line="false" size="small" :scroll-x="700" max-height="260" />

        <div class="section-title">行为与对账</div>
        <div class="stat-grid">
          <n-card v-for="s in behaviorStats" :key="s.label" size="small">
            <n-statistic :label="s.label" :value="s.value" />
          </n-card>
        </div>
        <div class="stat-grid">
          <n-card v-for="s in reconStats" :key="s.label" size="small">
            <n-statistic :label="s.label" :value="s.value" />
          </n-card>
        </div>
        <div class="sub-title">对账告警</div>
        <template v-if="warnings.length > 0">
          <n-alert
            v-for="(w, i) in warnings"
            :key="i"
            type="warning"
            :bordered="false"
            class="tip-alert"
          >{{ w }}</n-alert>
        </template>
        <div v-else class="meta-line">无对账告警。</div>
        <div class="sub-title">持仓差异（台账 vs 导入持仓）</div>
        <n-data-table
          :columns="diffColumns"
          :data="analysis?.reconciliation.holding_diff ?? []"
          :bordered="false"
          :single-line="false"
          size="small"
          :scroll-x="700"
          max-height="260"
        />
      </template>
    </LoadingState>
  </div>
</template>

<style scoped>
.review-panel { display: flex; flex-direction: column; gap: 8px; }
.filter-bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; margin-bottom: 6px; }
.filter-item { display: flex; flex-direction: column; gap: 4px; min-width: 160px; }
.filter-item label { font-size: 12px; color: var(--text-muted); }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 12px; }
.section-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); margin: 18px 0 8px; }
.sub-title { font-size: 12px; color: var(--text-muted); margin: 12px 0 6px; }
.meta-line { font-size: 12px; color: var(--text-muted); margin: 4px 0 12px; }
.empty-hint { padding: 28px; text-align: center; color: var(--text-muted); font-size: 13px; }
.tip-alert { margin-bottom: 12px; }
.mono { font-variant-numeric: tabular-nums; }
</style>
