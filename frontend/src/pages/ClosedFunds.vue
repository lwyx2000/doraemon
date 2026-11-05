<script setup lang="ts">
defineOptions({ name: 'ClosedFunds' })
import { h, ref, computed, onMounted } from 'vue'
import { NButton, NDataTable, NIcon, NTag, NSelect, NInputNumber, useMessage } from 'naive-ui'
import type { PaginationProps } from 'naive-ui'
import { TimerOutline, WarningOutline, FlashOutline, StatsChartOutline } from '@vicons/ionicons5'
import { api, useAsyncData, isGatewayNoData } from '../composables/useApi'
import { useSignalScan } from '../composables/useSignalScan'
import {
  buildTacticalSignalColumns,
  buildWinrateColumns,
  tacticalStateOf as tacticalState,
  winrateExportCells,
} from '../utils/signalDisplay'
import type { FundItem } from '../types'
import { exportToCSV } from '../utils/export'
import { analyzeClosedFundBatch } from '../utils/closedFund'
import type { ClosedFundAnalysis } from '../utils/closedFund'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import DataPanel from '../components/DataPanel.vue'
import LoadingState from '../components/LoadingState.vue'
import SectionFallback from '../components/SectionFallback.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: funds, loading, error, meta, execute: refetch } = useAsyncData(() => api.getClosedFundAnalysis())
const gatewayEmpty = computed(() => isGatewayNoData(meta.value))

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

// 三维度分析映射 (code → ClosedFundAnalysis)；数值全部来自后端，前端只做展示适配
const analysisMap = computed(() => {
  if (!funds.value) return new Map<string, ClosedFundAnalysis>()
  return analyzeClosedFundBatch(funds.value)
})

// ---- 数据质量与口径工具 ----
// 无有效场内报价的行 premium_pct=0 只是占位，不是「平价成交」，必须排除所有统计
function isQuoted(f: FundItem): boolean {
  return f.quote_missing !== true
    && typeof f.premium_pct === 'number'
    && Number.isFinite(f.premium_pct)
    && (f.price ?? 0) > 0
}
const quotedFunds = computed(() => (funds.value ?? []).filter(isQuoted))
// 仅折价品种参与折价统计：溢价是风险，不是「折价套利机会」
const discountFunds = computed(() => quotedFunds.value.filter(f => f.premium_pct < 0))
function discountOf(f: FundItem): number {
  return f.discount_pct ?? Math.abs(f.premium_pct)
}
function fmtPct(v: number | null | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(2)}%` : '—'
}
function fmtValue(v: number | null | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${v}%` : '—'
}

// 页面加载时获取数据
onMounted(() => {
  refetch()
  loadStrategies()
})

// 按综合评分降序排序
const sortedFunds = computed(() => {
  if (!funds.value) return []
  return [...funds.value].sort((a, b) => {
    const sa = analysisMap.value.get(a.code)?.score ?? 0
    const sb = analysisMap.value.get(b.code)?.score ?? 0
    return sb - sa
  })
})

// 套利机会排名：只排折价品种（溢价不是套利机会），按综合评分降序取前 5
const arbitrageRanking = computed(() =>
  sortedFunds.value
    .filter(f => isQuoted(f) && f.premium_pct < 0)
    .slice(0, 5)
    .map(f => {
      const a = analysisMap.value.get(f.code)!
      return { name: f.name, score: a.score, convergenceYield: a.convergenceYield }
    }),
)

// 风险预警：只列真实风险；「信息未披露」属数据覆盖问题，不算风险结论
const DATA_GAP_KEYWORDS = ['未披露', '缺少后端分析字段']
const riskWarnings = computed(() =>
  sortedFunds.value
    .map(f => {
      const a = analysisMap.value.get(f.code)
      if (!a) return null
      const real = a.warnings.filter(w => !DATA_GAP_KEYWORDS.some(k => w.includes(k)))
      if (!real.length) return null
      return { name: f.name, count: real.length, first: real[0] }
    })
    .filter((x): x is { name: string; count: number; first: string } => x !== null),
)

