<script setup lang="ts">
defineOptions({ name: 'DividendFundHub' })
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { NTag, NTooltip } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import {
  CashOutline,
  CloudDownloadOutline,
  GiftOutline,
  RefreshOutline,
  TrendingUpOutline,
  WarningOutline,
} from '@vicons/ionicons5'
import { api } from '../utils/api'
import { pctColor } from '../utils/percentile'
import type {
  CashflowOverview,
  DividendFeeProgress,
  DividendFund,
  DividendFundHoldings,
  DividendIndexFunds,
  DividendIndexMapProgress,
  DividendIndexMetric,
  DividendOverview,
  DividendSignal,
} from '../types'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import TabBar from '../components/TabBar.vue'
import LoadingState from '../components/LoadingState.vue'
import SectionSkeleton from '../components/SectionSkeleton.vue'
import SectionFallback from '../components/SectionFallback.vue'
import BaseChart from '../components/BaseChart.vue'

const loading = ref(false)
const error = ref<string | null>(null)
const refreshing = ref(false)
const overview = ref<DividendOverview | null>(null)
const overviewMeta = ref<{ updateTime?: string | null } | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    const res = await api.getDividendOverview()
    overview.value = (res.data as DividendOverview) ?? null
    overviewMeta.value = res.meta ?? null
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

// ---------------- 现金流名录（独立一条线，2026-10-07 用户拍板「单开 Tab」）----------------
//
// ⚠️ 刻意与红利名录**分开取数**：红线是「红利名录闸门一个字都不动」。
// 红利闸门只认「红利/高股息/股息」，会把 159399「现金流ETF国泰」挡掉；
// 现金流是另一条因子线（自由现金流 vs 股息率），所以这里另挂一条 Tab + 另一套接口。

const cashflowLoading = ref(false)
const cashflowError = ref<string | null>(null)
const cashflow = ref<CashflowOverview | null>(null)

async function loadCashflow(force = false) {
  cashflowLoading.value = true
  cashflowError.value = null
  try {
    const res = await api.getCashflowFunds(force)
    cashflow.value = (res.data as CashflowOverview) ?? null
  } catch (e: any) {
    cashflowError.value = e?.message || '现金流名录加载失败'
  } finally {
    cashflowLoading.value = false
  }
}

async function refresh() {
  refreshing.value = true
  try {
    await api.refreshDividend()
    await load()
  } catch (e: any) {
    error.value = e?.message || '刷新失败'
  } finally {
    refreshing.value = false
  }
}

// ---------------- 费率/规模后台补全 ----------------

const feeProgress = computed<DividendFeeProgress | null>(() => overview.value?.fee_progress ?? null)
const filling = ref(false)
let pollTimer: number | null = null

function stopPoll() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPoll() {
  if (pollTimer) return
  pollTimer = window.setInterval(async () => {
    try {
      const res = await api.getDividendFeeProgress()
      const d = res.data as DividendFeeProgress
      if (overview.value) overview.value.fee_progress = d
      if (!d.running) {
        stopPoll()
        filling.value = false
        await load()
      }
    } catch {
      stopPoll()
      filling.value = false
    }
  }, 5000)
}

async function fillFees() {
  filling.value = true
  try {
    const res = await api.fillDividendFees(80)
    if (overview.value) overview.value.fee_progress = res.data as DividendFeeProgress
    startPoll()
  } catch (e: any) {
    filling.value = false
    error.value = e?.message || '触发补全失败'
  }
}

// ---------------- 三类补充指标后台补全（跟踪误差 / 分红频率 / 行业集中度）----------------

// C 折中展示：红利与现金流两条线共用同一套后台补全频道（start_fill 覆盖全部 394 只），
// 取数优先级 overview -> cashflow，两侧在轮询时都会同步写入，保证一致。
const extraProgress = computed<DividendFeeProgress | null>(
  () => overview.value?.extra_progress ?? cashflow.value?.extra_progress ?? null,
)
const fillingExtra = ref(false)
let extraPollTimer: number | null = null

function stopExtraPoll() {
  if (extraPollTimer) {
    window.clearInterval(extraPollTimer)
    extraPollTimer = null
  }
}

function startExtraPoll() {
  if (extraPollTimer) return
  extraPollTimer = window.setInterval(async () => {
    try {
      const res = await api.getExtraMetricsProgress()
      const d = res.data as DividendFeeProgress
      if (overview.value) overview.value.extra_progress = d
      if (cashflow.value) cashflow.value.extra_progress = d
      if (!d.running) {
        stopExtraPoll()
        fillingExtra.value = false
        await load()
        await loadCashflow()
      }
    } catch {
      stopExtraPoll()
      fillingExtra.value = false
    }
  }, 5000)
}

async function fillExtra() {
  fillingExtra.value = true
  try {
    const res = await api.fillExtraMetrics(80)
    const d = res.data as DividendFeeProgress
    if (overview.value) overview.value.extra_progress = d
    if (cashflow.value) cashflow.value.extra_progress = d
    startExtraPoll()
  } catch (e: any) {
    fillingExtra.value = false
    error.value = e?.message || '触发补全失败'
  }
}

// ---------------- 通用渲染 ----------------

function fmt(v: number | null | undefined, digits = 2, suffix = '') {
  if (v == null) return '—'
  return `${v.toFixed(digits)}${suffix}`
}

// 注：pctColor 已统一从 ../utils/percentile 导入（低蓝→高红，全局分位配色标准）
function percentileBar(pct: number | null) {
  if (pct == null) return null
  return h('div', { class: 'div-bar' }, [
    h('div', { class: 'div-bar-fill', style: { width: `${pct}%`, background: pctColor(pct) } }),
  ])
}

function signalCell(sig: DividendSignal | null | undefined) {
  if (!sig) return h('span', { class: 'dim-cell' }, '—')
  // 「低估·持有」(hold_low) 用紫色，与下方信号图例一致；其余信号沿用后端返回的色
  const color = sig.label === '低估·持有' ? '#8b5cf6' : sig.color
  return h(
    NTooltip,
    { trigger: 'hover', placement: 'top' },
    {
      trigger: () =>
        h(
          NTag,
          {
            size: 'small',
            bordered: false,
            color: { color: `${color}1f`, textColor: color, borderColor: `${color}59` },
          },
          { default: () => sig.label },
        ),
      default: () => sig.reason,
    },
  )
}

// ---------------- 三类补充指标渲染 ----------------

function payoutFreqLabel(v: number | null): string {
  if (v == null) return '—'
  const map: Record<number, string> = { 0: '不定期', 1: '年度', 2: '半年', 4: '季度', 12: '月度' }
  return map[v] ?? `每${v}次/年`
}

function trackingErrorCell(r: DividendFund) {
  if (r.tracking_error == null) return h('span', { class: 'dim-cell' }, '待补全')
  const tip =
    r.tracking_error_n != null
      ? `基于 ${r.tracking_error_n} 个重叠交易日年化（基金日净值增长率 vs 跟踪指数日收益）`
      : '年化跟踪误差（基金日净值增长率 vs 跟踪指数日收益）'
  return h(
    NTooltip,
    { trigger: 'hover', placement: 'top' },
    {
      trigger: () => h('span', null, `${r.tracking_error!.toFixed(2)}%`),
      default: () => tip,
    },
  )
}

function sectorCell(r: DividendFund) {
  if (r.sector_concentration == null) return h('span', { class: 'dim-cell' }, '待补全')
  const tip =
    r.sector_count != null
      ? `前 3 申万一级行业占净值 ${r.sector_concentration}% · 共 ${r.sector_count} 个行业`
      : `前 3 申万一级行业占净值 ${r.sector_concentration}%`
  return h(
    NTooltip,
    { trigger: 'hover', placement: 'top' },
    {
      trigger: () => h('span', null, `${r.sector_concentration!.toFixed(1)}%`),
      default: () => tip,
    },
  )
}

// ---------------- 研究区：指数估值与三信号 ----------------

const indices = computed<DividendIndexMetric[]>(() => overview.value?.indices ?? [])
const counts = computed(() => overview.value?.counts ?? { etf: 0, passive: 0, active: 0, index: 0, excluded: 0, excluded_detail: { non_passive: 0, bond: 0, money: 0, no_name_hit: 0 } })
const thresholds = computed(() => overview.value?.thresholds ?? null)
const yield10y = computed(() => overview.value?.yield_10y ?? null)
const fundTotal = computed(() => counts.value.etf + counts.value.passive + counts.value.active)

