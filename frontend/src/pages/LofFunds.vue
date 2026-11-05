<script setup lang="ts">
defineOptions({ name: 'LofFunds' })
import { ref, computed, h, onMounted, watch } from 'vue'
import { NDataTable, NButton, NIcon, NSelect, NInput, NInputNumber, useMessage } from 'naive-ui'
import type { PaginationProps } from 'naive-ui'
import {
  TrendingUp,
  WalletOutline,
  EarthOutline,
  PulseOutline,
  FlashOutline,
  StatsChartOutline,
  SearchOutline,
} from '@vicons/ionicons5'
import { api, useAsyncData, isGatewayNoData } from '../composables/useApi'
import { pctColor } from '../utils/percentile'
import { estIndexLabel, estIndexNote, valuationErrorTip } from '../utils/estDisplay'
import { useSignalScan } from '../composables/useSignalScan'
import {
  buildTacticalSignalColumns,
  buildWinrateColumns,
  tacticalStateOf as tacticalState,
  winrateExportCells,
} from '../utils/signalDisplay'
import type { FundItem } from '../types'
import { exportToCSV } from '../utils/export'
import { analyzeArbitrageBatch, FEASIBILITY_ORDER } from '../utils/arbitrage'
import type { ArbitrageAnalysis } from '../utils/arbitrage'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import StatCard from '../components/StatCard.vue'
import TabBar from '../components/TabBar.vue'
import LoadingState from '../components/LoadingState.vue'
import SectionFallback from '../components/SectionFallback.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import FundRotationPanel from '../components/FundRotationPanel.vue'
import { useFieldHelp } from '../composables/useFieldHelp'
import { getFieldTip } from '../composables/helpContent'

const message = useMessage()
const { titleWithHelp } = useFieldHelp()
const { data: funds, loading, error, meta, execute: refetch } = useAsyncData(() => api.getFunds('lof'))
const gatewayEmpty = computed(() => isGatewayNoData(meta.value))
const activeTab = ref<string>('lof')
const selectedCode = ref<string | null>(null)
const scanning = ref(false)
// 基金搜索：同时匹配 6 位代码与基金名称（含中文/英文简称），作用于当前 Tab
const searchQuery = ref('')

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
// 搜索条件变化同样回到第一页，避免停在第 8 页却只显示 1 条结果
watch(searchQuery, () => { pagination.value.page = 1 })

function scan() {
  scanning.value = true
  message.loading('正在扫描套利机会...', { duration: 1500 })
  setTimeout(() => {
    scanning.value = false
    if (activeTab.value === 'qdii') {
      const feasible = displayFunds.value.filter(f => {
        const a = qdiiAnalysisMap.value.get(f.code)
        return a && a.feasibility === 'feasible'
      }).length
      const infeasible = displayFunds.value.filter(f => {
        const a = qdiiAnalysisMap.value.get(f.code)
        return a && a.feasibility === 'infeasible'
      }).length
      message.success(`扫描完成：${feasible} 个可行套利，${infeasible} 个不可行(限购/资金不足)`)
    } else {
      const opportunities = displayFunds.value.filter(f => Math.abs(f.premium_pct) > 3).length
      message.success(`扫描完成：发现 ${opportunities} 个套利机会`)
    }
  }, 1500)
}

