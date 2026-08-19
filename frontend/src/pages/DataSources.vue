<script setup lang="ts">
defineOptions({ name: 'DataSources' })
import { ref, onMounted, computed, h } from 'vue'
import { NDataTable, NTag, NIcon, NCollapse, NCollapseItem } from 'naive-ui'
import {
  ServerOutline,
  CalendarOutline,
  PulseOutline,
  CloudDownloadOutline,
  InformationCircleOutline,
  CheckmarkCircleOutline,
} from '@vicons/ionicons5'
import PageHeader from '../components/PageHeader.vue'
import DataPanel from '../components/DataPanel.vue'
import StatCard from '../components/StatCard.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import LoadingState from '../components/LoadingState.vue'

// 模拟加载：短暂展示骨架屏后显示内容
const loading = ref(true)
onMounted(() => {
  setTimeout(() => { loading.value = false }, 700)
})

// ============================================================
// 数据频率定义
// ============================================================
type Frequency = 'daily' | 'weekly' | 'monthly' | 'realtime'
type UpdateMethod = 'api' | 'manual' | 'derived'

interface FrequencyConfig {
  label: string
  color: string
  bg: string
}
const freqConfig: Record<Frequency, FrequencyConfig> = {
  daily: { label: '日频', color: 'var(--tag-blue-text)', bg: 'var(--tag-blue-bg)' },
  weekly: { label: '周频', color: 'var(--tag-orange-text)', bg: 'var(--tag-orange-bg)' },
  monthly: { label: '月频', color: 'var(--tag-orange-text)', bg: 'var(--tag-orange-bg)' },
  realtime: { label: '实时', color: 'var(--tag-red-text)', bg: 'var(--tag-red-bg)' },
}

const methodConfig: Record<UpdateMethod, { label: string; color: string; bg: string }> = {
  api: { label: 'API拉取', color: 'var(--tag-blue-text)', bg: 'var(--tag-blue-bg)' },
  manual: { label: '手动维护', color: 'var(--tag-orange-text)', bg: 'var(--tag-orange-bg)' },
  derived: { label: '计算派生', color: 'var(--tag-green-text)', bg: 'var(--tag-green-bg)' },
}

// ============================================================
// 数据来源总览
// ============================================================
interface DataSourceSummary {
  source: string
  category: string
  frequency: Frequency
  method: UpdateMethod
  fields: string
  note: string
}

// ============================================================
// 数据来源总览（含具体接口）
// ============================================================
interface DataSourceDetail extends DataSourceSummary {
  apiEndpoint?: string
  dataSource?: string
}

