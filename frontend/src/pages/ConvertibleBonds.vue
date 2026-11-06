<script setup lang="ts">
defineOptions({ name: 'ConvertibleBonds' })
import { ref, computed, h, onMounted, watch } from 'vue'
import { NDataTable, NInput, NSelect, NInputNumber, NIcon, NModal, NButton, useMessage } from 'naive-ui'
import type { PaginationProps } from 'naive-ui'
import { DownloadOutline, FilterOutline, WarningOutline, SwapHorizontalOutline, StatsChartOutline, WalletOutline, TimeOutline, SearchOutline, FlashOutline } from '@vicons/ionicons5'
import type { Component } from 'vue'
import { useAsyncData } from '../composables/useApi'
import { api, isGatewayNoData } from '../utils/api'
import { useSignalScan } from '../composables/useSignalScan'
import {
  buildTacticalSignalColumns,
  buildWinrateColumns,
  tacticalStateOf as tacticalState,
  winrateExportCells,
} from '../utils/signalDisplay'
import type { ConvertibleBond } from '../types'
import { exportToCSV } from '../utils/export'
import { analyzeConversionBatch, analyzeVolatilityBatch, CONVERSION_ORDER, VOL_SIGNAL_ORDER } from '../utils/convertibleBond'
import type { ConversionArbitrage, VolatilityAnalysis } from '../utils/convertibleBond'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import LoadingState from '../components/LoadingState.vue'
import SectionFallback from '../components/SectionFallback.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
// 可转债是实时行情，手动刷新/进入页面都穿透 30s 列表缓存（告警引擎仍复用缓存）
const { data: bonds, loading, error, meta, refresh: refetch } = useAsyncData<ConvertibleBond[]>(() => api.getConvertibleBonds(true))
const gatewayEmpty = computed(() => isGatewayNoData(meta.value))
onMounted(() => {
  refetch()
  loadStrategies()
})

// 有真实成交的存续债：所有统计/策略/排名/扫描都只基于这一子集。
// 主源含 5 只待上市新债（现价 100 面值占位、成交额 0），它们不是行情。
const activeBonds = computed(() => (bonds.value ?? []).filter(b => b.has_trade))
const pendingCount = computed(() => (bonds.value ?? []).length - activeBonds.value.length)

// 转股套利可行性分析映射
const conversionMap = computed(() => {
  if (!bonds.value) return new Map<string, ConversionArbitrage>()
  return analyzeConversionBatch(bonds.value)
})

// IV/HV 波动率分析映射
const volatilityMap = computed(() => {
  if (!bonds.value) return new Map<string, VolatilityAnalysis>()
  return analyzeVolatilityBatch(bonds.value)
})

// 市场统计：中位价格 / 中位溢价率（从实际数据计算，不使用硬编码数值）
function median(nums: number[]): number {
  if (!nums.length) return 0
  const sorted = [...nums].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}
const medianPrice = computed(() => median(activeBonds.value.map(b => b.price)))
const medianPremium = computed(() => median(activeBonds.value.map(b => b.premium_pct)))
const tradedCount = computed(() => activeBonds.value.length)

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
// 策略快捷按钮
interface StrategyDef {
  key: string
  label: string
  icon: Component
  desc: string
  filter: (b: ConvertibleBond) => boolean
}

const strategies: StrategyDef[] = [
  {
    key: 'discount_arb',
    label: '折价套利',
    icon: SwapHorizontalOutline,
    desc: '有成交、且转股溢价率为负（负溢价 ≠ 可套利，需看转股套利列）',
    filter: b => b.has_trade && b.premium_pct < 0,
  },
  {
    key: 'double_low',
    label: '双低轮动',
    icon: StatsChartOutline,
    desc: '有成交、价格 ≤ 120 且溢价率 ≤ 30%，经典双低策略池',
    filter: b => b.has_trade && b.price <= 120 && b.premium_pct <= 30,
  },
  {
    key: 'high_ytm',
    label: '到期高收益',
    icon: WalletOutline,
    desc: '有成交、集思录真实到期税前收益 ≥ 2%（无数据不参与）',
    filter: b => b.has_trade && b.ytm !== null && b.ytm >= 2,
  },
  {
    key: 'near_maturity',
    label: '临期转债',
    icon: TimeOutline,
    desc: '有成交、剩余年限 ≤ 1 年，关注到期/强赎安排',
    filter: b => b.has_trade && b.remaining_years !== null && b.remaining_years <= 1,
  },
]

const activeStrategyKey = ref<string | null>(null)
const activeStrategy = computed(() => strategies.find(s => s.key === activeStrategyKey.value) ?? null)

function selectStrategy(key: string) {
  activeStrategyKey.value = activeStrategyKey.value === key ? null : key
}

const searchQuery = ref('')
const filterPriceMin = ref('')
const filterPriceMax = ref('')
const filterPremiumMin = ref('')
const filterPremiumMax = ref('')
// clearable 清空后 Naive UI 回传 null，类型必须允许 null，否则经判断会把整表筛空
const filterRating = ref<string | null>('全部评级')
// 高级筛选 (更多筛选弹窗)
const showAdvancedFilter = ref(false)
const filterYtmMin = ref('')
const filterYearsMax = ref('')
const filterDoubleLowMax = ref('')
const filterPbMax = ref('')
const onlyTraded = ref(true)

// 评级下拉从真实数据生成（实际有 25 种，旧版只列了 4 项）
const ratingOptions = computed(() => {
  const set = new Set<string>()
  ;(bonds.value ?? []).forEach(b => { if (b.rating) set.add(b.rating) })
  return [
    { label: '全部评级', value: '全部评级' },
    ...[...set].sort().map(r => ({ label: r, value: r })),
  ]
})

const filteredBonds = computed(() => {
  if (!bonds.value) return []
  const q = searchQuery.value.trim().toLowerCase()
  const digits = q.replace(/\D/g, '')
  return bonds.value.filter(b => {
    if (onlyTraded.value && !b.has_trade) return false
    if (q) {
      const nameHit = b.name.toLowerCase().includes(q)
      const codeHit = b.code.toLowerCase().includes(q) || (digits.length >= 2 && b.code.includes(digits))
      if (!nameHit && !codeHit) return false
    }
    if (filterPriceMin.value && b.price < Number(filterPriceMin.value)) return false
    if (filterPriceMax.value && b.price > Number(filterPriceMax.value)) return false
    if (filterPremiumMin.value && b.premium_pct < Number(filterPremiumMin.value)) return false
    if (filterPremiumMax.value && b.premium_pct > Number(filterPremiumMax.value)) return false
    if (filterRating.value && filterRating.value !== '全部评级' && b.rating !== filterRating.value) return false
    // 无源字段用 ±Infinity 兜底：缺值不冒充「满足条件」，也不冒充「不满足」
    if (filterYtmMin.value && (b.ytm ?? -Infinity) < Number(filterYtmMin.value)) return false
    if (filterYearsMax.value && (b.remaining_years ?? Infinity) > Number(filterYearsMax.value)) return false
    if (filterDoubleLowMax.value && (b.double_low_score ?? Infinity) > Number(filterDoubleLowMax.value)) return false
    if (filterPbMax.value && (b.stock_pb ?? Infinity) > Number(filterPbMax.value)) return false
    if (activeStrategyKey.value && !activeStrategy.value?.filter(b)) return false
    return true
  })
})