function exportFunds() {
  const headers = ['基金名称', '代码', '类型', '价格', '预估净值', '溢价率', '百分位', '净套利收益', '成交量']
  if (tacticalLoaded.value) {
    headers.push('MA20偏离度%', 'RSI14', '布林位置%', '当前信号')
  }
  if (winrateLoaded.value) {
    headers.push('触发次数', '5日胜率%', '10日胜率%', '20日胜率%', '赔率(10日)', '半凯利%(10日)', '凯利%(10日)',
      '样本内胜率%(10日)', '样本外胜率%(10日)', '分年度胜率%(10日)')
  }
  const rows = displayFunds.value.map(f => {
    const t = tacticalMap.value.get(f.code)
    const state = tacticalState(t)
    const base = [
      f.name, f.code, activeTab.value === 'qdii' ? 'QDII-LOF' : f.type,
      f.price.toFixed(3), f.iopv.toFixed(3), f.premium_pct,
      f.premium_percentile ?? '', f.net_arbitrage_yield, f.volume ?? '',
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
  exportToCSV(`lof_funds_${activeTab.value}_${new Date().toISOString().slice(0, 10)}`, headers, rows)
  message.success(`已导出 ${rows.length} 条基金数据`)
}

// 页面加载时获取数据
onMounted(() => {
  refetch()
  loadStrategies()
})

// QDII/跨境标的判定：
//   后段 /funds?type=lof 返回的每条 type 恒为 'lof'（由 fund_subtype 统一赋值），
//   不存在 type='qdii' / 'closed' 的条目 —— 旧版按 type 筛导致两个 tab 恒空。
//   真实可用的分类是后端按名称算的 category='cross_border'（28 只跨境 LOF）。
//   其中约 12 只是场外联接 C/E 份额：price==iopv、premium_pct==0、volume 为 null，
//   没有场内报价、无套利意义，故剔除；只保留有场内价/成交的品种。
const isCrossBorderTradable = (f: FundItem) =>
  f.category === 'cross_border' && (f.premium_pct !== 0 || f.volume != null)

const filteredFunds = computed(() => {
  if (!funds.value) return []
  if (activeTab.value === 'qdii') {
    // QDII: 按可行性分级排序，同级按调整后收益下限降序
    return funds.value
      .filter(isCrossBorderTradable)
      .sort((a, b) => {
        const fa = qdiiAnalysisMap.value.get(a.code)
        const fb = qdiiAnalysisMap.value.get(b.code)
        if (!fa || !fb) return Math.abs(b.premium_pct) - Math.abs(a.premium_pct)
        const orderDiff = FEASIBILITY_ORDER[fa.feasibility] - FEASIBILITY_ORDER[fb.feasibility]
        if (orderDiff !== 0) return orderDiff
        return fb.adjustedYieldLow - fa.adjustedYieldLow
      })
  }
  // LOF（默认）：单独菜单「封闭基金」负责封基，本页不再重复承载
  return funds.value.filter(f => f.type === 'lof')
})

// ---- 基金搜索（代码 / 名称）----
// filteredFunds 保持「当前 Tab 全量」语义，供底部口径说明与战术信号扫描使用；
// 表格、导出、手动扫描改用 displayFunds（所见即所得），搜索不会污染全市场统计。
// 兼容 clearable 清空时个别版本回传 null，统一转字符串避免 .trim() 报错
const searchKeyword = computed(() => String(searchQuery.value ?? '').trim().toLowerCase())
// 代码粘贴常带 .SH/.SZ 后缀或空格，取纯数字片段兜底匹配（至少 2 位，避免误命中一片）
const searchDigits = computed(() => searchKeyword.value.replace(/[^0-9]/g, ''))
const displayFunds = computed(() => {
  const list = filteredFunds.value
  const q = searchKeyword.value
  if (!q) return list
  const digits = searchDigits.value
  const matched = list.filter(f => {
    const code = (f.code ?? '').toLowerCase()
    const name = (f.name ?? '').toLowerCase()
    if (code.includes(q) || name.includes(q)) return true
    return digits.length >= 2 && code.includes(digits)
  })
  // 代码精确匹配 > 代码前缀匹配 > 名称匹配；同级保持 Tab 原有排序（sort 稳定）
  const rank = (f: FundItem) => {
    const code = (f.code ?? '').toLowerCase()
    if (code === q || (digits && code === digits)) return 0
    if (code.startsWith(q) || (digits && code.startsWith(digits))) return 1
    return 2
  }
  return matched.sort((a, b) => rank(a) - rank(b))
})

// 全量套利可行性分析映射 (LOF/QDII 均需 T+N 敞口分析)
const arbitrageAnalysisMap = computed(() => {
  if (!funds.value) return new Map<string, ArbitrageAnalysis>()
  // 对所有有套利收益的基金执行分析；QDII 跨境标的即使毛收益为 0 也纳入（限购/停牌判定需要）
  const arbitrageFunds = funds.value.filter(f => Math.abs(f.net_arbitrage_yield) > 0 || isCrossBorderTradable(f))
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
  { key: 'qdii', label: 'QDII / 跨境LOF', icon: EarthOutline },
]

// ---- 战术信号 + 胜率扫描（共享逻辑见 useSignalScan；对当前 Tab 筛选结果生效，最多前 100 只）----
const LOF_SCAN_LIMIT = 100
const {
  selectedStrategyId, selectedParams, strategyOptions, strategyParams, loadStrategies,
  tacticalMap, tacticalLoading, tacticalLoaded, loadTactical,
  winrateMap, winrateLoading, winrateLoaded, winrateMeta, scanWinrate, statsOf,
} = useSignalScan(
  () => filteredFunds.value.map(f => f.code),
  { onError: msg => message.error(msg), notify: msg => message.success(msg), limit: LOF_SCAN_LIMIT },
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
  if (!tacticalLoaded.value) return columns.value
  return winrateLoaded.value
    ? [...columns.value, ...tacticalAppendColumns, ...winrateAppendColumns]
    : [...columns.value, ...tacticalAppendColumns]
})

function onRowClick(fund: FundItem) {
  selectedCode.value = fund.code
  message.info(`${fund.name}: ${fund.premium_pct}%`)
}

/**
 * 自算净值的口径说明（铁律：可以近似，不可以假装精确）。
 *
 * 指数跟踪法用的是代理指数，残差就是「这只指数解释不了的净值波动」，会和真实溢价混在一起，
 * 所以必须让用户能看到 基准指数 / 残差 / 仓位 / 基准日，而不是只给一个漂亮的三位小数。
 */
function estNavTip(row: FundItem): string {
  if (row.est_method === 'futures') {
    // 商品基金净值按**结算价**估值（实测 161226 用结算价残差 0.06%，用收盘价 1.29%）
    const parts = [
      `期货结算价口径：跟踪 ${row.est_futures_symbol ?? '期货合约'}，仓位 ${row.est_position ?? '-'}%`,
    ]
    if (row.est_futures_price_kind === 'settle') parts.push('现价用最新交易日结算价（已定盘）')
    else if (row.est_futures_price_kind === 'live') parts.push('现价用盘中最新价（当日结算价未出）')
    if (row.est_futures_resid_pct != null) parts.push(`实测残差 ${row.est_futures_resid_pct}%/日`)
    if (row.est_basis_rate != null) {
      const curve = row.est_basis_curve === 'back' ? '贴水/换月正展期' : row.est_basis_curve === 'contango' ? '升水/换月负展期' : '平水'
      parts.push(`主力基差 ${row.est_basis_rate > 0 ? '+' : ''}${row.est_basis_rate}%（${curve}）`)
      parts.push('基差不参与估值：业绩基准本身就是期货价格指数')
    }
    if (row.est_basis_note) parts.push(row.est_basis_note)
    if (row.est_base_date) parts.push(`基准日 ${row.est_base_date}`)
    return parts.join('；')
  }
  if (row.est_method === 'index') {
    const parts = [`指数跟踪法：按仓位跟踪 ${estIndexLabel(row.est_index_symbol)} 涨跌推算`]
    const idxNote = estIndexNote(row.est_index_symbol)
    if (idxNote) parts.push(idxNote)
    if (row.est_index_resid_pct != null) parts.push(`该指数实测残差 ${row.est_index_resid_pct}%/日`)
    if (row.est_index_proxy) parts.push('该指数只是代理，未精确复制持仓')
    if (row.est_position != null) parts.push(`仓位 ${row.est_position}%`)
    if (row.est_base_date) parts.push(`基准日 ${row.est_base_date}`)
    return parts.join('；')
  }
  const parts = ['篮子法：按持仓权重与成分行情加权']
  if (row.est_position != null) parts.push(`篮子仓位 ${row.est_position}%`)
  if (row.est_base_date) parts.push(`基准日 ${row.est_base_date}`)
  if (row.est_price_date) parts.push(`行情日 ${row.est_price_date}`)
  return parts.join('；')
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
        // 净值锚陈旧（T+5 起）时溢价读数不可用：数字照给但必须带警示，
        // 否则就是「EST 停在一年多前还显示 14.67% 溢价」那类陷阱
        const stale = row.nav_stale_level === 'stale'
        const tip = row.nav_lag_days != null
          ? `净值锚 ${row.nav_date ?? '-'}（落后 ${row.nav_lag_days} 个交易日${stale ? '，已失效，勿据此下单' : ''}）`
          : undefined
        const text = `${row.premium_pct >= 0 ? '+' : ''}${row.premium_pct}%${stale ? ' ⚠' : ''}`
        return h('span', { class: 'mono right', style: { color }, title: tip }, text)
      },
    },
    {
      title: titleWithHelp('篮子自算净值', 'est_nav'),
      key: 'est_nav',
      align: 'right' as const,
      render: (row: FundItem) => {
        // 跨境LOF/QDII自算：basket=篮子加权，index=单指数跟踪（代理，加「~」区分）
        // position/篮子/行情/质量标定缺一 → 后端不写 → '-'
        if (row.est_nav == null) return h('span', { class: 'mono right' }, '-')
        const isIndex = row.est_method === 'index'
        return h(
          'span',
          { class: 'mono right', title: estNavTip(row) },
          isIndex
            ? [row.est_nav.toFixed(3), h('sup', { style: 'color: var(--text-muted)' }, '~')]
            : row.est_nav.toFixed(3),
        )
      },
    },
    {
      title: titleWithHelp('自算溢价', 'est_premium_pct'),
      key: 'est_premium_pct',
      align: 'right' as const,
      render: (row: FundItem) => {
        if (row.est_premium_pct == null) return h('span', { class: 'mono right' }, '-')
        const color = row.est_premium_pct >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
        const text = `${row.est_premium_pct >= 0 ? '+' : ''}${row.est_premium_pct.toFixed(2)}%`
        // 指数跟踪法的溢价率带着代理误差，同样要能悬浮看到口径
        return h('span', { class: 'mono right', style: { color }, title: estNavTip(row) }, text)
      },
    },
    {
      title: titleWithHelp('估值误差', 'valuation_error'),
      key: 'valuation_error',
      align: 'right' as const,
      render: (row: FundItem) => {
        // T3 自检：过去算出的 est_nav 与基金公司公布真实净值的偏差。
        // null = 还没有回填样本（刚上线首日全空），显示 '-' 而不是 0 —— 0 会被读成「零误差」。
        if (row.valuation_error == null) return h('span', { class: 'mono right' }, '-')
        const abs = Math.abs(row.valuation_error)
        const color =
          abs > 1.5 ? 'var(--color-danger)'
            : abs > 0.5 ? 'var(--color-warning)'
            : 'var(--text-muted)'
        const text = `${row.valuation_error >= 0 ? '+' : ''}${row.valuation_error.toFixed(2)}%`
        return h('span', { class: 'mono right', style: { color }, title: valuationErrorTip(row) }, text)
      },
    },
    {
      // 口径差：官方口径（基金公司净值）− 自算口径（est_nav）。
      // 跨境 ETF 类官方参考净值含汇率口径差异，实测系统性低 0.7~0.9 个点；
      // LOF 类两口径基本一致。不标出来，跨基金比溢价就会串口径。
      title: titleWithHelp('口径差', 'premium_gap'),
      key: 'premium_gap',
      align: 'right' as const,
      render: (row: FundItem) => {
        if (row.premium_gap == null) return h('span', { class: 'mono right' }, '-')
        const big = Math.abs(row.premium_gap) > 0.5
        return h('span', {
          class: 'mono right',
          style: big ? { color: 'var(--color-warning)', fontWeight: 600 } : undefined,
          title: `官方口径 ${row.premium_pct}% − 自算口径 ${row.est_premium_pct}%；跨基金比较时请统一口径`,
        }, `${row.premium_gap >= 0 ? '+' : ''}${row.premium_gap.toFixed(2)}`)
      },
    },
    {
      title: titleWithHelp('溢价百分位', 'premium_percentile'),
      key: 'premium_percentile',
      align: 'right' as const,
      render: (row: FundItem) => {
        // 分位来自本项目每日落库的自建序列（base_fund_premium_daily）。
        // 样本不足 15 个交易日时后端不给值 → 显示 '-'，不伪造
        if (row.premium_percentile == null) {
          return h('span', {
            class: 'mono right',
            title: '样本不足 15 个交易日，暂不出分位（不是 0，是没有可比历史）',
          }, '-')
        }
        const bg = pctColor(row.premium_percentile)
        const tip = `${row.premium_hist_base === 'est' ? '自算' : '官方'}口径；样本 ${row.premium_hist_n ?? '-'} 个交易日` +
          (row.premium_ma20 != null ? `；20 日均值 ${row.premium_ma20}%` : '')
        return h('div', { class: 'perc-bar-cell', title: tip }, [
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

  // 封基专属列（剩余期限 / 预估收益）已随「封闭式」tab 一并移除：
  // 封闭基金由侧边栏独立菜单承载，本页不再重复提供。

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
    <SectionFallback v-if="gatewayEmpty" :gateway-empty="true" :min-height="520" @retry="refetch" />
    <div v-else-if="funds" class="lof-page">
    <PageHeader title="基金套利扫描" subtitle="场内基金估值与套利扫描 - 实时监控折溢价机会" helpKey="lofFunds" :updated-at="meta?.updateTime">
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
      <template #actions>
        <n-input
          v-model:value="searchQuery"
          size="small"
          clearable
          placeholder="搜索基金代码 / 名称"
          class="fund-search"
        >
          <template #prefix>
            <n-icon :component="SearchOutline" size="14" />
          </template>
        </n-input>
      </template>
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
        :data="displayFunds"
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
      <div v-if="searchQuery && displayFunds.length === 0" class="search-empty">
        未找到匹配「{{ searchQuery }}」的基金，请检查代码或名称（搜索仅在当前 Tab 内生效）
      </div>
      <div class="table-footer">
        <span class="footer-info">
          当前 {{ displayFunds.length }} 条基金数据
          <template v-if="searchQuery">（搜索「{{ searchQuery }}」· 本 Tab 共 {{ filteredFunds.length }} 条）</template>
        </span>
        <n-button v-if="searchQuery" size="tiny" quaternary @click="searchQuery = ''">清空搜索</n-button>
      </div>
    </DataPanel>

    <!-- 同标的跨基金溢价轮动：卖组内高溢价、买低溢价（懒加载，点「分析」才拉全市场） -->
    <FundRotationPanel />

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

    <!-- 底部提示：全部由当前真实列表推导，不再使用硬编码示例数值 -->
    <div v-if="activeTab === 'qdii'" class="insight-bar qdii-insight">
      <n-icon :component="PulseOutline" size="20" class="insight-icon" />
      <span>
        <strong>口径说明：</strong>本页 QDII / 跨境 LOF 共 {{ filteredFunds.length }} 只，
        取自 LOF 列表中后端标记为「跨境」且有场内报价的品种（已剔除无场内价的场外联接份额）。
        跨境份额 T+2 到账，套利需扣资金占用与限购成本；
        <span v-if="filteredFunds.some(f => qdiiAnalysisMap.get(f.code)?.feasibility === 'infeasible')">
          <strong style="color: var(--color-danger)">当前检测到限购 / 资金容量 C 级品种，其套利收益已归零。</strong>
        </span>
        <span v-else>当前未检测到不可行标的，执行前仍需自行核对净值与外汇额度。</span>
      </span>
    </div>
    <div v-else class="insight-bar">
      <n-icon :component="PulseOutline" size="20" class="insight-icon" />
      <span>
        <strong>LOF 折溢价概览：</strong>当前 {{ filteredFunds.length }} 只，折溢价绝对值超过 3% 的
        {{ lofStats.opportunityCount }} 只。封闭基金请从左侧「封闭基金」菜单查看。
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

.fund-search { width: 260px; }
.search-empty {
  padding: 10px 16px;
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  border-top: 1px solid var(--border-default);
}

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
  .fund-search { width: 100%; }
  .insight-bar { flex-wrap: wrap; }
}
</style>