const selectedCode = ref<string>('000922')
const selected = computed<DividendIndexMetric | null>(
  () => indices.value.find((i) => i.code === selectedCode.value) ?? indices.value[0] ?? null,
)

const indexColumns = computed<DataTableColumns<DividendIndexMetric>>(() => [
  {
    title: '指数',
    key: 'name',
    width: 130,
    fixed: 'left',
    render: (r) =>
      h('div', null, [
        h('div', { class: 'cell-strong' }, r.name),
        h('div', { class: 'dim-cell' }, r.code),
      ]),
  },
  {
    title: 'PE',
    key: 'pe',
    width: 72,
    align: 'right',
    sorter: (a, b) => (a.pe ?? 0) - (b.pe ?? 0),
    render: (r) =>
      r.pe_stale
        ? h(
            NTooltip,
            { trigger: 'hover', placement: 'top' },
            {
              trigger: () => h('span', { style: { opacity: 0.75 } }, `${fmt(r.pe)} *`),
              default: () => `中证估值接口临时不可用，沿用本地最后一期（${r.pe_date ?? '—'}）`,
            },
          )
        : h('span', null, fmt(r.pe)),
  },
  {
    title: 'PE分位',
    key: 'pe_percentile',
    width: 110,
    sorter: (a, b) => (a.pe_percentile ?? 0) - (b.pe_percentile ?? 0),
    render: (r) =>
      h('div', null, [
        h(
          NTooltip,
          { trigger: 'hover', placement: 'top' },
          {
            trigger: () =>
              h(
                'span',
                { style: { color: pctColor(r.pe_percentile), opacity: r.pe_stale ? 0.75 : 1 } },
                `${fmt(r.pe_percentile, 1, '%')}${r.pe_stale ? ' *' : ''}`,
              ),
            default: () =>
              r.pe_stale
                ? `中证估值接口临时不可用，分位基于本地序列（截至 ${r.pe_date ?? '—'}，共 ${r.window_days ?? 0} 个交易日）`
                : `基于 ${r.window_days ?? 0} 个交易日的 PE 序列（${r.window_start ?? '—'} 起）`,
          },
        ),
        percentileBar(r.pe_percentile),
      ]),
  },
  { title: 'PE区间', key: 'pe_range', width: 118, render: (r) => `${fmt(r.pe_min, 1)} ~ ${fmt(r.pe_max, 1)}` },
  {
    title: '股息率',
    key: 'dividend_yield',
    width: 94,
    align: 'right',
    sorter: (a, b) => (a.dividend_yield ?? 0) - (b.dividend_yield ?? 0),
    render: (r) =>
      r.dy_stale
        ? h(
            NTooltip,
            { trigger: 'hover', placement: 'top' },
            {
              trigger: () => h('span', { style: { opacity: 0.75 } }, `${fmt(r.dividend_yield, 2, '%')} *`),
              default: () => `中证估值接口临时不可用，沿用最后一期（${r.dy_date ?? '—'}）`,
            },
          )
        : h('span', null, fmt(r.dividend_yield, 2, '%')),
  },
  { title: '股债收益比', key: 'eb_ratio', width: 96, align: 'right', sorter: (a, b) => (a.eb_ratio ?? 0) - (b.eb_ratio ?? 0), render: (r) => fmt(r.eb_ratio, 2, 'x') },
  { title: '信号·股债比', key: 'sig_eb', width: 108, render: (r) => signalCell(r.signals?.eb) },
  { title: '信号·PE分位', key: 'sig_pe', width: 108, render: (r) => signalCell(r.signals?.pe) },
  { title: '信号·股息率', key: 'sig_dy', width: 108, render: (r) => signalCell(r.signals?.dy) },
  {
    title: '分歧',
    key: 'conflict',
    width: 70,
    render: (r) =>
      r.conflict
        ? h(NTag, { size: 'small', type: 'warning', bordered: false }, { default: () => '⚠ 分歧' })
        : h('span', { class: 'dim-cell' }, '—'),
  },
  {
    title: '数据日',
    key: 'pe_date',
    width: 108,
    // ⚠️ **陈旧时标色+ 提示**（2026-10-09）：星号只在 stale 时出现，
    //   而数据全新鲜时一个星号都没有 —— 用户会以为「没提示=没问题」，
    //   反而看不出数据是哪天的。故此列**始终显示日期**，陈旧时额外标橙 + tooltip。
    render: (r) => {
      const d = r.pe_date ?? '—'
      if (!r.pe_date) return h('span', { class: 'dim-cell' }, '—')
      if (!r.pe_stale) return h('span', { class: 'dim-cell' }, d)
      return h(
        NTooltip,
        { trigger: 'hover', placement: 'top' },
        {
          trigger: () => h('span', { style: { color: 'var(--color-warning, #d97706)' } }, `${d} *`),
          default: () => `数据已陈旧：最新只到${d}，共 ${r.window_days ?? 0} 个交易日样本`,
        },
      )
    },
  },
])

const detailOpen = ref(false)
const detailCode = ref<string>('')
const detailLoading = ref(false)
const detailError = ref<string | null>(null)
const detail = ref<DividendIndexFunds | null>(null)

async function openIndexDetail(code: string) {
  detailCode.value = code
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = null
  detail.value = null
  try {
    const res = await api.getDividendIndexFunds(code)
    detail.value = (res.data as DividendIndexFunds) ?? null
  } catch (e: any) {
    detailError.value = e?.message || '加载失败'
  } finally {
    detailLoading.value = false
  }
}

// 「业绩比较基准 → 跟踪指数」识别进度
const mapProgress = ref<DividendIndexMapProgress | null>(null)
const mapping = ref(false)

async function loadMapProgress() {
  try {
    const res = await api.getDividendIndexMapProgress()
    mapProgress.value = (res.data as DividendIndexMapProgress) ?? null
  } catch {
    /* 进度拿不到不影响主页面 */
  }
}

async function fillIndexMap() {
  mapping.value = true
  try {
    await api.fillDividendIndexMap(40)
    await loadMapProgress()
    await load()
  } catch (e: any) {
    error.value = e?.message || '识别任务触发失败'
  } finally {
    mapping.value = false
  }
}

onMounted(async () => {
  await load()
  // 现金流名录独立加载：冷启动首个请求要拉全市场 2.8 万条（约 9s），不阻塞红利区
  await loadCashflow()
  await loadMapProgress()
  if (feeProgress.value?.running) startPoll()
  if (extraProgress.value?.running) startExtraPoll()
})

function indexRowProps(row: DividendIndexMetric) {
  // ⚠️ 双击才弹窗：单击只联动 PE 历史，不弹窗（避免误触）
  return {
    style: 'cursor: pointer',
    onDblclick: () => {
      selectedCode.value = row.code
      openIndexDetail(row.code)
    },
  }
}

// ---------------- 名录区：双击基金行看持仓 ----------------

type HoldingsRow = DividendFundHoldings['rows'][number]
const holdingsOpen = ref(false)
const holdingsCode = ref<string>('')
const holdingsLoading = ref(false)
const holdingsError = ref<string | null>(null)
const holdingsData = ref<DividendFundHoldings | null>(null)

// ⚠️ 必须与后端 services/fund_holdings_service.HOLDINGS_TTL_DAYS 保持一致，
// 用来判断「这份持仓数据是不是已经过期」。后端 stale 字段是权威口径，这里只是
// 为了让用户在看到数据之前就先知道它偏老，别把「过期」当成「抓错了」。
const HOLDINGS_TTL_DAYS = 60

const holdingsStaleDays = computed(() => {
  const raw = holdingsData.value?.fetched_at
  if (!raw) return null
  const t = new Date(raw.replace(' ', 'T'))
  if (Number.isNaN(t.getTime())) return null
  return Math.floor((Date.now() - t.getTime()) / 86400000)
})

const holdingsStale = computed(() => {
  if (!holdingsData.value) return false
  if (holdingsData.value.stale) return true
  const d = holdingsStaleDays.value
  return d !== null && d > HOLDINGS_TTL_DAYS
})

async function openFundHoldings(code: string) {
  holdingsCode.value = code
  holdingsOpen.value = true
  holdingsLoading.value = true
  holdingsError.value = null
  holdingsData.value = null
  try {
    const res = await api.getDividendFundHoldings(code)
    holdingsData.value = (res.data as DividendFundHoldings) ?? null
  } catch (e: any) {
    holdingsError.value = e?.message || '加载失败'
  } finally {
    holdingsLoading.value = false
  }
}