function applyFilters() {
  const total = bonds.value?.length ?? 0
  const matched = filteredBonds.value.length
  message.success(`筛选完成：${matched} / ${total} 只转债匹配（有成交 ${tradedCount.value} 只）`)
}

// 筛选条件/策略变化时回到第一页
watch(filteredBonds, () => { pagination.value.page = 1 })

function resetAdvancedFilters() {
  filterYtmMin.value = ''
  filterYearsMax.value = ''
  filterDoubleLowMax.value = ''
  filterPbMax.value = ''
}

const tagColors: Record<string, { bg: string; text: string; border: string }> = {
  double_low: { bg: '#d2e4ff', text: '#005ea1', border: 'rgba(0,94,161,0.2)' },
  undervalued: { bg: '#f2f3fa', text: '#717782', border: 'rgba(226,232,240,0.3)' },
  high_risk: { bg: '#ffdad6', text: '#ba1a1a', border: 'rgba(186,26,26,0.2)' },
  stable_yield: { bg: '#d2e4ff', text: '#005ea1', border: 'rgba(0,94,161,0.2)' },
  mean_reversion: { bg: '#f2f3fa', text: '#717782', border: 'rgba(226,232,240,0.3)' },
  defensive: { bg: '#d2e4ff', text: '#005ea1', border: 'rgba(0,94,161,0.2)' },
}

// Shared progress bar renderer for 条款触发进度
function progressCell(days: number, total: number) {
  const ratio = total > 0 ? days / total : 0
  const cls = ratio >= 0.8 ? 'danger' : ratio >= 0.5 ? 'warn' : ''
  return h('div', { class: 'redemption-cell' }, [
    h('div', { class: 'redemption-track' }, [
      h('div', { class: ['redemption-fill', cls], style: { width: (ratio * 100) + '%' } }),
    ]),
    h('span', { class: 'redemption-text' }, `${days}/${total}天`),
  ])
}

const columns = [
  {
    title: '代码',
    key: 'code',
    render: (row: ConvertibleBond) => h('span', { class: 'cb-code' }, row.code),
  },
  {
    title: '转债名称',
    key: 'name',
    render: (row: ConvertibleBond) => h('div', { class: 'cb-name-cell' }, [
      h('span', { class: 'cb-name' }, row.name),
      row.has_trade ? null : h('span', { class: 'pending-tag' }, '无成交'),
    ]),
  },
  {
    title: '价格',
    key: 'price',
    align: 'right' as const,
    render: (row: ConvertibleBond) => row.price.toFixed(3),
  },
  {
    title: '涨跌幅',
    key: 'change_pct',
    align: 'right' as const,
    render: (row: ConvertibleBond) => {
      const v = row.change_pct
      if (v === null) return h('span', { class: 'na-text' }, '—')
      return h('span', { style: { color: v >= 0 ? 'var(--color-danger)' : 'var(--color-success)' } },
        `${v >= 0 ? '+' : ''}${v}%`)
    },
  },
  {
    title: titleWithHelp('转股价值', 'conv_value'),
    key: 'conv_value',
    align: 'right' as const,
    render: (row: ConvertibleBond) => row.conv_value.toFixed(2),
  },
  {
    title: titleWithHelp('溢价率', 'premium_pct_cb'),
    key: 'premium_pct',
    align: 'right' as const,
    render: (row: ConvertibleBond) => {
      const color = row.premium_pct < 5
        ? 'var(--color-success)'
        : row.premium_pct > 30
          ? 'var(--color-danger)'
          : 'var(--text-primary)'
      return h('span', { style: { color } }, `${row.premium_pct}%`)
    },
  },
  {
    title: 'IV/HV',
    key: 'volatility',
    align: 'center' as const,
    render: (row: ConvertibleBond) => {
      const v = volatilityMap.value.get(row.code)
      // 网关未提供 IV/HV：明确标「未接入」，不再把 0 显示成真实波动率
      if (!v || v.iv === null || v.hv === null) {
        return h('span', { class: 'na-text', title: v?.suggestion ?? '数据源未接入' }, '未接入')
      }
      const signalStyle: Record<string, { color: string; fontWeight: number }> = {
        undervalued: { color: 'var(--color-success)', fontWeight: 700 },
        overvalued: { color: 'var(--color-danger)', fontWeight: 700 },
        fair: { color: 'var(--text-secondary)', fontWeight: 500 },
      }
      const s = signalStyle[v.signal] ?? signalStyle.fair
      return h('div', { class: 'vol-cell' }, [
        h('div', { class: 'vol-numbers' }, [
          h('span', { style: { color: 'var(--text-muted)', fontSize: '9px' } }, 'IV'),
          h('span', { style: { color: s.color, fontWeight: s.fontWeight } }, `${v.iv}%`),
        ]),
        h('div', { class: 'vol-numbers' }, [
          h('span', { style: { color: 'var(--text-muted)', fontSize: '9px' } }, 'HV'),
          h('span', { style: { color: 'var(--text-secondary)' } }, `${v.hv}%`),
        ]),
        h('span', { class: ['vol-signal', v.signal], title: v.suggestion }, v.signalLabel),
      ])
    },
  },
  {
    title: titleWithHelp('转股套利', 'conversion_feasibility'),
    key: 'conversion_arb',
    align: 'center' as const,
    render: (row: ConvertibleBond) => {
      const a = conversionMap.value.get(row.code)
      if (!a) return '-'
      if (!a.isNegativePremium) {
        return h('span', { style: { color: 'var(--text-muted)', fontSize: '11px' } }, '-')
      }
      const feasStyle: Record<string, { bg: string; color: string }> = {
        feasible: { bg: 'var(--tag-green-bg)', color: 'var(--tag-green-text)' },
        risky: { bg: 'var(--tag-orange-bg)', color: 'var(--tag-orange-text)' },
        unknown: { bg: 'var(--bg-subtle)', color: 'var(--text-muted)' },
        infeasible: { bg: 'var(--tag-red-bg)', color: 'var(--tag-red-text)' },
      }
      const s = feasStyle[a.feasibility] ?? { bg: '', color: '' }
      const children: any[] = [
        h('span', { class: 'conv-yield', style: { color: a.theoreticalYield > 0 ? 'var(--color-success)' : 'var(--color-danger)' } }, `${a.theoreticalYield > 0 ? '+' : ''}${a.theoreticalYield}%`),
        h('span', { class: 'feas-badge', style: { background: s.bg, color: s.color } }, a.feasibilityLabel),
      ]
      if (a.blockers.length > 0) {
        children.push(h('span', { class: 'conv-blocker', title: a.blockers.join('\n') }, `${a.blockers.length}项阻碍`))
      }
      if (a.dataMissing.length > 0) {
        children.push(h('span', { class: 'conv-blocker muted', title: a.dataMissing.join('\n') }, `${a.dataMissing.length}项未披露`))
      }
      return h('div', { class: 'conv-cell' }, children)
    },
  },
  {
    title: titleWithHelp('到期收益', 'ytm'),
    key: 'ytm',
    align: 'right' as const,
    render: (row: ConvertibleBond) => {
      // 集思录真实到期税前收益；异常值/降级源无源时显示 —，不再用近似公式补数
      if (row.ytm === null) return h('span', { class: 'na-text' }, '—')
      return h('span', { class: 'ytm-cell' }, [
        h('span', { style: { color: row.ytm >= 0 ? 'var(--color-success)' : 'var(--color-danger)' } },
          `${row.ytm >= 0 ? '+' : ''}${row.ytm}%`),
      ])
    },
  },
  {
    title: '剩余年限',
    key: 'remaining_years',
    align: 'center' as const,
    render: (row: ConvertibleBond) => row.remaining_years === null
      ? h('span', { class: 'na-text' }, '—')
      : `${row.remaining_years}Y`,
  },
  {
    title: '评级',
    key: 'rating',
    align: 'center' as const,
    render: (row: ConvertibleBond) => row.rating
      ? h('span', { class: ['rating-tag', row.rating] }, row.rating)
      : h('span', { class: 'na-text' }, '—'),
  },
  {
    title: titleWithHelp('强赎状态', 'redemption_status'),
    key: 'redemption',
    align: 'center' as const,
    render: (row: ConvertibleBond) => {
      // 只有上游明确给出「n/m 天」才画进度条；否则展示状态文字，不再写死 0/15天
      if (row.redemption_days !== null && row.total_redemption_days) {
        return progressCell(row.redemption_days, row.total_redemption_days)
      }
      const status = row.redemption_status
      if (!status) return h('span', { class: 'na-text' }, '—')
      const risky = status.includes('公告') || status.includes('满足') || status.includes('强赎')
      return h('span', {
        class: 'cb-status',
        style: { color: risky ? 'var(--color-danger)' : 'var(--text-secondary)' },
        title: `强赎触发价 ${row.redemption_trigger_price ?? '—'}`,
      }, status)
    },
  },
  {
    title: titleWithHelp('回售触发价', 'putback_trigger_price'),
    key: 'putback',
    align: 'right' as const,
    render: (row: ConvertibleBond) => row.putback_trigger_price == null
      ? h('span', { class: 'na-text' }, '—')
      : row.putback_trigger_price.toFixed(2),
  },
  {
    title: titleWithHelp('到期日', 'maturity_date'),
    key: 'maturity',
    align: 'center' as const,
    render: (row: ConvertibleBond) => row.maturity_date ?? h('span', { class: 'na-text' }, '—'),
  },
  {
    title: '正股',
    key: 'stock',
    align: 'center' as const,
    render: (row: ConvertibleBond) => {
      // Z-Score / 质押率 / ST 无上游源，改为展示真实的正股名称与涨跌
      if (!row.stock_name) return h('span', { class: 'na-text' }, '—')
      const chg = row.stock_change_pct ?? null
      return h('div', { class: 'cb-stock-cell' }, [
        h('span', { class: 'cb-stock-name' }, row.stock_name),
        chg === null ? null : h('span', {
          style: { color: chg >= 0 ? 'var(--color-danger)' : 'var(--color-success)', fontSize: '10px' },
        }, `${chg >= 0 ? '+' : ''}${chg}%`),
      ])
    },
  },
  {
    title: '标签',
    key: 'tag',
    render: (row: ConvertibleBond) => {
      if (!row.tag) return h('span', { class: 'na-text' }, '—')
      const c = tagColors[row.tag_type]
      return h(
        'span',
        {
          class: ['bond-tag', row.tag_type],
          style: c ? { background: c.bg, color: c.text, border: `1px solid ${c.border}` } : {},
        },
        row.tag,
      )
    },
  },
]

