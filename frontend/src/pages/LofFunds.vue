<script setup lang="ts">
defineOptions({ name: 'LofFunds' })
import { ref, computed, h, onMounted, watch } from 'vue'
import { NDataTable, NButton, NIcon, useMessage } from 'naive-ui'
import type { PaginationProps } from 'naive-ui'
import {
  TrendingUp,
  WalletOutline,
  EarthOutline,
  LockClosedOutline,
  PulseOutline,
} from '@vicons/ionicons5'
import { api, useAsyncData } from '../composables/useApi'
import type { FundItem } from '../types'
import { exportToCSV } from '../utils/export'
import { analyzeArbitrageBatch, FEASIBILITY_ORDER } from '../utils/arbitrage'
import type { ArbitrageAnalysis } from '../utils/arbitrage'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import StatCard from '../components/StatCard.vue'
import TabBar from '../components/TabBar.vue'
import LoadingState from '../components/LoadingState.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'
import { getFieldTip } from '../composables/helpContent'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: funds, loading, error, execute: refetch } = useAsyncData(() => api.getFunds('lof'))
const activeTab = ref<string>('lof')
const selectedCode = ref<string | null>(null)
const scanning = ref(false)

// 表格分页：每页默认 20 行，客户端分页（参考可转债页面）
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

// 切换 tab 时回到第一页
watch(activeTab, () => { pagination.value.page = 1 })

function scan() {
  scanning.value = true
  message.loading('正在扫描套利机会...', { duration: 1500 })
  setTimeout(() => {
    scanning.value = false
    if (activeTab.value === 'qdii') {
      const feasible = filteredFunds.value.filter(f => {
        const a = qdiiAnalysisMap.value.get(f.code)
        return a && a.feasibility === 'feasible'
      }).length
      const infeasible = filteredFunds.value.filter(f => {
        const a = qdiiAnalysisMap.value.get(f.code)
        return a && a.feasibility === 'infeasible'
      }).length
      message.success(`扫描完成：${feasible} 个可行套利，${infeasible} 个不可行(限购/资金不足)`)
    } else {
      const opportunities = filteredFunds.value.filter(f => Math.abs(f.premium_pct) > 3).length
      message.success(`扫描完成：发现 ${opportunities} 个套利机会`)
    }
  }, 1500)
}

function exportFunds() {
  const headers = ['基金名称', '代码', '类型', '价格', '预估净值', '溢价率', '百分位', '净套利收益', '成交量']
  const rows = filteredFunds.value.map(f => [
    f.name, f.code, f.type, f.price.toFixed(3), f.iopv.toFixed(3), f.premium_pct,
    f.premium_percentile ?? '', f.net_arbitrage_yield, f.volume ?? '',
  ])
  exportToCSV(`lof_funds_${activeTab.value}_${new Date().toISOString().slice(0, 10)}`, headers, rows)
  message.success(`已导出 ${rows.length} 条基金数据`)
}

// 页面加载时获取数据
onMounted(() => {
  refetch()
})

const filteredFunds = computed(() => {
  if (!funds.value) return []
  if (activeTab.value === 'lof') return funds.value.filter(f => f.type === 'lof')
  if (activeTab.value === 'qdii') {
    // QDII: 按可行性分级排序，同级按调整后收益下限降序
    return funds.value
      .filter(f => f.type === 'qdii')
      .sort((a, b) => {
        const fa = qdiiAnalysisMap.value.get(a.code)
        const fb = qdiiAnalysisMap.value.get(b.code)
        if (!fa || !fb) return Math.abs(b.premium_pct) - Math.abs(a.premium_pct)
        const orderDiff = FEASIBILITY_ORDER[fa.feasibility] - FEASIBILITY_ORDER[fb.feasibility]
        if (orderDiff !== 0) return orderDiff
        return fb.adjustedYieldLow - fa.adjustedYieldLow
      })
  }
  return funds.value.filter(f => f.type === 'closed')
})