function fundRowProps(row: DividendFund) {
  // ⚠️ 双击才看持仓：单击留给表格自身的排序/滚动，避免误触
  return {
    style: 'cursor: pointer',
    onDblclick: () => openFundHoldings(row.code),
  }
}

const holdingsColumns: DataTableColumns<HoldingsRow> = [
  { title: '#', key: 'seq', width: 56, align: 'right', render: (r) => r.seq ?? '—' },
  { title: '股票代码', key: 'stock_code', width: 90 },
  { title: '股票名称', key: 'stock_name', width: 120 },
  {
    title: '占净值比例',
    key: 'pct',
    width: 110,
    align: 'right',
    sorter: (a, b) => (a.pct ?? -1) - (b.pct ?? -1),
    render: (r) => fmt(r.pct, 2, '%'),
  },
  {
    title: '持股数',
    key: 'shares',
    width: 104,
    align: 'right',
    render: (r) =>
      r.shares == null
        ? h('span', { class: 'dim-cell' }, '—')
        : h(
            NTooltip,
            { trigger: 'hover', placement: 'top' },
            { trigger: () => h('span', null, r.shares!.toFixed(0)), default: () => '单位：万份（东财口径）' },
          ),
  },
  {
    title: '持仓市值',
    key: 'mv',
    width: 116,
    align: 'right',
    render: (r) =>
      r.mv == null
        ? h('span', { class: 'dim-cell' }, '—')
        : h(
            NTooltip,
            { trigger: 'hover', placement: 'top' },
            { trigger: () => h('span', null, r.mv!.toFixed(0)), default: () => '单位：万元（东财口径）' },
          ),
  },
]

const peChartOption = computed(() => {
  const s = selected.value
  const series = s?.pe_series ?? []
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 56, right: 20, top: 28, bottom: 58 },
    xAxis: { type: 'category', data: series.map((p) => p.date), boundaryGap: false },
    yAxis: { type: 'value', scale: true, name: 'PE(TTM)' },
    dataZoom: [
      { type: 'inside' },
      { type: 'slider', height: 18, bottom: 16 },
    ],
    series: [
      {
        name: 'PE(TTM)',
        type: 'line',
        data: series.map((p) => p.pe),
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.08 },
        markLine: {
          symbol: 'none',
          label: { formatter: (p: any) => `${p.name} ${p.value}`, position: 'insideEndTop' },
          lineStyle: { type: 'dashed', opacity: 0.6 },
          data: [
            { yAxis: s?.pe ?? undefined, name: '当前' },
            { yAxis: s?.pe_p25 ?? undefined, name: '25分位' },
            { yAxis: s?.pe_median ?? undefined, name: '中位' },
            { yAxis: s?.pe_p75 ?? undefined, name: '75分位' },
          ].filter((d) => d.yAxis != null),
        },
      },
    ],
  }
})

const conflictCount = computed(() => indices.value.filter((i) => i.conflict).length)
const addCount = computed(
  () => indices.value.filter((i) => i.signals?.eb?.action === 'add' || i.signals?.pe?.action === 'add' || i.signals?.dy?.action === 'add').length,
)

// ---------------- 名录区：场内 / 场外 两个 Tab ----------------

const allFunds = computed<DividendFund[]>(() => {
  const f = overview.value?.funds
  if (!f) return []
  return [...(f.etf ?? []), ...(f.passive ?? []), ...(f.active ?? [])]
})

const mappedTotal = computed(() => allFunds.value.filter((x) => !!x.index_code).length)
const mappedRate = computed(() => (fundTotal.value ? (mappedTotal.value / fundTotal.value) * 100 : 0))
const onshoreFunds = computed<DividendFund[]>(() => allFunds.value.filter((x) => x.market === '场内'))
const offshoreFunds = computed<DividendFund[]>(() => allFunds.value.filter((x) => x.market !== '场内'))
const onshoreCount = computed(() => onshoreFunds.value.length)
const offshoreCount = computed(() => offshoreFunds.value.length)

const activeTab = ref<string>('onshore')
const fundTabs = computed(() => [
  { key: 'onshore', label: `场内 ${onshoreCount.value} 只`, icon: GiftOutline },
  { key: 'offshore', label: `场外 ${offshoreCount.value} 只`, icon: CashOutline },
  { key: 'cashflow', label: `现金流 ${cashflowTotal.value} 只`, icon: TrendingUpOutline },
])

// ---------------- 现金流 Tab（独立数据源，独立于红利 361 只）----------------
//
// ⚠️ 红线（2026-10-07 用户拍板「方案 2 · 单开一条现金流 Tab」）：
//   **红利名录的闸门逻辑一个字都没动**——红利 Tab 的场内/场外/筛选/补全全部原样。
//   这里只是多挂一条 Tab，走另一个接口（GET /dividend/cashflow-funds）。
// 159399「现金流ETF国泰」不会出现在红利名录（名字没「红利」二字），但会出现在这里。

const cashflowKeyword = ref<string>('')

// ⚠️ 只看场内 ETF（2026-10-07 用户拍板「只要场内」）：场外 78 只绝大多数是同一指数的
// A/C/E 份额（华夏 159201 与 159221 同跟国证自由现金流），摊进列表只会灌满重复项。
// 后端 `_build_cashflow_fund_list` 同样只吐 etf，这里不再合并 passive / active。
const cashflowFunds = computed<DividendFund[]>(() => cashflow.value?.funds?.etf ?? [])
const cashflowTotal = computed(() => cashflowFunds.value.length)
const filteredCashflowFunds = computed<DividendFund[]>(() => {
  const kw = cashflowKeyword.value.trim().toLowerCase()
  if (!kw) return cashflowFunds.value
  return cashflowFunds.value.filter(
    (x) =>
      x.code.toLowerCase().includes(kw) ||
      x.name.toLowerCase().includes(kw) ||
      (x.index_name ?? '').toLowerCase().includes(kw),
  )
})
const cashflowCounts = computed(
  () => cashflow.value?.counts ?? { etf: 0, index: 0, index_valued: 0, excluded: 0, excluded_detail: {} },
)
const cashflowPagination = { pageSize: 50 }

// 指数估值（2026-10-07 用户拍板「动吧」）：只有中证那 5 个现金流指数有官方 PE
const cashflowIndices = computed<DividendIndexMetric[]>(() => cashflow.value?.indices ?? [])
const cashflowNoData = computed(() => cashflow.value?.no_data_indices ?? [])
/** 指数名 → 「为什么没估值」，用来给表里那些 PE 为 — 的行做悬停解释 */
const cfNoDataByIndex = computed(() => {
  const m = new Map<string, string>()
  for (const x of cashflowNoData.value) m.set(x.name, x.reason)
  return m
})

const cashflowIndexColumns: DataTableColumns<DividendIndexMetric> = [
  { title: '代码', key: 'code', width: 80 },
  { title: '指数', key: 'name', width: 200 },
  {
    title: 'PE(TTM)',
    key: 'pe',
    width: 88,
    align: 'right',
    sorter: (a, b) => (a.pe ?? -1) - (b.pe ?? -1),
    render: (r) => fmt(r.pe, 2, ''),
  },
  {
    title: 'PE分位',
    key: 'pe_percentile',
    width: 88,
    align: 'right',
    sorter: (a, b) => (a.pe_percentile ?? -1) - (b.pe_percentile ?? -1),
    render: (r) =>
      h('span', { style: { color: pctColor(r.pe_percentile) } }, fmt(r.pe_percentile, 1, '%')),
  },
  { title: '信号·PE分位', key: 'sig_pe', width: 108, render: (r) => signalCell(r.signals?.pe) },
  {
    title: '25%/中位/75%',
    key: 'quantile',
    width: 130,
    align: 'right',
    render: (r) =>
      h('span', { class: 'dim-cell' }, `${fmt(r.pe_p25, 2, '')} / ${fmt(r.pe_median, 2, '')} / ${fmt(r.pe_p75, 2, '')}`),
  },
  {
    title: '窗口',
    key: 'window_days',
    width: 120,
    align: 'right',
    render: (r) => h('span', { class: 'dim-cell' }, r.window_days ? `${r.window_days} 天（${r.window_start ?? '—'} 起）` : '—'),
  },
]