// ---- 行详情（真实字段，替代原来的 message.info 假交互）----
const showDetail = ref(false)
const detailBond = ref<ConvertibleBond | null>(null)
const na = '—'
const detailRows = computed<Array<[string, string]>>(() => {
  const b = detailBond.value
  if (!b) return []
  const num = (v: number | null | undefined, suffix = '') => v === null || v === undefined ? na : `${v}${suffix}`
  return [
    ['代码 / 名称', `${b.code} · ${b.name}`],
    ['价格', num(b.price)],
    ['涨跌幅', num(b.change_pct, '%')],
    ['转股价值', num(b.conv_value)],
    ['转股溢价率', num(b.premium_pct, '%')],
    ['双低值', num(b.double_low_score)],
    ['到期税前收益', num(b.ytm, '%')],
    ['剩余年限', num(b.remaining_years, ' 年')],
    ['信用评级', b.rating || na],
    ['正股', b.stock_name ? `${b.stock_name}（${b.stock_code ?? na}）` : na],
    ['正股涨跌 / PB', `${num(b.stock_change_pct, '%')} / ${num(b.stock_pb)}`],
    ['剩余规模', num(b.remaining_size, ' 亿元')],
    ['换手率', num(b.turnover_rate, '%')],
    ['到期日', b.maturity_date ?? na],
    ['最后交易日', b.last_trade_date ?? na],
    ['转股起始日', b.conversion_start_date ?? na],
    ['转股期', b.is_in_conversion_period === null ? '未披露' : b.is_in_conversion_period ? '已进入' : '未进入'],
    ['强赎状态', b.redemption_status ?? na],
    ['强赎触发价 / 回售触发价', `${num(b.redemption_trigger_price)} / ${num(b.putback_trigger_price)}`],
    ['强赎进度', b.redemption_days !== null ? `${b.redemption_days}/${b.total_redemption_days ?? na} 天` : na],
    ['有成交', b.has_trade ? '是' : '否（待上市/停牌，价格可能为面值占位）'],
    ['转股套利结论', b.conversion_analysis?.feasibility_label ?? na],
    ['未披露项', b.conversion_analysis?.data_missing?.join('、') || na],
    ['数据源', b.data_source ?? na],
  ]
})

const rowProps = (row: ConvertibleBond) => ({
  style: 'cursor: pointer',
  onClick: () => {
    detailBond.value = row
    showDetail.value = true
  },
})