// 收敛收益率排名：无折价 / 无期限 / 期限<30天（年化失真）的不参与
const convergenceYieldRanking = computed(() =>
  sortedFunds.value
    .map(f => ({ name: f.name, yield: analysisMap.value.get(f.code)?.convergenceYield ?? null }))
    .filter((x): x is { name: string; yield: number } => x.yield !== null)
    .sort((a, b) => b.yield - a.yield)
    .slice(0, 5),
)

// 颜色映射 — 流动性
const liquidityColorMap: Record<string, string> = {
  illiquid: 'var(--tag-red-text)',
  moderate: 'var(--tag-orange-text)',
  ample: 'var(--tag-green-text)',
}
const liquidityBgMap: Record<string, string> = {
  illiquid: 'var(--tag-red-bg)',
  moderate: 'var(--tag-orange-bg)',
  ample: 'var(--tag-green-bg)',
}
// 颜色映射 — 收敛确定性 (NTag type)；unknown=无报价，属数据缺失而非风险
const convergenceTypeMap: Record<string, 'success' | 'warning' | 'error' | 'default'> = {
  certain: 'success',
  likely: 'warning',
  uncertain: 'warning',
  unknown: 'default',
}
// 颜色映射 — 信用风险；unknown=未披露，用中性色，不能刷成红色高风险
const creditColorMap: Record<string, string> = {
  safe: 'var(--tag-green-text)',
  watch: 'var(--tag-orange-text)',
  risky: 'var(--tag-red-text)',
  unknown: 'var(--text-muted)',
}
const creditBgMap: Record<string, string> = {
  safe: 'var(--tag-green-bg)',
  watch: 'var(--tag-orange-bg)',
  risky: 'var(--tag-red-bg)',
  unknown: 'var(--bg-subtle)',
}