/** 指数估值拿不到时：显示 — 并用悬停说明具体原因（国证 / 富时两源都不覆盖），不假填数 */
function cfNoDataReasonCell(r: DividendFund) {
  const reason = cfNoDataByIndex.value.get(r.index_name ?? '')
  if (!reason) return h('span', { class: 'dim-cell' }, '—')
  return h(
    NTooltip,
    { trigger: 'hover', placement: 'top' },
    { trigger: () => h('span', { class: 'dim-cell' }, '—'), default: () => reason },
  )
}

// 现金流 Tab 的列（2026-10-07）：跟踪指数已按天天基金 F10「跟踪标的」逐只实测回填；
// PE 取中证官方滚轮市盈率、只对窗口内的 5 个中证指数可得（国证 / 富时两源都不覆盖 →
// 悬停看具体原因，不假填数）；规模 / 费率与红利共用后台补全频道，补全到位后自动有值。
const cashflowColumns: DataTableColumns<DividendFund> = [
  { title: '代码', key: 'code', width: 84, fixed: 'left' },
  { title: '名称', key: 'name', width: 220, fixed: 'left' },
  {
    title: '市场',
    key: 'market',
    width: 70,
    render: (r) =>
      h(
        NTag,
        { size: 'small', bordered: false, type: r.market === '场内' ? 'error' : 'default' },
        { default: () => r.market },
      ),
  },
  {
    title: '份额',
    key: 'share_class',
    width: 72,
    render: (r: DividendFund) =>
      r.share_class
        ? h(
            NTooltip,
            { trigger: 'hover', placement: 'top' },
            {
              trigger: () => h('span', null, r.share_class!),
              default: () => '份额类别（A / C / E / 联接）：同一只基金的收费方式分支，不是基金规模',
            },
          )
        : h('span', { class: 'dim-cell' }, '—'),
  },
  {
    title: '跟踪指数',
    key: 'index_name',
    width: 150,
    render: (r: DividendFund) =>
      r.index_name ? h('span', null, r.index_name) : h('span', { class: 'dim-cell' }, '未识别'),
  },
  {
    title: '指数PE',
    key: 'pe',
    width: 84,
    align: 'right',
    sorter: (a, b) => (a.pe ?? -1) - (b.pe ?? -1),
    render: (r: DividendFund) =>
      r.pe == null
        ? cfNoDataReasonCell(r)
        : h(
            NTooltip,
            { trigger: 'hover', placement: 'top' },
            {
              trigger: () => h('span', null, r.pe!.toFixed(2)),
              default: () => `${r.index_name} · 中证官方滚动市盈率（${r.pe_date ?? '日期未知'}）`,
            },
          ),
  },
  {
    title: 'PE分位',
    key: 'pe_percentile',
    width: 88,
    align: 'right',
    sorter: (a, b) => (a.pe_percentile ?? -1) - (b.pe_percentile ?? -1),
    render: (r: DividendFund) =>
      h('span', { style: { color: pctColor(r.pe_percentile) } }, fmt(r.pe_percentile, 1, '%')),
  },
  {
    title: '信号·PE分位',
    key: 'sig_pe',
    width: 108,
    render: (r: DividendFund) => signalCell(r.signals?.pe),
  },
  {
    title: '基金类型',
    key: 'type',
    width: 120,
    render: (r) => h('span', { class: 'dim-cell' }, r.type),
  },
  {
    title: '规模(亿份)',
    key: 'scale',
    width: 100,
    align: 'right',
    sorter: (a, b) => (a.scale ?? -1) - (b.scale ?? -1),
    render: (r: DividendFund) =>
      r.scale == null
        ? h('span', { class: 'dim-cell' }, '待补全')
        : h(
            NTooltip,
            { trigger: 'hover', placement: 'top' },
            {
              trigger: () => h('span', null, r.scale!.toFixed(2)),
              default: () => `份额规模（${r.scale_date ?? '日期未知'}）· 基金经理 ${r.manager ?? '—'}`,
            },
          ),
  },
  {
    title: '管理费',
    key: 'mgmt_fee',
    width: 80,
    align: 'right',
    sorter: (a, b) => (a.mgmt_fee ?? -1) - (b.mgmt_fee ?? -1),
    render: (r: DividendFund) => fmt(r.mgmt_fee, 2, '%'),
  },
  {
    title: '托管费',
    key: 'custody_fee',
    width: 80,
    align: 'right',
    sorter: (a, b) => (a.custody_fee ?? -1) - (b.custody_fee ?? -1),
    render: (r: DividendFund) => fmt(r.custody_fee, 2, '%'),
  },
  {
    title: '最高申购费',
    key: 'subscribe_fee',
    width: 96,
    align: 'right',
    sorter: (a, b) => (a.subscribe_fee ?? -1) - (b.subscribe_fee ?? -1),
    render: (r: DividendFund) => fmt(r.subscribe_fee, 2, '%'),
  },
  {
    title: '跟踪误差',
    key: 'tracking_error',
    width: 88,
    align: 'right',
    sorter: (a, b) => (a.tracking_error ?? -1) - (b.tracking_error ?? -1),
    render: (r) => trackingErrorCell(r),
  },
  {
    title: '分红频率',
    key: 'payout_freq',
    width: 88,
    align: 'right',
    sorter: (a, b) => (a.payout_freq ?? -1) - (b.payout_freq ?? -1),
    render: (r: DividendFund) => h('span', { class: r.payout_freq == null ? 'dim-cell' : '' }, payoutFreqLabel(r.payout_freq)),
  },
  {
    title: '行业集中度',
    key: 'sector_concentration',
    width: 100,
    align: 'right',
    sorter: (a, b) => (a.sector_concentration ?? -1) - (b.sector_concentration ?? -1),
    render: (r) => sectorCell(r),
  },
]

// 类型维度（ETF / 被动 / 主动）：Tab 换成「场内/场外」后仍可独立按类型筛，不丢分档能力
const etfCodes = computed(() => new Set((overview.value?.funds?.etf ?? []).map((x) => x.code)))
const passiveCodes = computed(() => new Set((overview.value?.funds?.passive ?? []).map((x) => x.code)))
const activeCodes = computed(() => new Set((overview.value?.funds?.active ?? []).map((x) => x.code)))
const typeFilter = ref<string>('all')
// ⚠️ 名录口径（2026-10-06）：纯债 / 主动不进红利名录，active 桶恒为空 → 该筛选项只在其真有值时出现
const typeOptions = computed(() => {
  const opts = [
    { label: '全部类型', value: 'all' },
    { label: '场内ETF', value: 'etf' },
    { label: '被动红利', value: 'passive' },
  ]
  if (counts.value.active > 0) opts.push({ label: '主动红利', value: 'active' })
  return opts
})

// 被闸门剔除的只数（不含「名字不命中红利关键词」的全市场其余基金）
const excludedCount = computed(() => {
  const d = (counts.value.excluded_detail ?? {}) as Record<string, number>
  return (d.non_passive ?? 0) + (d.bond ?? 0) + (d.money ?? 0)
})

const keyword = ref<string>('')
const showPending = ref<boolean>(true)
const onlyMapped = ref<boolean>(false)
const onlyOnshore = ref<boolean>(false)
const pagination = { pageSize: 50 }

// 「仅看场内」是市场维度总开关：打开时忽略 Tab，直接看全量场内基金
// ⚠️ 切到「现金流」Tab 时红利列表恒为空（那块模板由下面的 cashflow card 接管）
const currentFunds = computed<DividendFund[]>(() => {
  if (activeTab.value === 'cashflow') return []
  if (onlyOnshore.value) return onshoreFunds.value
  return activeTab.value === 'onshore' ? onshoreFunds.value : offshoreFunds.value
})

const scopeLabel = computed(() => {
  if (activeTab.value === 'cashflow') return '现金流'
  if (onlyOnshore.value) return '全市场 · 仅看场内'
  return activeTab.value === 'onshore' ? '场内' : '场外'
})

const filteredFunds = computed<DividendFund[]>(() => {
  const kw = keyword.value.trim().toLowerCase()
  return currentFunds.value.filter((x) => {
    if (onlyMapped.value && !x.index_code) return false
    if (typeFilter.value === 'etf' && !etfCodes.value.has(x.code)) return false
    if (typeFilter.value === 'passive' && !passiveCodes.value.has(x.code)) return false
    if (typeFilter.value === 'active' && !activeCodes.value.has(x.code)) return false
    if (!kw) return true
    return (
      x.code.toLowerCase().includes(kw) ||
      x.name.toLowerCase().includes(kw) ||
      (x.index_name ?? '').toLowerCase().includes(kw)
    )
  })
})