// ---- 战术信号 + 胜率扫描（共享逻辑见 useSignalScan；转债无成交额字段，
//      按"当前筛选结果"顺序取前 100 只——先用筛选缩小范围再扫描）----
const CB_SCAN_LIMIT = 100
const {
  selectedStrategyId, selectedParams, strategyOptions, strategyParams, loadStrategies,
  tacticalMap, tacticalLoading, tacticalLoaded, loadTactical,
  winrateMap, winrateLoading, winrateLoaded, winrateMeta, scanWinrate, statsOf,
} = useSignalScan(
  () => filteredBonds.value.map(b => b.code),
  { onError: msg => message.error(msg), notify: msg => message.success(msg), limit: CB_SCAN_LIMIT },
)

// 战术/胜率列（计算完成后追加到主表，列定义共享于 signalDisplay）
const tacticalAppendColumns = buildTacticalSignalColumns<ConvertibleBond>({
  titleWithHelp,
  getSignal: code => tacticalMap.value.get(code),
  symbolOf: row => row.code,
})
const winrateAppendColumns = buildWinrateColumns<ConvertibleBond>({
  titleWithHelp,
  statsOf,
  getScanItem: code => winrateMap.value.get(code),
  symbolOf: row => row.code,
})
const tableColumns = computed(() => {
  if (!tacticalLoaded.value) return columns
  return winrateLoaded.value
    ? [...columns, ...tacticalAppendColumns, ...winrateAppendColumns]
    : [...columns, ...tacticalAppendColumns]
})

// 所有排名/预警只基于「有真实成交」的存续债，且无源字段不参与排序
const topDoubleLow = computed(() =>
  [...activeBonds.value]
    .filter(b => b.double_low_score !== null)
    .sort((a, b) => (a.double_low_score ?? Infinity) - (b.double_low_score ?? Infinity))
    .slice(0, 5),
)

const topYtm = computed(() =>
  [...activeBonds.value]
    .filter(b => b.ytm !== null)
    .sort((a, b) => (b.ytm ?? -Infinity) - (a.ytm ?? -Infinity))
    .slice(0, 5),
)

/** 强赎风险：进度 ≥80% 或状态含「公告/满足」 */
function redemptionRiskPct(b: ConvertibleBond): number | null {
  if (b.redemption_days !== null && b.total_redemption_days) {
    return Math.round(b.redemption_days / b.total_redemption_days * 100)
  }
  const s = b.redemption_status ?? ''
  return (s.includes('公告') || s.includes('满足')) ? 100 : null
}
const redemptionWarnings = computed(() =>
  activeBonds.value
    .filter(b => redemptionRiskPct(b) !== null)
    .sort((a, b) => (redemptionRiskPct(b) ?? 0) - (redemptionRiskPct(a) ?? 0))
    .slice(0, 8),
)

// 高溢价风险：替代无数据源的「正股 Z-Score/质押率」预警
const highPremiumWarnings = computed(() =>
  [...activeBonds.value]
    .filter(b => b.premium_pct >= 50)
    .sort((a, b) => b.premium_pct - a.premium_pct)
    .slice(0, 8),
)

// 转股套利机会：负溢价且可行/有风险的标的，按可行性排序
const conversionOpportunities = computed(() =>
  activeBonds.value
    .filter(b => {
      const a = conversionMap.value.get(b.code)
      return a && a.isNegativePremium && (a.feasibility === 'feasible' || a.feasibility === 'risky')
    })
    .sort((a, b) => {
      const fa = conversionMap.value.get(a.code)!
      const fb = conversionMap.value.get(b.code)!
      return CONVERSION_ORDER[fa.feasibility] - CONVERSION_ORDER[fb.feasibility]
    }),
)
const pendingVerifyCount = computed(() =>
  activeBonds.value.filter(b => conversionMap.value.get(b.code)?.feasibility === 'unknown').length,
)

// 波动率套利信号：网关未提供 IV/HV，恒为空（面板明确标「数据源未接入」）
const volArbSignals = computed(() =>
  activeBonds.value
    .filter(b => {
      const v = volatilityMap.value.get(b.code)
      return v && (v.signal === 'undervalued' || v.signal === 'overvalued')
    })
    .sort((a, b) => {
      const va = volatilityMap.value.get(a.code)!
      const vb = volatilityMap.value.get(b.code)!
      return VOL_SIGNAL_ORDER[va.signal] - VOL_SIGNAL_ORDER[vb.signal]
    }),
)

