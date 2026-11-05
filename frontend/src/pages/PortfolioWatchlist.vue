<script setup lang="ts">
defineOptions({ name: 'PortfolioWatchlist' })
import { ref, computed, h, reactive, onMounted } from 'vue'
import { NButton, NIcon, NDataTable, NModal, NInput, NSelect, useMessage } from 'naive-ui'
import type { PaginationProps } from 'naive-ui'
import { Add, Download, FilterOutline } from '@vicons/ionicons5'
import { useAsyncData } from '../composables/useApi'
import { api, isGatewayNoData } from '../utils/api'
import type { FundItem } from '../types'
import { exportToCSV } from '../utils/export'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import DataPanel from '../components/DataPanel.vue'
import TabBar from '../components/TabBar.vue'
import LoadingState from '../components/LoadingState.vue'
import SectionFallback from '../components/SectionFallback.vue'
import BaseChart from '../components/BaseChart.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: funds, loading, error, meta, refresh: refetch } = useAsyncData<FundItem[]>(() => api.getFunds())
const gatewayEmpty = computed(() => isGatewayNoData(meta.value))
onMounted(refetch)
const activeTab = ref<string>('all')

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

// 添加标的弹窗
const showAddModal = ref(false)
const addForm = reactive<{ name: string; code: string; type: FundItem['type'] }>({ name: '', code: '', type: 'lof' })
const typeOptions = [
  { label: 'LOF 基金', value: 'lof' },
  { label: 'QDII 基金', value: 'qdii' },
]
function openAddModal() {
  addForm.name = ''
  addForm.code = ''
  addForm.type = 'lof'
  showAddModal.value = true
}
function submitAdd() {
  if (!addForm.name.trim() || !addForm.code.trim()) {
    message.warning('请填写基金名称和代码')
    return
  }
  if (!funds.value) return
  if (funds.value.some(f => f.code === addForm.code.trim())) {
    message.error(`代码 ${addForm.code.trim()} 已存在`)
    return
  }
  // 只写进当前内存列表：无行情源，绝不编造 1.000 的价格或 50% 的分位。
  funds.value.push({
    name: addForm.name.trim(),
    code: addForm.code.trim(),
    type: addForm.type,
    category: addForm.type === 'qdii' ? 'cross_border' : undefined,
    price: 0,
    iopv: 0,
    premium_pct: 0,
    premium_percentile: null,
    net_arbitrage_yield: 0,
    volume: null,
  })
  message.info(`已临时添加 ${addForm.name.trim()}（仅本次会话有效、无行情数据，刷新后不保留）`)
  showAddModal.value = false
}

// 只保留本页真正有数据源的分类：
// · 封闭式基金已有独立菜单 /closed-funds，这里不再重复做 tab（2026-11-04）
// · 原「指数 / 可转债」tab 的数据源根本不是基金列表（靠 slice(0,4) 截 4 行基金凑数），
//   点进去是误导，故一并移除。
const tabs = [
  { key: 'all', label: '全部' },
  { key: 'lof', label: 'LOF基金' },
  { key: 'qdii', label: '跨境QDII' },
]

function exportPortfolio() {
  // 只导出真实有值的字段；原先的年化收益/到期收益/百分位全市场 0 条有值，不应出现在导出里
  const headers = ['标的名称', '代码', '价格', '溢价率', '成交量', '分类', '自算净值', '口径差']
  const rows = displayFunds.value.map(f => [
    f.name, f.code, f.price.toFixed(3), f.premium_pct, f.volume ?? '',
    categoryLabel(f), f.est_nav ?? '', f.premium_gap ?? '',
  ])
  exportToCSV(`portfolio_${activeTab.value}_${new Date().toISOString().slice(0, 10)}`, headers, rows)
  message.success(`已导出 ${rows.length} 条 ${tabs.find(t => t.key === activeTab.value)?.label || ''} 数据`)
}

// ⚠️ 不能按 `f.type` 分类：后端 `/funds` 不带 type 时 subtype_map 没有 'all' 键，
//    5100 只里 5095 只被统一标成 'etf'（实测），按 type 筛 LOF/QDII/封闭式必然恒空。
//    可靠依据：代码段 16x / 50x = LOF；`category='cross_border'` = 跨境 QDII。
function isLofCode(code: string) {
  return code.startsWith('16') || code.startsWith('50')
}
const displayFunds = computed(() => {
  if (!funds.value) return []
  if (activeTab.value === 'lof') return funds.value.filter(f => isLofCode(f.code))
  if (activeTab.value === 'qdii') {
    // 剔除 price==iopv 且无成交的场外联接份额（没有场内溢价可看）
    return funds.value.filter(f =>
      f.category === 'cross_border' && (f.premium_pct !== 0 || f.volume != null),
    )
  }
  return funds.value
})