const fundColumns = computed<DataTableColumns<DividendFund>>(() => {
  const cols: DataTableColumns<DividendFund> = [
    { title: '代码', key: 'code', width: 84, fixed: 'left' },
    { title: '名称', key: 'name', width: 220, fixed: 'left' },
    {
      title: '市场',
      key: 'market',
      width: 70,
      render: (r) =>
        h(
          NTag,
          { size: 'small', bordered: false, type: r.market === '场内' ? 'error' : 'default' },
          { default: () => r.market },
        ),
    },
    {
    title: '份额',
    key: 'share_class',
    width: 72,
    render: (r: DividendFund) =>
      r.share_class
        ? h(
            NTooltip,
            { trigger: 'hover', placement: 'top' },
            {
              trigger: () => h('span', null, r.share_class!),
              default: () => '份额类别（A / C / E / 联接）：同一只基金的收费方式分支，不是基金规模',
            },
          )
        : h('span', { class: 'dim-cell' }, '—'),
  },
    {
      title: '跟踪指数',
      key: 'index_name',
      width: 140,
      render: (r: DividendFund) => {
        if (r.index_name) return h('span', null, r.index_name)
        if (!r.tracking_text) return h('span', { class: 'dim-cell' }, '未识别')
        // 识别不上但已知它实际跟踪的指数：悬停说明「为什么留空」，别干瘪一个 —
        return h(
          NTooltip,
          { trigger: 'hover', placement: 'top' },
          {
            default: () =>
              h('span', { style: 'font-size:12px' }, `实际跟踪 ${r.tracking_text}（不在当前红利指数池内 · 池内共 ${counts.value.index} 个指数）`),
            trigger: () => h('span', { class: 'out-of-pool' }, '—'),
          },
        )
      },
    },
    {
      title: 'PE分位',
      key: 'pe_percentile',
      width: 96,
      align: 'right',
      sorter: (a, b) => (a.pe_percentile ?? -1) - (b.pe_percentile ?? -1),
      render: (r) =>
        h('span', { style: { color: pctColor(r.pe_percentile) } }, fmt(r.pe_percentile, 1, '%')),
    },
    {
      title: '股息率',
      key: 'dividend_yield',
      width: 84,
      align: 'right',
      sorter: (a, b) => (a.dividend_yield ?? -1) - (b.dividend_yield ?? -1),
      render: (r) => fmt(r.dividend_yield, 2, '%'),
    },
    {
      title: '股债比',
      key: 'eb_ratio',
      width: 78,
      align: 'right',
      sorter: (a, b) => (a.eb_ratio ?? -1) - (b.eb_ratio ?? -1),
      render: (r) => fmt(r.eb_ratio, 2, 'x'),
    },
    { title: '信号·股债比', key: 'sig_eb', width: 108, render: (r) => signalCell(r.signals?.eb) },
    { title: '信号·PE分位', key: 'sig_pe', width: 108, render: (r) => signalCell(r.signals?.pe) },
    { title: '信号·股息率', key: 'sig_dy', width: 108, render: (r) => signalCell(r.signals?.dy) },
    { title: '基金类型', key: 'type', width: 120, render: (r) => h('span', { class: 'dim-cell' }, r.type) },
  ]
  if (showPending.value) {
    cols.push(
      {
        title: '规模(亿份)',
        key: 'scale',
        width: 100,
        align: 'right',
        sorter: (a, b) => (a.scale ?? -1) - (b.scale ?? -1),
        render: (r) =>
          r.scale == null
            ? h('span', { class: 'dim-cell' }, '—')
            : h(
                NTooltip,
                { trigger: 'hover', placement: 'top' },
                {
                  trigger: () => h('span', null, r.scale!.toFixed(2)),
                  default: () => `份额规模（${r.scale_date ?? '日期未知'}）· 基金经理 ${r.manager ?? '—'}`,
                },
              ),
      },
      { title: '管理费', key: 'mgmt_fee', width: 80, align: 'right', sorter: (a, b) => (a.mgmt_fee ?? -1) - (b.mgmt_fee ?? -1), render: (r) => fmt(r.mgmt_fee, 2, '%') },
      { title: '托管费', key: 'custody_fee', width: 80, align: 'right', sorter: (a, b) => (a.custody_fee ?? -1) - (b.custody_fee ?? -1), render: (r) => fmt(r.custody_fee, 2, '%') },
      { title: '最高申购费', key: 'subscribe_fee', width: 96, align: 'right', sorter: (a, b) => (a.subscribe_fee ?? -1) - (b.subscribe_fee ?? -1), render: (r) => fmt(r.subscribe_fee, 2, '%') },
      { title: '跟踪误差', key: 'tracking_error', width: 88, align: 'right', sorter: (a, b) => (a.tracking_error ?? -1) - (b.tracking_error ?? -1), render: (r) => trackingErrorCell(r) },
      { title: '分红频率', key: 'payout_freq', width: 88, align: 'right', sorter: (a, b) => (a.payout_freq ?? -1) - (b.payout_freq ?? -1), render: (r: DividendFund) => h('span', { class: r.payout_freq == null ? 'dim-cell' : '' }, payoutFreqLabel(r.payout_freq)) },
      { title: '行业集中度', key: 'sector_concentration', width: 100, align: 'right', sorter: (a, b) => (a.sector_concentration ?? -1) - (b.sector_concentration ?? -1), render: (r) => sectorCell(r) },
    )
  }
  return cols
})

const detailFundColumns = computed<DataTableColumns<DividendFund>>(() => [
  { title: '代码', key: 'code', width: 84, fixed: 'left' },
  { title: '名称', key: 'name', width: 240, fixed: 'left' },
  {
    title: '份额',
    key: 'share_class',
    width: 72,
    render: (r: DividendFund) =>
      r.share_class
        ? h(
            NTooltip,
            { trigger: 'hover', placement: 'top' },
            {
              trigger: () => h('span', null, r.share_class!),
              default: () => '份额类别（A / C / E / 联接）：同一只基金的收费方式分支，不是基金规模',
            },
          )
        : h('span', { class: 'dim-cell' }, '—'),
  },
  {
    title: '规模(亿份)',
    key: 'scale',
    width: 100,
    align: 'right',
    render: (r: DividendFund) =>
      r.scale == null
        ? h('span', { class: 'dim-cell' }, '—')
        : h(
            NTooltip,
            { trigger: 'hover', placement: 'top' },
            {
              trigger: () => h('span', null, r.scale!.toFixed(2)),
              default: () => `份额规模（${r.scale_date ?? '日期未知'}）· 基金经理 ${r.manager ?? '—'}`,
            },
          ),
  },
  {
    title: 'PE分位',
    key: 'pe_percentile',
    width: 92,
    align: 'right',
    render: (r) => h('span', { style: { color: pctColor(r.pe_percentile) } }, fmt(r.pe_percentile, 1, '%')),
  },
  { title: '股息率', key: 'dividend_yield', width: 84, align: 'right', render: (r) => fmt(r.dividend_yield, 2, '%') },
  { title: '股债比', key: 'eb_ratio', width: 78, align: 'right', render: (r) => fmt(r.eb_ratio, 2, 'x') },
  { title: '信号·股债比', key: 'sig_eb', width: 108, render: (r) => signalCell(r.signals?.eb) },
  { title: '信号·PE分位', key: 'sig_pe', width: 108, render: (r) => signalCell(r.signals?.pe) },
  { title: '信号·股息率', key: 'sig_dy', width: 108, render: (r) => signalCell(r.signals?.dy) },
  { title: '跟踪误差', key: 'tracking_error', width: 88, align: 'right', render: (r) => trackingErrorCell(r) },
  { title: '分红频率', key: 'payout_freq', width: 88, align: 'right', render: (r: DividendFund) => h('span', { class: r.payout_freq == null ? 'dim-cell' : '' }, payoutFreqLabel(r.payout_freq)) },
  { title: '行业集中度', key: 'sector_concentration', width: 100, align: 'right', render: (r) => sectorCell(r) },
])

