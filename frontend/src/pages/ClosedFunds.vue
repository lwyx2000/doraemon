<script setup lang="ts">
import { h, ref, reactive, computed } from 'vue'
import { NButton, NDataTable, NIcon, NModal, NInput, NTag, useMessage } from 'naive-ui'
import { TrendingUpOutline, TimerOutline, WarningOutline } from '@vicons/ionicons5'
import { mockFunds } from '../composables/useMockData'
import { useAsyncMock } from '../composables/useApi'
import type { FundItem } from '../types'
import { exportToCSV } from '../utils/export'
import { analyzeClosedFundBatch, parseRemainingDays } from '../utils/closedFund'
import type { ClosedFundAnalysis } from '../utils/closedFund'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import DataPanel from '../components/DataPanel.vue'
import LoadingState from '../components/LoadingState.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: funds, loading, error, refresh: refetch } = useAsyncMock(mockFunds.filter(f => f.type === 'closed'))

// 三维度分析映射 (code → ClosedFundAnalysis)
const analysisMap = computed(() => {
  if (!funds.value) return new Map<string, ClosedFundAnalysis>()
  return analyzeClosedFundBatch(funds.value)
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

// 套利机会排名 (按评分降序, 取前5)
const arbitrageRanking = computed(() =>
  sortedFunds.value.slice(0, 5).map(f => {
    const a = analysisMap.value.get(f.code)!
    return { name: f.name, score: a.score, convergenceYield: a.convergenceYield }
  }),
)

// 风险预警列表 (有预警的基金)
const riskWarnings = computed(() =>
  sortedFunds.value
    .map(f => {
      const a = analysisMap.value.get(f.code)
      if (!a || a.warnings.length === 0) return null
      return { name: f.name, count: a.warnings.length, first: a.warnings[0] }
    })
    .filter((x): x is { name: string; count: number; first: string } => x !== null),
)

// 收敛收益率排名 (降序, 取前5)
const convergenceYieldRanking = computed(() =>
  [...sortedFunds.value]
    .map(f => {
      const a = analysisMap.value.get(f.code)!
      return { name: f.name, yield: a.convergenceYield }
    })
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
// 颜色映射 — 收敛确定性 (NTag type)
const convergenceTypeMap: Record<string, 'success' | 'warning' | 'error'> = {
  certain: 'success',
  likely: 'warning',
  uncertain: 'error',
}
// 颜色映射 — 信用风险
const creditColorMap: Record<string, string> = {
  safe: 'var(--tag-green-text)',
  watch: 'var(--tag-orange-text)',
  risky: 'var(--tag-red-text)',
}
const creditBgMap: Record<string, string> = {
  safe: 'var(--tag-green-bg)',
  watch: 'var(--tag-orange-bg)',
  risky: 'var(--tag-red-bg)',
}

function scoreColor(score: number): string {
  if (score >= 70) return 'var(--color-success)'
  if (score >= 40) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

// 添加标的弹窗
const showAddModal = ref(false)
const addForm = reactive({ name: '', code: '' })
function openAddModal() {
  addForm.name = ''
  addForm.code = ''
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
  funds.value.push({
    name: addForm.name.trim(),
    code: addForm.code.trim(),
    type: 'closed',
    price: 1.0,
    iopv: 1.0,
    premium_pct: 0,
    premium_percentile: 50,
    net_arbitrage_yield: 0,
    volume: 0,
  })
  message.success(`已添加: ${addForm.name.trim()} (${addForm.code.trim()})`)
  showAddModal.value = false
}

function exportFunds() {
  if (!funds.value) return
  const headers = [
    '基金名称', '代码', '剩余期限', '折价率', '年化收益', '预估到期收益', '到期日', '成交量',
    '流动性', '收敛路径', '年化收敛收益率', '信用评级', '底层类型', '综合评分', '风险提示',
  ]
  const rows = funds.value.map(f => {
    const a = analysisMap.value.get(f.code)
    return [
      f.name, f.code, f.remaining_term ?? '', f.premium_pct, f.annualized ?? '',
      f.est_ytm ?? '', f.maturity ?? '', f.volume,
      a?.liquidityLabel ?? '', a?.convergenceLabel ?? '', a?.convergenceYield ?? '',
      a?.creditRating ?? '', a?.underlyingType ?? '', a?.score ?? '',
      a?.warnings.join('; ') ?? '',
    ]
  })
  exportToCSV(`closed_funds_${new Date().toISOString().slice(0, 10)}`, headers, rows)
  message.success(`已导出 ${rows.length} 条封闭基金数据`)
}

const summaryStats = {
  totalPnl: 1.24,
  pnlToday: 2.4,
  volatility: 14.2,
  beta: 0.85,
  maxDrawdown: -8.4,
  avgDiscount: 12.5,
}

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
    render: (row: FundItem) => row.remaining_term ?? '',
  },
  {
    title: titleWithHelp('折价率', 'premium_pct'),
    key: 'premium_pct',
    align: 'right' as const,
    render: (row: FundItem) => {
      // 折价越深=机会越大→绿色突出；溢价=危险→红色
      const color = row.premium_pct < -15
        ? 'var(--color-success)'
        : row.premium_pct < 0
          ? 'var(--color-primary)'
          : 'var(--color-danger)'
      return h('span', { style: { color, fontWeight: row.premium_pct < -15 ? 700 : 400 } }, `${row.premium_pct}%`)
    },
  },
  {
    title: '年化收益',
    key: 'annualized',
    align: 'right' as const,
    render: (row: FundItem) => `${row.annualized}%`,
  },
  {
    title: '预估到期收益',
    key: 'est_ytm',
    align: 'right' as const,
    render: (row: FundItem) =>
      h('span', { style: { color: 'var(--color-primary)', fontWeight: 700 } }, `${row.est_ytm}%`),
  },
  {
    title: '到期日',
    key: 'maturity',
    render: (row: FundItem) => {
      // 按剩余天数阈值判断是否显示到期警告（< 60天）
      const remainingDays = parseRemainingDays(row.remaining_term)
      if (remainingDays < 60 && row.maturity) {
        return h('span', { class: 'maturity-warning' }, [
          h(NIcon, { component: TimerOutline, size: 14 }),
          row.maturity,
        ])
      }
      return row.maturity ?? ''
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
        h('span', { class: 'sub-info' }, `${(a.volume / 10000).toFixed(1)}万手`),
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
        h('span', { class: 'sub-info' }, `年化${a.convergenceYield}%`),
      ]
      if (a.isLofConvertible) {
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
        h('span', { class: 'sub-info' }, `${a.creditRating} · ${a.underlyingType}`),
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
    title: '收敛度',
    key: 'conv',
    align: 'right' as const,
    render: (row: FundItem) =>
      h('div', { class: 'conv-bar' }, [
        h('div', {
          class: 'conv-fill',
          style: { width: `${Math.min(Math.abs(row.premium_pct) * 4, 100)}%` },
        }),
      ]),
  },
]
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    :min-height="520"
    text="正在加载封闭基金数据..."
    @retry="refetch"
  >
    <div v-if="funds" class="closed-page">
    <PageHeader title="封闭基金分析" subtitle="封闭基金折价率监控与到期套利分析" helpKey="closedFunds">
      <template #actions>
        <n-button size="small" @click="openAddModal">添加</n-button>
        <n-button size="small" type="primary" @click="exportFunds">导出</n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="closedFunds" />

    <!-- Dashboard Cards -->
    <div class="stat-grid cols-5">
      <div class="dash-card">
        <h3 class="dash-title">投资组合概览</h3>
        <div class="portfolio-ring">
          <svg class="ring-svg" viewBox="0 0 100 50">
            <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" style="stroke: var(--border-default)" stroke-width="10" />
            <path d="M 10 50 A 40 40 0 0 1 40 15" fill="none" style="stroke: var(--color-primary)" stroke-width="10" />
            <path d="M 40 15 A 40 40 0 0 1 70 20" fill="none" stroke="#585e6c" stroke-width="10" />
            <path d="M 70 20 A 40 40 0 0 1 90 50" fill="none" stroke="#864f00" stroke-width="10" />
          </svg>
          <div class="ring-center">
            <span class="ring-total">{{ funds?.length ?? 0 }}</span>
            <span class="ring-label">持仓</span>
          </div>
        </div>
        <div class="legend-grid">
          <div class="legend-item"><span class="dot" style="background: var(--color-primary)" />封闭基金 (60%)</div>
          <div class="legend-item"><span class="dot" style="background:#585e6c" />LOF (25%)</div>
          <div class="legend-item"><span class="dot" style="background:#864f00" />其他 (15%)</div>
        </div>
      </div>

      <div class="dash-card">
        <span class="dash-label">总盈亏</span>
        <span class="dash-value" style="color: var(--color-success)">+¥{{ summaryStats.totalPnl }}M</span>
        <div class="dash-trend">
          <n-icon :component="TrendingUpOutline" size="16" />
          {{ summaryStats.pnlToday }}% 今日
        </div>
        <div class="progress-bar">
          <div class="progress-fill success" style="width: 75%" />
        </div>
      </div>

      <StatCard label="波动率" :value="`${summaryStats.volatility}%`" :sub="`Beta: ${summaryStats.beta}`" tip="投资组合年化波动率，衡量净值波动幅度" />

      <StatCard label="最大回撤" :value="`${summaryStats.maxDrawdown}%`" sub="近12月恢复期: 12天">
        <div class="progress-bar">
          <div class="progress-fill blue" style="width: 25%" />
        </div>
      </StatCard>

      <StatCard label="平均折价" :value="`${summaryStats.avgDiscount}%`" color="#864f00" sub="目标: 15%" tip="持仓封闭基金的平均折价率，折价越深潜在收益越大但风险也越高" />
    </div>

    <!-- Fund Table -->
    <DataPanel title="封闭基金监控列表" meta="自动刷新: 5秒">
      <n-data-table
        :columns="columns"
        :data="sortedFunds"
        :row-key="(row: any) => row.code"
        :bordered="false"
        :single-line="false"
        size="small"
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
            <span class="rank-yield">年化{{ item.convergenceYield }}%</span>
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
        <h4>折价收敛趋势</h4>
        <div class="sparkline-bars">
          <div v-for="bar in [75, 60, 80, 55, 85, 95]" :key="bar"
            :style="{ height: bar + '%' }"
            :class="['spark-bar', { active: bar === 95 }]" />
        </div>
      </div>
    </div>
    </div>

    <!-- 添加标的弹窗 -->
    <n-modal v-model:show="showAddModal" preset="card" title="添加封闭基金" style="width: 420px; max-width: 92vw;" :bordered="false">
      <div style="display: flex; flex-direction: column; gap: 12px;">
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; font-weight: 700; color: var(--text-muted);">基金名称</label>
          <n-input v-model:value="addForm.name" placeholder="例如：科创封闭1年" />
        </div>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label style="font-size: 11px; font-weight: 700; color: var(--text-muted);">基金代码</label>
          <n-input v-model:value="addForm.code" placeholder="例如：508056.SH" />
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
  gap: 12px;
}

/* Kept: overview card (complex SVG ring + legend) */
.dash-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dash-title {
  font-family: 'Work Sans', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin: 0;
}

/* Kept: 总盈亏 card has a trend indicator (custom content, not converted to StatCard) */
.dash-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.dash-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}

.dash-trend {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-success);
}

