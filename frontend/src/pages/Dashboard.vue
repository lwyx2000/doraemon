<script setup lang="ts">
defineOptions({ name: 'Dashboard' })
import { ref, computed, h, onMounted } from 'vue'
import { NDataTable, NButton, NIcon, useMessage, NTabs, NTabPane } from 'naive-ui'
import { TrendingUp, WarningOutline, CheckmarkCircleOutline, ChevronDownOutline, ChevronUpOutline, SparklesOutline } from '@vicons/ionicons5'
import { api } from '../utils/api'
import { pctColor } from '../utils/percentile'
import { formatBackendTime } from '../utils/time'
import type {
  MacroIndicators,
  IndexValuation,
  MarketOverview as MarketOverviewData, // 与组件 MarketOverview.vue 重名，需别名
  BoardSector,
  FundFlows,
  ZTStats,
  FundRankingItem,
  SectionSourceMeta,
  SwSector,
  FearGreedLatest,
  FearGreedPoint,
} from '../types'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import LoadingState from '../components/LoadingState.vue'
import SectionSkeleton from '../components/SectionSkeleton.vue'
import SectionFallback from '../components/SectionFallback.vue'
import FieldHelp from '../components/FieldHelp.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import MarketOverview from '../components/MarketOverview.vue'
import BoardSectorPanel from '../components/BoardSectorPanel.vue'
import SwHeatmap from '../components/SwHeatmap.vue'
import FundFlowPanel from '../components/FundFlowPanel.vue'
import ZTStatsPanel from '../components/ZTStatsPanel.vue'
import FundRankingPanel from '../components/FundRankingPanel.vue'
import FearGreedPanel from '../components/FearGreedPanel.vue'
import AiInterpretModal from '../components/AiInterpretModal.vue'
import { useFieldHelp } from '../composables/useFieldHelp'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const valuationCollapsed = ref(true)

// 使用真实API数据（分区接口：并行调用，各模块互不影响）
const indicators = ref<MacroIndicators | null>(null)
const indices = ref<IndexValuation[]>([])
const marketOverview = ref<MarketOverviewData | null>(null)
const boardSectors = ref<BoardSector[]>([])
const fundFlows = ref<FundFlows | null>(null)
const ztStats = ref<ZTStats | null>(null)
const fundRanking = ref<FundRankingItem[]>([])
const swSectors = ref<SwSector[]>([])
const fearGreedLatest = ref<FearGreedLatest | null>(null)
const fearGreedHistory = ref<FearGreedPoint[]>([])

// AI 解读弹窗（后端组装真实数据 + 知识库口径）
const showAiInterpret = ref(false)

// 各分区数据来源标记（真实/模拟）
const sectionSources = ref<Record<string, SectionSourceMeta>>({})

type SectionKey = 'indicators' | 'indices' | 'overview' | 'boardSectors' | 'fundFlows' | 'ztStats' | 'fundRanking' | 'swSectors' | 'fearGreed'
const TOTAL_SECTIONS = 9

// 各分区加载状态：骨架屏按分区独立显示，任一接口完成即渲染对应模块
const sectionLoading = ref<Record<SectionKey, boolean>>({
  indicators: true,
  indices: true,
  overview: true,
  boardSectors: true,
  fundFlows: true,
  ztStats: true,
  fundRanking: true,
  swSectors: true,
  fearGreed: true,
})

const error = ref<string | null>(null)
const refreshing = ref(false)
const activeMarket = ref<'a_share' | 'hk' | 'us'>('a_share')

// 各分区失败标记：用于渲染失败兜底（带重试），与加载中/内容互斥
const sectionError = ref<Record<SectionKey, boolean>>({
  indicators: false,
  indices: false,
  overview: false,
  boardSectors: false,
  fundFlows: false,
  ztStats: false,
  fundRanking: false,
  swSectors: false,
  fearGreed: false,
})

// 单分区重试闭包注册表（fetchMacroData 时填充）
const sectionRetries = ref<Partial<Record<SectionKey, () => void>>>({})

function retrySection(key: SectionKey) {
  sectionRetries.value[key]?.()
}

const anySectionLoading = computed(() =>
  Object.values(sectionLoading.value).some(v => v)
)

const hasData = computed(() =>
  !!indicators.value ||
  indices.value.length > 0 ||
  !!marketOverview.value ||
  boardSectors.value.length > 0 ||
  !!fundFlows.value ||
  !!ztStats.value ||
  fundRanking.value.length > 0 ||
  swSectors.value.length > 0 ||
  !!fearGreedLatest.value
)

let failedCount = 0
let settledCount = 0