const sourceSummaries: DataSourceDetail[] = [
  { source: '指数估值', category: '宏观/指数', frequency: 'daily', method: 'api', fields: 'PE、PB、股息率、分位数', apiEndpoint: '/api/processed_data?category=index_valuation&subtype=all', dataSource: '乐咕乐股(PE/PB历史) + 新浪(指数行情) + baostock/腾讯(K线)', note: '12个宽基指数估值，含PE/PB百分位、近3月涨跌、胜率' },
  { source: '板块涨幅', category: '宏观/指数', frequency: 'daily', method: 'api', fields: '概念名称、涨跌幅、成交额', apiEndpoint: '/api/processed_data?category=board&subtype=concept_list', dataSource: '同花顺(_ths) 8个接口优先 → 东财(_em) 兜底', note: '概念板块涨幅排行，容灾链保障稳定性' },
  { source: '资金流向', category: '宏观/指数', frequency: 'daily', method: 'api', fields: '主力/超大单/大单净流入及占比', apiEndpoint: '/api/processed_data?category=fund_flow&subtype=market', dataSource: 'akshare 东财为主 → efinance 个股降级', note: '市场资金流向 + 行业资金流向排名' },
  { source: '市场统计', category: '宏观/指数', frequency: 'realtime', method: 'api', fields: '总成交额、涨跌家数、涨跌停数', apiEndpoint: '/api/processed_data?category=market_stats&subtype=overview', dataSource: '新浪A股spot（非东财），5分钟内存快照', note: '沪深两市成交额、涨跌家数、涨跌停统计' },
  { source: '涨跌停池', category: '宏观/指数', frequency: 'realtime', method: 'api', fields: '涨停/跌停股票列表、连板数', apiEndpoint: '/api/processed_data?category=zt_pool&subtype=zt|dt', dataSource: '新浪spot自算（非东财），涨停判定基于价格限制', note: '主板10%/创业板科创板20%/ST股5%/北交所30%，2%容差' },
  { source: 'ETF排行', category: '基金', frequency: 'daily', method: 'api', fields: '代码、名称、最新价、涨跌幅、成交额', apiEndpoint: '/api/processed_data?category=fund_rank&subtype=etf', dataSource: '新浪ETF基金 → 同花顺 fund_etf_spot_ths（非东财）', note: 'ETF涨跌排行，容灾链保障稳定性' },
  { source: 'LOF排行', category: '基金', frequency: 'daily', method: 'api', fields: '代码、名称、最新价、涨跌幅、成交额', apiEndpoint: '/api/processed_data?category=fund_rank&subtype=lof', dataSource: '新浪ETF基金 → 同花顺 fund_etf_spot_ths（非东财）', note: 'LOF基金涨跌排行' },
  { source: '封闭基金排行', category: '基金', frequency: 'daily', method: 'api', fields: '代码、名称、最新价、涨跌幅、成交额', apiEndpoint: '/api/processed_data?category=fund_rank&subtype=closed', dataSource: '新浪ETF基金 → 同花顺 fund_etf_spot_ths（非东财）', note: '封闭式基金涨跌排行' },
  { source: '宏观指标', category: '宏观', frequency: 'daily', method: 'manual', fields: 'DR007、GC001、ERP', note: '银行间流动性 + 股权风险溢价（暂无稳定数据源）' },
  { source: '可转债行情', category: '可转债', frequency: 'daily', method: 'manual', fields: '转债价格、转股价值、溢价率、到期收益率', note: '需自建数据源或第三方付费接口' },
  { source: '可转债条款', category: '可转债', frequency: 'daily', method: 'manual', fields: '强赎进度、回售进度、下修进度、转股期', note: '需跟踪公司公告，手动维护触发天数' },
  { source: 'REITs行情', category: 'REITs', frequency: 'daily', method: 'manual', fields: '市场价格、成交量', note: '暂无稳定数据源' },
  { source: 'REITs基本面', category: 'REITs', frequency: 'monthly', method: 'manual', fields: 'NAV、DSCR、出租率趋势、杠杆率', note: '季报/半年报披露，出租率需手动跟踪' },
]

// ============================================================
// 各页面数据需求明细
// ============================================================
interface PageDataReq {
  page: string
  route: string
  category: string
  fields: string
  frequency: Frequency
  method: UpdateMethod
  purpose: string
}