// 全量套利可行性分析映射 (LOF/QDII/封闭均需 T+N 敞口分析)
const arbitrageAnalysisMap = computed(() => {
  if (!funds.value) return new Map<string, ArbitrageAnalysis>()
  // 对所有有套利收益的基金执行分析
  const arbitrageFunds = funds.value.filter(f => Math.abs(f.net_arbitrage_yield) > 0 || f.type === 'qdii')
  return analyzeArbitrageBatch(arbitrageFunds)
})

// 兼容旧引用
const qdiiAnalysisMap = arbitrageAnalysisMap

// 市场统计卡片：从实际数据动态计算（不再使用硬编码假数据）
const lofStats = computed(() => {
  const list = funds.value ?? []
  if (!list.length) {
    return {
      avgPremium: 0, avgPremiumStr: '—', maxDiscountStr: '—', opportunityCount: 0,
      top5AvgPremium: 0, top5AvgPremiumStr: '—', sentimentBarWidth: '0%',
      volumeSparkline: [] as number[], signals: [] as { id: string; text: string; dotClass: string }[],
    }
  }
  // 平均溢价率
  const avgPremium = list.reduce((s, f) => s + f.premium_pct, 0) / list.length
  // 最大折价（premium_pct 最小值，负值=折价）
  const maxDiscount = Math.min(...list.map(f => f.premium_pct))
  // 套利机会数（折溢价绝对值 > 3%）
  const opportunityCount = list.filter(f => Math.abs(f.premium_pct) > 3).length
  // 前5平均溢价（按溢价率绝对值降序取前5）
  const top5 = [...list].sort((a, b) => Math.abs(b.premium_pct) - Math.abs(a.premium_pct)).slice(0, 5)
  const top5AvgPremium = top5.reduce((s, f) => s + f.premium_pct, 0) / (top5.length || 1)
  // 情绪条宽度（|avgPremium| 归一化到 0-100%，上限 10%）
  const sentimentBarWidth = `${Math.min(Math.abs(avgPremium) * 10, 100)}%`
  // 成交量 sparkline：取前5按成交量降序，归一化为百分比高度
  const top5Vol = [...list].sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0)).slice(0, 5)
  const maxVol = Math.max(...top5Vol.map(f => f.volume ?? 0), 1)
  const volumeSparkline = top5Vol.map(f => Math.round(((f.volume ?? 0) / maxVol) * 100))
  // 实时信号：从实际数据生成
  const signals: { id: string; text: string; dotClass: string }[] = []
  list.filter(f => f.premium_pct > 5).slice(0, 3).forEach(f => {
    signals.push({ id: `sig-${f.code}`, text: `${f.code} 溢价 ${f.premium_pct.toFixed(2)}%`, dotClass: 'pulse' })
  })
  list.filter(f => f.premium_pct < -5).slice(0, 2).forEach(f => {
    signals.push({ id: `sig-${f.code}`, text: `${f.code} 折价 ${f.premium_pct.toFixed(2)}%`, dotClass: 'blue' })
  })
  list.filter(f => f.subscribe_limit && /限购|暂停/.test(f.subscribe_limit)).slice(0, 2).forEach(f => {
    signals.push({ id: `sig-${f.code}`, text: `${f.code} ${f.subscribe_limit}`, dotClass: 'gray' })
  })
  return {
    avgPremium,
    avgPremiumStr: `${avgPremium >= 0 ? '+' : ''}${avgPremium.toFixed(2)}%`,
    maxDiscountStr: `${maxDiscount.toFixed(2)}%`,
    opportunityCount,
    top5AvgPremium,
    top5AvgPremiumStr: `${top5AvgPremium >= 0 ? '+' : ''}${top5AvgPremium.toFixed(2)}%`,
    sentimentBarWidth,
    volumeSparkline,
    signals,
  }
})