function loadSection<T>(
  key: SectionKey,
  request: Promise<{ data: T; meta?: SectionSourceMeta }>,
  assign: (data: T) => void,
): Promise<void> {
  sectionLoading.value[key] = true
  sectionError.value[key] = false
  return request
    .then((res) => {
      assign(res.data)
      sectionSources.value[key] = res.meta ?? { isMock: true }
    })
    .catch(() => {
      failedCount += 1
      sectionError.value[key] = true
      sectionSources.value[key] = { isMock: true, dataSource: '加载失败' }
    })
    .finally(() => {
      sectionLoading.value[key] = false
      settledCount += 1
      if (settledCount >= TOTAL_SECTIONS) {
        if (failedCount === TOTAL_SECTIONS) {
          error.value = '获取数据失败'
          message.error(error.value)
        } else if (failedCount > 0) {
          error.value = `部分数据加载失败 (${failedCount}/${TOTAL_SECTIONS})`
          message.warning(error.value)
        }
      }
    })
}

/**
 * 注册并触发单个分区的加载；把重试闭包存入 sectionRetries，供 retrySection 复用。
 * 每个 api.* 调用都返回全新 Promise，因此重试可安全重新发起请求。
 */
function reg(
  key: SectionKey,
  req: () => Promise<{ data: any; meta?: SectionSourceMeta }>,
  assign: (d: any) => void,
): Promise<void> {
  const run = () => loadSection(key, req(), assign)
  sectionRetries.value[key] = run
  return run()
}

async function fetchMacroData(force = false) {
  failedCount = 0
  settledCount = 0
  error.value = null
  const t0 = performance.now()
  await Promise.all([
    reg('indicators', () => api.getMacroIndicators(), (d) => { indicators.value = d }),
    reg('indices', () => api.getIndices(), (d) => { indices.value = d }),
    // overview 带 15s 短缓存 + SWR 后台刷新（2026-10-19 重定，原 600s）；
    // 仅刷新按钮 force 穿透，SWR 过期有旧值时立即返旧值后台限流刷新
    reg('overview', () => api.getMarketOverview(force), (d) => { marketOverview.value = d }),
    reg('boardSectors', () => api.getMarketBoardSectors(), (d) => { boardSectors.value = d }),
    reg('fundFlows', () => api.getMarketFundFlows(), (d) => { fundFlows.value = d }),
    reg('ztStats', () => api.getMarketZTStats(), (d) => { ztStats.value = d }),
    reg('fundRanking', () => api.getMarketFundRanking(), (d) => { fundRanking.value = d }),
    reg('swSectors', () => api.getSwSectors(), (d) => { swSectors.value = d }),
    reg('fearGreed', async () => {
      const [latestRes, historyRes] = await Promise.all([
        api.getFearGreedLatest(),
        api.getFearGreedHistory(90),
      ])
      return {
        data: { latest: latestRes.data, history: historyRes.data || [] },
        meta: latestRes.meta,
      }
    }, (d) => {
      fearGreedLatest.value = d.latest
      fearGreedHistory.value = d.history
    }),
  ])
  sysLatency.value = Math.round(performance.now() - t0)
}

onMounted(() => {
  fetchMacroData()
})

async function refresh() {
  refreshing.value = true
  message.loading('正在刷新宏观数据...', { duration: 1200 })
  try {
    // force=true：overview 穿透 15s 缓存（其余区无缓存，语义不变）
    await fetchMacroData(true)
    if (hasData.value) {
      message.success(`已刷新 ${indices.value.length} 个指数数据`)
    }
  } finally {
    refreshing.value = false
  }
}

const allSectionsMock = computed(() => {
  const sources = Object.values(sectionSources.value)
  if (sources.length === 0) return true
  return sources.every(s => s.isMock)
})

const mockTimeText = computed(() => {
  const s = Object.values(sectionSources.value).find(x => x.mockTime)
  // 与 pageUpdatedAtText 同理：mockTime 也是容器 UTC 的 naive 串，按 UTC 解析转本地
  return formatBackendTime(s?.mockTime)
})

const dataSourceText = computed(() => {
  const real = Object.values(sectionSources.value).find(x => !x.isMock)
  return real?.dataSource ?? '实时行情'
})

// 全页数据更新时间：取各分区 updateTime 中最新的一个（后端 _build_meta 的取数时刻）
const pageUpdatedAt = computed(() => {
  const times = Object.values(sectionSources.value)
    .map(s => s.updateTime)
    .filter((t): t is string => !!t)
    .sort()
  return times.length ? times[times.length - 1] : null
})

// banner 展示用本地化时间：后端 updateTime 是容器 UTC 的 naive 串，
// 直接插值会显示 UTC 墙钟（比 CST 少 8 小时，像过期其实才生成），
// PageHeader 内部已做同样转换（2026-10-19 修复）
const pageUpdatedAtText = computed(() => formatBackendTime(pageUpdatedAt.value))