const pageDataReqs: PageDataReq[] = [
  // 宏观看板
  { page: '大类资产配置看板', route: '/dashboard', category: '宏观/指数', fields: 'ERP、ERP分位数(3/5/10Y)、DR007、GC001', frequency: 'daily', method: 'api', purpose: '股权风险溢价 + 银行间流动性监控' },
  { page: '大类资产配置看板', route: '/dashboard', category: '指数估值', fields: '6大指数PE/PB + 分位数 + 3月涨跌 + 胜率', frequency: 'daily', method: 'api', purpose: '宽基指数估值定投信号' },
  // 指数分析
  { page: '指数估值分析', route: '/index-analysis', category: '指数行情', fields: '日K线收盘价、开高低、成交量', frequency: 'daily', method: 'api', purpose: 'K线图表绘制 + 技术分析' },
  { page: '指数估值分析', route: '/index-analysis', category: '指数估值', fields: 'PE、PB、股息率、历史分位数', frequency: 'daily', method: 'api', purpose: '估值百分位 + 定投信号' },
  { page: '指数估值分析', route: '/index-analysis', category: '宏观流动性', fields: 'DR007、GC001、十年国债', frequency: 'daily', method: 'api', purpose: '资金面松紧判断' },
  // LOF基金
  { page: 'LOF基金套利扫描', route: '/lof-funds', category: '基金行情', fields: '二级市场价格、IOPV、折溢价率', frequency: 'daily', method: 'api', purpose: '折溢价套利信号' },
  { page: 'LOF基金套利扫描', route: '/lof-funds', category: '申赎信息', fields: '申购限额、暂停状态', frequency: 'daily', method: 'api', purpose: '资金容量分级(A/B/C) + 限购陷阱识别' },
  { page: 'LOF基金套利扫描', route: '/lof-funds', category: '波动率', fields: '日波动率(%)', frequency: 'daily', method: 'derived', purpose: 'T+N敞口VaR计算(95%单侧)' },
  { page: 'LOF基金套利扫描', route: '/lof-funds', category: 'QDII额度', fields: '外汇额度、T+2到账天数', frequency: 'daily', method: 'manual', purpose: '跨境QDII套利可行性判断' },
  // 封闭基金
  { page: '封闭基金', route: '/closed-funds', category: '基金行情', fields: '二级市场价格、成交量', frequency: 'daily', method: 'api', purpose: '折价率计算 + 流动性评估' },
  { page: '封闭基金', route: '/closed-funds', category: '基金净值', fields: 'NAV(基金净值)', frequency: 'daily', method: 'api', purpose: '折价率 = (价格-NAV)/NAV' },
  { page: '封闭基金', route: '/closed-funds', category: '到期信息', fields: '到期日、剩余期限、是否转LOF', frequency: 'daily', method: 'manual', purpose: '折价收敛路径分析(确定/不确定)' },
  { page: '封闭基金', route: '/closed-funds', category: '底层持仓', fields: '信用评级、底层资产类型', frequency: 'monthly', method: 'manual', purpose: '底层信用风险评估' },
  // 可转债
  { page: '可转债扫描', route: '/convertible-bonds', category: '转债行情', fields: '转债价格、涨跌幅、成交量', frequency: 'daily', method: 'api', purpose: '双低策略 + K线分析' },
  { page: '可转债扫描', route: '/convertible-bonds', category: '转股数据', fields: '转股价值、溢价率、转股价', frequency: 'daily', method: 'api', purpose: '转股套利可行性分析' },
  { page: '可转债扫描', route: '/convertible-bonds', category: '正股行情', fields: '正股价格、涨跌幅、涨停状态', frequency: 'daily', method: 'api', purpose: '涨停阻断判断 + T+1隔夜敞口' },
  { page: '可转债扫描', route: '/convertible-bonds', category: '波动率', fields: 'IV(隐含波动率)、HV(20日历史波动率)', frequency: 'daily', method: 'derived', purpose: 'IV/HV对比 → Delta对冲套利信号' },
  { page: '可转债扫描', route: '/convertible-bonds', category: '条款进度', fields: '强赎天数、回售天数、下修天数、转股期', frequency: 'daily', method: 'manual', purpose: '条款触发预警 + 伪机会识别' },
  { page: '可转债扫描', route: '/convertible-bonds', category: '正股风控', fields: 'Altman Z-Score、质押率、ST标记', frequency: 'monthly', method: 'manual', purpose: '正股信用风险量化' },
  // ETF基金
  { page: 'ETF基金策略', route: '/etf-funds', category: 'ETF行情', fields: '二级市场价格、IOPV、折溢价率、成交量', frequency: 'daily', method: 'api', purpose: '折溢价套利 + 网格交易参数' },
  { page: 'ETF基金策略', route: '/etf-funds', category: '申赎信息', fields: '申购限额、暂停状态、T+N天数', frequency: 'daily', method: 'api', purpose: '资金容量分级 + 假机会过滤' },
  { page: 'ETF基金策略', route: '/etf-funds', category: '估值数据', fields: 'PE、PE分位数、估值类别', frequency: 'daily', method: 'api', purpose: '估值定投信号 + 行业轮动' },
  { page: 'ETF基金策略', route: '/etf-funds', category: '动量数据', fields: '动量评分(momentum_score)', frequency: 'daily', method: 'derived', purpose: '行业轮动排名' },
  // REITs
  { page: '公募REITs分析', route: '/reits', category: 'REITs行情', fields: '市场价格、成交量', frequency: 'daily', method: 'api', purpose: 'NAV溢折价 + 流动性评估' },
  { page: '公募REITs分析', route: '/reits', category: '基金净值', fields: 'NAV(基金净值)', frequency: 'daily', method: 'api', purpose: 'NAV溢折价率 = (市价-NAV)/NAV' },
  { page: '公募REITs分析', route: '/reits', category: '基本面', fields: 'DSCR、出租率、出租率趋势、杠杆率', frequency: 'monthly', method: 'manual', purpose: '分红可持续性三因子评估' },
  { page: '公募REITs分析', route: '/reits', category: '分红数据', fields: '年化分红、分红率、IRR', frequency: 'monthly', method: 'manual', purpose: '收益率对比 + 配置价值评分' },
  // 预警中心
  { page: '预警中心', route: '/alert-center', category: '全量数据', fields: '以上所有页面的分析结果', frequency: 'daily', method: 'derived', purpose: '动态信号生成(套利/转股/波动率/收敛/NAV/流动性/信用)' },
  { page: '预警中心', route: '/alert-center', category: '预警规则', fields: '规则名称、类型、标的、阈值、通知渠道', frequency: 'daily', method: 'manual', purpose: '用户自定义预警规则' },
  // 策略中心
  { page: '策略管理中心', route: '/strategy-center', category: '策略规则', fields: '因子、操作符、阈值、逻辑(AND/OR)', frequency: 'daily', method: 'manual', purpose: '策略条件筛选 + 回测' },
  // AI决策
  { page: 'AI决策中心', route: '/ai-decision', category: '全量数据', fields: '以上所有页面数据 + 策略匹配结果', frequency: 'daily', method: 'derived', purpose: 'AI宏观评估 + 策略匹配 + 套利提示' },
  // 投资组合
  { page: '投资组合自选', route: '/portfolio-watchlist', category: '持仓数据', fields: '标的代码、名称、持仓量、成本价', frequency: 'daily', method: 'manual', purpose: '持仓盈亏跟踪' },
  { page: '投资组合自选', route: '/portfolio-watchlist', category: '行情数据', fields: '持仓标的实时价格', frequency: 'daily', method: 'api', purpose: '实时盈亏计算' },
]