const tabs = [
  { key: 'lof', label: 'LOF基金', icon: WalletOutline },
  { key: 'qdii', label: 'QDII', icon: EarthOutline },
  { key: 'closed', label: '封闭式', icon: LockClosedOutline },
]

function onRowClick(fund: FundItem) {
  selectedCode.value = fund.code
  message.info(`${fund.name}: ${fund.premium_pct}%`)
}

const columns = computed(() => {
  const cols: any[] = [
    {
      title: '基金名称',
      key: 'name',
      render: (row: FundItem) => h('span', { class: 'fund-name' }, row.name),
    },
    {
      title: '价格',
      key: 'price',
      align: 'right' as const,
      render: (row: FundItem) => h('span', { class: 'mono right' }, row.price.toFixed(3)),
    },
    {
      title: titleWithHelp('预估净值', 'iopv'),
      key: 'iopv',
      align: 'right' as const,
      render: (row: FundItem) => h('span', { class: 'mono right' }, row.iopv.toFixed(3)),
    },
    {
      title: titleWithHelp('溢价率', 'premium_pct'),
      key: 'premium_pct',
      align: 'right' as const,
      render: (row: FundItem) => {
        const color = row.premium_pct >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
        const text = `${row.premium_pct >= 0 ? '+' : ''}${row.premium_pct}%`
        return h('span', { class: 'mono right', style: { color } }, text)
      },
    },
    {
      title: '百分位',
      key: 'premium_percentile',
      align: 'right' as const,
      render: (row: FundItem) => {
        // 溢价百分位需历史溢价率序列，无源时后端返回 null，显示 '-' 而非伪造数值
        if (row.premium_percentile == null) return h('span', { class: 'mono right' }, '-')
        const bg = row.premium_percentile > 80
          ? 'var(--color-danger)'
          : row.premium_percentile > 50
            ? 'var(--color-warning)'
            : 'var(--color-primary)'
        return h('div', { class: 'perc-bar-cell' }, [
          h('div', { class: 'perc-bar-track' }, [
            h('div', {
              class: 'perc-bar-fill',
              style: { width: `${row.premium_percentile}%`, background: bg },
            }),
          ]),
          h('span', { class: 'perc-bar-value' }, `${row.premium_percentile}%`),
        ])
      },
    },
    {
      title: titleWithHelp('套利收益(区间)', 'net_arbitrage_yield'),
      key: 'net_arbitrage_yield',
      align: 'right' as const,
      render: (row: FundItem) => {
        const a = arbitrageAnalysisMap.value.get(row.code)
        // 无分析数据或无套利收益的品种：显示原始值或-
        if (!a) {
          if (row.net_arbitrage_yield === 0) return h('span', { class: 'mono right', style: { color: 'var(--text-muted)' } }, '-')
          const color = row.net_arbitrage_yield > 0 ? 'var(--color-success)' : 'var(--text-muted)'
          const text = `${row.net_arbitrage_yield >= 0 ? '+' : ''}${row.net_arbitrage_yield}%`
          return h('span', { class: 'mono right', style: { color } }, text)
        }
        // 不可行(限购/停牌): 划线+收益归零
        if (a.feasibility === 'infeasible') {
          return h('div', { style: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px' } }, [
            h('span', { style: { textDecoration: 'line-through', color: 'var(--text-muted)', fontSize: '11px', fontFamily: 'JetBrains Mono, monospace' } }, `+${row.net_arbitrage_yield}%`),
            h('span', { style: { fontSize: '9px', color: 'var(--color-danger)', fontWeight: 700 } }, '收益归零'),
          ])
        }
        // 显示 T+N 调整后收益区间
        const lowColor = a.adjustedYieldLow < 0 ? 'var(--color-danger)' : 'var(--color-success)'
        return h('div', { style: { display: 'flex', alignItems: 'center', gap: '2px', fontFamily: 'JetBrains Mono, monospace', fontSize: '11px' } }, [
          h('span', { style: { color: lowColor, fontWeight: 700 } }, `${a.adjustedYieldLow >= 0 ? '+' : ''}${a.adjustedYieldLow}%`),
          h('span', { style: { color: 'var(--text-muted)', fontSize: '10px' } }, ' ~ '),
          h('span', { style: { color: 'var(--color-success)', fontWeight: 700 } }, `+${a.adjustedYieldHigh}%`),
        ])
      },
    },
    {
      title: titleWithHelp('成交量', 'volume'),
      key: 'volume',
      align: 'right' as const,
      render: (row: FundItem) => row.volume != null
        ? h('span', { class: 'mono right' }, `${(row.volume / 10000).toFixed(0)}万`)
        : h('span', { class: 'mono right' }, '-'),
    },
  ]

  // 条件列：QDII/LOF tab 显示套利可行性分析
  if (activeTab.value === 'qdii' || activeTab.value === 'lof') {
    cols.push(
      {
        title: titleWithHelp('资金容量', 'capital_grade'),
        key: 'capital',
        align: 'center' as const,
        render: (row: FundItem) => {
          const a = arbitrageAnalysisMap.value.get(row.code)
          if (!a) return '-'
          const gradeStyle: Record<string, { bg: string; color: string }> = {
            A: { bg: 'var(--tag-green-bg)', color: 'var(--tag-green-text)' },
            B: { bg: 'var(--tag-orange-bg)', color: 'var(--tag-orange-text)' },
            C: { bg: 'var(--tag-red-bg)', color: 'var(--tag-red-text)' },
          }
          const s = gradeStyle[a.capitalGrade]
          return h('div', { style: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' } }, [
            h('span', { style: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '18px', height: '18px', borderRadius: '3px', background: s.bg, color: s.color, fontSize: '10px', fontWeight: 800 } }, a.capitalGrade),
            h('span', { style: { fontSize: '9px', color: 'var(--text-muted)' } }, a.capitalLabel),
          ])
        },
      },
      {
        title: 'T+N',
        key: 'holding_days',
        align: 'center' as const,
        render: (row: FundItem) => {
          const a = arbitrageAnalysisMap.value.get(row.code)
          if (!a) return '-'
          const bg = a.holdingDays >= 2 ? 'var(--tag-orange-bg)' : 'var(--tag-gray-bg)'
          const color = a.holdingDays >= 2 ? 'var(--tag-orange-text)' : 'var(--tag-gray-text)'
          return h('span', { style: { display: 'inline-block', padding: '2px 8px', borderRadius: '3px', background: bg, color, fontFamily: 'JetBrains Mono, monospace', fontSize: '10px', fontWeight: 700 } }, `T+${a.holdingDays}`)
        },
      },
      {
        title: titleWithHelp('敞口风险', 'risk_exposure'),
        key: 'risk_exposure',
        align: 'right' as const,
        render: (row: FundItem) => {
          const a = arbitrageAnalysisMap.value.get(row.code)
          if (!a) return '-'
          const exceeds = a.riskExposure > Math.abs(a.netYieldAfterCosts)
          const color = exceeds ? 'var(--color-danger)' : a.riskExposure > 2 ? 'var(--color-warning)' : 'var(--text-secondary)'
          return h('span', { style: { color, fontWeight: exceeds ? 700 : 500, fontFamily: 'JetBrains Mono, monospace' } }, `${a.riskExposure}%`)
        },
      },
      {
        title: titleWithHelp('可行性', 'feasibility'),
        key: 'feasibility',
        align: 'center' as const,
        render: (row: FundItem) => {
          const a = arbitrageAnalysisMap.value.get(row.code)
          if (!a) return '-'
          const feasStyle: Record<string, { bg: string; color: string }> = {
            feasible: { bg: 'var(--tag-green-bg)', color: 'var(--tag-green-text)' },
            risky: { bg: 'var(--tag-orange-bg)', color: 'var(--tag-orange-text)' },
            infeasible: { bg: 'var(--tag-red-bg)', color: 'var(--tag-red-text)' },
          }
          const s = feasStyle[a.feasibility]
          const children: any[] = [
            h('span', { style: { display: 'inline-block', padding: '2px 10px', borderRadius: '3px', background: s.bg, color: s.color, fontSize: '10px', fontWeight: 700 } }, a.feasibilityLabel),
          ]
          if (a.traps.length > 0) {
            children.push(h('span', { style: { fontSize: '8px', color: 'var(--color-danger)', textDecoration: 'underline dotted', cursor: 'help' }, title: a.traps.join('\n') }, `${a.traps.length}项陷阱`))
          }
          return h('div', { style: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' } }, children)
        },
      },
    )
  }

  // 条件列：仅封闭式 tab 显示（位于成交量与状态之间）
  if (activeTab.value === 'closed') {
    cols.push(
      {
        title: '剩余期限',
        key: 'remaining_term',
        align: 'right' as const,
        render: (row: FundItem) => h('span', { class: 'mono right' }, row.remaining_term ?? '-'),
      },
      {
        title: '预估收益',
        key: 'est_ytm',
        align: 'right' as const,
        render: (row: FundItem) => h('span', {
          class: 'mono right',
          style: { color: 'var(--color-primary)', fontWeight: 700 },
        }, `${row.est_ytm ?? '-'}%`),
      },
    )
  }

  cols.push({
    title: '状态',
    key: 'status',
    render: (row: FundItem) => {
      const cls = row.premium_pct > 5 ? 'premium' : row.premium_pct < -10 ? 'discount' : 'normal'
      const text = row.premium_pct > 5 ? '溢价' : row.premium_pct < -10 ? '折价' : '正常'
      return h('span', { class: ['status-tag', cls] }, text)
    },
  })

  return cols
})
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    skeleton
    :min-height="520"
    text="正在加载LOF基金数据..."
    @retry="refetch"
  >
    <div v-if="funds" class="lof-page">
    <PageHeader title="基金套利扫描" subtitle="场内基金估值与套利扫描 - 实时监控折溢价机会" helpKey="lofFunds">
      <template #actions>
        <n-button size="small" @click="exportFunds">导出</n-button>
        <n-button size="small" type="primary" :loading="scanning" @click="scan">
          <template #icon><n-icon :component="TrendingUp" /></template>
          扫描
        </n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="lofFunds" />

    <!-- 市场统计（动态计算） -->
    <div class="stat-grid">
      <StatCard label="平均溢价" :value="lofStats.avgPremiumStr" :color="lofStats.avgPremium >= 0 ? 'var(--color-danger)' : 'var(--color-success)'" :tip="getFieldTip('premium_pct')" />
      <StatCard label="最大折价" :value="lofStats.maxDiscountStr" color="var(--color-success)" :tip="getFieldTip('premium_pct')" />
      <StatCard label="套利机会" :value="lofStats.opportunityCount" color="var(--color-primary)" tip="折溢价率绝对值超过3%的基金数量，通常存在套利空间" />
      <StatCard label="基金总数" :value="funds?.length ?? 0" />
    </div>

    <!-- Tab切换 -->
    <TabBar v-model="activeTab" :tabs="tabs" />

    <!-- 基金列表 -->
    <DataPanel title="实时基金估值">
      <n-data-table
        :columns="columns"
        :data="filteredFunds"
        :row-key="(row: any) => row.code"
        :bordered="false"
        :single-line="false"
        size="small"
        :pagination="pagination"
        :row-props="(row: any) => ({ onClick: () => onRowClick(row) })"
        :row-class-name="(row: any) => {
          const classes: string[] = []
          if (selectedCode === row.code) classes.push('row-selected')
          if (activeTab === 'qdii') {
            const a = qdiiAnalysisMap.get(row.code)
            if (a?.feasibility === 'infeasible') classes.push('row-infeasible')
          }
          return classes.join(' ')
        }"
      />
      <!-- 表格底部 -->
      <div class="table-footer">
        <span class="footer-info">当前 {{ filteredFunds.length }} 条基金数据</span>
      </div>
    </DataPanel>

    <!-- 底部面板（动态计算） -->
    <div class="bottom-bento">
      <div class="bento-card">
        <span class="bento-label">市场情绪</span>
        <div class="bento-value-row">
          <span class="sentiment-value" :class="lofStats.top5AvgPremium >= 0 ? 'text-red' : 'text-green'">{{ lofStats.top5AvgPremiumStr }}</span>
          <span class="sentiment-sub">前5平均溢价</span>
        </div>
        <div class="sentiment-bar">
          <div class="sentiment-fill" :style="{ width: lofStats.sentimentBarWidth }" />
        </div>
        <span class="sentiment-note">当前溢价/折价压力指标</span>
      </div>
      <div class="bento-card">
        <span class="bento-label">成交量 Top 5</span>
        <div class="sparkline-bars">
          <div v-for="(bar, i) in lofStats.volumeSparkline" :key="i"
            :class="['spark-bar', bar >= 50 ? 'hot' : 'cold']"
            :style="{ height: bar + '%' }" />
        </div>
        <div class="sparkline-labels">
          <span>高成交量</span>
          <span>低成交量</span>
        </div>
      </div>
      <div class="bento-card">
        <span class="bento-label">实时信号</span>
        <div class="signal-list">
          <div v-for="sig in lofStats.signals" :key="sig.id" class="signal-item">
            <span :class="['signal-dot', sig.dotClass]" />
            <span class="signal-text">{{ sig.text }}</span>
          </div>
          <div v-if="lofStats.signals.length === 0" class="empty-hint">暂无信号</div>
        </div>
      </div>
    </div>

    <!-- 底部提示 -->
    <div v-if="activeTab === 'qdii'" class="insight-bar qdii-insight">
      <n-icon :component="PulseOutline" size="20" class="insight-icon" />
      <span v-if="filteredFunds.some(f => qdiiAnalysisMap.get(f.code)?.feasibility === 'infeasible')">
        <strong style="color: var(--color-danger)">QDII套利陷阱预警：</strong>
        检测到限购品种，资金容量C级，套利收益已归零。
        T+2到账期间净值波动敞口可达 4-5%，需严格评估资金容量与时间成本后再执行。
      </span>
      <span v-else>
        <strong>QDII溢价套利提示：</strong>当前QDII基金溢价处于高位，扣除成本后净套利收益为正，但需关注T+2到账敞口风险。
      </span>
    </div>
    <div v-else class="insight-bar">
      <n-icon :component="PulseOutline" size="20" class="insight-icon" />
      <span>
        <strong>QDII溢价套利提示：</strong>纳指LOF当前溢价6.25%，扣除申购赎回成本后净套利收益约1.82%，存在套利空间。
      </span>
    </div>
    </div>
  </LoadingState>