.dash-trend .n-icon { font-size: 16px; }

.progress-bar {
  height: 6px;
  background: var(--border-default);
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}

.progress-fill.success { background: var(--color-success); }
.progress-fill.blue { background: var(--color-primary); }

/* Portfolio Ring */
.portfolio-ring {
  display: flex;
  justify-content: center;
  align-items: center;
  position: relative;
  height: 120px;
}

.ring-svg { width: 160px; height: 80px; }

.ring-center {
  position: absolute;
  bottom: 10px;
  text-align: center;
}

.ring-total {
  display: block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}

.ring-label {
  font-size: 10px;
  color: var(--text-muted);
  font-weight: 700;
  letter-spacing: 0.05em;
}

.legend-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  border-top: 1px solid var(--border-default);
  padding-top: 12px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* Bottom Grid */
.bottom-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.bottom-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 16px;
  height: 200px;
  display: flex;
  flex-direction: column;
}

.bottom-panel h4 {
  font-family: 'Work Sans', sans-serif;
  font-size: 11px;
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
  font-size: 12px;
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
  font-size: 10px;
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
  font-size: 13px;
  font-weight: 700;
  color: var(--color-primary);
  flex-shrink: 0;
}

.rank-yield {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.rank-yield.primary {
  color: var(--color-success);
  font-weight: 700;
  font-size: 13px;
}

/* Warning items */
.warning-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 12px;
  border-bottom: 1px solid var(--border-default);
}

.warning-item:last-child { border-bottom: none; }

.warn-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--text-muted);
}

.empty-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  font-size: 12px;
  color: var(--text-muted);
}

.sparkline-bars {
  flex: 1;
  display: flex;
  align-items: flex-end;
  gap: 4px;
}

.spark-bar {
  flex: 1;
  background: rgba(0, 94, 161, 0.3);
  border-radius: 3px 3px 0 0;
  transition: all 0.2s;
}

.spark-bar.active { background: var(--color-primary); }
.spark-bar:hover { background: var(--color-primary-hover); }

/* Responsive: collapse multi-column grids on smaller screens */
@media (max-width: 768px) {
  .bottom-grid { grid-template-columns: 1fr; }
  .legend-grid { grid-template-columns: 1fr; }
}
</style>