const subtitle = computed(() => {
  const o = overview.value
  if (!o) return '红利指数估值 + 全市场红利基金名录（数据源：中证指数 / 东方财富 / 同花顺）'
  return `更新 ${o.updated_at} · 10Y国债 ${o.yield_10y != null ? o.yield_10y.toFixed(2) + '%' : '—'} · 红利基金 ${fundTotal.value} 只（已识别跟踪指数 ${mappedTotal.value} 只）`
})

onMounted(async () => {
  await load()
  if (feeProgress.value?.running) startPoll()
})
onUnmounted(() => {
  stopPoll()
  stopExtraPoll()
})
</script>

<template>
  <div class="page">
    <PageHeader title="红利基金" :subtitle="subtitle" :updated-at="overviewMeta?.updateTime" />

    <n-space vertical size="large">
      <!-- 口径与规则说明 -->
      <n-card size="small">
        <template #header>
          <span>指标口径与仓位规则</span>
        </template>
        <div class="rule-grid">
          <div class="rule-item">
            <span class="rule-title">股债收益比</span>
            <span class="rule-body">股息率 ÷ 10Y国债收益率</span>
            <span class="rule-th">
              ≥{{ thresholds?.eb_add ?? 3 }} 加仓 ｜ {{ thresholds?.eb_low ?? 2.5 }}~{{ thresholds?.eb_add ?? 3 }} 低估·持有 ｜
              {{ thresholds?.eb_risk ?? 1.5 }}~{{ thresholds?.eb_low ?? 2.5 }} 持有 ｜ &lt;{{ thresholds?.eb_risk ?? 1.5 }} 减仓
            </span>
          </div>
          <div class="rule-item">
            <span class="rule-title">PE 分位</span>
            <span class="rule-body">当前 PE 在近 10 年日频序列中的百分位</span>
            <span class="rule-th">
              &gt;{{ thresholds?.pe_reduce ?? 90 }}% 减仓 ｜ &gt;{{ thresholds?.pe_stop ?? 80 }}% 停止加仓（新增资金转向更低估品种） ｜
              &lt;{{ thresholds?.pe_add ?? 20 }}% 可加仓
            </span>
          </div>
          <div class="rule-item">
            <span class="rule-title">股息率</span>
            <span class="rule-body">中证官方股息率（简易档，月度查看即可）</span>
            <span class="rule-th">
              &gt;{{ thresholds?.dy_hold ?? 4 }}% 正常持有 ｜ {{ thresholds?.dy_stop ?? 3.5 }}~{{ thresholds?.dy_hold ?? 4 }}% 停止加仓不减仓 ｜
              &lt;{{ thresholds?.dy_stop ?? 3.5 }}% 减仓 3 成转宽基
            </span>
          </div>
        </div>
        <div class="legend">
          <span class="legend-title">信号图例（A股习惯色）</span>
          <n-tag size="small" :bordered="false" :color="{ color: '#d030501f', textColor: '#d03050', borderColor: '#d0305059' }">加仓</n-tag>
          <n-tag size="small" :bordered="false" :color="{ color: '#8b5cf61f', textColor: '#8b5cf6', borderColor: '#8b5cf659' }">低估·持有</n-tag>
          <n-tag size="small" :bordered="false" :color="{ color: '#2080f01f', textColor: '#2080f0', borderColor: '#2080f059' }">持有</n-tag>
          <n-tag size="small" :bordered="false" :color="{ color: '#f0a0201f', textColor: '#f0a020', borderColor: '#f0a02059' }">停止加仓</n-tag>
          <n-tag size="small" :bordered="false" :color="{ color: '#18a0581f', textColor: '#18a058', borderColor: '#18a05859' }">减仓</n-tag>
          <span class="legend-hint">三套信号彼此独立、不做综合裁决，出现「⚠ 分歧」时请自行权衡。</span>
        </div>
      </n-card>

      <!-- 概览：研究页 4 张 + 数据页 5 张（ETF/被动/主动/映射率）合并为 8 张 -->
      <!-- 冷启动时 overview 要串行打多路网关（实测 14s）：统计卡先出骨架占位，
           避免渲染 0 / — 的误导值（2026-10-17 P2-1） -->
      <SectionSkeleton v-if="loading" variant="overview" />
      <n-grid v-else cols="2 s:2 m:4" :x-gap="12" :y-gap="12" responsive="screen">
        <n-gi><StatCard label="红利指数" :value="counts.index" :sub="`分歧 ${conflictCount} 个`" /></n-gi>
        <n-gi>
          <StatCard
            label="10Y 国债收益率"
            :value="yield10y != null ? yield10y.toFixed(2) + '%' : '—'"
            :sub="overview?.yield_10y_date ?? ''"
            tip="股债收益比的分母，取最新交易日中债 10Y 到期收益率"
          />
        </n-gi>
        <n-gi><StatCard label="含「加仓」信号" :value="addCount" sub="任一指标给出加仓" /></n-gi>
        <n-gi>
          <StatCard
            label="红利基金总数"
            :value="fundTotal"
            :sub="`场内 ${onshoreCount} · 场外 ${offshoreCount} 只`"
          />
        </n-gi>
        <n-gi><StatCard label="场内ETF" :value="counts.etf" sub="可在场内直接买卖" /></n-gi>
        <n-gi><StatCard label="被动红利基金" :value="counts.passive" sub="含 A/C 份额与联接" /></n-gi>
        <n-gi v-if="counts.active > 0">
          <StatCard label="主动红利基金" :value="counts.active" sub="主动管理型" />
        </n-gi>
        <n-gi v-else>
          <StatCard
            label="已剔除（纯债/主动）"
            :value="excludedCount"
            sub="名录只收被动指数型"
            tip="按 2026-10-06 定下的口径：纯债型与主动管理型（混合型-偏股/灵活、股票型、QDII 等）不进红利名录，名录只收基金类型为「指数型」的被动产品"
          />
        </n-gi>
        <n-gi>
          <StatCard
            label="指数映射率"
            :value="fundTotal ? mappedRate.toFixed(1) + '%' : '—'"
            sub="未识别的按名称未匹配处理"
            tip="基金名称→红利指数的匹配按区域隔离（A股 / 港股 / 沪港深），只在该区域内匹配最长别名"
          />
        </n-gi>
      </n-grid>

      <template v-if="!loading && !error && indices.length">
        <!-- 指数估值表 -->
        <n-card size="small">
          <template #header>红利指数估值与仓位信号（双击行：PE 历史 + 该指数跟踪基金清单）</template>
          <n-data-table
            :columns="indexColumns"
            :data="indices"
            :row-props="indexRowProps"
            size="small"
            :max-height="430"
            :scroll-x="1180"
          />
        </n-card>

        <!-- PE 历史 -->
        <n-card size="small">
          <template #header>
            PE 历史 · {{ selected?.name ?? '' }}
            <span class="dim-cell">
              （{{ selected?.window_start ?? '—' }} 起 {{ selected?.window_days ?? 0 }} 个交易日，当前分位
              {{ selected?.pe_percentile != null ? selected.pe_percentile.toFixed(1) + '%' : '—' }}）
            </span>
          </template>
          <BaseChart :option="peChartOption" :height="260" />
        </n-card>
      </template>
      <!-- 指数表区 loading 骨架（2026-10-17 P2-1）：冷启动 14s 期间占位，避免布局跳动 -->
      <SectionSkeleton v-else-if="loading" variant="table" :rows="6" />

      <SectionFallback
        v-if="!loading && !error && !indices.length"
        :error="null"
        :min-height="160"
        empty-text="暂无红利指数估值数据"
      />

      <!-- 红利基金名录（场内 / 场外）：切到「现金流」Tab 时整块让位 -->
      <n-card size="small" v-if="activeTab !== 'cashflow'">
        <template #header>
          红利基金名录（全量 {{ fundTotal }} 只 · ETF {{ counts.etf }} / 被动 {{ counts.passive }} · 已识别指数 {{ mappedTotal }} 只 · 剔除纯债/主动 {{ excludedCount }} 只）
        </template>
        <template #header-extra>
          <n-space size="small" align="center">
            <span class="dim-cell">
              规模/费率已补 {{ feeProgress?.filled ?? 0 }}/{{ feeProgress?.total ?? 0 }}
              <template v-if="feeProgress?.running">
                （后台补全中 {{ feeProgress.round_done }}/{{ feeProgress.round_total }}）
              </template>
              <template v-else-if="feeProgress?.throttled">
                （上游限流，{{ feeProgress.retry_in_hours }} 小时后自动续跑）
              </template>
            </span>
            <n-button size="tiny" tertiary :loading="filling" @click="fillFees">
              <template #icon><n-icon :component="CloudDownloadOutline" /></template>
              补一批(80只)
            </n-button>
            <n-button size="tiny" tertiary :loading="mapping" @click="fillIndexMap">
              识别跟踪指数(已 {{ mapProgress?.matched ?? 0 }} 只)
            </n-button>
            <span class="dim-cell">
              三类指标已补 {{ extraProgress?.filled ?? 0 }}/{{ extraProgress?.total ?? 0 }}
              <template v-if="extraProgress?.running">（后台补全中 {{ extraProgress.round_done }}/{{ extraProgress.round_total }}）</template>
              <template v-else-if="extraProgress?.throttled">（上游限流，{{ extraProgress.retry_in_hours }} 小时后续跑）</template>
              <template v-if="extraProgress?.perm_failed">（{{ extraProgress.perm_failed }} 只永久失败）</template>
            </span>
            <n-button size="tiny" tertiary :loading="fillingExtra" @click="fillExtra">
              <template #icon><n-icon :component="TrendingUpOutline" /></template>
              补三类指标(80只)
            </n-button>
            <n-button size="tiny" tertiary :loading="refreshing" @click="refresh">
              <template #icon><n-icon :component="RefreshOutline" /></template>
              刷新
            </n-button>
          </n-space>
        </template>

        <LoadingState :loading="loading" :error="error" :min-height="120" text="正在拉取红利基金数据…" />

        <template v-if="!loading && !error && allFunds.length">
          <n-space size="small" align="center" style="margin-bottom: 8px">
            <n-input
              v-model:value="keyword"
              size="small"
              placeholder="搜索代码 / 名称 / 跟踪指数"
              clearable
              style="width: 220px"
            />
            <n-select v-model:value="typeFilter" size="small" :options="typeOptions" style="width: 120px" />
            <n-switch v-model:value="onlyMapped" size="small" />
            <span class="dim-cell">仅看已识别指数</span>
            <n-switch v-model:value="onlyOnshore" size="small" />
            <span class="dim-cell">仅看场内</span>
            <n-switch v-model:value="showPending" size="small" />
            <span class="dim-cell">规模/费率列</span>
            <span class="dim-cell">当前筛选 {{ filteredFunds.length }} / {{ currentFunds.length }} 只（{{ scopeLabel }}）</span>
          </n-space>

          <n-progress
            v-if="feeProgress && feeProgress.total"
            type="line"
            :percentage="Math.round(((feeProgress.filled ?? 0) / feeProgress.total) * 100)"
            :height="6"
            :border-radius="3"
            :processing="!!feeProgress.running"
            style="margin: 6px 0 2px"
          />

          <TabBar :tabs="fundTabs" v-model="activeTab" />

          <div class="dim-cell" style="margin-top: 6px; font-size: 12px">
            双击名录里的基金行 → 看该基金的季报持仓明细（逐只后台补全，落库后纯读本地）
          </div>

          <n-alert v-if="showPending" type="default" :bordered="false" style="margin-top: 8px">
            <template #icon><n-icon :component="WarningOutline" /></template>
            规模 / 管理费 / 托管费 / 最高申购费来自同花顺（逐只查询，后台渐进补全，结果落库，30 天刷新一次）；
            跟踪误差（东财日净值增长率 vs 跟踪指数日收益年化）/ 分红频率（天天基金 F10 分红配送）/
            行业集中度（季报持仓映射申万一级行业，前 3 行业占净值比）三项已接入后台渐进补全，
            结果落 DuckDB，越用越全；「待补全」= 该基金暂无跟踪指数 / 持仓或样本不足。
          </n-alert>

          <n-data-table
            :columns="fundColumns"
            :data="filteredFunds"
            :row-props="fundRowProps"
            :pagination="pagination"
            size="small"
            :max-height="640"
            :scroll-x="1560"
            style="margin-top: 8px"
          />
        </template>
      </n-card>

      <!-- 现金流基金名录（独立一条因子线，与上面红利名录互不相干） -->
      <n-card size="small" v-else>
        <template #header>
          现金流场内 ETF（{{ cashflowTotal }} 只 · 已识别跟踪指数 {{ cashflowCounts.index }} 个 ·
          有官方 PE 估值 {{ cashflowCounts.index_valued ?? 0 }} 个 ·
          场外已剔除 {{ cashflowCounts.excluded ?? 0 }} 只 A/C 份额）
        </template>
        <template #header-extra>
          <n-space size="small" align="center">
            <span class="dim-cell">
              三类指标已补 {{ extraProgress?.filled ?? 0 }}/{{ extraProgress?.total ?? 0 }}
              <template v-if="extraProgress?.running">（后台补全中 {{ extraProgress.round_done }}/{{ extraProgress.round_total }}）</template>
              <template v-else-if="extraProgress?.throttled">（上游限流，{{ extraProgress.retry_in_hours }} 小时后续跑）</template>
              <template v-if="extraProgress?.perm_failed">（{{ extraProgress.perm_failed }} 只永久失败）</template>
            </span>
            <n-button size="tiny" tertiary :loading="fillingExtra" @click="fillExtra">
              <template #icon><n-icon :component="TrendingUpOutline" /></template>
              补三类指标(80只)
            </n-button>
            <n-button size="tiny" tertiary :loading="cashflowLoading" @click="loadCashflow(true)">
              <template #icon><n-icon :component="RefreshOutline" /></template>
              刷新
            </n-button>
          </n-space>
        </template>

        <LoadingState
          :loading="cashflowLoading"
          :error="cashflowError"
          :min-height="120"
          text="正在拉取现金流基金名录…"
        />

        <template v-if="!cashflowLoading && !cashflowError && cashflowTotal">
          <n-space size="small" align="center" style="margin-bottom: 8px">
            <n-input
              v-model:value="cashflowKeyword"
              size="small"
              placeholder="搜索代码 / 名称 / 跟踪指数"
              clearable
              style="width: 220px"
            />
            <span class="dim-cell">
              当前筛选 {{ filteredCashflowFunds.length }} / {{ cashflowTotal }} 只
            </span>
          </n-space>

          <n-alert type="default" :bordered="false" style="margin-top: 8px">
            <template #icon><n-icon :component="WarningOutline" /></template>
            口径：<b>{{ cashflow?.gate ?? '—' }}</b>
            <span style="margin-left: 6px">
              （更新于 {{ cashflow?.updated_at ?? '—' }}）。这条线是独立的因子口径（自由现金流 / 经营性现金流
              vs 红利页的股息率），<b>不参与</b>上面红利名录的 PE 分位 / 股息率 / 股债比信号。
              跟踪指数取自天天基金 F10「跟踪标的」逐只实测（中证 932365 全指 / 932366 沪深300 /
              932367 中证500 / 932368 中证800 / 932369 中证1000 + 国证 980092 六个指数，159399
              那只跟踪富时系、该指数无公开通用代码故只显示名称）。
            </span>
          </n-alert>

          <!-- 指数估值（2026-10-07 补）：只有 PE 一路，中证官方滚动市盈率 -->
          <template v-if="cashflowIndices.length">
            <div style="margin: 10px 0 4px">
              <b>现金流指数估值</b>
              <span class="dim-cell" style="margin-left: 6px; font-size: 12px">
                PE 取中证官方「滚动市盈率」（更新于 {{ cashflow?.index_updated_at ?? '—' }}）；
                ⚠️ 这类指数<b>不是股息导向</b>，中证不披露官方股息率 → 本页<b>没有</b>股息率 / 股债比两列
              </span>
            </div>
            <n-data-table
              :columns="cashflowIndexColumns"
              :data="cashflowIndices"
              size="small"
              :pagination="false"
            />
            <div class="dim-cell" style="margin: 4px 0 0; font-size: 12px">
              窗口只有约 2 年（指数 2024-10 起才有 PE 数据），分位数样本明显少于红利页那 26 个指数。
            </div>
          </template>

          <div v-if="cashflowNoData.length" class="dim-cell" style="margin-top: 6px; font-size: 12px">
            无官方估值的指数：
            <span v-for="(x, i) in cashflowNoData" :key="x.name">
              {{ i ? '；' : '' }}<b>{{ x.name }}</b>（{{ x.reason }}）
            </span>
          </div>

          <div v-if="cashflow?.fee_progress && cashflow.fee_progress.total" class="dim-cell" style="margin-top: 6px; font-size: 12px">
            规模 / 费率已补全 {{ cashflow.fee_progress.filled }} / {{ cashflow.fee_progress.total }} 只
            <span v-if="cashflow.fee_progress.running">（后台正在跑…）</span>
            <span v-else-if="cashflow.fee_progress.throttled">
              （上一轮撞上同花顺限流已中止，约 {{ cashflow.fee_progress.retry_in_hours }} 小时后自动续跑，不影响其余功能）
            </span>
          </div>

          <div v-if="extraProgress && extraProgress.total" class="dim-cell" style="margin-top: 6px; font-size: 12px">
            三类指标已补全 {{ extraProgress.filled }} / {{ extraProgress.total }} 只
            <span v-if="extraProgress.running">（后台补全中 {{ extraProgress.round_done }}/{{ extraProgress.round_total }}…）</span>
            <span v-else-if="extraProgress.throttled">（上游限流，约 {{ extraProgress.retry_in_hours }} 小时后自动续跑）</span>
            <span v-if="extraProgress.perm_failed">（{{ extraProgress.perm_failed }} 只永久失败）</span>
          </div>

          <div class="dim-cell" style="margin-top: 6px; font-size: 12px">
            双击行 → 看该基金的季报持仓明细（现金流 ETF 已和红利共用后台补全频道，未抓到的会显示「暂无」）
          </div>

          <n-data-table
            :columns="cashflowColumns"
            :data="filteredCashflowFunds"
            :row-props="fundRowProps"
            :pagination="cashflowPagination"
            size="small"
            :max-height="640"
            :scroll-x="1280"
            style="margin-top: 8px"
          />
        </template>
      </n-card>

      <!-- 点指数行：跟踪它的场内/场外基金 + 该指数编制说明 -->
      <n-modal v-model:show="detailOpen" preset="card" style="width: 1000px">
        <template #header>
          <span>
            跟踪指数 · {{ detail?.name ?? '' }}
            <span class="dim-cell">{{ detailCode }}</span>
          </span>
        </template>

        <LoadingState
          :loading="detailLoading"
          :error="detailError"
          :min-height="120"
          text="正在加载该指数的跟踪基金…"
        />

        <template v-if="!detailLoading && !detailError && detail">
          <n-card size="small" style="margin-bottom: 12px">
            <template #header>指数编制说明（中证指数公司）</template>
            <template v-if="detail.compilation && detail.compilation.desc">
              <div class="comp-desc">{{ detail.compilation.desc }}</div>
              <div class="comp-meta">
                <span>官方全称：{{ detail.compilation.full_name || '—' }}</span>
                <span>调样频率：{{ detail.compilation.adj_freq || '—' }}</span>
                <span>加权方式：{{ detail.compilation.weighting || '—' }}</span>
                <span>合规声明：{{ detail.compilation.compliance || '—' }}</span>
              </div>
            </template>
            <template v-else>
              <n-alert type="warning" :bordered="false" style="margin-bottom: 8px">
                中证官网暂时不可用（403 限流），官方编制说明未取到。下面用跟踪该指数的代表基金
                「业绩比较基准」原文说明指数口径（同为真实数据）。
              </n-alert>
              <div v-if="!(detail.benchmark_samples || []).length" class="dim-cell">
                暂无业绩比较基准样本（这些基金尚未抓取基准文本，点名录里的「识别跟踪指数」可补）。
              </div>
              <div
                v-for="b in detail.benchmark_samples || []"
                :key="b.code"
                class="bench-item"
              >
                <span class="bench-code">{{ b.code }}</span>
                <span class="bench-name">{{ b.name }}</span>
                <span class="bench-text">{{ b.benchmark }}</span>
              </div>
            </template>
          </n-card>

          <n-space vertical size="small">
            <n-card size="small">
              <template #header>场内基金（{{ detail.counts.onshore }} 只）</template>
              <n-data-table
                :columns="detailFundColumns"
                :data="detail.funds.onshore"
                :pagination="{ pageSize: 20 }"
                size="small"
                :max-height="340"
                :scroll-x="1120"
              />
            </n-card>
            <n-card size="small">
              <template #header>场外基金（{{ detail.counts.offshore }} 只）</template>
              <n-data-table
                :columns="detailFundColumns"
                :data="detail.funds.offshore"
                :pagination="{ pageSize: 20 }"
                size="small"
                :max-height="340"
                :scroll-x="1120"
              />
            </n-card>
          </n-space>
        </template>
      </n-modal>

      <!-- 双击基金行：该基金的季报持仓明细 -->
      <n-modal v-model:show="holdingsOpen" preset="card" style="width: 900px">
        <template #header>
          <span>
            持仓明细 · <span class="cell-strong">{{ holdingsCode }}</span>
            <span class="dim-cell">{{ holdingsData?.quarter ?? '' }}</span>
            <n-tag v-if="holdingsStale" type="warning" size="small" style="margin-left: 8px">
              数据已过期（抓取于 {{ holdingsStaleDays }} 天前，超过 {{ HOLDINGS_TTL_DAYS }} 天口径）
            </n-tag>
          </span>
        </template>

        <LoadingState
          :loading="holdingsLoading"
          :error="holdingsError"
          :min-height="120"
          text="正在加载该基金的季报持仓…"
        />

        <template v-if="!holdingsLoading && !holdingsError && holdingsData">
          <n-alert :type="holdingsStale ? 'warning' : 'default'" :bordered="false" style="margin-bottom: 8px">
            季报口径：来自基金定期报告（{{ holdingsData?.quarter ?? '—' }}），是上一季度的快照、
            <b>不是实时持仓</b>；「占净值比例 / 持股数 / 持仓市值」沿用东财口径（持股数万份、持仓市值万元）。
            （数据源：{{ holdingsData?.source ?? '—' }}）
            <template v-if="holdingsData?.fetched_at">
              <br />
              本地抓取于 <b>{{ holdingsData.fetched_at.slice(0, 19) }}</b>
              <span v-if="holdingsStale">
                ，已超过 {{ HOLDINGS_TTL_DAYS }} 天缓存口径——这段时间的持仓可能有更新，
                等每日定时任务自动续抓即可，或让管理员在后台触发一次持仓补全。
              </span>
              <span v-else>，在 {{ HOLDINGS_TTL_DAYS }} 天缓存口径内。</span>
            </template>
          </n-alert>

          <div v-if="!holdingsData.rows.length" class="dim-cell">
            该基金暂无季报持仓记录（次新基金或联接基金季报尚未披露，未抓到就显示「—」，不做估算）。
          </div>
          <n-data-table
            v-else
            :columns="holdingsColumns"
            :data="holdingsData.rows"
            :pagination="{ pageSize: 30 }"
            size="small"
            :max-height="460"
            :scroll-x="620"
          />
        </template>
      </n-modal>
    </n-space>
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
}