</template>

<!-- 非 scoped 样式：h() 渲染的 VNode 元素需要非 scoped 样式才能生效。
     .mono / .right 已在全局 style.css 中定义，此处仅放 LofFunds 专用的 h() 类。 -->
<style>
.fund-name {
  font-family: 'Work Sans', sans-serif !important;
  font-weight: 600;
  color: var(--text-primary);
}

.perc-bar-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100px;
}

.perc-bar-track {
  width: 60px;
  height: 4px;
  background: var(--border-default);
  border-radius: 2px;
  overflow: hidden;
}

.perc-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease, background 0.3s ease;
}

.perc-bar-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-muted);
  min-width: 28px;
}

.status-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 2px;
  font-family: 'Work Sans', sans-serif;
  font-size: 10px;
  font-weight: 700;
  border: 1px solid transparent;
}

.status-tag.premium {
  background: var(--tag-red-bg);
  color: var(--tag-red-text);
  border-color: rgba(186, 26, 26, 0.2);
}

.status-tag.discount {
  background: var(--tag-blue-bg);
  color: var(--tag-blue-text);
  border-color: rgba(0, 94, 161, 0.2);
}

.status-tag.normal {
  background: var(--tag-gray-bg);
  color: var(--tag-gray-text);
  border-color: rgba(113, 119, 130, 0.2);
}