function scoreColor(score: number): string {
  if (score >= 70) return 'var(--color-success)'
  if (score >= 40) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

// 折价率 · 剩余期限分布（真实横截面，替代原写死的「折价收敛趋势」假柱状图）
// 后端只提供当日截面，没有逐日折价历史；这里按后端补算的 term_days 分组展示
// 折价品种的平均折价，用于观察「越临近到期折价是否越浅」，属横截面而非时间序列。
interface DiscountBucket {
  label: string
  count: number
  avgDiscount: number
  height: number
}
const DISCOUNT_BUCKETS = [
  { label: '<3月', min: 0, max: 90 },
  { label: '3-6月', min: 90, max: 180 },
  { label: '6-12月', min: 180, max: 365 },
  { label: '1-2年', min: 365, max: 730 },
  { label: '>2年', min: 730, max: Infinity },
]
const discountByMaturity = computed<DiscountBucket[]>(() => {
  // 仅折价品种 + 有可靠剩余天数；后端缺 remaining_term 时已用 maturity 补算，
  // 仍无期限则不计入（不再默认 365 天制造假样本），溢价品种不参与「折价」统计。
  const list = discountFunds.value.filter(
    f => typeof f.term_days === 'number' && f.term_days > 0,
  )
  const buckets = DISCOUNT_BUCKETS.map(b => {
    const items = list.filter(f => {
      const d = f.term_days!
      return d >= b.min && d < b.max
    })
    const avg = items.length
      ? items.reduce((s, f) => s + discountOf(f), 0) / items.length
      : 0
    return { label: b.label, count: items.length, avgDiscount: avg, height: 0 }
  })
  const max = Math.max(...buckets.map(b => b.avgDiscount), 0.0001)
  return buckets.map(b => ({
    ...b,
    height: b.count ? Math.max(8, Math.round((b.avgDiscount / max) * 100)) : 0,
  }))
})
const discountCovered = computed(() => discountByMaturity.value.reduce((s, b) => s + b.count, 0))
const maxDiscountBucketLabel = computed(() => {
  const valid = discountByMaturity.value.filter(b => b.count > 0)
  return valid.length ? valid.reduce((a, b) => (b.avgDiscount > a.avgDiscount ? b : a)).label : ''
})

function exportFunds() {
  if (!funds.value) return
  const headers = [
    '基金名称', '代码', '剩余期限', '剩余天数', '溢折价率(%)', '折价率(%)',
    '年化收益(%)', '预估到期收益(%)', '到期日', '成交额(元)',
    '流动性', '收敛路径', '年化收敛收益率(%)', '信用评级', '底层类型', '综合评分', '风险提示',
  ]
  if (tacticalLoaded.value) {
    headers.push('MA20偏离度%', 'RSI14', '布林位置%', '当前信号')
  }
  if (winrateLoaded.value) {
    headers.push('触发次数', '5日胜率%', '10日胜率%', '20日胜率%', '赔率(10日)', '半凯利%(10日)', '凯利%(10日)',
      '样本内胜率%(10日)', '样本外胜率%(10日)', '分年度胜率%(10日)')
  }
  const rows = funds.value.map(f => {
    const a = analysisMap.value.get(f.code)
    const t = tacticalMap.value.get(f.code)
    const state = tacticalState(t)
    const base = [
      f.name, f.code, f.remaining_term ?? '', f.term_days ?? '',
      isQuoted(f) ? f.premium_pct : '无报价', a?.discountPct ?? '',
      f.annualized ?? '', f.est_ytm ?? '', f.maturity ?? '', f.volume ?? '',
      a?.liquidityLabel ?? '', a?.convergenceLabel ?? '', a?.convergenceYield ?? '',
      a?.creditRating ?? '', a?.underlyingType ?? '', a?.score ?? '',
      a?.warnings.join('; ') ?? '',
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
      base.push(...winrateExportCells(winrateMap.value.get(f.code)))
    }
    return base
  })
  exportToCSV(`closed_funds_${new Date().toISOString().slice(0, 10)}`, headers, rows)
  message.success(`已导出 ${rows.length} 条封闭基金数据`)
}

// 统计卡片：排除无报价行；折价口径只取 premium_pct < 0，绝不把溢价用 abs() 折进来
const summaryStats = computed(() => {
  const list = funds.value ?? []
  const quoted = list.filter(isQuoted)
  const discounts = quoted.filter(f => f.premium_pct < 0).map(f => discountOf(f))
  const avgDiscount = discounts.length
    ? discounts.reduce((a, b) => a + b, 0) / discounts.length
    : null
  const maxDiscount = discounts.length ? Math.max(...discounts) : null
  // 年化收益源当前全部为 null：无样本显示 —，不能把 null 当 0 混入均值
  const annualizedValues = list
    .map(f => f.annualized)
    .filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
  const avgAnnualized = annualizedValues.length
    ? annualizedValues.reduce((a, b) => a + b, 0) / annualizedValues.length
    : null
  const opportunityCount = discounts.filter(v => v > 5).length
  const totalVolume = list.reduce((s, f) => s + (f.volume ?? 0), 0) / 10000 // 万元
  return {
    avgDiscountStr: fmtPct(avgDiscount),
    avgAnnualizedStr: fmtPct(avgAnnualized),
    maxDiscountStr: fmtPct(maxDiscount),
    opportunityCount,
    totalVolume,
    quotedCount: quoted.length,
    discountCount: discounts.length,
    premiumCount: quoted.filter(f => f.premium_pct > 0).length,
    noQuoteCount: list.length - quoted.length,
    undisclosedPath: list.filter(f => f.is_lof_convertible == null).length,
  }
})

// ---- 战术信号 + 胜率扫描（共享逻辑见 useSignalScan；对综合评分排序后的列表生效，最多前 100 只）----
const CLOSED_SCAN_LIMIT = 100
const {
  selectedStrategyId, selectedParams, strategyOptions, strategyParams, loadStrategies,
  tacticalMap, tacticalLoading, tacticalLoaded, loadTactical,
  winrateMap, winrateLoading, winrateLoaded, winrateMeta, scanWinrate, statsOf,
} = useSignalScan(
  () => sortedFunds.value.map(f => f.code),
  { onError: msg => message.error(msg), notify: msg => message.success(msg), limit: CLOSED_SCAN_LIMIT },
)

// 战术/胜率列（计算完成后追加到主表，列定义共享于 signalDisplay）
const tacticalAppendColumns = buildTacticalSignalColumns<FundItem>({
  titleWithHelp,
  getSignal: code => tacticalMap.value.get(code),
  symbolOf: row => row.code,
})
const winrateAppendColumns = buildWinrateColumns<FundItem>({
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

const columns = [
  {
    title: '基金名称',
    key: 'name',
    render: (row: FundItem) => h('span', { class: 'fund-name' }, row.name),
  },
  {
    title: '剩余期限',
    key: 'remaining_term',
    align: 'right' as const,
    render: (row: FundItem) => row.remaining_term ?? '—',
  },
  {
    title: titleWithHelp('溢折价率', 'discount_pct'),
    key: 'premium_pct',
    align: 'right' as const,
    sorter: (a: FundItem, b: FundItem) => a.premium_pct - b.premium_pct,
    render: (row: FundItem) => {
      // 无场内报价的行没有溢折价率，0 是占位而非「平价成交」
      if (!isQuoted(row)) return h('span', { class: 'sub-info' }, '无报价')
      const v = row.premium_pct
      // 折价（负）= 机会色；溢价（正）= 风险色（红）
      const color = v < -15
        ? 'var(--color-success)'
        : v < 0
          ? 'var(--color-primary)'
          : 'var(--color-danger)'
      return h('span', { style: { color, fontWeight: v < -15 ? 700 : 400 } }, `${v > 0 ? '+' : ''}${v}%`)
    },
  },
  {
    title: '净值',
    key: 'nav',
    align: 'right' as const,
    render: (row: FundItem) => row.nav != null
      ? h('div', {}, [
          h('span', { style: { fontFamily: 'JetBrains Mono, monospace' } }, row.nav!.toFixed(4)),
          h('span', { class: 'sub-info' }, row.nav_date ?? ''),
        ])
      : '',
  },
  {
    title: '年化收益',
    key: 'annualized',
    align: 'right' as const,
    render: (row: FundItem) => fmtValue(row.annualized),
  },
  {
    title: '预估到期收益',
    key: 'est_ytm',
    align: 'right' as const,
    render: (row: FundItem) =>
      h('span', { style: { color: 'var(--color-primary)', fontWeight: 700 } }, fmtValue(row.est_ytm)),
  },
  {
    title: '到期日',
    key: 'maturity',
    render: (row: FundItem) => {
      // 用后端补算好的剩余天数判断临近到期；无期限不做 365 天假设
      const remainingDays = row.term_days
      if (remainingDays != null && remainingDays < 60 && row.maturity) {
        return h('span', { class: 'maturity-warning' }, [
          h(NIcon, { component: TimerOutline, size: 14 }),
          row.maturity,
        ])
      }
      return row.maturity ?? '—'
    },
  },
  {
    title: titleWithHelp('流动性', 'liquidity'),
    key: 'liquidity',
    align: 'center' as const,
    render: (row: FundItem) => {
      const a = analysisMap.value.get(row.code)
      if (!a) return ''
      return h('div', { class: 'liquidity-cell' }, [
        h('span', {
          class: 'level-tag',
          style: {
            color: liquidityColorMap[a.liquidity],
            background: liquidityBgMap[a.liquidity],
          },
        }, a.liquidityLabel),
        h('span', { class: 'sub-info' }, `${a.volumeWan.toFixed(1)}万元`),
      ])
    },
  },
  {
    title: titleWithHelp('收敛路径', 'convergence'),
    key: 'convergence',
    align: 'center' as const,
    render: (row: FundItem) => {
      const a = analysisMap.value.get(row.code)
      if (!a) return ''
      const children = [
        h(NTag, {
          size: 'small',
          type: convergenceTypeMap[a.convergence],
          bordered: false,
        }, { default: () => a.convergenceLabel }),
        // 无折价 / 无期限 / 期限<30天时后端给 null，显示 — 而不是 0%
        h('span', { class: 'sub-info' }, a.convergenceYield == null
          ? '年化 —'
          : `年化${a.convergenceYield}%`),
      ]
      // is_lof_convertible 为 null 表示数据源未披露，不能当成 false 后随便打标签
      if (a.isLofConvertible === true) {
        children.push(h(NTag, {
          size: 'small',
          bordered: false,
          class: 'lof-tag',
        }, { default: () => '转LOF' }))
      }
      return h('div', { class: 'convergence-cell' }, children)
    },
  },
  {
    title: titleWithHelp('底层信用', 'credit_rating'),
    key: 'credit',
    align: 'center' as const,
    render: (row: FundItem) => {
      const a = analysisMap.value.get(row.code)
      if (!a) return ''
      return h('div', { class: 'credit-cell' }, [
        h('span', {
          class: 'level-tag',
          style: {
            color: creditColorMap[a.creditRisk],
            background: creditBgMap[a.creditRisk],
          },
        }, a.creditLabel),
        h('span', { class: 'sub-info' }, a.creditRisk === 'unknown'
          ? '评级未披露'
          : `${a.creditRating} · ${a.underlyingType}`),
      ])
    },
  },
  {
    title: '综合评分',
    key: 'score',
    align: 'center' as const,
    sorter: (a: FundItem, b: FundItem) =>
      (analysisMap.value.get(a.code)?.score ?? 0) - (analysisMap.value.get(b.code)?.score ?? 0),
    render: (row: FundItem) => {
      const a = analysisMap.value.get(row.code)
      if (!a) return ''
      const color = scoreColor(a.score)
      return h('div', { class: 'score-cell' }, [
        h('span', { class: 'score-value', style: { color } }, String(a.score)),
        h('div', { class: 'score-bar' }, [
          h('div', {
            class: 'score-bar-fill',
            style: { width: `${a.score}%`, background: color },
          }),
        ]),
      ])
    },
  },
  {
    // 折价深度：只按折价品种的折价幅度显示（10% 折价为满格），溢价不再被算成「收敛度」
    title: '折价深度',
    key: 'conv',
    align: 'right' as const,
    render: (row: FundItem) => {
      const d = analysisMap.value.get(row.code)?.discountPct ?? null
      return h('div', {
        class: 'conv-bar',
        title: d == null
          ? '非折价品种或无报价，不参与折价深度'
          : `折价 ${d.toFixed(2)}%，按 10% 折价为满格`,
      }, [
        h('div', {
          class: 'conv-fill',
          style: { width: `${d == null ? 0 : Math.min((d / 10) * 100, 100)}%` },
        }),
      ])
    },
  },
]
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    skeleton
    :min-height="520"
    text="正在加载封闭基金数据..."
    @retry="refetch"
  >
    <SectionFallback v-if="gatewayEmpty" :gateway-empty="true" :min-height="520" @retry="refetch" />
    <div v-else-if="funds" class="closed-page">
    <PageHeader title="封闭基金分析" subtitle="封闭基金折价率监控与到期套利分析" helpKey="closedFunds" :updated-at="meta?.updateTime">
      <template #actions>
        <n-button size="small" type="primary" @click="exportFunds">导出</n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="closedFunds" />

    <!-- 统计卡片（动态计算，口径见下方说明） -->
    <div class="stat-grid">
      <StatCard label="基金总数" :value="funds?.length ?? 0" :sub="`有效报价 ${summaryStats.quotedCount} 只`" />
      <StatCard label="平均折价" :value="summaryStats.avgDiscountStr" color="#864f00" :sub="`折价 ${summaryStats.discountCount} 只 · 最深 ${summaryStats.maxDiscountStr}`" tip="仅统计有有效报价且溢折价率为负的基金；溢价与无报价行不参与" />
      <StatCard label="平均年化" :value="summaryStats.avgAnnualizedStr" color="var(--color-primary)" sub="数据源暂未提供" tip="仅在数据源提供 annualized 时计算；无样本显示 —，不把 null 当 0 求均值" />
      <StatCard label="套利机会" :value="summaryStats.opportunityCount" color="var(--color-danger)" sub="折价 > 5%" tip="真实折价率超过 5% 的基金数量，溢价不算折价套利机会" />
      <StatCard label="总成交额" :value="`${summaryStats.totalVolume.toFixed(0)}万`" color="var(--color-success)" sub="元，展示为万元" tip="全部封闭基金场内成交额合计（元），不是成交量手数" />
    </div>
    <p class="data-note">
      {{ summaryStats.quotedCount }}/{{ funds?.length ?? 0 }} 只有效报价 · 折价 {{ summaryStats.discountCount }} 只 · 溢价 {{ summaryStats.premiumCount }} 只<span v-if="summaryStats.noQuoteCount"> · 无报价 {{ summaryStats.noQuoteCount }} 只已排除统计</span>；
      {{ summaryStats.undisclosedPath }} 只「到期是否转 LOF」及底层评级未披露，按中性处理、不等于高风险；
      年化收益 / IOPV / 净套利收益当前无上游数据源，统一显示 —；剩余期限缺失时由到期日补算，仍缺失则不年化。
    </p>

    <!-- Fund Table -->
    <DataPanel title="封闭基金监控列表" meta="数据源：封闭基金分析接口（集思录截面 + 腾讯场内价补全 · 当前截面）">
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
        :data="sortedFunds"
        :row-key="(row: any) => row.code"
        :bordered="false"
        :single-line="false"
        size="small"
        :pagination="pagination"
        :row-props="(row: any) => ({ onClick: () => message.info(row.name) })"
      />
    </DataPanel>

    <!-- Bottom Panels -->
    <div class="bottom-grid">
      <div class="bottom-panel">
        <h4>套利机会排名</h4>
        <div class="ranking-list">
          <div v-for="(item, idx) in arbitrageRanking" :key="item.name" class="ranking-item">
            <span class="rank-num" :class="{ top: idx < 3 }">{{ idx + 1 }}</span>
            <span class="rank-name">{{ item.name }}</span>
            <span class="rank-score">{{ item.score }}</span>
            <span class="rank-yield">{{ item.convergenceYield == null ? '年化 —' : '年化' + item.convergenceYield + '%' }}</span>
          </div>
          <div v-if="arbitrageRanking.length === 0" class="empty-hint">暂无数据</div>
        </div>
      </div>

      <div class="bottom-panel">
        <h4 class="warning-title">
          <n-icon :component="WarningOutline" size="14" />
          风险预警
        </h4>
        <div class="ranking-list">
          <div v-for="item in riskWarnings" :key="item.name" class="warning-item">
            <span class="rank-name">{{ item.name }}</span>
            <n-tag size="small" :bordered="false" type="error">{{ item.count }}项预警</n-tag>
            <span class="warn-text">{{ item.first }}</span>
          </div>
          <div v-if="riskWarnings.length === 0" class="empty-hint">暂无风险预警</div>
        </div>
      </div>

      <div class="bottom-panel">
        <h4>收敛收益率排名</h4>
        <div class="ranking-list">
          <div v-for="(item, idx) in convergenceYieldRanking" :key="item.name" class="ranking-item">
            <span class="rank-num" :class="{ top: idx < 3 }">{{ idx + 1 }}</span>
            <span class="rank-name">{{ item.name }}</span>
            <span class="rank-yield primary">{{ item.yield }}%</span>
          </div>
          <div v-if="convergenceYieldRanking.length === 0" class="empty-hint">暂无数据</div>
        </div>
      </div>

      <div class="bottom-panel">
        <h4>折价率 · 剩余期限分布（仅折价）</h4>
        <div v-if="discountCovered > 0" class="sparkline-bars">
          <div v-for="b in discountByMaturity" :key="b.label" class="bar-col">
            <div class="bar-track">
              <div
                class="spark-bar"
                :class="{ active: b.label === maxDiscountBucketLabel, empty: b.count === 0 }"
                :style="{ height: b.height + '%' }"
                :title="`${b.label}｜${b.count} 只｜平均折价 ${b.count ? b.avgDiscount.toFixed(2) + '%' : '无样本'}`"
              />
            </div>
            <span class="bar-value">{{ b.count ? b.avgDiscount.toFixed(1) + '%' : '—' }}</span>
            <span class="bar-label">{{ b.label }}</span>
          </div>
        </div>
        <div v-else class="empty-hint">暂无可用样本（需同时具备折价率与剩余期限）</div>
        <p class="panel-note">横截面：{{ discountCovered }} 只折价基金按剩余期限分组的平均折价率；溢价与无报价行不计入，非时间序列</p>
      </div>
    </div>
    </div>
  </LoadingState>
</template>

<!-- Non-scoped styles for h()-rendered table cells (VNodes need non-scoped styles) -->
<style>
.fund-name {
  font-family: 'Work Sans', sans-serif;
  font-weight: 600;
  color: var(--text-primary);
}

.maturity-warning {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--tag-red-bg);
  color: var(--tag-red-text);
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
}

.maturity-warning .n-icon { font-size: 14px; }

.conv-bar {
  width: 80px;
  height: 6px;
  background: var(--border-default);
  border-radius: 3px;
  overflow: hidden;
  margin-left: auto;
}

.conv-fill {
  height: 100%;
  background: var(--color-primary);
  border-radius: 3px;
  transition: width 0.3s;
}

/* ---- 流动性 / 信用 等级标签 ---- */
.level-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.4;
}

.sub-info {
  display: block;
  margin-top: 4px;
  font-size: 10px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.liquidity-cell,
.convergence-cell,
.credit-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

/* ---- 收敛路径 cell ---- */
.convergence-cell .n-tag {
  font-size: 11px;
}

.lof-tag {
  background: var(--bg-subtle) !important;
  color: var(--color-primary) !important;
  font-size: 10px !important;
}

/* ---- 综合评分 cell ---- */
.score-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  width: 60px;
}

.score-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  font-weight: 700;
  line-height: 1;
}

