<script setup lang="ts">
defineOptions({ name: 'ConvertibleBonds' })
import { ref, computed, h, onMounted } from 'vue'
import { NDataTable, NInput, NSelect, NIcon, NModal, NButton, useMessage } from 'naive-ui'
import { DownloadOutline, FilterOutline, WarningOutline, SwapHorizontalOutline, StatsChartOutline, WalletOutline, ConstructOutline } from '@vicons/ionicons5'
import type { Component } from 'vue'
import { useAsyncData } from '../composables/useApi'
import { api } from '../utils/api'
import type { ConvertibleBond } from '../types'
import { exportToCSV } from '../utils/export'
import { analyzeConversionBatch, analyzeVolatilityBatch, CONVERSION_ORDER, VOL_SIGNAL_ORDER } from '../utils/convertibleBond'
import type { ConversionArbitrage, VolatilityAnalysis } from '../utils/convertibleBond'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import LoadingState from '../components/LoadingState.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: bonds, loading, error, refresh: refetch } = useAsyncData<ConvertibleBond[]>(() => api.getConvertibleBonds())
onMounted(refetch)

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
    desc: '转股溢价率为负，存在转股折价套利空间',
    filter: b => b.premium_pct < 0,
  },
  {
    key: 'double_low',
    label: '双低轮动',
    icon: StatsChartOutline,
    desc: '价格 ≤ 120 且溢价率 ≤ 30%，经典双低策略池',
    filter: b => b.price <= 120 && b.premium_pct <= 30,
  },
  {
    key: 'high_ytm',
    label: '到期高收益',
    icon: WalletOutline,
    desc: '到期收益率 ≥ 2%，偏债型防守策略',
    filter: b => b.ytm >= 2,
  },
  {
    key: 'revision_play',
    label: '下修博弈',
    icon: ConstructOutline,
    desc: '价格 ≤ 110、转股价值 ≤ 85 且下修进度 ≥ 50%',
    filter: b =>
      b.price <= 110 &&
      b.conv_value <= 85 &&
      (b.total_revision_days ?? 0) > 0 &&
      (b.revision_days ?? 0) / (b.total_revision_days ?? 1) >= 0.5,
  },
]

const activeStrategyKey = ref<string | null>(null)
const activeStrategy = computed(() => strategies.find(s => s.key === activeStrategyKey.value) ?? null)

function selectStrategy(key: string) {
  activeStrategyKey.value = activeStrategyKey.value === key ? null : key
}

const filterPriceMin = ref('')
const filterPriceMax = ref('')
const filterPremiumMin = ref('')
const filterPremiumMax = ref('')
const filterRating = ref('全部评级')
// 高级筛选 (更多筛选弹窗)
const showAdvancedFilter = ref(false)
const filterYtmMin = ref('')
const filterYearsMax = ref('')
const filterDoubleLowMax = ref('')
const filterZscoreMin = ref('')

const ratings = ['全部评级', 'AAA', 'AA+', 'AA']
const ratingOptions = ratings.map(r => ({ label: r, value: r }))

const filteredBonds = computed(() => {
  if (!bonds.value) return []
  return bonds.value.filter(b => {
    if (filterPriceMin.value && b.price < Number(filterPriceMin.value)) return false
    if (filterPriceMax.value && b.price > Number(filterPriceMax.value)) return false
    if (filterPremiumMin.value && b.premium_pct < Number(filterPremiumMin.value)) return false
    if (filterPremiumMax.value && b.premium_pct > Number(filterPremiumMax.value)) return false
    if (filterRating.value !== '全部评级' && b.rating !== filterRating.value) return false
    if (filterYtmMin.value && b.ytm < Number(filterYtmMin.value)) return false
    if (filterYearsMax.value && b.remaining_years > Number(filterYearsMax.value)) return false
    if (filterDoubleLowMax.value && (b.double_low_score ?? b.price + b.premium_pct) > Number(filterDoubleLowMax.value)) return false
    if (filterZscoreMin.value && (b.altman_z_score ?? 99) < Number(filterZscoreMin.value)) return false
    if (activeStrategyKey.value && !activeStrategy.value?.filter(b)) return false
    return true
  })
})