/* 选中行高亮（NDataTable 行类名） */
.n-data-table-tr.row-selected {
  background: rgba(0, 94, 161, 0.06) !important;
}

.n-data-table-tr.row-selected td:first-child {
  box-shadow: inset 3px 0 0 var(--color-primary);
}

/* 不可行行灰化（QDII限购/停牌） */
.n-data-table-tr.row-infeasible {
  opacity: 0.45;
  background: var(--bg-subtle) !important;
}
.n-data-table-tr.row-infeasible:hover {
  opacity: 0.7;
}
</style>

<style scoped>
.lof-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 16px;
  border-top: 1px solid var(--border-default);
  background: var(--bg-overlay);
  height: 32px;
}

.footer-info {
  font-family: 'Work Sans', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.bottom-bento {
  display: grid;
  grid-template-columns: 3fr 5fr 4fr;
  gap: 14px;
  height: 160px;
}

.bento-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: var(--shadow-card);
  transition: box-shadow 0.2s;
}

.bento-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.bento-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  text-transform: uppercase;
}

.bento-value-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.sentiment-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px;
  font-weight: 700;
}

.sentiment-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.sentiment-bar {
  height: 4px;
  background: rgba(186, 26, 26, 0.12);
  border-radius: 2px;
  overflow: hidden;
}