// ERP 股债利差 3年分位：按全局"分位越高色温越高"标准机械映射（高分位=红）。
// 注：ERP 分位越高=市场越便宜=越好，但视觉上仍显红，属一致性映射，不在此反转。
const erpColor = computed(() => (indicators.value ? pctColor(indicators.value.erp_percentile_3y) : '#8b919e'))

const filteredIndices = computed(() =>
  indices.value.filter(idx => idx.market === activeMarket.value)
)

const marketStats = computed(() => {
  const list = indices.value.filter(idx => idx.market === activeMarket.value)
  if (list.length === 0) return null
  // 仅对具备估值数据的指数求均值（科创板/科创50/中证A500 暂无估值，跳过）
  const valued = list.filter(idx => idx.hasValuation !== false && idx.pe != null && idx.pb != null)
  const undervalued = list.filter(idx => idx.category === 'undervalued').length
  const overvalued = list.filter(idx => idx.category === 'overvalued').length
  // 无任何具备估值的指数时均值置 null（模板显示"—"），不用 ||1 兜底制造假的 0.0
  const avgPE = valued.length
    ? (valued.reduce((sum, idx) => sum + (idx.pe ?? 0), 0) / valued.length).toFixed(1)
    : null
  const avgPB = valued.length
    ? (valued.reduce((sum, idx) => sum + (idx.pb ?? 0), 0) / valued.length).toFixed(2)
    : null
  return { avgPE, avgPB, undervalued, overvalued, total: list.length }
})

// 真实派生指标（取代原硬编码的 35% / 1,242 / 428 / 112 / 12ms）
const sysLatency = ref<number | null>(null)

const marketHeat = computed(() => {
  const ov = marketOverview.value
  if (!ov) return 0
  const total = ov.upCount + ov.downCount
  return total > 0 ? Math.round((ov.upCount / total) * 100) : 0
})

const indicesTotal = computed(() => indices.value.length)

const undervaluedCount = computed(() =>
  indices.value.filter(i => i.category === 'undervalued' || i.category === 'opportunity').length
)
const overvaluedCount = computed(() =>
  indices.value.filter(i => i.category === 'overvalued').length
)

// 指数估值区数据时间：优先展示真实数据日期（行情快照 + 估值快照），
// 二者都缺失时才回退到接口响应时间（updateTime 是后端响应时刻，并非数据时刻）
const indicesUpdateMeta = computed(() => {
  const src = sectionSources.value.indices
  const time = src?.updateTime || src?.mockTime
  const dataDate = indices.value.find(i => i.valuation_date)?.valuation_date
  const peAsOf = indices.value.find(i => i.pe_as_of)?.pe_as_of
  const parts: string[] = []
  if (dataDate) parts.push(`行情 ${dataDate}`)
  if (peAsOf) parts.push(`估值快照 ${peAsOf}`)
  if (parts.length > 0) return parts.join(' · ')
  return time ? `Last update: ${time}` : 'Last update: —'
})

// 申万热力图数据更新时间（后端 meta.updateTime = 取数时刻；sw-sectors 进程内缓存 3 分钟，失败态 30s）
const swSectorsUpdatedAt = computed(() => sectionSources.value.swSectors?.updateTime ?? null)

// 宏观指标区是否有有效数据：空对象/无关键利率数据时不渲染4个指标卡片
const hasIndicatorsData = computed(() => {
  return !!indicators.value && Object.keys(indicators.value).length > 0 &&
    (indicators.value.erp !== undefined || indicators.value.dr007 !== undefined || indicators.value.gc001 !== undefined)
})

// CATEGORY 估值分类本地化（后端返回 undervalued/overvalued/normal/opportunity）
const CATEGORY_LABEL: Record<string, string> = {
  undervalued: '低估',
  opportunity: '极度低估',
  normal: '正常',
  overvalued: '高估',
  unknown: '—',
}

