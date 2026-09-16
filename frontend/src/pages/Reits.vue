<script setup lang="ts">
defineOptions({ name: 'Reits' })
import { ref, h, computed, onMounted } from 'vue'
import { NButton, NDataTable, NIcon, NTag, useMessage } from 'naive-ui'
import type { PaginationProps } from 'naive-ui'
import { WarningOutline } from '@vicons/ionicons5'
import { useAsyncData } from '../composables/useApi'
import { api } from '../utils/api'
import type { ReitItem } from '../types'
import { exportToCSV } from '../utils/export'
import { analyzeReitsBatch } from '../utils/reits'
import type { ReitsAnalysis } from '../utils/reits'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import DataPanel from '../components/DataPanel.vue'
import LoadingState from '../components/LoadingState.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: reits, loading, error, refresh: refetch } = useAsyncData<ReitItem[]>(() => api.getReits())
onMounted(refetch)
const refreshing = ref(false)

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

// 三维度分析映射 (code → ReitsAnalysis)
const analysisMap = computed(() => {
  if (!reits.value) return new Map<string, ReitsAnalysis>()
  return analyzeReitsBatch(reits.value)
})

// 按综合评分降序排序
const sortedReits = computed(() => {
  if (!reits.value) return []
  return [...reits.value].sort((a, b) => {
    const sa = analysisMap.value.get(a.code)?.score ?? 0
    const sb = analysisMap.value.get(b.code)?.score ?? 0
    return sb - sa
  })
})

// 真实可得的统计（仅基于实时行情，基本面缺失时如实显示 —）
const reitStats = computed(() => {
  const list = reits.value ?? []
  if (!list.length) return { count: 0, avgPrice: null as number | null, up: 0, down: 0 }
  const prices = list.map(r => r.market_price).filter((v): v is number => typeof v === 'number')
  const avgPrice = prices.length ? prices.reduce((a, b) => a + b, 0) / prices.length : null
  const up = list.filter(r => (r.change_pct ?? 0) > 0).length
  const down = list.filter(r => (r.change_pct ?? 0) < 0).length
  return { count: list.length, avgPrice, up, down }
})

// 配置价值排名 (按评分降序, 取前5)
const scoreRanking = computed(() =>
  sortedReits.value.slice(0, 5).map(r => {
    const a = analysisMap.value.get(r.code)!
    return { name: r.name, score: a.score, dividendRate: r.dividend_rate }
  }),
)

// NAV折价机会 (navLevel === 'discount')
const discountOpportunities = computed(() =>
  sortedReits.value
    .map(r => {
      const a = analysisMap.value.get(r.code)
      if (!a || a.navLevel !== 'discount') return null
      return { name: r.name, navPremiumPct: a.navPremiumPct, safetyMargin: a.safetyMargin }
    })
    .filter((x): x is { name: string; navPremiumPct: number; safetyMargin: string } => x !== null),
)

// 风险预警列表 (有预警的REITs)
const riskWarnings = computed(() =>
  sortedReits.value
    .map(r => {
      const a = analysisMap.value.get(r.code)
      if (!a || a.warnings.length === 0) return null
      return { name: r.name, count: a.warnings.length, first: a.warnings[0] }
    })
    .filter((x): x is { name: string; count: number; first: string } => x !== null),
)

// 颜色映射 — NAV 溢折价
const navColorMap: Record<string, string> = {
  discount: 'var(--tag-green-text)',
  fair: 'var(--text-muted)',
  premium: 'var(--tag-red-text)',
}
const navBgMap: Record<string, string> = {
  discount: 'var(--tag-green-bg)',
  fair: 'var(--bg-subtle)',
  premium: 'var(--tag-red-bg)',
}
// 颜色映射 — 可持续性
const sustainColorMap: Record<string, string> = {
  sustainable: 'var(--tag-green-text)',
  watch: 'var(--tag-orange-text)',
  at_risk: 'var(--tag-red-text)',
}
const sustainBgMap: Record<string, string> = {
  sustainable: 'var(--tag-green-bg)',
  watch: 'var(--tag-orange-bg)',
  at_risk: 'var(--tag-red-bg)',
}
// 颜色映射 — 流动性
const liquidityColorMap: Record<string, string> = {
  ample: 'var(--tag-green-text)',
  moderate: 'var(--tag-orange-text)',
  illiquid: 'var(--tag-red-text)',
}
const liquidityBgMap: Record<string, string> = {
  ample: 'var(--tag-green-bg)',
  moderate: 'var(--tag-orange-bg)',
  illiquid: 'var(--tag-red-bg)',
}