// ============================================================
// 统计概览
// ============================================================
const totalFields = computed(() => pageDataReqs.length)
const apiCount = computed(() => pageDataReqs.filter(r => r.method === 'api').length)
const manualCount = computed(() => pageDataReqs.filter(r => r.method === 'manual').length)
const derivedCount = computed(() => pageDataReqs.filter(r => r.method === 'derived').length)
const dailyCount = computed(() => pageDataReqs.filter(r => r.frequency === 'daily').length)

// ============================================================
// 表格列定义
// ============================================================
const sourceColumns = [
  {
    title: '数据来源',
    key: 'source',
    render: (row: DataSourceDetail) => h('span', { class: 'ds-name' }, row.source),
  },
  {
    title: '类别',
    key: 'category',
    render: (row: DataSourceDetail) => h('span', { class: 'ds-cat' }, row.category),
  },
  {
    title: 'API接口',
    key: 'apiEndpoint',
    render: (row: DataSourceDetail) => row.apiEndpoint 
      ? h('code', { class: 'ds-api' }, row.apiEndpoint)
      : h('span', { class: 'ds-no-api' }, '-'),
  },
  {
    title: '数据源',
    key: 'dataSource',
    render: (row: DataSourceDetail) => row.dataSource
      ? h('span', { class: 'ds-source' }, row.dataSource)
      : h('span', { class: 'ds-no-api' }, '-'),
  },
  {
    title: '字段',
    key: 'fields',
    render: (row: DataSourceDetail) => h('span', { class: 'ds-fields' }, row.fields),
  },
  {
    title: '频率',
    key: 'frequency',
    align: 'center' as const,
    width: 80,
    render: (row: DataSourceDetail) => h(NTag, {
      size: 'small',
      bordered: false,
      style: { background: freqConfig[row.frequency].bg, color: freqConfig[row.frequency].color },
    }, { default: () => freqConfig[row.frequency].label }),
  },
  {
    title: '获取方式',
    key: 'method',
    align: 'center' as const,
    width: 100,
    render: (row: DataSourceDetail) => h(NTag, {
      size: 'small',
      bordered: false,
      style: { background: methodConfig[row.method].bg, color: methodConfig[row.method].color },
    }, { default: () => methodConfig[row.method].label }),
  },
  {
    title: '说明',
    key: 'note',
    render: (row: DataSourceDetail) => h('span', { class: 'ds-note' }, row.note),
  },
]