const columns = [
  { title: 'INDEX NAME', key: 'name', width: 160, render: (row: any) => row.name },
  { title: 'LEVEL', key: 'level', width: 100, align: 'right' as const,
    // ⚠️ 判空：上游降级 / 字段缺失时 level 可能为 undefined，`undefined.toLocaleString()` 会抛
    render: (row: any) => (row.level == null ? '—' : Number(row.level).toLocaleString()) },
  { title: 'CHG%', key: 'change_pct', width: 90, align: 'right' as const,
    render: (row: any) => {
      // ⚠️ 上游 `index_realtime_sw` 超时/挂掉时，后端会降级返回**只有估值、没有涨跌幅**
      //   的数据（price / change_pct 为 null，后端 2026-08 新增的兜底）。
      //   这里**必须显式判空**——直接 `.toFixed()` 会在 null 上抛 TypeError **整页白屏**。
      const v = row.change_pct
      if (v == null || Number.isNaN(Number(v))) {
        return h('span', { style: { color: 'var(--text-tertiary)' } }, '—')
      }
      // 涨红跌绿（A股惯例，与全站其余面板一致）
      const color = v >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
      return h('span', { style: { color } },
        `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`)
    },
  },
  { title: titleWithHelp('PE PERCENTILE', 'pe_percentile'), key: 'pe_percentile', width: 130, align: 'center' as const,
    render: (row: any) =>
      row.hasValuation === false || row.pe_percentile == null
        ? h('span', { class: 'percentile-label' }, '—')
        : h('div', { class: 'percentile-cell' }, [
            h('div', { class: 'percentile-track' }, [
              h('div', { class: 'percentile-needle', style: { left: `${row.pe_percentile}%`, background: pctColor(row.pe_percentile) } }),
            ]),
            h('span', { class: 'percentile-label', style: { color: pctColor(row.pe_percentile) } }, `${row.pe_percentile}%`),
          ]),
  },
  { title: titleWithHelp('PB PERCENTILE', 'pb_percentile'), key: 'pb_percentile', width: 130, align: 'center' as const,
    render: (row: any) =>
      row.hasValuation === false || row.pb_percentile == null
        ? h('span', { class: 'percentile-label' }, '—')
        : h('div', { class: 'percentile-cell' }, [
            h('div', { class: 'percentile-track' }, [
              h('div', { class: 'percentile-needle', style: { left: `${row.pb_percentile}%`, background: pctColor(row.pb_percentile) } }),
            ]),
            h('span', { class: 'percentile-label', style: { color: pctColor(row.pb_percentile) } }, `${row.pb_percentile}%`),
          ]),
  },
  { title: 'CATEGORY', key: 'category', width: 120,
    render: (row: any) => {
      // 高分红类指数（上证红利/深证红利等）PE 分位触顶多因基数极低（盈利上行期 PE 仍翻倍），
      // 绝对 PE < 12 时软化为「高估·PE绝对低」橙色警示，避免一律标红误导（2026-10-13）
      if (row.category === 'overvalued' && row.pe != null && Number(row.pe) < 12) {
        return h('span', { class: ['category-tag', 'overvalued-soft'] }, '高估·PE绝对低')
      }
      return h('span', { class: ['category-tag', row.category] }, CATEGORY_LABEL[row.category] ?? row.category)
    },
  },
  { title: titleWithHelp('近3月涨跌', 'change_3m_pct'), key: 'change_3m_pct', width: 110, align: 'right' as const,
    render: (row: any) => {
      // ⚠️ 同 CHG%：上游降级时可能为 null，必须判空（否则整页白屏）
      const v = row.change_3m_pct
      if (v == null || Number.isNaN(Number(v))) {
        return h('span', { style: { color: 'var(--text-tertiary)' } }, '—')
      }
      const color = v >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
      return h('span', { style: { color } },
        `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`)
    },
  },
  { title: titleWithHelp('近1年涨跌', 'change_1y_pct'), key: 'change_1y_pct', width: 110, align: 'right' as const,
    render: (row: any) => {
      // 同口径 PB/PE 历史序列月度桶实算（替代原 win_rate——250日上涨日占比恒≈50% 无区分度）；
      // ⚠️ 判空：无历史序列的指数（科创综指）为 null，直接 toFixed 会抛
      const v = row.change_1y_pct
      if (v == null || Number.isNaN(Number(v))) {
        return h('span', { style: { color: 'var(--text-tertiary)' } }, '—')
      }
      const color = v >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
      return h('span', { style: { color } },
        `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`)
    },
  },
  { title: titleWithHelp('估值胜率', 'win_rate'), key: 'win_rate', width: 100, align: 'center' as const,
    render: (row: any) => {
      // 条件胜率：历史上与当前 PE 相当(±10%)的月份持有 3 个月的正收益占比（同口径月度序列实算）；
      // ⚠️ 判空：无历史序列 / 可比样本<10 个月（科创综指等）为 null
      const v = row.win_rate
      if (v == null || Number.isNaN(Number(v))) {
        return h('span', { style: { color: 'var(--text-tertiary)' } }, '—')
      }
      // >60% 历史统计有利（蓝），<40% 谨慎（橙），中间默认色
      const style: Record<string, string> = { fontWeight: '700' }
      if (v >= 60) style.color = 'var(--tag-blue-text)'
      else if (v < 40) style.color = 'var(--tag-orange-text)'
      return h('span', { style }, `${Number(v).toFixed(1)}%`)
    },
  },
]