.sentiment-fill {
  height: 100%;
  width: 75%;
  background: var(--color-danger);
  border-radius: 2px;
}

.sentiment-note {
  font-size: 12px;
  color: var(--text-muted);
  font-style: italic;
}

.sparkline-bars {
  flex: 1;
  display: flex;
  align-items: flex-end;
  gap: 2px;
}

.spark-bar {
  flex: 1;
  border-radius: 2px 2px 0 0;
  transition: all 0.2s;
  min-height: 4px;
}

.spark-bar.hot {
  background: rgba(186, 26, 26, 0.35);
  border-top: 2px solid var(--color-danger);
}

.spark-bar.cold {
  background: rgba(0, 94, 161, 0.3);
  border-top: 2px solid var(--color-primary);
}

.spark-bar:hover {
  opacity: 0.8;
  transform: scaleY(1.05);
  transform-origin: bottom;
}

.sparkline-labels {
  display: flex;
  justify-content: space-between;
  font-family: 'Work Sans', sans-serif;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.signal-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}

.signal-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.signal-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.signal-dot.pulse {
  background: var(--color-danger);
  animation: pulse 2s infinite;
}

.signal-dot.blue {
  background: var(--color-primary);
}

.signal-dot.gray {
  background: var(--text-placeholder);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.signal-text {
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.empty-hint {
  font-size: 12px;
  color: var(--text-muted);
  font-style: italic;
}

.insight-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-secondary);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: box-shadow 0.2s;
}

.insight-bar:hover {
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
}

.insight-icon {
  color: var(--color-warning);
}

.insight-bar.qdii-insight {
  border-left: 3px solid var(--color-danger);
}

/* Responsive: collapse multi-column grids on smaller screens */
@media (max-width: 1280px) {
  .bottom-bento { grid-template-columns: 1fr 1fr; }
}

@media (max-width: 768px) {
  .bottom-bento { grid-template-columns: 1fr; height: auto; }
  .table-footer { flex-wrap: wrap; gap: 8px; }
  .insight-bar { flex-wrap: wrap; }
}
</style>