.score-bar {
  width: 100%;
  height: 4px;
  background: var(--border-default);
  border-radius: 2px;
  overflow: hidden;
}

.score-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}
</style>

<style scoped>
.closed-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.tactical-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.data-note {
  margin: -4px 0 0;
  padding: 8px 12px;
  border-left: 3px solid var(--color-primary);
  background: var(--bg-subtle);
  border-radius: 0 6px 6px 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.param-field { display: inline-flex; align-items: center; gap: 4px; }
.param-label { font-size: 12px; color: var(--text-secondary); white-space: nowrap; }
.scan-meta { font-size: 11px; color: var(--text-muted); }

/* Bottom Grid */
.bottom-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.bottom-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 18px;
  height: 200px;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-card);
}

.bottom-panel h4 {
  font-family: 'Work Sans', sans-serif;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin: 0 0 12px;
}

.warning-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--color-danger) !important;
}

.warning-title .n-icon { font-size: 14px; }

/* Ranking list (套利机会 / 收敛收益率) */
.ranking-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
}

.ranking-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.rank-num {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 4px;
  background: var(--bg-subtle);
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}

.rank-num.top {
  background: var(--color-primary);
  color: #fff;
}

.rank-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-weight: 600;
}

.rank-score {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-primary);
  flex-shrink: 0;
}