function handleCheckedChange(keys: (string | number)[]) {
  if (keys.length === 0) return
  const names = indices.value
    .filter(idx => keys.includes(idx.name))
    .map(idx => idx.name)
  message.info(`已选 ${keys.length} 个指数: ${names.join(', ')}`)
}
</script>

<template>
  <!-- 全部加载失败：错误页（可重试） -->
  <LoadingState
    v-if="!hasData && !anySectionLoading"
    :loading="false"
    :error="error || '获取数据失败'"
    :min-height="480"
    text="正在加载宏观数据..."
    @retry="fetchMacroData"
  />

  <!-- 分区加载：页面直接渲染，各模块独立显示骨架屏 -->
  <div v-else class="dashboard-page">
    <template v-if="hasData">
    <!-- 数据来源标记（按各分区 meta 汇总） -->
    <div v-if="allSectionsMock" class="data-source-banner mock">
      <n-icon :component="WarningOutline" />
      <span>当前显示模拟数据 ({{ mockTimeText }}) - 真实数据源待接入</span>
    </div>
    <div v-else class="data-source-banner real">
      <n-icon :component="CheckmarkCircleOutline" />
      <span>数据来源: {{ dataSourceText }}</span>
      <span v-if="pageUpdatedAt" class="banner-updated">数据更新于 {{ pageUpdatedAtText }}（非实时，缓存数据，点「刷新」可强制更新）</span>
    </div>
    </template>

    <!-- Page Header -->
    <PageHeader title="A股大盘行情看板" subtitle="实时行情、板块涨幅、资金流向、龙虎榜" helpKey="dashboard" :updated-at="pageUpdatedAt">
      <template #actions>
        <n-button size="small" @click="showAiInterpret = true">
          <template #icon><n-icon :component="SparklesOutline" /></template>
          AI 解读
        </n-button>
        <n-button size="small" :loading="refreshing" @click="refresh">
          <template #icon><n-icon :component="TrendingUp" /></template>
          刷新
        </n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="dashboard" />

    <!-- 市场概况（骨架屏 ↔ 内容平滑过渡） -->
    <Transition name="fade" mode="out-in">
      <SectionSkeleton v-if="sectionLoading.overview" key="skeleton" variant="overview" />
      <MarketOverview v-else-if="marketOverview" key="content" :overview="marketOverview" />
      <SectionFallback v-else key="fallback" :error="sectionError.overview ? '加载失败，请点击重试' : null" :gateway-empty="!sectionSources.overview?.isMock && sectionSources.overview?.gatewayEmpty" :min-height="200" @retry="retrySection('overview')" />
    </Transition>

    <!-- 贪婪恐惧指数（情绪温度计；完整口径/历史见详情页 /fear-greed） -->
    <Transition name="fade" mode="out-in">
      <SectionSkeleton v-if="sectionLoading.fearGreed" key="skeleton" variant="card" :rows="4" />
      <FearGreedPanel
        v-else-if="fearGreedLatest"
        key="content"
        :latest="fearGreedLatest"
        :history="fearGreedHistory"
      />
      <SectionFallback v-else key="fallback" :error="sectionError.fearGreed ? '加载失败，请点击重试' : null" :gateway-empty="!sectionSources.fearGreed?.isMock && sectionSources.fearGreed?.gatewayEmpty" :min-height="160" @retry="retrySection('fearGreed')" />
    </Transition>

    <!-- 新布局：板块 + 资金 + 涨跌停 + 龙虎榜 -->
    <div class="market-data-grid">
      <!-- 板块涨幅 -->
      <Transition name="fade" mode="out-in">
        <SectionSkeleton v-if="sectionLoading.boardSectors" key="skeleton" variant="card" :rows="6" />
        <BoardSectorPanel
          v-else-if="boardSectors.length > 0"
          key="content"
          :sectors="boardSectors"
          title="板块涨幅排行"
          :max-items="6"
        />
        <SectionFallback v-else key="fallback" :error="sectionError.boardSectors ? '加载失败，请点击重试' : null" :gateway-empty="!sectionSources.boardSectors?.isMock && sectionSources.boardSectors?.gatewayEmpty" :min-height="160" @retry="retrySection('boardSectors')" />
      </Transition>

      <!-- 资金流向 -->
      <Transition name="fade" mode="out-in">
        <SectionSkeleton v-if="sectionLoading.fundFlows" key="skeleton" variant="flow" />
        <FundFlowPanel
          v-else-if="fundFlows"
          key="content"
          :fund-flows="fundFlows"
          title="资金流向"
        />
        <SectionFallback v-else key="fallback" :error="sectionError.fundFlows ? '加载失败，请点击重试' : null" :gateway-empty="!sectionSources.fundFlows?.isMock && sectionSources.fundFlows?.gatewayEmpty" :min-height="160" @retry="retrySection('fundFlows')" />
      </Transition>

      <!-- 涨跌停统计 -->
      <Transition name="fade" mode="out-in">
        <SectionSkeleton v-if="sectionLoading.ztStats" key="skeleton" variant="card" :rows="4" />
        <ZTStatsPanel
          v-else-if="ztStats"
          key="content"
          :zt-stats="ztStats"
          title="涨跌停统计"
        />
        <SectionFallback v-else key="fallback" :error="sectionError.ztStats ? '加载失败，请点击重试' : null" :gateway-empty="!sectionSources.ztStats?.isMock && sectionSources.ztStats?.gatewayEmpty" :min-height="160" @retry="retrySection('ztStats')" />
      </Transition>

      <!-- 基金涨跌排行 -->
      <Transition name="fade" mode="out-in">
        <SectionSkeleton v-if="sectionLoading.fundRanking" key="skeleton" variant="card" :rows="6" />
        <FundRankingPanel
          v-else-if="fundRanking.length > 0"
          key="content"
          :funds="fundRanking"
          title="基金涨跌排行"
          :max-items="6"
        />
        <SectionFallback v-else key="fallback" :error="sectionError.fundRanking ? '加载失败，请点击重试' : null" :gateway-empty="!sectionSources.fundRanking?.isMock && sectionSources.fundRanking?.gatewayEmpty" :min-height="160" @retry="retrySection('fundRanking')" />
      </Transition>
    </div>

    <!-- 申万一级行业热力图 -->
    <Transition name="fade" mode="out-in">
      <SectionSkeleton v-if="sectionLoading.swSectors" key="skeleton" variant="card" :rows="6" />
      <SwHeatmap
        v-else-if="swSectors.length > 0"
        key="content"
        :sectors="swSectors"
        title="A股行业热力图（申万一级）"
        :updated-at="swSectorsUpdatedAt"
      />
      <SectionFallback v-else key="fallback" :error="sectionError.swSectors ? '加载失败，请点击重试' : null" :gateway-empty="!sectionSources.swSectors?.isMock && sectionSources.swSectors?.gatewayEmpty" :min-height="160" @retry="retrySection('swSectors')" />
    </Transition>

    <!-- 跨市场指数估值（默认收起） -->
    <div class="market-valuation-section">
      <div class="section-header" @click="valuationCollapsed = !valuationCollapsed" :class="{ collapsed: valuationCollapsed }">
        <h3 class="section-title">
          跨市场指数估值
          <n-icon :component="valuationCollapsed ? ChevronDownOutline : ChevronUpOutline" size="18" class="section-chevron" />
        </h3>
        <div v-if="marketStats && !valuationCollapsed" class="market-stats">
          <span class="stat-item">平均PE: {{ marketStats.avgPE ?? '—' }}</span>
          <span class="stat-item">平均PB: {{ marketStats.avgPB ?? '—' }}</span>
          <span class="stat-item undervalued">低估: {{ marketStats.undervalued }}</span>
          <span class="stat-item overvalued">高估: {{ marketStats.overvalued }}</span>
        </div>
      </div>
      
      <div v-show="!valuationCollapsed">
      <n-tabs v-model:value="activeMarket" type="segment" class="market-tabs">
        <n-tab-pane name="a_share" tab="A股">
          <div class="market-description">中国A股市场主要宽基指数</div>
        </n-tab-pane>
        <n-tab-pane name="hk" tab="港股">
          <div class="market-description">香港股市主要指数</div>
        </n-tab-pane>
        <n-tab-pane name="us" tab="美股">
          <div class="market-description">美国股市主要指数</div>
        </n-tab-pane>
      </n-tabs>

      <!-- ERP & Rate Cards (仅A股显示，骨架屏 ↔ 内容平滑过渡) -->
      <div v-if="activeMarket === 'a_share'">
        <Transition name="fade" mode="out-in">
          <SectionSkeleton v-if="sectionLoading.indicators" key="skeleton" variant="metric" />
          <div v-else-if="hasIndicatorsData" key="content" class="metric-grid">
        <div class="metric-card">
          <span class="metric-label">ERP (股权风险溢价)<FieldHelp field="erp" /></span>
          <div class="metric-value-row">
            <span class="metric-value" :style="{ color: erpColor }">{{ indicators?.erp }}%</span>
            <div class="percentile-indicator">
              <div class="percentile-bar">
                <div class="percentile-fill" :style="{ width: `${indicators?.erp_percentile_3y}%`, background: erpColor }" />
              </div>
              <span class="percentile-text">3Y: {{ indicators?.erp_percentile_3y }}%</span>
            </div>
          </div>
          <div class="metric-footnotes">
            <span>5Y: {{ indicators?.erp_percentile_5y }}%</span>
            <span>10Y: {{ indicators?.erp_percentile_10y }}%</span>
          </div>
        </div>

        <div class="metric-card">
          <span class="metric-label">DR007<FieldHelp field="dr007" /></span>
          <div class="metric-value-row">
            <span class="metric-value">{{ indicators?.dr007 }}%</span>
          </div>
          <div class="metric-footnotes">存款类机构7天质押式回购</div>
        </div>

        <div class="metric-card">
          <span class="metric-label">GC001<FieldHelp field="gc001" /></span>
          <div class="metric-value-row">
            <span class="metric-value">{{ indicators?.gc001 }}%</span>
          </div>
          <div class="metric-footnotes">上交所1天国债回购</div>
        </div>

        <div class="metric-card">
          <span class="metric-label">Market Heat</span>
          <div class="metric-value-row">
            <span class="metric-value" style="color: #005ea1">{{ marketHeat }}%</span>
          </div>
          <div class="heat-track">
            <div class="heat-gradient" />
            <div class="heat-needle" :style="{ left: marketHeat + '%' }" />
          </div>
          <div class="metric-footnotes">上涨家数占比（实时）</div>
        </div>
          </div>
          <SectionFallback v-else key="fallback" :error="sectionError.indicators ? '加载失败，请点击重试' : null" :min-height="120" @retry="retrySection('indicators')" />
        </Transition>
      </div>

      <!-- Index Valuation Table -->
      <DataPanel :title="`${activeMarket === 'a_share' ? 'A股' : activeMarket === 'hk' ? '港股' : '美股'}指数估值`" :meta="indicesUpdateMeta">
        <Transition name="fade" mode="out-in">
          <SectionSkeleton v-if="sectionLoading.indices" key="skeleton" variant="table" :rows="6" />
          <n-data-table
            v-else-if="filteredIndices.length > 0"
            key="content"
            :columns="columns"
          :data="filteredIndices"
          :row-key="(row: any) => row.name"
          :bordered="false"
          :single-line="false"
          size="small"
          :row-class-name="() => 'data-row'"
          @update:checked-row-keys="handleCheckedChange"
          />
          <SectionFallback v-else key="fallback" :error="sectionError.indices ? '加载失败，请点击重试' : null" :gateway-empty="!sectionSources.indicators?.isMock && sectionSources.indicators?.gatewayEmpty" :min-height="240" :empty-text="filteredIndices.length === 0 ? '当前市场暂无指数数据' : '暂无数据'" @retry="retrySection('indices')" />
        </Transition>
      </DataPanel>
      </div>
    </div>

    <!-- Bottom Stats -->
    <div class="bottom-stats">
      <div class="stat-item">
        <span class="stat-label">市场热度</span>
        <div class="heat-bar">
          <div class="heat-gradient" />
          <div class="heat-needle" :style="{ left: marketHeat + '%' }" />
        </div>
        <span class="stat-value">{{ marketHeat }}%</span>
      </div>
      <div class="stat-divider" />
      <div class="stat-item">
        <span class="stat-label">指数总数</span>
        <span class="stat-value">{{ indicesTotal }}</span>
      </div>
      <div class="stat-divider" />
      <div class="stat-item">
        <span class="stat-label text-blue">低估</span>
        <span class="stat-value text-blue">{{ undervaluedCount }}</span>
      </div>
      <div class="stat-divider" />
      <div class="stat-item">
        <span class="stat-label text-red">高估</span>
        <span class="stat-value text-red">{{ overvaluedCount }}</span>
      </div>
      <div class="stat-divider" />
      <div class="stat-item right">
        <span class="stat-label">系统延迟: {{ sysLatency ?? '—' }}ms</span>
      </div>
    </div>

    <!-- AI 解读（真实数据 + 知识库口径 → LLM 流式） -->
    <AiInterpretModal v-model:show="showAiInterpret" context-type="dashboard" title="AI 解读 · 宏观看板" />
  </div>