function exportBonds() {
  const headers = [
    '转债名称', '代码', '价格', '涨跌幅%', '转股价值', '溢价率%', '双低值',
    'IV%', 'HV%', 'IV/HV信号',
    '转股套利收益%', '转股套利可行性', '阻碍因素', '未披露项',
    '到期税前收益%', '剩余年限', '评级', '强赎状态', '强赎进度',
    '强赎触发价', '回售触发价', '到期日', '最后交易日', '转股起始日',
    '正股名称', '正股代码', '正股涨跌%', '正股PB', '剩余规模', '换手率%',
    '有成交', '标签', '数据源',
  ]
  if (tacticalLoaded.value) {
    headers.push('MA20偏离度%', 'RSI14', '布林位置%', '当前信号')
  }
  if (winrateLoaded.value) {
    headers.push('触发次数', '5日胜率%', '10日胜率%', '20日胜率%', '赔率(10日)', '半凯利%(10日)', '凯利%(10日)',
      '样本内胜率%(10日)', '样本外胜率%(10日)', '分年度胜率%(10日)')
  }
  const rows = filteredBonds.value.map(b => {
    const v = volatilityMap.value.get(b.code)
    const a = conversionMap.value.get(b.code)
    const t = tacticalMap.value.get(b.code)
    const state = tacticalState(t)
    const base = [
      b.name, b.code, b.price.toFixed(3), b.change_pct ?? '', b.conv_value.toFixed(2),
      b.premium_pct, b.double_low_score ?? '',
      v?.iv ?? '', v?.hv ?? '', v?.signalLabel ?? '',
      a?.theoreticalYield ?? '', a?.feasibilityLabel ?? '', a?.blockers.join('; ') ?? '',
      a?.dataMissing.join('; ') ?? '',
      b.ytm ?? '', b.remaining_years ?? '', b.rating,
      b.redemption_status ?? '',
      b.redemption_days !== null ? `${b.redemption_days}/${b.total_redemption_days ?? ''}天` : '',
      b.redemption_trigger_price ?? '', b.putback_trigger_price ?? '',
      b.maturity_date ?? '', b.last_trade_date ?? '', b.conversion_start_date ?? '',
      b.stock_name ?? '', b.stock_code ?? '', b.stock_change_pct ?? '', b.stock_pb ?? '',
      b.remaining_size ?? '', b.turnover_rate ?? '',
      b.has_trade ? '是' : '否', b.tag, b.data_source ?? '',
    ]
    if (tacticalLoaded.value) {
      base.push(
        t && !t.error ? (t.bias_20 ?? '') : '',
        t && !t.error ? (t.rsi_14 ?? '') : '',
        t && !t.error ? (t.boll_pos ?? '') : '',
        state === 'oversold' ? '超卖·关注' : state === 'overbought' ? '超买·谨慎' : state === 'neutral' ? '中性' : '',
      )
    }
    if (winrateLoaded.value) {
      base.push(...winrateExportCells(winrateMap.value.get(b.code)))
    }
    return base
  })
  exportToCSV(`convertible_bonds_${new Date().toISOString().slice(0, 10)}`, headers, rows)
  message.success(`已导出 ${rows.length} 条可转债数据`)
}
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    skeleton
    :min-height="480"
    text="正在加载可转债数据..."
    @retry="refetch"
  >
    <SectionFallback v-if="gatewayEmpty" :gateway-empty="true" :min-height="480" @retry="refetch" />
    <div v-else-if="bonds" class="cb-page">
    <!-- Page Header -->
    <PageHeader title="可转债扫描器" subtitle="集思录全量存续转债 - 双低 / 折价 / 到期收益 / 强赎状态扫描" helpKey="convertibleBonds" :updated-at="meta?.updateTime" />
    <GlossaryPanel page-key="convertibleBonds" />
    <div class="source-note">
      数据源：登录态集思录存续转债（{{ bonds?.length ?? 0 }} 只，其中有成交 {{ tradedCount }} 只<span v-if="pendingCount">、待上市/无成交 {{ pendingCount }} 只</span>），条款来自强赎公告表。
      IV/HV、下修进度、Altman Z、质押率、ST 标记当前无上游源，统一显示「— / 未接入」，不以 0 或 false 代替。
      <span v-if="meta?.note">{{ meta.note }}</span>
    </div>

    <!-- Filter Bar + Market Stats -->
    <div class="top-row">
      <!-- Filter Panel -->
      <div class="filter-panel">
        <div class="filter-item wide">
          <span class="filter-label">价格区间</span>
          <div class="filter-inputs">
            <n-input v-model:value="filterPriceMin" placeholder="最低" size="small" clearable />
            <span class="filter-sep">—</span>
            <n-input v-model:value="filterPriceMax" placeholder="最高" size="small" clearable />
          </div>
        </div>
        <div class="filter-item wide">
          <span class="filter-label">溢价区间</span>
          <div class="filter-inputs">
            <n-input v-model:value="filterPremiumMin" placeholder="0%" size="small" clearable />
            <span class="filter-sep">—</span>
            <n-input v-model:value="filterPremiumMax" placeholder="100%" size="small" clearable />
          </div>
        </div>
        <div class="filter-item">
          <span class="filter-label">信用评级</span>
          <n-select v-model:value="filterRating" :options="ratingOptions" size="small" clearable />
        </div>
        <div class="filter-item action">
          <button class="filter-apply" @click="applyFilters">应用筛选</button>
        </div>
      </div>

      <!-- Market Stats -->
      <div class="market-stats">
        <div class="mstat">
          <span class="mstat-label">中位价格</span>
          <div class="mstat-row">
            <span class="mstat-value">{{ medianPrice.toFixed(2) }}</span>
          </div>
        </div>
        <div class="mstat-divider" />
        <div class="mstat">
          <span class="mstat-label">中位溢价</span>
          <div class="mstat-row">
            <span class="mstat-value">{{ medianPremium.toFixed(1) }}%</span>
          </div>
        </div>
        <div class="mstat-divider" />
        <div class="mstat">
          <span class="mstat-label">有成交存续债</span>
          <div class="mstat-row">
            <span class="mstat-value">{{ tradedCount }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Main CB Table -->
    <DataPanel title="可转债全景">
      <template #actions>
        <button class="icon-btn" @click="exportBonds" aria-label="导出CSV">
          <n-icon :component="DownloadOutline" size="16" />
        </button>
        <button class="icon-btn" @click="showAdvancedFilter = true" aria-label="更多筛选">
          <n-icon :component="FilterOutline" size="16" />
        </button>
      </template>
      <!-- 代码 / 名称搜索 -->
      <div class="search-bar">
        <n-input v-model:value="searchQuery" placeholder="搜索转债代码 / 名称" size="small" clearable style="width: 260px">
          <template #prefix><n-icon :component="SearchOutline" size="14" /></template>
        </n-input>
        <label class="traded-toggle">
          <input type="checkbox" v-model="onlyTraded" />
          仅看有成交
        </label>
        <span class="search-meta">
          当前 {{ filteredBonds.length }} 条<span v-if="searchQuery.trim()">（搜索「{{ searchQuery.trim() }}」）</span>
        </span>
      </div>
      <!-- Strategy Quick Filters -->
      <div class="strategy-bar">
        <span class="strategy-label">策略</span>
        <div class="strategy-buttons">
          <button
            v-for="s in strategies"
            :key="s.key"
            class="strategy-btn"
            :class="{ active: activeStrategyKey === s.key }"
            :title="s.desc"
            @click="selectStrategy(s.key)"
          >
            <n-icon :component="s.icon" size="14" />
            <span>{{ s.label }}</span>
          </button>
        </div>
        <div v-if="activeStrategy" class="strategy-hint">
          {{ activeStrategy.desc }} · 匹配 {{ filteredBonds.length }} 只
        </div>
      </div>
      <!-- 战术信号 + 胜率扫描工具栏（对当前筛选结果生效，最多前 100 只） -->
      <div class="tactical-toolbar">
        <n-select
          v-model="selectedStrategyId"
          :options="strategyOptions"
          size="small"
          placeholder="选择策略"
          style="width: 200px"
        />
        <div v-for="p in strategyParams" :key="p.key" class="param-field">
          <span class="param-label">{{ p.label }}</span>
          <n-input-number
            v-model="selectedParams[p.key]"
            size="small"
            style="width: 110px"
            :min="p.min"
            :max="p.max"
            :step="p.step ?? 1"
          />
        </div>
        <n-button size="small" :loading="tacticalLoading" @click="loadTactical">
          <template #icon><n-icon :component="FlashOutline" /></template>
          战术信号
        </n-button>
        <n-button size="small" type="primary" :loading="winrateLoading" :disabled="!tacticalLoaded" @click="scanWinrate">
          <template #icon><n-icon :component="StatsChartOutline" /></template>
          扫描胜率
        </n-button>
        <span v-if="winrateMeta" class="scan-meta">{{ winrateMeta }}</span>
      </div>
      <n-data-table
        :columns="tableColumns"
        :data="filteredBonds"
        :row-key="(row: any) => row.code"
        :bordered="false"
        :single-line="false"
        size="small"
        :row-props="rowProps"
        :pagination="pagination"
      />
      <div class="table-footer">
        <span class="footer-info">
          当前 {{ filteredBonds.length }} 只 / 存续 {{ bonds?.length ?? 0 }} 只（有成交 {{ tradedCount }} 只，按成交额降序）
        </span>
        <span class="footer-info">点击任意行查看详情</span>
      </div>
    </DataPanel>

    <!-- Bottom Rankings -->
    <div class="bottom-grid">
      <!-- 转股套利机会 (新增) -->
      <div class="rank-panel">
        <div class="rank-header arb">
          <h4>转股套利机会</h4>
        </div>
        <div class="rank-list">
          <div v-for="bond in conversionOpportunities" :key="bond.code" class="rank-item conv-item">
            <span class="rank-name">{{ bond.name }}</span>
            <span class="conv-tags">
              <span class="conv-yield-tag" :class="{ pos: (conversionMap.get(bond.code)?.theoreticalYield ?? 0) > 0 }">
                {{ (conversionMap.get(bond.code)?.theoreticalYield ?? 0) > 0 ? '+' : '' }}{{ conversionMap.get(bond.code)?.theoreticalYield }}%
              </span>
              <span class="conv-feas-tag" :class="conversionMap.get(bond.code)?.feasibility">
                {{ conversionMap.get(bond.code)?.feasibilityLabel }}
              </span>
            </span>
          </div>
          <div v-if="conversionOpportunities.length === 0" class="empty-hint">暂无已确认的转股套利机会</div>
          <div v-if="pendingVerifyCount" class="empty-hint">另有 {{ pendingVerifyCount }} 只负溢价债「信息不全」，未计入机会</div>
        </div>
      </div>

      <!-- 波动率套利信号 (新增) -->
      <div class="rank-panel">
        <div class="rank-header vol">
          <h4>波动率套利信号</h4>
        </div>
        <div class="rank-list">
          <div v-for="bond in volArbSignals" :key="bond.code" class="rank-item vol-item">
            <span class="rank-name" :title="volatilityMap.get(bond.code)?.suggestion">{{ bond.name }}</span>
            <span class="vol-tags">
              <span class="vol-iv">IV{{ volatilityMap.get(bond.code)?.iv }}%</span>
              <span class="vol-hv">HV{{ volatilityMap.get(bond.code)?.hv }}%</span>
              <span class="vol-signal-tag" :class="volatilityMap.get(bond.code)?.signal">
                {{ volatilityMap.get(bond.code)?.signalLabel }}
              </span>
            </span>
          </div>
          <div v-if="volArbSignals.length === 0" class="empty-hint">IV / HV 数据源未接入，不生成波动率套利信号</div>
        </div>
      </div>

      <!-- Top Double Low -->
      <div class="rank-panel">
        <div class="rank-header">
          <h4>双低排名</h4>
        </div>
        <div class="rank-list">
          <div v-for="(bond, i) in topDoubleLow" :key="bond.code" class="rank-item">
            <span class="rank-num">{{ i + 1 }}.</span>
            <span class="rank-name">{{ bond.name }}</span>
            <span class="rank-score">{{ bond.double_low_score }}分</span>
          </div>
          <div v-if="topDoubleLow.length === 0" class="empty-hint">当前数据源未提供双低值</div>
        </div>
      </div>

      <!-- Top YTM -->
      <div class="rank-panel">
        <div class="rank-header">
          <h4>高收益排名</h4>
        </div>
        <div class="rank-list">
          <div v-for="(bond, i) in topYtm" :key="bond.code" class="rank-item">
            <span class="rank-num">{{ i + 1 }}.</span>
            <span class="rank-name">{{ bond.name }}</span>
            <span class="rank-score" style="color: var(--color-success)">{{ bond.ytm }}%</span>
          </div>
          <div v-if="topYtm.length === 0" class="empty-hint">当前数据源未提供真实到期收益</div>
        </div>
      </div>

      <!-- Redemption Warnings -->
      <div class="rank-panel">
        <div class="rank-header danger">
          <h4>强赎风险预警</h4>
        </div>
        <div class="rank-list">
          <div v-for="bond in redemptionWarnings" :key="bond.code" class="rank-item">
            <n-icon :component="WarningOutline" size="14" class="warn-icon" />
            <span class="rank-name" :title="bond.redemption_status ?? ''">
              {{ bond.name }}
              <span class="stock-sub">{{ bond.redemption_status ?? '' }}</span>
            </span>
            <span class="rank-score" style="color: var(--color-danger); font-size: 11px;">{{ redemptionRiskPct(bond) }}%</span>
          </div>
          <div v-if="redemptionWarnings.length === 0" class="empty-hint">暂无强赎公告 / 进度预警</div>
        </div>
      </div>

      <!-- 高溢价风险（替代无数据源的 Z-Score/质押率预警） -->
      <div class="rank-panel">
        <div class="rank-header danger">
          <h4>高溢价风险</h4>
        </div>
        <div class="rank-list">
          <div v-for="bond in highPremiumWarnings" :key="bond.code" class="rank-item">
            <span class="rank-name" :title="bond.stock_name ?? ''">{{ bond.name }}</span>
            <span class="rank-score" style="color: var(--color-danger); font-size: 12px;">{{ bond.premium_pct }}%</span>
          </div>
          <div v-if="highPremiumWarnings.length === 0" class="empty-hint">无溢价率 ≥ 50% 的存续债</div>
          <div class="empty-hint muted">正股 Z-Score / 质押率 / ST 数据源未接入</div>
        </div>
      </div>
    </div>
    </div>

    <!-- 高级筛选弹窗 (更多筛选) -->
    <n-modal v-model:show="showAdvancedFilter" preset="card" title="高级筛选" style="width: 480px; max-width: 92vw;" :bordered="false">
      <div class="adv-filter-body">
        <div class="adv-field">
          <label class="adv-label">到期收益率 (YTM) ≥</label>
          <n-input v-model:value="filterYtmMin" placeholder="例如 -2" size="small">
            <template #suffix>%</template>
          </n-input>
        </div>
        <div class="adv-field">
          <label class="adv-label">剩余年限 ≤</label>
          <n-input v-model:value="filterYearsMax" placeholder="例如 3" size="small">
            <template #suffix>年</template>
          </n-input>
        </div>
        <div class="adv-field">
          <label class="adv-label">双低值 ≤</label>
          <n-input v-model:value="filterDoubleLowMax" placeholder="例如 150" size="small" />
        </div>
        <div class="adv-field">
          <label class="adv-label">正股 PB ≤</label>
          <n-input v-model:value="filterPbMax" placeholder="例如 3" size="small" />
          <span class="adv-tip">Z-Score / 质押率无上游源，已移除该筛选；无 PB 数据的转债不会被此条件误纳入。</span>
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: space-between; gap: 8px;">
          <n-button size="small" @click="resetAdvancedFilters">重置</n-button>
          <div style="display: flex; gap: 8px;">
            <n-button size="small" @click="showAdvancedFilter = false">取消</n-button>
            <n-button size="small" type="primary" @click="() => { applyFilters(); showAdvancedFilter = false }">应用</n-button>
          </div>
        </div>
      </template>
    </n-modal>

    <!-- 行详情：展示后端真实字段，无源项明确标 — / 未披露 -->
    <n-modal v-model:show="showDetail" preset="card" :title="`${detailBond?.name ?? ''} · ${detailBond?.code ?? ''}`" style="width: 640px; max-width: 94vw;" :bordered="false">
      <div class="detail-grid">
        <div v-for="([label, value]) in detailRows" :key="label" class="detail-item">
          <span class="detail-label">{{ label }}</span>
          <span class="detail-value">{{ value }}</span>
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end;">
          <n-button size="small" @click="showDetail = false">关闭</n-button>
        </div>
      </template>
    </n-modal>
  </LoadingState>
</template>

<!-- Non-scoped styles for h()-rendered elements -->
<style>
.cb-name {
  font-family: 'Work Sans', sans-serif;
  font-weight: 600;
  color: var(--text-primary);
}

.rating-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 2px;
  font-family: 'Work Sans', sans-serif;
  font-size: 10px;
  font-weight: 700;
  border: 1px solid transparent;
}
.rating-tag.AAA { background: #dcfce7; color: #166534; border-color: rgba(22,101,52,0.2); }
.rating-tag.AA { background: #fef9c3; color: #854d0e; border-color: rgba(133,77,14,0.2); }

.redemption-cell { display: flex; flex-direction: column; gap: 2px; align-items: flex-start; }
.redemption-track { width: 100%; height: 4px; background: var(--border-default); border-radius: 2px; overflow: hidden; }
.redemption-fill { height: 100%; border-radius: 2px; transition: width 0.3s ease; background: var(--color-primary); }
.redemption-fill.warn { background: var(--color-warning); }
.redemption-fill.danger { background: var(--color-danger); }
.redemption-text { font-size: 9px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }

/* 正股风险 cell (table) */
.risk-cell { display: flex; flex-direction: column; gap: 2px; align-items: center; position: relative; }
.risk-row { display: flex; align-items: center; gap: 4px; font-size: 11px; font-family: 'JetBrains Mono', monospace; }
.risk-label { font-size: 9px; color: var(--text-muted); font-weight: 700; letter-spacing: 0.02em; }
.st-flag {
  position: absolute; top: -2px; right: -8px;
  background: var(--color-danger); color: #fff;
  font-size: 8px; font-weight: 700; padding: 1px 4px; border-radius: 2px;
}

.bond-tag { display: inline-block; padding: 2px 8px; border-radius: 2px; font-size: 10px; font-weight: 700; white-space: nowrap; }

/* IV/HV 波动率 cell (table, h()-rendered) */
.vol-cell { display: flex; flex-direction: column; gap: 2px; align-items: center; }
.vol-numbers { display: flex; align-items: baseline; gap: 3px; font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.vol-signal {
  display: inline-block; padding: 1px 6px; border-radius: 2px;
  font-size: 9px; font-weight: 700; letter-spacing: 0.02em; margin-top: 1px;
}
.vol-signal.undervalued { background: var(--tag-green-bg); color: var(--tag-green-text); }
.vol-signal.overvalued { background: var(--tag-red-bg); color: var(--tag-red-text); }
.vol-signal.fair { background: var(--bg-subtle); color: var(--text-muted); }

/* 战术信号 + 胜率扫描工具栏（与 ETF 页一致） */
.tactical-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.param-field { display: inline-flex; align-items: center; gap: 4px; }
.param-label { font-size: 12px; color: var(--text-secondary); white-space: nowrap; }
.scan-meta { font-size: 11px; color: var(--text-muted); }

/* 转股套利 cell (table, h()-rendered) */
.conv-cell { display: flex; flex-direction: column; gap: 3px; align-items: center; }
.conv-yield { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700; }
.feas-badge {
  display: inline-block; padding: 1px 6px; border-radius: 2px;
  font-size: 9px; font-weight: 700; letter-spacing: 0.02em;
}
.conv-blocker {
  font-size: 9px; color: var(--color-danger); cursor: help;
  border-bottom: 1px dotted var(--color-danger);
}

/* 到期收益近似角标 (table, h()-rendered) */
.ytm-cell { display: inline-flex; align-items: baseline; gap: 4px; justify-content: flex-end; font-family: 'JetBrains Mono', monospace; }
.approx-badge {
  display: inline-block; padding: 0 4px; border-radius: 2px;
  font-size: 9px; font-weight: 700; letter-spacing: 0.02em;
  background: var(--tag-orange-bg, #fff3e0); color: var(--tag-orange-text, #b45309);
  font-family: 'Work Sans', sans-serif; cursor: help;
}

/* ---- 2026-11-06 换主源后的新增渲染类（非 scoped，兼容 h() 与 modal teleport）---- */
.cb-code { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-muted); }
.cb-name-cell { display: inline-flex; align-items: center; gap: 6px; }
.pending-tag {
  display: inline-block; padding: 0 4px; border-radius: 2px; font-size: 9px;
  background: var(--tag-orange-bg); color: var(--tag-orange-text); white-space: nowrap;
}
.na-text { color: var(--text-muted); font-size: 11px; }
.cb-status { font-size: 10px; font-weight: 600; white-space: nowrap; cursor: help; }
.cb-stock-cell { display: flex; flex-direction: column; align-items: center; gap: 1px; }
.cb-stock-name { font-size: 11px; color: var(--text-primary); white-space: nowrap; }
.conv-blocker.muted { color: var(--text-muted); border-bottom-color: var(--text-muted); }
.empty-hint.muted { font-size: 10px; padding: 4px 0; opacity: 0.75; }
.adv-tip { font-size: 10px; color: var(--text-muted); line-height: 1.5; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 18px; }
.detail-item { display: flex; justify-content: space-between; gap: 12px; padding: 5px 0; border-bottom: 1px dashed var(--border-default); min-width: 0; }
.detail-label { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
.detail-value { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-primary); text-align: right; word-break: break-all; }
@media (max-width: 640px) { .detail-grid { grid-template-columns: 1fr; } }
</style>

<style scoped>
.cb-page { display: flex; flex-direction: column; gap: 14px; }

.source-note {
  font-size: 11px; line-height: 1.6; color: var(--text-muted);
  background: var(--bg-subtle); border: 1px solid var(--border-default);
  border-radius: 6px; padding: 8px 12px;
}
.search-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
.traded-toggle { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-secondary); cursor: pointer; }
.search-meta { font-size: 11px; color: var(--text-muted); margin-left: auto; }

/* Strategy quick filter bar */
.strategy-bar { display: flex; align-items: center; gap: 12px; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 10px; padding: 10px 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); flex-wrap: wrap; }
.strategy-label { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); flex-shrink: 0; }
.strategy-buttons { display: flex; gap: 8px; flex-wrap: wrap; }
.strategy-btn { display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-card); color: var(--text-secondary); font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; cursor: pointer; transition: all 0.15s; }
.strategy-btn:hover { background: var(--bg-hover); border-color: var(--color-primary); color: var(--color-primary); }
.strategy-btn.active { background: var(--color-primary); border-color: var(--color-primary); color: var(--bg-card); }
.strategy-btn.active:hover { opacity: 0.9; }
.strategy-hint { font-size: 12px; color: var(--text-muted); margin-left: auto; white-space: nowrap; }