const pageColumns = [
  {
    title: '页面',
    key: 'page',
    width: 140,
    render: (row: PageDataReq) => h('div', { class: 'page-cell' }, [
      h('span', { class: 'page-name' }, row.page),
      h('span', { class: 'page-route' }, row.route),
    ]),
  },
  {
    title: '数据类别',
    key: 'category',
    width: 120,
    render: (row: PageDataReq) => h('span', { class: 'ds-cat' }, row.category),
  },
  {
    title: '所需字段',
    key: 'fields',
    render: (row: PageDataReq) => h('span', { class: 'ds-fields' }, row.fields),
  },
  {
    title: '频率',
    key: 'frequency',
    align: 'center' as const,
    width: 80,
    render: (row: PageDataReq) => h(NTag, {
      size: 'small',
      bordered: false,
      style: { background: freqConfig[row.frequency].bg, color: freqConfig[row.frequency].color },
    }, { default: () => freqConfig[row.frequency].label }),
  },
  {
    title: '获取方式',
    key: 'method',
    align: 'center' as const,
    width: 100,
    render: (row: PageDataReq) => h(NTag, {
      size: 'small',
      bordered: false,
      style: { background: methodConfig[row.method].bg, color: methodConfig[row.method].color },
    }, { default: () => methodConfig[row.method].label }),
  },
  {
    title: '用途',
    key: 'purpose',
    render: (row: PageDataReq) => h('span', { class: 'ds-purpose' }, row.purpose),
  },
]

// ============================================================
// 按页面分组
// ============================================================
const uniquePages = computed(() => {
  const seen = new Set<string>()
  return pageDataReqs.filter(r => {
    if (seen.has(r.page)) return false
    seen.add(r.page)
    return true
  }).map(r => ({ page: r.page, route: r.route }))
})

function getPageReqs(pageName: string) {
  return pageDataReqs.filter(r => r.page === pageName)
}
</script>

<template>
  <LoadingState
    :loading="loading"
    skeleton
    :min-height="480"
    text="正在加载数据来源说明..."
  >
    <div class="ds-page">
    <PageHeader title="数据来源说明" subtitle="各页面数据需求明细 — 研究数据频率：日K线级别" helpKey="dataSources" />

    <GlossaryPanel page-key="dataSources" />

    <!-- 概览卡片 -->
    <div class="stat-grid">
      <StatCard label="数据需求总数" :value="totalFields" sub="字段维度" />
      <div class="stat-card-custom">
        <span class="stat-label">日频数据</span>
        <span class="stat-value">{{ dailyCount }} 项</span>
        <span class="stat-sub">日K线收盘级别</span>
      </div>
      <div class="stat-card-custom">
        <span class="stat-label">API拉取</span>
        <span class="stat-value">{{ apiCount }} 项</span>
        <span class="stat-sub">自动化获取</span>
      </div>
      <div class="stat-card-custom">
        <span class="stat-label">手动维护</span>
        <span class="stat-value">{{ manualCount }} 项</span>
        <span class="stat-sub">公告/季报跟踪</span>
      </div>
      <div class="stat-card-custom">
        <span class="stat-label">计算派生</span>
        <span class="stat-value">{{ derivedCount }} 项</span>
        <span class="stat-sub">由原始数据计算</span>
      </div>
    </div>

    <!-- 数据频率说明 -->
    <DataPanel title="数据频率说明">
      <div class="freq-info">
        <div class="freq-item">
          <n-icon :component="CalendarOutline" size="20" class="freq-icon" />
          <div class="freq-content">
            <h4>日K线级别（主要频率）</h4>
            <p>所有行情数据（指数、ETF/LOF、可转债、REITs、正股）均使用日K线收盘数据。研究层面无需分钟级数据，日频足以支撑套利分析、估值定投、网格交易等策略。</p>
          </div>
        </div>
        <div class="freq-item">
          <n-icon :component="PulseOutline" size="20" class="freq-icon" />
          <div class="freq-content">
            <h4>实时数据（仅盘中参考）</h4>
            <p>IOPV（基金参考净值）在交易时段内实时更新，折溢价率随之变化。日K线收盘后取最终值用于策略信号。实际套利执行时需接入实时行情。</p>
          </div>
        </div>
        <div class="freq-item">
          <n-icon :component="ServerOutline" size="20" class="freq-icon" />
          <div class="freq-content">
            <h4>月频/季频数据（基本面）</h4>
            <p>REITs的DSCR/出租率/杠杆率、封闭基金底层持仓信用评级、可转债条款进度等基本面数据按月或按季更新，来源于定期报告和公司公告，需手动维护。</p>
          </div>
        </div>
        <div class="freq-item">
          <n-icon :component="CloudDownloadOutline" size="20" class="freq-icon" />
          <div class="freq-content">
            <h4>派生数据（模型计算）</h4>
            <p>波动率（IV/HV）、VaR敞口、套利评分、可行性分级等由原始日K线数据计算派生，无需额外数据源。IV通过BS模型反推，HV通过20日窗口历史波动率计算。</p>
          </div>
        </div>
      </div>
    </DataPanel>

    <!-- 数据来源汇总表 -->
    <DataPanel title="数据来源汇总">
      <n-data-table
        :columns="sourceColumns"
        :data="sourceSummaries"
        :row-key="(row: any) => row.source"
        :bordered="false"
        :single-line="false"
        size="small"
      />
    </DataPanel>

    <!-- 各页面数据需求明细 -->
    <DataPanel title="各页面数据需求明细">
      <n-data-table
        :columns="pageColumns"
        :data="pageDataReqs"
        :row-key="(row: any) => row.page + row.category"
        :bordered="false"
        :single-line="false"
        size="small"
        :pagination="{ pageSize: 15 }"
      />
    </DataPanel>

    <!-- 按页面分组详情 -->
    <div class="grouped-section">
      <h3 class="section-title">
        <n-icon :component="InformationCircleOutline" size="18" />
        按页面分组
      </h3>
      <n-collapse accordion>
        <n-collapse-item
          v-for="pg in uniquePages"
          :key="pg.route"
          :name="pg.route"
          :title="pg.page"
        >
          <div class="grouped-reqs">
            <div v-for="req in getPageReqs(pg.page)" :key="req.category" class="grouped-req">
              <div class="req-header">
                <span class="req-category">{{ req.category }}</span>
                <div class="req-tags">
                  <n-tag size="tiny" :bordered="false" :style="{ background: freqConfig[req.frequency].bg, color: freqConfig[req.frequency].color }">
                    {{ freqConfig[req.frequency].label }}
                  </n-tag>
                  <n-tag size="tiny" :bordered="false" :style="{ background: methodConfig[req.method].bg, color: methodConfig[req.method].color }">
                    {{ methodConfig[req.method].label }}
                  </n-tag>
                </div>
              </div>
              <div class="req-fields">
                <n-icon :component="CheckmarkCircleOutline" size="14" class="check-icon" />
                <span>{{ req.fields }}</span>
              </div>
              <div class="req-purpose">用途：{{ req.purpose }}</div>
            </div>
          </div>
        </n-collapse-item>
      </n-collapse>
    </div>
  </div>
  </LoadingState>