.rank-yield {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.rank-yield.primary {
  color: var(--color-success);
  font-weight: 700;
  font-size: 14px;
}

/* Warning items */
.warning-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
  border-bottom: 1px solid var(--border-default);
}

.warning-item:last-child { border-bottom: none; }

.warn-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-muted);
}

.empty-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  font-size: 13px;
  color: var(--text-muted);
}

.sparkline-bars {
  flex: 1;
  display: flex;
  align-items: flex-end;
  gap: 6px;
  padding: 4px 0;
}

.bar-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.bar-track {
  width: 100%;
  height: 72px;
  display: flex;
  align-items: flex-end;
}

.spark-bar {
  width: 100%;
  min-height: 2px;
  background: rgba(0, 94, 161, 0.3);
  border-radius: 3px 3px 0 0;
  transition: height 0.2s;
}

.spark-bar.empty { background: rgba(0, 94, 161, 0.08); }
.spark-bar.active { background: var(--color-primary); }
.spark-bar:hover { background: var(--color-primary-hover); }

.bar-value {
  font-family: 'JetBrains Mono, monospace';
  font-size: 10px;
  color: var(--text-primary);
}

.bar-label {
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}

.panel-note {
  margin: 6px 0 0;
  font-size: 10px;
  line-height: 1.4;
  color: var(--text-muted);
}

/* Responsive: collapse multi-column grids on smaller screens */
@media (max-width: 768px) {
  .bottom-grid { grid-template-columns: 1fr; }
}
</style>