/* 高级筛选弹窗 */
.adv-filter-body { display: flex; flex-direction: column; gap: 12px; }
.adv-field { display: flex; flex-direction: column; gap: 4px; }
.adv-label { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); }

/* Top Row */
.top-row { display: grid; grid-template-columns: 2fr 1.5fr; gap: 14px; }

.filter-panel {
  background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 10px;
  padding: 12px 18px; display: flex; gap: 16px; align-items: flex-end;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

/* Responsive: collapse filter + grid on smaller screens */
@media (max-width: 1024px) {
  .top-row { grid-template-columns: 1fr; }
  .bottom-grid { grid-template-columns: repeat(2, 1fr); }
  .filter-panel { flex-wrap: wrap; gap: 12px; }
  .filter-item.wide { flex: 1 1 100%; }
}

@media (max-width: 768px) {
  .bottom-grid { grid-template-columns: 1fr; }
  .filter-panel { flex-direction: column; align-items: stretch; }
  .filter-item.action { align-self: stretch; }
  .filter-apply { width: 100%; }
}

.filter-item { 
  flex: 0 0 auto; 
  display: flex; 
  flex-direction: column; 
  gap: 4px; 
  min-width: 0;
}
.filter-item.wide { flex: 1 1 180px; }
.filter-item.action { 
  display: flex; 
  flex-direction: column; 
  justify-content: flex-end;
}
.filter-label { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 2px; }

.filter-inputs { display: flex; align-items: center; gap: 6px; }
.filter-inputs .n-input { flex: 1; }
.filter-sep { color: var(--text-muted); font-size: 13px; flex-shrink: 0; }

.filter-apply {
  height: 28px; padding: 0 16px; background: var(--color-primary); color: var(--bg-card);
  border: none; border-radius: 4px; font-family: 'Work Sans', sans-serif;
  font-size: 12px; font-weight: 700; letter-spacing: 0.05em; cursor: pointer;
  transition: opacity 0.15s, box-shadow 0.15s;
  white-space: nowrap;
}
.filter-apply:hover { opacity: 0.9; box-shadow: 0 1px 4px rgba(0,94,161,0.3); }
.filter-apply:active { opacity: 0.8; }

.market-stats {
  background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 10px;
  display: flex; align-items: center; gap: 0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.mstat-divider {
  width: 1px; height: 48px; background: var(--border-default); flex-shrink: 0;
}

.mstat {
  flex: 1; display: flex; flex-direction: column; gap: 4px;
  padding: 16px 20px; min-height: 80px;
  justify-content: center;
}

.mstat-label { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); }
.mstat-row { display: flex; align-items: center; gap: 8px; }
.mstat-value { font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 600; color: var(--text-primary); line-height: 1.2; }
.mstat-chg { font-size: 13px; font-weight: 700; }
.mstat-chg.pos { color: var(--color-success); }
.mstat-chg.neg { color: var(--color-danger); }

.table-footer {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 16px; border-top: 1px solid var(--border-default); background: var(--bg-card);
}

.footer-info { font-size: 13px; color: var(--text-muted); }

/* Bottom Rankings：6 个面板按 3×2 排列，不再用固定 200px 压扁第二行 */
.bottom-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.rank-panel { min-height: 170px; max-height: 240px; }

.rank-panel { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }

.rank-header {
  padding: 8px 12px; border-bottom: 1px solid var(--border-default); background: var(--bg-subtle);
}
.rank-header.danger { background: var(--tag-red-bg); }
.rank-header h4 { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-brand); margin: 0; }
.rank-header.danger h4 { color: var(--color-danger); }