function scoreColor(score: number): string {
  if (score >= 70) return 'var(--color-success)'
  if (score >= 40) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

function refresh() {
  refreshing.value = true
  message.loading('正在刷新 REITs 数据...', { duration: 1200 })
  refetch().finally(() => {
    refreshing.value = false
    if (reits.value) {
      message.success(`已刷新 ${reits.value.length} 条 REITs 数据`)
    }
  })
}

function exportReits() {
  if (!reits.value) return
  const headers = [
    'REIT名称', '代码', '市场价格', '年化分红', '分红率', 'IRR', '出租率',
    'NAV溢折价率', '可持续性', 'DSCR', '出租率趋势', '杠杆率', '成交量', '综合评分', '风险提示', '项目',
  ]
  const rows = reits.value.map(r => {
    const a = analysisMap.value.get(r.code)
    return [
      r.name, r.code, r.market_price.toFixed(3), (r.annual_distribution ?? 0).toFixed(3),
      r.dividend_rate ?? '', r.irr ?? '', r.occupancy_rate ?? '',
      a?.navPremiumPct ?? '', a?.sustainabilityLabel ?? '', a?.dscr ?? '',
      a?.occupancyTrend ?? '', a?.leverageRatio ?? '', a?.volume ?? '',
      a?.score ?? '', a?.warnings.join('; ') ?? '', r.project_name ?? '',
    ]
  })
  exportToCSV(`reits_${new Date().toISOString().slice(0, 10)}`, headers, rows)
  message.success(`已导出 ${rows.length} 条 REITs 数据`)
}

const columns = [
  { title: 'REIT名称', key: 'name',
    render: (row: ReitItem) => h('span', { class: 'reit-name' }, row.name) },
  { title: '市场价格', key: 'market_price', align: 'right' as const,
    render: (row: ReitItem) => `¥${row.market_price.toFixed(3)}` },
  { title: '年化分红', key: 'annual_distribution', align: 'right' as const,
    render: (row: ReitItem) => row.annual_distribution != null ? `¥${row.annual_distribution.toFixed(3)}` : '—' },
  { title: '分红率', key: 'dividend_rate', align: 'right' as const,
    render: (row: ReitItem) => h('span', { style: { color: 'var(--color-primary)', fontWeight: 700 } }, row.dividend_rate != null ? `${row.dividend_rate}%` : '—') },
  { title: 'IRR', key: 'irr', align: 'right' as const,
    render: (row: ReitItem) => row.irr != null ? `${row.irr}%` : '—' },
  { title: titleWithHelp('出租率', 'occupancy_rate'), key: 'occupancy_rate', align: 'right' as const,
    render: (row: ReitItem) => {
      if (row.occupancy_rate == null) return h('span', { style: { color: 'var(--text-muted)' } }, '—')
      const color = row.occupancy_rate >= 90 ? 'var(--color-success)' : 'var(--color-warning)'
      return h('span', { style: { color } }, `${row.occupancy_rate}%`)
    } },
  // NAV 溢折价
  { title: titleWithHelp('NAV溢折价', 'nav_premium'), key: 'nav', align: 'center' as const,
    render: (row: ReitItem) => {
      const a = analysisMap.value.get(row.code)
      if (!a) return ''
      const pctText = a.navPremiumPct >= 0 ? `+${a.navPremiumPct}%` : `${a.navPremiumPct}%`
      return h('div', { class: 'nav-cell', title: a.safetyMargin }, [
        h('span', {
          class: 'level-tag',
          style: { color: navColorMap[a.navLevel], background: navBgMap[a.navLevel] },
        }, a.navLabel),
        h('span', { class: 'sub-info' }, pctText),
      ])
    } },
  // 可持续性
  { title: titleWithHelp('可持续性', 'sustainability'), key: 'sustainability', align: 'center' as const,
    render: (row: ReitItem) => {
      const a = analysisMap.value.get(row.code)
      if (!a) return ''
      return h('div', { class: 'sustain-cell' }, [
        h('span', {
          class: 'level-tag',
          style: { color: sustainColorMap[a.sustainability], background: sustainBgMap[a.sustainability] },
        }, a.sustainabilityLabel),
        h('span', { class: 'sub-info' }, `DSCR ${a.dscr.toFixed(2)}`),
      ])
    } },
  // 流动性
  { title: titleWithHelp('流动性', 'liquidity'), key: 'liquidity', align: 'center' as const,
    render: (row: ReitItem) => {
      const a = analysisMap.value.get(row.code)
      if (!a) return ''
      return h('div', { class: 'liquidity-cell' }, [
        h('span', {
          class: 'level-tag',
          style: { color: liquidityColorMap[a.liquidity], background: liquidityBgMap[a.liquidity] },
        }, String(a.liquidityLabel)),
        h('span', { class: 'sub-info' }, `${(a.volume / 10000).toFixed(1)}万`),
      ])
    } },
  // 综合评分
  { title: '综合评分', key: 'score', align: 'center' as const,
    sorter: (a: ReitItem, b: ReitItem) =>
      (analysisMap.value.get(a.code)?.score ?? 0) - (analysisMap.value.get(b.code)?.score ?? 0),
    render: (row: ReitItem) => {
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
    } },
  { title: '项目', key: 'project_name' },
  // 健康度 (基于可持续性数据)
  { title: '健康度', key: 'health', align: 'center' as const,
    render: (row: ReitItem) => {
      const a = analysisMap.value.get(row.code)
      if (!a) return ''
      const level = a.sustainability
      const text = level === 'sustainable' ? '健康' : level === 'watch' ? '关注' : '风险'
      const cls = level === 'sustainable' ? 'healthy' : level === 'watch' ? 'normal' : 'risky'
      return h('span', { class: ['health-tag', cls] }, text)
    } },
]
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    skeleton
    :min-height="480"
    text="正在加载REITs数据..."
    @retry="refetch"
  >
    <div v-if="reits" class="reits-page">
    <PageHeader title="公募REITs中心" subtitle="公募REITs 深度价值分析 - 底层资产评估与分红率跟踪" helpKey="reits">
      <template #actions>
        <n-button size="small" :loading="refreshing" @click="refresh">刷新</n-button>
        <n-button size="small" type="primary" @click="exportReits">导出</n-button>
      </template>
    </PageHeader>
    <GlossaryPanel page-key="reits" />

    <!-- Summary Cards (基于真实实时行情，基本面缺失时显示 —) -->
    <div class="stat-grid">
      <StatCard label="REITs总数" :value="reitStats.count" />
      <StatCard label="实时均价" :value="reitStats.avgPrice != null ? reitStats.avgPrice.toFixed(3) : '—'" color="#005ea1" />
      <StatCard label="上涨" :value="reitStats.up" color="#16a34a" />
      <StatCard label="下跌" :value="reitStats.down" color="#dc2626" />
    </div>

    <!-- REITs Table -->
    <DataPanel title="REITs估值看板" meta="中国A股公募REITs">
<n-data-table
:columns="columns"
:data="sortedReits"
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
        <h4>配置价值排名</h4>
        <div class="ranking-list">
          <div v-for="(item, idx) in scoreRanking" :key="item.name" class="ranking-item">
            <span class="rank-num" :class="{ top: idx < 3 }">{{ idx + 1 }}</span>
            <span class="rank-name">{{ item.name }}</span>
            <span class="rank-score">{{ item.score }}</span>
            <span class="rank-yield">分红{{ item.dividendRate != null ? item.dividendRate + '%' : '—' }}</span>
          </div>
          <div v-if="scoreRanking.length === 0" class="empty-hint">暂无数据</div>
        </div>
      </div>

      <div class="bottom-panel">
        <h4>NAV折价机会</h4>
        <div class="ranking-list">
          <div v-for="item in discountOpportunities" :key="item.name" class="ranking-item">
            <span class="rank-name">{{ item.name }}</span>
            <span class="rank-premium green">{{ item.navPremiumPct }}%</span>
            <span class="rank-margin">{{ item.safetyMargin }}</span>
          </div>
          <div v-if="discountOpportunities.length === 0" class="empty-hint">暂无折价机会</div>
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
    </div>
    </div>
  </LoadingState>
</template>

<style>
/* Non-scoped styles for h()-rendered elements */
.reit-name {
  font-family: 'Work Sans', sans-serif;
  font-weight: 600;
  color: var(--text-primary);
}

.health-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 2px;
  font-size: 10px;
  font-weight: 700;
}
.health-tag.healthy { background: var(--tag-green-bg); color: var(--tag-green-text); }
.health-tag.normal { background: var(--tag-orange-bg); color: var(--tag-orange-text); }
.health-tag.risky { background: var(--tag-red-bg); color: var(--tag-red-text); }

/* 等级标签 (NAV / 可持续性 / 流动性) */
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

.nav-cell,
.sustain-cell,
.liquidity-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

/* 综合评分 cell */
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
.reits-page { display: flex; flex-direction: column; gap: 14px; }

/* Bottom Panels */
.bottom-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.bottom-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 18px;
  height: 220px;
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

.warning-title .n-icon { font-size: 15px; }

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

.rank-premium {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.rank-premium.green { color: var(--color-success); }

.rank-margin {
  font-size: 12px;
  color: var(--text-muted);
  flex-shrink: 0;
}

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

/* Responsive: collapse multi-column grids on smaller screens */
@media (max-width: 768px) {
  .bottom-grid { grid-template-columns: 1fr; }
}
</style>