</template>

<style>
/* Non-scoped styles for h()-rendered table cells */
.ds-name {
  font-family: 'Work Sans', sans-serif;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}
.ds-cat {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.ds-fields {
  font-size: 12px;
  color: var(--text-primary);
  line-height: 1.5;
}
.ds-note {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}
.ds-purpose {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}
.page-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.page-name {
  font-family: 'Work Sans', sans-serif;
  font-weight: 600;
  font-size: 12px;
  color: var(--text-primary);
}
.page-route {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-muted);
}
</style>

<style scoped>
.ds-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 概览卡片 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
}
.stat-card-custom {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.stat-label {
  font-family: 'Work Sans', sans-serif;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  text-transform: uppercase;
}
.stat-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.2;
}
.stat-sub {
  font-size: 12px;
  color: var(--text-muted);
}

/* 频率说明 */
.freq-info {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 0;
}
.freq-item {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.freq-icon {
  color: var(--color-primary);
  flex-shrink: 0;
  margin-top: 2px;
}
.freq-content h4 {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 4px;
}
.freq-content p {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0;
}

/* 分组详情 */
.grouped-section {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 18px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: 'Work Sans', sans-serif;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 12px;
}
.section-title .n-icon {
  color: var(--color-primary);
}
.grouped-reqs {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.grouped-req {
  padding: 12px;
  background: var(--bg-subtle);
  border-radius: 6px;
  border: 1px solid var(--border-default);
}
.req-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.req-category {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}
.req-tags {
  display: flex;
  gap: 4px;
}
.req-fields {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 6px;
}
.check-icon {
  color: var(--color-success);
  flex-shrink: 0;
  margin-top: 2px;
}
.req-purpose {
  font-size: 12px;
  color: var(--text-muted);
  padding-left: 20px;
}

/* API接口样式 */
.ds-api {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: var(--bg-hover);
  padding: 4px 8px;
  border-radius: 4px;
  color: var(--color-primary);
  word-break: break-all;
}
.ds-source {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.4;
}
.ds-no-api {
  font-size: 12px;
  color: var(--text-muted);
  font-style: italic;
}

/* Responsive */
@media (max-width: 1024px) {
  .stat-grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 768px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .freq-item { flex-direction: column; gap: 8px; }
}
</style>