.rank-list { flex: 1; padding: 8px 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.rank-item { display: flex; align-items: center; gap: 8px; font-size: 14px; transition: background 0.15s; padding: 2px 4px; border-radius: 4px; }
.rank-item:hover { background: var(--bg-hover); }
.rank-num { color: var(--text-muted); font-weight: 600; min-width: 20px; }
.rank-name { flex: 1; color: var(--text-primary); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rank-score { font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 600; color: var(--color-primary); }
.warn-icon { color: var(--color-danger); }

.empty-hint { font-size: 12px; color: var(--text-muted); text-align: center; padding: 12px 0; font-style: italic; }

/* 正股风险预警 list item */
.stock-risk-item { flex-wrap: wrap; }
.stock-sub { font-size: 11px; color: var(--text-muted); font-weight: 400; margin-left: 2px; }
.risk-badges { display: flex; gap: 4px; flex-wrap: wrap; }
.risk-badge {
  display: inline-block; padding: 1px 6px; border-radius: 2px;
  font-family: 'JetBrains Mono', monospace; font-size: 9px; font-weight: 700;
  background: var(--tag-orange-bg); color: var(--tag-orange-text);
}
.risk-badge.danger { background: var(--tag-red-bg); color: var(--tag-red-text); }
.risk-badge.st { background: var(--color-danger); color: #fff; }

/* 转股套利机会排名面板 */
.rank-header.arb { background: var(--tag-green-bg); }
.rank-header.arb h4 { color: var(--tag-green-text); }
.rank-header.vol { background: var(--tag-blue-bg); }
.rank-header.vol h4 { color: var(--tag-blue-text); }

.conv-item { flex-wrap: wrap; }
.conv-tags { display: flex; gap: 4px; align-items: center; flex-shrink: 0; }
.conv-yield-tag {
  font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700;
  color: var(--color-danger);
}
.conv-yield-tag.pos { color: var(--color-success); }
.conv-feas-tag {
  display: inline-block; padding: 1px 6px; border-radius: 2px;
  font-size: 9px; font-weight: 700;
}
.conv-feas-tag.feasible { background: var(--tag-green-bg); color: var(--tag-green-text); }
.conv-feas-tag.risky { background: var(--tag-orange-bg); color: var(--tag-orange-text); }
.conv-feas-tag.infeasible { background: var(--tag-red-bg); color: var(--tag-red-text); }

/* 波动率套利信号排名面板 */
.vol-item { flex-wrap: wrap; }
.vol-tags { display: flex; gap: 4px; align-items: center; flex-shrink: 0; }
.vol-iv, .vol-hv {
  font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 600;
  color: var(--text-secondary);
}
.vol-signal-tag {
  display: inline-block; padding: 1px 6px; border-radius: 2px;
  font-size: 9px; font-weight: 700;
}
.vol-signal-tag.undervalued { background: var(--tag-green-bg); color: var(--tag-green-text); }
.vol-signal-tag.overvalued { background: var(--tag-red-bg); color: var(--tag-red-text); }
.vol-signal-tag.fair { background: var(--bg-subtle); color: var(--text-muted); }
</style>