.rule-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}

.rule-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rule-title {
  font-weight: 600;
  font-size: 13px;
}

.rule-body {
  opacity: 0.65;
  font-size: 12px;
}

.rule-th {
  font-size: 12px;
  opacity: 0.8;
}

.legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(128, 128, 128, 0.16);
}

.legend-title {
  font-size: 12px;
  font-weight: 600;
  margin-right: 4px;
}

.legend-hint {
  font-size: 12px;
  opacity: 0.65;
}

:deep(.cell-strong) {
  font-weight: 600;
}

:deep(.dim-cell) {
  opacity: 0.55;
  font-size: 12px;
}
/* 已确认跟踪「池外指数」的基金：留空但可悬停查原因 */
:deep(.out-of-pool) {
  cursor: help;
  border-bottom: 1px dashed rgba(128, 128, 128, 0.6);
  font-size: 12px;
}

.comp-desc {
  font-size: 13px;
  line-height: 1.7;
}

.comp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin-top: 8px;
  font-size: 12px;
  opacity: 0.7;
}

.bench-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 5px 0;
  border-bottom: 1px solid rgba(128, 128, 128, 0.12);
  font-size: 12px;
}

.bench-code {
  opacity: 0.6;
  flex: none;
}

.bench-name {
  font-weight: 600;
  flex: none;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-text {
  opacity: 0.8;
}

:deep(.div-bar) {
  margin-top: 3px;
  height: 3px;
  width: 100%;
  border-radius: 2px;
  background: rgba(128, 128, 128, 0.2);
  overflow: hidden;
}

:deep(.div-bar-fill) {
  height: 100%;
  border-radius: 2px;
}
</style>