function categoryLabel(f: FundItem) {
  if (f.category === 'cross_border') return '跨境QDII'
  if (isLofCode(f.code)) return '境内LOF'
  return '其他ETF'
}
function formatVolume(v: number | null | undefined) {
  if (v == null) return '-'
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`
  if (v >= 1e4) return `${(v / 1e4).toFixed(2)}万`
  return String(Math.round(v))
}
const dash = () => h('span', { class: 'text-muted' }, '-')

// 原「年化收益 / 到期收益 / 到期日 / 百分位」四列全市场 0 条有值（实测 0/5100），
// 旧代码用 `(x || 0).toFixed(1)` 把缺失渲染成 `0.0%` 属于伪造数据，已换成真实有值的列。
const columns = computed(() => [
  {
    title: '基金名称',
    key: 'name',
    render: (row: FundItem) => h('span', { class: 'fund-name' }, row.name),
  },
  {
    title: '代码',
    key: 'code',
    render: (row: FundItem) => h('span', { style: { fontFamily: 'monospace' } }, row.code),
  },
  {
    title: '价格',
    key: 'price',
    align: 'right' as const,
    render: (row: FundItem) => row.price ? row.price.toFixed(3) : dash(),
  },
  {
    title: titleWithHelp('溢价率', 'premium_pct'),
    key: 'premium_pct',
    align: 'right' as const,
    render: (row: FundItem) => {
      // 红涨绿跌（A股惯例）：溢价为正标红、折价为负标绿
      const color = row.premium_pct >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
      const text = `${row.premium_pct >= 0 ? '+' : ''}${Number(row.premium_pct).toFixed(2)}%`
      return h('span', { style: { color } }, text)
    },
  },
  {
    title: '成交额',
    key: 'volume',
    align: 'right' as const,
    render: (row: FundItem) => row.volume != null ? formatVolume(row.volume) : dash(),
  },
  {
    title: '分类',
    key: 'category',
    render: (row: FundItem) => h('span', {
      class: 'category-tag',
      style: { color: row.category === 'cross_border' ? 'var(--color-primary)' : undefined },
    }, categoryLabel(row)),
  },
  {
    title: titleWithHelp('自算净值', undefined, '跨境 LOF/QDII 的篮子自算预估净值；底层行情不足时不估算，显示 -'),
    key: 'est_nav',
    align: 'right' as const,
    render: (row: FundItem) => row.est_nav != null ? Number(row.est_nav).toFixed(4) : dash(),
  },
  {
    title: titleWithHelp('口径差', undefined, '官方溢价 − 自算溢价（百分点）；绝对值 > 0.5 说明两套口径明显不一致'),
    key: 'premium_gap',
    align: 'right' as const,
    render: (row: FundItem) => row.premium_gap != null
      ? h('span', { style: { color: Math.abs(row.premium_gap) > 0.5 ? 'var(--color-danger)' : undefined } },
        `${row.premium_gap >= 0 ? '+' : ''}${Number(row.premium_gap).toFixed(2)}pp`)
      : dash(),
  },
])

// ============================================================
// ECharts options — replace static SVG donut + sparkline
// ============================================================

// 资产配置：按真实列表分类计数（互斥，避免同一只被重复计数）。
// 原实现是 45/30/15/10 四个写死的假数 + 「封闭基金」标签，已废弃。
const allocationCounts = computed(() => {
  const all = funds.value || []
  const qdii = all.filter(f => f.category === 'cross_border').length
  const lof = all.filter(f => isLofCode(f.code) && f.category !== 'cross_border').length
  return { qdii, lof, other: Math.max(0, all.length - qdii - lof), total: all.length }
})
const allocationLegend = computed(() => {
  const { qdii, lof, other, total } = allocationCounts.value
  const pct = (n: number) => total ? `${Math.round(n / total * 100)}%` : '0%'
  return [
    { label: `境内LOF (${pct(lof)})`, color: '#005ea1' },
    { label: `跨境QDII (${pct(qdii)})`, color: '#585e6c' },
    { label: `其他ETF (${pct(other)})`, color: '#2178c3' },
  ]
})
const allocationChartOption = computed(() => {
  const { qdii, lof, other } = allocationCounts.value
  return {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} ({d}%)',
    },
    legend: { show: false },
    series: [
      {
        type: 'pie',
        radius: ['55%', '78%'],
        avoidLabelOverlap: false,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: {
          borderColor: 'transparent',
          borderWidth: 2,
        },
        data: [
          { value: lof, name: '境内LOF', itemStyle: { color: '#005ea1' } },
          { value: qdii, name: '跨境QDII', itemStyle: { color: '#585e6c' } },
          { value: other, name: '其他ETF', itemStyle: { color: '#2178c3' } },
        ],
      },
    ],
  }
})

// ============================================================
// 折溢价统计：全部由 /funds 实时列表算出，无任何写死数值。
// 口径 = 全市场「境内 LOF + 跨境 QDII」中**有场内报价**的标的。
//       A股 ETF 官方溢价恒为 0（iopv==nav）、场外联接份额无成交，混进来会稀释均值。
// ============================================================
function hasExchangeQuote(f: FundItem) {
  return f.premium_pct !== 0 || f.volume != null
}
const premiumUniverse = computed(() => (funds.value || []).filter(f =>
  (isLofCode(f.code) || f.category === 'cross_border') && hasExchangeQuote(f),
))
const premiumStats = computed(() => {
  const all = funds.value || []
  const candidates = all.filter(f => isLofCode(f.code) || f.category === 'cross_border')
  const list = premiumUniverse.value
  const vals = list.map(f => Number(f.premium_pct) || 0)
  const sorted = [...list].sort((a, b) => Number(b.premium_pct) - Number(a.premium_pct))
  return {
    total: candidates.length,
    count: list.length,
    avg: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null,
    max: vals.length ? Math.max(...vals) : null,
    min: vals.length ? Math.min(...vals) : null,
    high: list.filter(f => f.premium_pct >= 3),
    discount: list.filter(f => f.premium_pct <= -1),
    topPremium: sorted.filter(f => f.premium_pct > 0).slice(0, 5),
    // 只列真正折价（<0）的标的；无折价时列表为空，模板显示空态而不是把最低的正溢价叫「折价」
    topDiscount: sorted.slice().reverse().filter(f => f.premium_pct < 0).slice(0, 5),
  }
})
const pctText = (v: number | null | undefined, digits = 2) =>
  v == null ? '-' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(digits)}%`
const pctOf = (n: number) => {
  const c = premiumStats.value.count
  return c ? `${Math.round(n / c * 100)}%` : '0%'
}
// 进度条宽度也用真实占比，不再写死 75% / 70% / 25% / 60%
const barWidth = (n: number, base?: number) => {
  const d = base ?? premiumStats.value.count
  return d ? `${Math.min(100, Math.max(0, n / d * 100)).toFixed(1)}%` : '0%'
}

const BUCKETS = ['<-5', '-5~-2', '-2~0', '0~2', '2~5', '>=5'] as const
function bucketOf(p: number) {
  if (p < -5) return 0
  if (p < -2) return 1
  if (p < 0) return 2
  if (p < 2) return 3
  if (p < 5) return 4
  return 5
}
const distributionChartOption = computed(() => {
  const counts: number[] = new Array(BUCKETS.length).fill(0)
  for (const f of premiumUniverse.value) counts[bucketOf(Number(f.premium_pct) || 0)] += 1
  return {
    tooltip: { trigger: 'axis', formatter: (p: any) => `${p[0].name}% : ${p[0].value} 只` },
    grid: { top: 18, right: 10, bottom: 22, left: 34 },
    xAxis: { type: 'category', data: [...BUCKETS], axisLabel: { fontSize: 9, color: '#8a9099' } },
    yAxis: { type: 'value', axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { type: 'dashed', opacity: 0.3 } } },
    series: [{
      type: 'bar',
      barMaxWidth: 34,
      data: counts.map((v, i) => ({
        value: v,
        // 红涨绿跌：溢价桶红、折价桶绿
        itemStyle: { color: i <= 2 ? '#2e9e6b' : '#d94a48', borderRadius: [3, 3, 0, 0] },
      })),
      label: { show: true, position: 'top', fontSize: 9, color: '#5c636d' },
    }],
  }
})
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    skeleton
    :min-height="520"
    text="正在加载投资组合数据..."
    @retry="refetch"
  >
    <SectionFallback v-if="gatewayEmpty" :gateway-empty="true" :min-height="520" @retry="refetch" />
    <div v-else-if="funds" class="watchlist-page">
    <!-- Header -->
    <PageHeader title="投资组合看板" :subtitle="`监控 ${funds?.length ?? 0} 只基金 · 聚焦 LOF / 跨境 QDII 的场内折溢价，均值、分布与极值榜均由实时列表计算`" help-key="portfolioWatchlist" :updated-at="meta?.updateTime">
      <template #actions>
        <n-button size="small" @click="openAddModal">
          <template #icon><n-icon :component="Add" /></template>
          添加
        </n-button>
        <n-button size="small" @click="exportPortfolio">
          <template #icon><n-icon :component="Download" /></template>
          导出
        </n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="portfolioWatchlist" />

    <!-- Bento Grid -->
    <div class="stat-grid wide-first">
      <!-- Allocation Card -->
      <div class="bento-card">
        <h3 class="bento-title">资产配置</h3>
        <div class="donut-container">
          <BaseChart :option="allocationChartOption" :height="140" />
          <div class="donut-center">
            <span class="donut-total">{{ allocationCounts.total }}</span>
            <span class="donut-label">总计</span>
          </div>
        </div>
        <div class="allocation-legend">
          <div v-for="item in allocationLegend" :key="item.label" class="legend-item">
            <span class="legend-dot" :style="{ background: item.color }" />{{ item.label }}
          </div>
        </div>
      </div>

      <!-- 折溢价统计卡片：数值与进度条宽度全部由实时列表计算 -->
      <div class="bento-card">
        <span class="bento-label">平均溢价（有场内报价）</span>
        <span class="bento-value" :style="{ color: (premiumStats.avg ?? 0) >= 0 ? 'var(--color-danger)' : 'var(--color-success)' }">
          {{ pctText(premiumStats.avg) }}
        </span>
        <div class="bento-trend" style="color: var(--text-muted)">
          最高 {{ pctText(premiumStats.max) }} · 最低 {{ pctText(premiumStats.min) }}
        </div>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: barWidth(premiumStats.high.length), background: 'var(--color-danger)' }" />
        </div>
      </div>

      <StatCard
        label="高溢价标的"
        :value="premiumStats.high.length"
        :sub="`溢价 ≥ 3% · 占 ${pctOf(premiumStats.high.length)}`"
        color="var(--color-danger)"
      >
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: barWidth(premiumStats.high.length), background: 'var(--color-danger)' }" />
        </div>
      </StatCard>

      <StatCard
        label="折价标的"
        :value="premiumStats.discount.length"
        :sub="`溢价 ≤ -1% · 占 ${pctOf(premiumStats.discount.length)}`"
        color="var(--color-success)"
      >
        <div class="progress-bar">
          <div class="progress-fill success" :style="{ width: barWidth(premiumStats.discount.length) }" />
        </div>
      </StatCard>

      <StatCard
        label="覆盖标的"
        :value="premiumStats.count"
        :sub="`全市场 ${premiumStats.total} 只 LOF / 跨境中有报价`"
      >
        <div class="progress-bar">
          <div class="progress-fill blue" :style="{ width: barWidth(premiumStats.count, premiumStats.total) }" />
        </div>
      </StatCard>
    </div>

    <!-- Tabs + Table -->
    <DataPanel>
      <template #actions>
        <TabBar v-model="activeTab" :tabs="tabs" />
        <div class="panel-info">
          <span>自动刷新: 5秒</span>
          <n-icon :component="FilterOutline" size="16" />
        </div>
      </template>
      <n-data-table
        :columns="columns"
        :data="displayFunds"
        :row-key="(row: any) => row.code"
        :bordered="false"
        :single-line="false"
        size="small"
        :pagination="pagination"
        :row-props="(row: any) => ({ onClick: () => message.info(row.name) })"
      />
    </DataPanel>

    <!-- 真实分布 + 极值榜：替代原写死的「折价收敛趋势」曲线与「相关性矩阵」色块 -->
    <div class="bottom-grid">
      <div class="risk-panel">
        <h4>溢价率分布 <span class="panel-sub">（{{ premiumStats.count }} 只有报价标的 · 横轴 %）</span></h4>
        <BaseChart :option="distributionChartOption" :height="160" />
      </div>
      <div class="risk-panel">
        <h4>溢价 / 折价极值 <span class="panel-sub">（实时列表）</span></h4>
        <div class="rank-cols">
          <div class="rank-col">
            <div class="rank-head" style="color: var(--color-danger)">溢价 TOP5</div>
            <div v-for="f in premiumStats.topPremium" :key="`h-${f.code}`" class="rank-row">
              <span class="rank-code">{{ f.code }}</span>
              <span class="rank-name">{{ f.name }}</span>
              <span class="rank-pct" style="color: var(--color-danger)">{{ pctText(f.premium_pct) }}</span>
            </div>
            <div v-if="!premiumStats.topPremium.length" class="rank-empty">当前无溢价标的</div>
          </div>
          <div class="rank-col">
            <div class="rank-head" style="color: var(--color-success)">折价 TOP5</div>
            <div v-for="f in premiumStats.topDiscount" :key="`d-${f.code}`" class="rank-row">
              <span class="rank-code">{{ f.code }}</span>
              <span class="rank-name">{{ f.name }}</span>
              <span class="rank-pct" style="color: var(--color-success)">{{ pctText(f.premium_pct) }}</span>
            </div>
            <div v-if="!premiumStats.topDiscount.length" class="rank-empty">当前无折价标的</div>
          </div>
        </div>
      </div>
    </div>
    </div>

    <!-- 添加标的弹窗 -->
    <n-modal v-model:show="showAddModal" preset="card" title="临时添加标的（仅本次会话、无行情）" style="width: 420px; max-width: 92vw;" :bordered="false">
      <div style="display: flex; flex-direction: column; gap: 12px;">
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; font-weight: 700; color: var(--text-muted);">标的名称</label>
          <n-input v-model:value="addForm.name" placeholder="例如：科创50ETF" />
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; font-weight: 700; color: var(--text-muted);">标的代码</label>
          <n-input v-model:value="addForm.code" placeholder="例如：588000.SH" />
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; font-weight: 700; color: var(--text-muted);">类型</label>
          <n-select v-model:value="addForm.type" :options="typeOptions" />
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px;">
          <n-button size="small" @click="showAddModal = false">取消</n-button>
          <n-button size="small" type="primary" @click="submitAdd">添加</n-button>
        </div>
      </template>
    </n-modal>
  </LoadingState>