</template>

<!-- Global styles for h()-rendered table cells (not scoped so VNodes get the styles) -->
<style>
.percentile-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.percentile-track {
  width: 80px;
  height: 4px;
  background: var(--border-default);
  border-radius: 2px;
  position: relative;
}

.percentile-needle {
  position: absolute;
  top: -3px;
  width: 2px;
  height: 10px;
  background: var(--color-primary);
  border-radius: 1px;
  transition: left 0.3s ease;
}

.percentile-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-muted);
}

.category-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 2px;
  font-family: 'Work Sans', sans-serif;
  font-size: 10px;
  font-weight: 700;
}
.category-tag.undervalued,
.category-tag.opportunity {
  background: var(--tag-blue-bg);
  color: var(--tag-blue-text);
}
.category-tag.normal {
  background: var(--tag-gray-bg);
  color: var(--tag-gray-text);
}
.category-tag.overvalued {
  background: var(--tag-red-bg);
  color: var(--tag-red-text);
}
/* 高分红类指数：分位触顶但绝对 PE 仍低（<12），软化为橙色警示而非红色高估 */
.category-tag.overvalued-soft {
  background: var(--tag-orange-bg);
  color: var(--tag-orange-text);
}
</style>

<style scoped>
.dashboard-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 骨架屏 ↔ 内容平滑过渡（out-in：骨架淡出后内容淡入） */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 数据来源标记横幅 */
.data-source-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
}