function applyFilters() {
  const total = bonds.value?.length ?? 0
  const matched = filteredBonds.value.length
  message.success(`筛选完成：${matched} / ${total} 只转债匹配`)
}

function resetAdvancedFilters() {
  filterYtmMin.value = ''
  filterYearsMax.value = ''
  filterDoubleLowMax.value = ''
  filterZscoreMin.value = ''
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
    title: '转债名称',
    key: 'name',
    render: (row: ConvertibleBond) => h('span', { class: 'cb-name' }, row.name),
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
    render: (row: ConvertibleBond) => h(
      'span',
      { style: { color: row.change_pct >= 0 ? 'var(--color-success)' : 'var(--color-danger)' } },
      `${row.change_pct >= 0 ? '+' : ''}${row.change_pct}%`,
    ),
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
      if (!v || v.iv === 0 || v.hv === 0) return h('span', { style: { color: 'var(--text-muted)' } }, '-')
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
        h('span', {
          class: ['vol-signal', v.signal],
          title: v.suggestion,
        }, v.signalLabel),
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
      return h('div', { class: 'conv-cell' }, children)
    },
  },
  {
    title: titleWithHelp('到期收益', 'ytm'),
    key: 'ytm',
    align: 'right' as const,
    render: (row: ConvertibleBond) => {
      const children: any[] = [
        h('span', { style: { color: row.ytm >= 0 ? 'var(--color-success)' : 'var(--color-danger)' } },
          `${row.ytm >= 0 ? '+' : ''}${row.ytm}%`),
      ]
      if (row.ytm_approx) {
        children.push(h('span', {
          class: 'approx-badge',
          title: '该到期收益率为本地近似估算，非集思录实时真实值',
        }, '近似'))
      }
      return h('span', { class: 'ytm-cell' }, children)
    },
  },
  {
    title: '剩余年限',
    key: 'remaining_years',
    align: 'center' as const,
    render: (row: ConvertibleBond) => `${row.remaining_years}Y`,
  },
  {
    title: '评级',
    key: 'rating',
    align: 'center' as const,
    render: (row: ConvertibleBond) => h('span', { class: ['rating-tag', row.rating] }, row.rating),
  },
  {
    title: titleWithHelp('强赎进度', 'redemption_days'),
    key: 'redemption',
    align: 'center' as const,
    render: (row: ConvertibleBond) => progressCell(row.redemption_days, row.total_redemption_days),
  },
  {
    title: titleWithHelp('回售进度', 'putback_days'),
    key: 'putback',
    align: 'center' as const,
    render: (row: ConvertibleBond) => progressCell(row.putback_days ?? 0, row.total_putback_days ?? 1),
  },
  {
    title: titleWithHelp('下修进度', 'revision_days'),
    key: 'revision',
    align: 'center' as const,
    render: (row: ConvertibleBond) => progressCell(row.revision_days ?? 0, row.total_revision_days ?? 1),
  },
  {
    title: '正股风险',
    key: 'stock_risk',
    align: 'center' as const,
    render: (row: ConvertibleBond) => {
      const z = row.altman_z_score ?? 0
      // Altman Z-Score: <1.81 危险区, 1.81-2.99 灰色区, >=3 安全区
      const zColor = z < 1.81 ? 'var(--color-danger)' : z < 2.99 ? 'var(--color-warning)' : 'var(--color-success)'
      const pledge = row.pledge_rate ?? 0
      const pledgeColor = pledge > 50 ? 'var(--color-danger)' : pledge > 30 ? 'var(--color-warning)' : 'var(--text-primary)'
      return h('div', { class: 'risk-cell' }, [
        h('div', { class: 'risk-row' }, [
          h('span', { class: 'risk-label' }, 'Z'),
          h('span', { style: { color: zColor, fontWeight: 700 } }, z.toFixed(2)),
        ]),
        h('div', { class: 'risk-row' }, [
          h('span', { class: 'risk-label' }, '押'),
          h('span', { style: { color: pledgeColor } }, `${pledge}%`),
        ]),
        row.is_st_risk
          ? h('span', { class: 'st-flag' }, 'ST')
          : null,
      ])
    },
  },
  {
    title: '标签',
    key: 'tag',
    render: (row: ConvertibleBond) => {
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

const rowProps = (row: ConvertibleBond) => ({
  style: 'cursor: pointer',
  onClick: () => message.info(row.name),
})

const topDoubleLow = computed(() =>
  bonds.value
    ? [...bonds.value]
        .filter(b => b.double_low_score)
        .sort((a, b) => (a.double_low_score || 0) - (b.double_low_score || 0))
        .slice(0, 5)
    : [],
)

const topYtm = computed(() =>
  bonds.value
    ? [...bonds.value].sort((a, b) => b.ytm - a.ytm).slice(0, 5)
    : [],
)

const redemptionWarnings = computed(() =>
  bonds.value
    ? bonds.value.filter(b => b.redemption_days / b.total_redemption_days >= 0.8)
    : [],
)

// 正股风险预警：Z-Score<2.99 或 质押率>50 或 ST
const stockRiskWarnings = computed(() =>
  bonds.value
    ? bonds.value.filter(b =>
        (b.altman_z_score ?? 99) < 2.99
        || (b.pledge_rate ?? 0) > 50
        || b.is_st_risk,
      )
    : [],
)

// 转股套利机会：负溢价且可行/有风险的标的，按可行性排序
const conversionOpportunities = computed(() => {
  if (!bonds.value) return []
  return bonds.value
    .filter(b => {
      const a = conversionMap.value.get(b.code)
      return a && a.isNegativePremium && (a.feasibility === 'feasible' || a.feasibility === 'risky')
    })
    .sort((a, b) => {
      const fa = conversionMap.value.get(a.code)!
      const fb = conversionMap.value.get(b.code)!
      return CONVERSION_ORDER[fa.feasibility] - CONVERSION_ORDER[fb.feasibility]
    })
})

// 波动率套利信号：IV低估的标的，按IV/HV比值升序
const volArbSignals = computed(() => {
  if (!bonds.value) return []
  return bonds.value
    .filter(b => {
      const v = volatilityMap.value.get(b.code)
      return v && (v.signal === 'undervalued' || v.signal === 'overvalued')
    })
    .sort((a, b) => {
      const va = volatilityMap.value.get(a.code)!
      const vb = volatilityMap.value.get(b.code)!
      return VOL_SIGNAL_ORDER[va.signal] - VOL_SIGNAL_ORDER[vb.signal]
    })
})

function exportBonds() {
  const headers = [
    '转债名称', '代码', '价格', '涨跌幅', '转股价值', '溢价率', 'IV%', 'HV%', 'IV/HV信号',
    '转股套利收益%', '转股套利可行性', '阻碍因素',
    '到期收益', '剩余年限', '评级', '强赎进度', '回售进度', '下修进度',
    'Altman Z', '质押率%', 'ST风险', '正股名称', '正股代码', '标签',
  ]
  const rows = filteredBonds.value.map(b => {
    const v = volatilityMap.value.get(b.code)
    const a = conversionMap.value.get(b.code)
    return [
      b.name, b.code, b.price.toFixed(3), b.change_pct, b.conv_value.toFixed(2),
      b.premium_pct,
      v?.iv ?? '', v?.hv ?? '', v?.signalLabel ?? '',
      a?.theoreticalYield ?? '', a?.feasibilityLabel ?? '', a?.blockers.join('; ') ?? '',
      b.ytm, b.remaining_years, b.rating,
      `${b.redemption_days}/${b.total_redemption_days}天`,
      `${b.putback_days ?? 0}/${b.total_putback_days ?? 0}天`,
      `${b.revision_days ?? 0}/${b.total_revision_days ?? 0}天`,
      b.altman_z_score?.toFixed(2) ?? '',
      b.pledge_rate ?? '',
      b.is_st_risk ? '是' : '否',
      b.stock_name ?? '', b.stock_code ?? '',
      b.tag,
    ]
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
    <div v-if="bonds" class="cb-page">
    <!-- Page Header -->
    <PageHeader title="可转债扫描器" subtitle="可转债多因子扫描 - 实时监控强赎、双低、折价机会" helpKey="convertibleBonds" />
    <GlossaryPanel page-key="convertibleBonds" />

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
            <span class="mstat-value">118.42</span>
            <span class="mstat-chg pos">+0.12%</span>
          </div>
        </div>
        <div class="mstat-divider" />
        <div class="mstat">
          <span class="mstat-label">中位溢价</span>
          <div class="mstat-row">
            <span class="mstat-value">35.1%</span>
            <span class="mstat-chg neg">-2.4%</span>
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
      <n-data-table
        :columns="columns"
        :data="filteredBonds"
        :row-key="(row: any) => row.code"
        :bordered="false"
        :single-line="false"
        size="small"
        :row-props="rowProps"
      />
      <div class="table-footer">
        <span class="footer-info">显示 1-{{ filteredBonds.length }} / {{ bonds?.length ?? 0 }} 只转债</span>
        <div class="footer-pages">
          <button class="page-btn">上一页</button>
          <button class="page-btn active">1</button>
          <button class="page-btn">下一页</button>
        </div>
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
          <div v-if="conversionOpportunities.length === 0" class="empty-hint">暂无转股套利机会</div>
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
          <div v-if="volArbSignals.length === 0" class="empty-hint">暂无波动率信号</div>
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
            <span class="rank-name">{{ bond.name }}</span>
            <span class="rank-score" style="color: var(--color-danger); font-size: 11px;">{{ Math.round(bond.redemption_days / bond.total_redemption_days * 100) }}%</span>
          </div>
          <div v-if="redemptionWarnings.length === 0" class="empty-hint">暂无预警</div>
        </div>
      </div>

      <!-- Stock Risk Warnings -->
      <div class="rank-panel">
        <div class="rank-header danger">
          <h4>正股风险预警</h4>
        </div>
        <div class="rank-list">
          <div v-for="bond in stockRiskWarnings" :key="bond.code" class="rank-item stock-risk-item">
            <span class="rank-name" :title="bond.stock_name">
              {{ bond.name }}
              <span class="stock-sub">({{ bond.stock_name }})</span>
            </span>
            <span class="risk-badges">
              <span v-if="(bond.altman_z_score ?? 99) < 2.99" class="risk-badge z" :class="{ danger: (bond.altman_z_score ?? 99) < 1.81 }">
                Z{{ bond.altman_z_score?.toFixed(1) }}
              </span>
              <span v-if="(bond.pledge_rate ?? 0) > 30" class="risk-badge pledge" :class="{ danger: (bond.pledge_rate ?? 0) > 50 }">
                押{{ bond.pledge_rate }}%
              </span>
              <span v-if="bond.is_st_risk" class="risk-badge st">ST</span>
            </span>
          </div>
          <div v-if="stockRiskWarnings.length === 0" class="empty-hint">暂无预警</div>
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
          <label class="adv-label">正股 Z-Score ≥</label>
          <n-input v-model:value="filterZscoreMin" placeholder="例如 2.99" size="small" />
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
</style>

<style scoped>
.cb-page { display: flex; flex-direction: column; gap: 14px; }

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
.top-row { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; }

.filter-panel {
  background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 10px;
  padding: 12px 18px; display: flex; gap: 16px; align-items: flex-end;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

/* Responsive: collapse filter + grid on smaller screens */
@media (max-width: 1024px) {
  .top-row { grid-template-columns: 1fr; }
  .bottom-grid { grid-template-columns: repeat(2, 1fr); height: auto; }
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
.footer-pages { display: flex; gap: 4px; }
.page-btn {
  padding: 4px 12px; border: 1px solid var(--border-default); border-radius: 4px;
  background: var(--bg-card); cursor: pointer; font-size: 13px; color: var(--text-muted); transition: all 0.15s;
}
.page-btn.active { background: var(--color-primary); color: var(--bg-card); border-color: var(--color-primary); }
.page-btn:hover:not(.active) { background: var(--bg-hover); }
.page-btn:active:not(.active) { background: var(--bg-active); }

/* Bottom Rankings */
.bottom-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; height: 200px; }

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