</template>

<!-- Non-scoped styles for h()-rendered NDataTable cells -->
<style>
.fund-name {
  font-family: 'Work Sans', sans-serif;
  font-weight: 600;
  color: var(--text-primary);
}

/* h() 渲染的表格单元格不受 scoped 样式影响，分类标签放这里 */
.category-tag {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}
</style>

<style scoped>
.watchlist-page { display: flex; flex-direction: column; gap: 14px; }

/* Kept: allocation card (complex SVG donut + legend) and 总盈亏 card (trend indicator) */
.bento-card {
  background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 10px; padding: 18px;
  display: flex; flex-direction: column; gap: 8px;
  box-shadow: var(--shadow-card);
}

.bento-title { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); margin: 0; }
.bento-label { font-family: 'Work Sans', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); }
.bento-value { font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 600; color: var(--text-primary); }
.bento-trend { display: flex; align-items: center; gap: 4px; font-size: 13px; color: var(--color-success); }
.bento-trend .n-icon { font-size: 16px; }

.progress-bar { height: 6px; background: var(--border-default); border-radius: 3px; overflow: hidden; margin-top: auto; }
.progress-fill { height: 100%; border-radius: 3px; background: var(--color-primary); transition: width 0.3s; }
.progress-fill.success { background: var(--color-success); }
.progress-fill.blue { background: var(--color-primary); }