.data-source-banner.mock {
  background: var(--tag-red-bg, #fff2f0);
  color: var(--tag-red-text, #cf1322);
  border: 1px solid #ffccc7;
}

.data-source-banner.real {
  background: var(--tag-green-bg, #f6ffed);
  color: var(--tag-green-text, #389e0d);
  border: 1px solid #b7eb8f;
}

.data-source-banner .banner-updated {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  opacity: 0.85;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* 新布局：市场数据网格 */
.market-data-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

@media (max-width: 1400px) {
  .market-data-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .market-data-grid { grid-template-columns: 1fr; }
}

.config-tabs {
  margin-top: 8px;
}

/* 跨市场指数估值样式 */
.market-valuation-section {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 20px;
  box-shadow: var(--shadow-card);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
  cursor: pointer;
  user-select: none;
}
.section-header.collapsed {
  margin-bottom: 0;
}

.section-title {
  font-family: 'Work Sans', sans-serif;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.section-chevron {
  color: var(--text-muted);
  transition: transform 0.2s;
}

.market-stats {
  display: flex;
  gap: 16px;
  font-size: 13px;
}

.market-stats .stat-item {
  color: var(--text-secondary);
}

.market-stats .undervalued {
  color: var(--color-primary);
  font-weight: 600;
}

.market-stats .overvalued {
  color: var(--color-danger);
  font-weight: 600;
}

.market-tabs {
  margin-bottom: 16px;
}

.market-description {
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px 0;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

@media (max-width: 1280px) {
  .metric-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .metric-grid { grid-template-columns: 1fr; }
  .bottom-stats { flex-wrap: wrap; gap: 8px; }
}

.metric-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: var(--shadow-card);
  transition: box-shadow 0.2s, border-color 0.2s;
}

.metric-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  border-color: var(--border-hover);
}

.metric-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.metric-value-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.metric-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 26px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.2;
}

.percentile-indicator {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.percentile-bar {
  height: 4px;
  background: var(--border-default);
  border-radius: 2px;
  overflow: hidden;
}

.percentile-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
}

.percentile-text {
  font-size: 11px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.metric-footnotes {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--text-muted);
}

.heat-track {
  height: 8px;
  background: linear-gradient(to right, var(--color-primary), var(--border-default), var(--color-danger));
  border-radius: 4px;
  position: relative;
  overflow: hidden;
}

.heat-gradient {
  height: 100%;
  width: 100%;
  border-radius: 4px;
}

.heat-needle {
  position: absolute;
  top: -3px;
  width: 4px;
  height: 14px;
  background: var(--text-primary);
  border-radius: 2px;
  transform: translateX(-50%);
  transition: left 0.3s ease;
}

:deep(.data-row) {
  height: 40px;
  cursor: pointer;
  transition: background 0.12s ease;
}

:deep(.data-row:hover) {
  background: var(--bg-hover);
}

:deep(.n-data-table-th) {
  background: var(--bg-subtle) !important;
  font-family: 'Work Sans', sans-serif;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

:deep(.n-data-table-td) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
}

.bottom-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 8px 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  transition: box-shadow 0.2s;
}

.bottom-stats:hover {
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stat-item.right {
  margin-left: auto;
}

.stat-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  text-transform: uppercase;
}

.stat-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}

.text-blue { color: var(--color-primary) !important; }
.text-red { color: var(--color-danger) !important; }

.stat-divider {
  width: 1px;
  height: 16px;
  background: var(--border-default);
}

.heat-bar {
  width: 80px;
  height: 8px;
  border-radius: 4px;
  background: linear-gradient(to right, var(--color-primary), var(--border-default), var(--color-danger));
  position: relative;
}
</style>