.donut-container { display: flex; justify-content: center; align-items: center; position: relative; height: 140px; }
.donut-center { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; pointer-events: none; }
.donut-total { display: block; font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 700; color: var(--text-primary); line-height: 1; }
.donut-label { font-size: 11px; color: var(--text-muted); font-weight: 700; letter-spacing: 0.05em; }

.allocation-legend { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; border-top: 1px solid var(--border-default); padding-top: 10px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary); }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

.panel-info { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-muted); }
.panel-info .n-icon { font-size: 18px; cursor: pointer; }

/* Bottom Grid */
.bottom-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; min-height: 220px; }
.risk-panel { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 10px; padding: 18px; display: flex; flex-direction: column; box-shadow: var(--shadow-card); }
.risk-panel h4 { font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: var(--text-muted); margin: 0 0 12px; }
.panel-sub { font-size: 10px; font-weight: 500; letter-spacing: 0; color: var(--text-muted); }

.rank-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; flex: 1; min-height: 0; }
.rank-col { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.rank-head { font-size: 10px; font-weight: 700; letter-spacing: 0.05em; margin-bottom: 4px; }
.rank-row { display: flex; align-items: center; gap: 6px; font-size: 11px; padding-bottom: 3px; border-bottom: 1px dashed var(--border-default); }
.rank-code { font-family: 'JetBrains Mono', monospace; color: var(--text-muted); flex-shrink: 0; }
.rank-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); }
.rank-pct { font-family: 'JetBrains Mono', monospace; font-weight: 700; flex-shrink: 0; }
.rank-empty { font-size: 11px; color: var(--text-muted); padding: 8px 0; }

/* Responsive: collapse multi-column grids on smaller screens */
@media (max-width: 768px) {
  .bottom-grid { grid-template-columns: 1fr; height: auto; }
  .allocation-legend { grid-template-columns: 1fr; }
}
</style>
