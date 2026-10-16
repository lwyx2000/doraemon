<script setup lang="ts">
/**
 * 长期视角（LongTerm）
 *
 * 以 10-20 年尺度观察 A 股的 5 个面板，数据全部爬取自「老钱日日谈 A股看板」
 * （https://ashare.laoqianriritan.com，纯静态站 data/*.json），后端每周六
 * 17:30 定时采集落库（services/longterm_service.py），首次部署后需点
 * 「立即采集」完成全量落库。本页只做展示，不改写上游数值；每个面板均注明
 * 数据来源与我方抓取时间。
 *
 * 面板：
 *   1. 申万行业年度涨跌幅热力图（2005 起 + YTD + CAGR）
 *   2. 指数收益三因子拆解（全收益 = 股息 + 盈利 + 估值）
 *   3. 市场趋势温度（个股 MA250 上方占比 日频 + 行业 MACD>0 占比 月频）
 *   4. 宽基指数全收益净值（9 指数，对数坐标）
 *   5. 华证六因子净值（成长/价值/低波/动量/质量/红利，对数坐标）
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { NCard, NButton, NSelect, NText, NEmpty, NSpin, useMessage } from 'naive-ui'
import { api } from '../utils/api'
import BaseChart from '../components/BaseChart.vue'
import PageHeader from '../components/PageHeader.vue'
import type {
  LqrSourceMeta,
  LqrSwReturns,
  LqrReturnDecomp,
  LqrTrendTemperature,
  LqrWideBase,
  LqrHuazheng,
  LqrStatus,
  LqrSwIndustry,
} from '../types'

const message = useMessage()

const loading = ref(false)
const collecting = ref(false)
const swReturns = ref<LqrSwReturns | null>(null)
const returnDecomp = ref<LqrReturnDecomp | null>(null)
const trendTemp = ref<LqrTrendTemperature | null>(null)
const wideBase = ref<LqrWideBase | null>(null)
const huazheng = ref<LqrHuazheng | null>(null)
const status = ref<LqrStatus | null>(null)

async function loadAll() {
  loading.value = true
  try {
    const [sw, decomp, trend, wide, hz, st] = await Promise.all([
      api.getLongtermSwReturns(),
      api.getLongtermReturnDecomp(),
      api.getLongtermTrendTemperature(),
      api.getLongtermWideBase(0),
      api.getLongtermHuazheng(0),
      api.getLongtermStatus(),
    ])
    swReturns.value = sw.data
    returnDecomp.value = decomp.data
    trendTemp.value = trend.data
    wideBase.value = wide.data
    huazheng.value = hz.data
    status.value = st.data
  } catch (e: any) {
    message.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

// ---------------------------------------------------------------- 采集 + 轮询
let pollTimer: number | null = null
let pollCount = 0

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
  pollCount = 0
}

function startPolling() {
  if (pollTimer !== null) return
  pollCount = 0
  pollTimer = window.setInterval(async () => {
    pollCount += 1
    try {
      const res = await api.getLongtermStatus()
      status.value = res.data
    } catch {
      /* 轮询失败静默，下一轮再试 */
    }
    const running = status.value?.scheduler?.manualCollect.running ?? false
    if (!running || pollCount >= 150) {
      stopPolling()
      collecting.value = false
      await loadAll()
      if (!running) message.success('采集完成，数据已刷新')
      else message.warning('采集仍在后台执行，可稍后刷新查看')
    }
  }, 5000)
}

onBeforeUnmount(stopPolling)

async function onCollect() {
  collecting.value = true
  try {
    const res = await api.collectLongterm(true)
    message.info(res.data?.message || '采集已开始在后台执行')
    startPolling()
  } catch (e: any) {
    collecting.value = false
    message.error(e?.message || '采集启动失败')
  }
}

// ---------------------------------------------------------------- 来源标注
const SOURCE_NAME = '老钱日日谈 A股看板（ashare.laoqianriritan.com）'

function srcNote(meta: LqrSourceMeta | null | undefined): string {
  if (!meta || !meta.fetchedAt) return `数据来源：${SOURCE_NAME}（尚未采集）`
  const up = meta.upstreamUpdated ? `（上游更新 ${meta.upstreamUpdated}）` : ''
  return `数据来源：${SOURCE_NAME} · 抓取于 ${meta.fetchedAt}${up}`
}

const hasData = computed(() => (swReturns.value?.industries.length ?? 0) > 0)

// 页面数据更新时间：取各面板抓取时间较新者（每周六 17:30 定时采集）
const pageUpdatedAt = computed(() => {
  const times = [swReturns.value, returnDecomp.value, trendTemp.value, wideBase.value, huazheng.value]
    .map((m) => m?.fetchedAt)
    .filter((t): t is string => !!t)
  if (!times.length) return null
  return times.sort()[times.length - 1]
})

// ---------------------------------------------------------------- 面板 1：行业年度热力图
const sortMode = ref<'ytd' | 'cagrFull' | 'cagr5y' | 'name'>('ytd')
const sortOptions = [
  { label: '按 YTD 涨跌幅', value: 'ytd' },
  { label: '按 21 年 CAGR', value: 'cagrFull' },
  { label: '按近 5 年 CAGR', value: 'cagr5y' },
  { label: '按行业名', value: 'name' },
]

function sortValue(ind: LqrSwIndustry, mode: string): number {
  if (mode === 'ytd') return ind.ytd ?? -9999
  if (mode === 'cagrFull') return ind.metrics?.cagrFull ?? -9999
  if (mode === 'cagr5y') return ind.metrics?.cagr5y ?? -9999
  return 0
}

const sortedIndustries = computed(() => {
  const arr = [...(swReturns.value?.industries ?? [])]
  if (sortMode.value === 'name') return arr.sort((a, b) => a.name.localeCompare(b.name, 'zh'))
  const mode = sortMode.value
  return arr.sort((a, b) => sortValue(b, mode) - sortValue(a, mode))
})

const heatYears = computed(() => swReturns.value?.years ?? [])

// 年度涨跌幅 ±80% 截断映射红涨绿跌透明度
function heatColor(v: number | null): string {
  if (v == null || !isFinite(v)) return 'var(--bg-subtle)'
  const c = Math.max(-80, Math.min(80, v)) / 80
  if (c >= 0) return `rgba(220,38,38,${(0.1 + c * 0.78).toFixed(3)})`
  return `rgba(22,163,74,${(0.1 + -c * 0.78).toFixed(3)})`
}

function heatText(v: number | null): string {
  if (v == null || !isFinite(v)) return 'var(--text-muted)'
  const c = Math.max(-80, Math.min(80, v)) / 80
  return Math.abs(c) > 0.55 ? '#ffffff' : 'var(--text-primary)'
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !isFinite(v)) return '—'
  return (v >= 0 ? '+' : '') + v.toFixed(digits) + '%'
}

function industryTip(ind: LqrSwIndustry): string {
  const m = ind.metrics
  const lines = [`${ind.name}（${ind.code || '—'}）`]
  lines.push(`YTD：${fmtPct(ind.ytd)}`)
  if (m) {
    lines.push(
      `CAGR：21年 ${fmtPct(m.cagrFull)} · 近7年 ${fmtPct(m.cagr7y)} · 近5年 ${fmtPct(m.cagr5y)} · 近3年 ${fmtPct(m.cagr3y)}`
    )
  }
  return lines.join('\n')
}

// ---------------------------------------------------------------- 面板 2：收益三因子拆解
const decompChartOption = computed(() => {
  const idx = returnDecomp.value?.indexes ?? []
  if (!idx.length) return null
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (v: any) => (v == null ? '—' : Number(v).toFixed(1) + '%'),
    },
    legend: { top: 0 },
    grid: { left: 84, right: 36, top: 40, bottom: 28 },
    xAxis: { type: 'value', name: '区间涨幅贡献（%）' },
    yAxis: { type: 'category', data: idx.map((i) => i.name) },
    series: [
      {
        name: '股息贡献',
        type: 'bar',
        stack: 'total',
        data: idx.map((i) => i.dividendPct),
        itemStyle: { color: '#f59e0b' },
      },
      {
        name: '盈利贡献',
        type: 'bar',
        stack: 'total',
        data: idx.map((i) => i.earningsPct),
        itemStyle: { color: '#3b82f6' },
      },
      {
        name: '估值贡献',
        type: 'bar',
        stack: 'total',
        data: idx.map((i) => i.valuationPct),
        itemStyle: { color: '#a78bfa' },
      },
    ],
  }
})

// ---------------------------------------------------------------- 面板 3：趋势温度
const stockMaOption = computed(() => {
  const pts = trendTemp.value?.stockMa250 ?? []
  if (!pts.length) return null
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: any) => (v == null ? '—' : Number(v).toFixed(1) + '%'),
    },
    grid: { left: 46, right: 16, top: 28, bottom: 48 },
    xAxis: { type: 'category', data: pts.map((p) => p.date), boundaryGap: false },
    yAxis: { type: 'value', min: 0, max: 100, name: '占比 %' },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 22 }],
    series: [
      {
        name: '个股 MA250 上方占比',
        type: 'line',
        data: pts.map((p) => p.pctAbove),
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 2, color: '#dc2626' },
        areaStyle: { opacity: 0.1 },
        markLine: {
          symbol: 'none',
          lineStyle: { type: 'dashed', opacity: 0.5 },
          label: { position: 'insideEndTop' },
          data: [{ yAxis: 50, name: '中位' }],
        },
      },
    ],
  }
})

const industryMacdOption = computed(() => {
  const pts = trendTemp.value?.industryMacd ?? []
  if (!pts.length) return null
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: any) => (v == null ? '—' : Number(v).toFixed(1) + '%'),
    },
    grid: { left: 46, right: 16, top: 28, bottom: 48 },
    xAxis: { type: 'category', data: pts.map((p) => p.date), boundaryGap: false },
    yAxis: { type: 'value', min: 0, max: 100, name: '占比 %' },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 22 }],
    series: [
      {
        name: '行业 MACD>0 占比',
        type: 'line',
        data: pts.map((p) => p.pctPositive),
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 2, color: '#2563eb' },
        areaStyle: { opacity: 0.1 },
        markLine: {
          symbol: 'none',
          lineStyle: { type: 'dashed', opacity: 0.5 },
          label: { position: 'insideEndTop' },
          data: [{ yAxis: 50, name: '中位' }],
        },
      },
    ],
  }
})

// ---------------------------------------------------------------- 面板 4/5：对数坐标净值
const LINE_COLORS = [
  '#dc2626',
  '#2563eb',
  '#16a34a',
  '#f59e0b',
  '#7c3aed',
  '#0891b2',
  '#db2777',
  '#65a30d',
  '#64748b',
]

const wideBaseOption = computed(() => {
  const s = wideBase.value?.series ?? {}
  const codes = Object.keys(s)
  if (!codes.length) return null
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: any) => (v == null ? '—' : Number(v).toFixed(2)),
    },
    legend: { top: 0, type: 'scroll' },
    grid: { left: 60, right: 20, top: 52, bottom: 60 },
    xAxis: { type: 'category', data: s[codes[0]].dates, boundaryGap: false },
    yAxis: { type: 'log', name: '全收益净值（对数）' },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 26 }],
    series: codes.map((code, i) => ({
      name: s[code].name || code,
      type: 'line',
      data: s[code].values,
      showSymbol: false,
      lineStyle: { width: 1.6, color: LINE_COLORS[i % LINE_COLORS.length] },
      itemStyle: { color: LINE_COLORS[i % LINE_COLORS.length] },
    })),
  }
})

const huazhengOption = computed(() => {
  const s = huazheng.value?.factors ?? {}
  const names = Object.keys(s)
  if (!names.length) return null
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: any) => (v == null ? '—' : Number(v).toFixed(3)),
    },
    legend: { top: 0 },
    grid: { left: 60, right: 20, top: 52, bottom: 60 },
    xAxis: { type: 'category', data: s[names[0]].dates, boundaryGap: false },
    yAxis: { type: 'log', name: '因子净值（对数）' },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 26 }],
    series: names.map((name, i) => ({
      name: s[name].name || name,
      type: 'line',
      data: s[name].values,
      showSymbol: false,
      lineStyle: { width: 1.8, color: LINE_COLORS[i % LINE_COLORS.length] },
      itemStyle: { color: LINE_COLORS[i % LINE_COLORS.length] },
    })),
  }
})
</script>

<template>
  <div class="longterm-page">
    <PageHeader
      title="长期视角"
      subtitle="行业年度收益 · 指数收益拆解 · 趋势温度 · 宽基/因子净值（数据来源：老钱日日谈 A股看板）"
      helpKey="longterm"
      :updated-at="pageUpdatedAt"
    >
      <template #actions>
        <NButton size="small" quaternary :loading="loading" @click="loadAll">刷新</NButton>
        <NButton size="small" type="primary" :loading="collecting" @click="onCollect">立即采集</NButton>
      </template>
    </PageHeader>

    <n-spin :show="loading">
      <div class="lt-stack">
        <!-- 空状态：尚未采集 -->
        <n-empty v-if="!hasData && !loading" description="暂无长期视角数据">
          <template #extra>
            <div class="empty-extra">
              <NText depth="3" style="font-size: 13px">
                首次使用请点右上角「立即采集」完成全量落库（约 1-2 分钟）；<br />
                此后每周六 17:30 会自动抓取本周更新。
              </NText>
              <NButton size="small" type="primary" :loading="collecting" @click="onCollect">
                立即采集
              </NButton>
            </div>
          </template>
        </n-empty>

        <template v-if="hasData">
          <!-- ============ 面板 1：申万行业年度涨跌幅热力图 ============ -->
          <n-card title="申万行业年度涨跌幅（2005 起）" :bordered="true">
            <template #header-extra>
              <n-text depth="3" class="src-note">{{ srcNote(swReturns) }}</n-text>
            </template>
            <div class="panel-toolbar">
              <NText depth="3" style="font-size: 12px">
                共 {{ swReturns!.industries.length }} 个申万一级行业 · 颜色按年度涨跌幅 ±80% 截断映射（红涨绿跌）· 悬停单元格看 CAGR
              </NText>
              <NSelect
                v-model:value="sortMode"
                :options="sortOptions"
                size="small"
                style="width: 150px"
              />
            </div>
            <div class="heat-wrap">
              <div
                class="heat-grid"
                :style="{
                  gridTemplateColumns: `84px repeat(${heatYears.length + 2}, minmax(36px, 1fr))`,
                }"
              >
                <!-- 表头 -->
                <div class="heat-cell heat-head heat-name-head">行业</div>
                <div v-for="y in heatYears" :key="y" class="heat-cell heat-head">
                  {{ String(y).slice(2) }}
                </div>
                <div class="heat-cell heat-head heat-ytd-head">YTD</div>
                <div class="heat-cell heat-head heat-cagr-head">21年CAGR</div>
                <!-- 数据行 -->
                <template v-for="ind in sortedIndustries" :key="ind.name">
                  <div class="heat-cell heat-name" :title="`${ind.name}（${ind.code || '—'}）`">
                    {{ ind.name }}
                  </div>
                  <div
                    v-for="(ret, i) in ind.rets"
                    :key="i"
                    class="heat-cell heat-val"
                    :style="{ background: heatColor(ret), color: heatText(ret) }"
                    :title="`${ind.name} ${heatYears[i]} 年：${fmtPct(ret)}`"
                  >
                    {{ ret == null ? '·' : ret.toFixed(0) }}
                  </div>
                  <div
                    class="heat-cell heat-val heat-ytd"
                    :style="{ background: heatColor(ind.ytd), color: heatText(ind.ytd) }"
                    :title="`${ind.name} YTD：${fmtPct(ind.ytd)}`"
                  >
                    {{ ind.ytd == null ? '·' : ind.ytd.toFixed(0) }}
                  </div>
                  <div
                    class="heat-cell heat-val heat-cagr"
                    :title="industryTip(ind)"
                    :class="{ up: (ind.metrics?.cagrFull ?? 0) >= 0, down: (ind.metrics?.cagrFull ?? 0) < 0 }"
                  >
                    {{ ind.metrics?.cagrFull == null ? '—' : ind.metrics.cagrFull.toFixed(1) }}
                  </div>
                </template>
              </div>
            </div>
            <div class="heat-legend">
              <span class="lg lg-down">-80%</span>
              <span class="lg-bar"></span>
              <span class="lg lg-up">+80%</span>
            </div>
          </n-card>

          <!-- ============ 面板 2：指数收益三因子拆解 ============ -->
          <n-card title="指数收益三因子拆解（全收益 = 股息 + 盈利 + 估值）">
            <template #header-extra>
              <n-text depth="3" class="src-note">{{ srcNote(returnDecomp) }}</n-text>
            </template>
            <BaseChart v-if="decompChartOption" :option="decompChartOption" :height="300" />
            <n-empty v-else description="暂无拆解数据" style="padding: 24px 0" />
            <div v-if="returnDecomp?.indexes.length" class="table-wrap">
              <table class="mini-table">
                <thead>
                  <tr>
                    <th>指数</th>
                    <th>区间</th>
                    <th class="num">全收益</th>
                    <th class="num">股息</th>
                    <th class="num">盈利</th>
                    <th class="num">估值</th>
                    <th class="num">PE（起→末）</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="ix in returnDecomp!.indexes" :key="ix.code">
                    <td>{{ ix.name }}</td>
                    <td class="muted">{{ ix.start }} → {{ ix.end }}</td>
                    <td class="num strong" :class="ix.totalReturnPct! >= 0 ? 'up' : 'down'">
                      {{ fmtPct(ix.totalReturnPct) }}
                    </td>
                    <td class="num" :class="ix.dividendPct! >= 0 ? 'up' : 'down'">{{ fmtPct(ix.dividendPct) }}</td>
                    <td class="num" :class="ix.earningsPct! >= 0 ? 'up' : 'down'">{{ fmtPct(ix.earningsPct) }}</td>
                    <td class="num" :class="ix.valuationPct! >= 0 ? 'up' : 'down'">{{ fmtPct(ix.valuationPct) }}</td>
                    <td class="num muted">
                      {{ ix.peStart == null ? '—' : ix.peStart.toFixed(1) }} →
                      {{ ix.peEnd == null ? '—' : ix.peEnd.toFixed(1) }}
                    </td>
                  </tr>
                </tbody>
              </table>
              <n-text depth="3" style="font-size: 11px">
                估值贡献为负 = 指数上涨主要来自盈利与股息而非估值扩张，长期持有体验通常更稳。
              </n-text>
            </div>
          </n-card>

          <!-- ============ 面板 3：市场趋势温度 ============ -->
          <n-card title="市场趋势温度（个股 MA250 上方占比 + 行业 MACD>0 占比）">
            <template #header-extra>
              <n-text depth="3" class="src-note">{{ srcNote(trendTemp) }}</n-text>
            </template>
            <div class="trend-block">
              <div class="trend-subtitle">
                <NText strong>个股 MA250 上方占比（日频，赚钱广度）</NText>
                <NText depth="3" style="font-size: 12px">
                  {{ trendTemp?.stockMa250.length ? `${trendTemp.stockMa250[0].date} 起 · ${trendTemp.stockMa250.length} 个交易日` : '' }}
                </NText>
              </div>
              <BaseChart v-if="stockMaOption" :option="stockMaOption" :height="220" />
              <n-empty v-else description="暂无个股温度数据" style="padding: 16px 0" />
            </div>
            <div class="trend-block">
              <div class="trend-subtitle">
                <NText strong>申万行业 MACD>0 占比（月频，中期趋势扩散度）</NText>
                <NText depth="3" style="font-size: 12px">
                  {{ trendTemp?.industryMacd.length ? `${trendTemp.industryMacd[0].date} 起 · ${trendTemp.industryMacd.length} 个月` : '' }}
                </NText>
              </div>
              <BaseChart v-if="industryMacdOption" :option="industryMacdOption" :height="220" />
              <n-empty v-else description="暂无行业温度数据" style="padding: 16px 0" />
            </div>
          </n-card>

          <!-- ============ 面板 4：宽基全收益净值 ============ -->
          <n-card title="宽基指数全收益净值（含股息再投资，对数坐标）">
            <template #header-extra>
              <n-text depth="3" class="src-note">{{ srcNote(wideBase) }}</n-text>
            </template>
            <BaseChart v-if="wideBaseOption" :option="wideBaseOption" :height="400" />
            <n-empty v-else description="暂无宽基净值数据" style="padding: 24px 0" />
            <n-text depth="3" style="font-size: 12px">
              全收益指数把股息按规则再投资，衡量「买入并持有」的真实长期回报；对数坐标下等比例涨跌幅为等距，便于对比不同起点的指数。
            </n-text>
          </n-card>

          <!-- ============ 面板 5：华证六因子净值 ============ -->
          <n-card title="华证六因子净值（成长/价值/低波/动量/质量/红利，对数坐标）">
            <template #header-extra>
              <n-text depth="3" class="src-note">{{ srcNote(huazheng) }}</n-text>
            </template>
            <BaseChart v-if="huazhengOption" :option="huazhengOption" :height="400" />
            <n-empty v-else description="暂无因子净值数据" style="padding: 24px 0" />
            <n-text depth="3" style="font-size: 12px">
              每因子由大中小微四档自由流通市值加权（9FF）日收益等权链式合成，观察长期风格轮动；单一因子可能连续多年跑输，宜作配置参考而非短期信号。
            </n-text>
          </n-card>

          <!-- ============ 来源与口径说明 ============ -->
          <n-card title="数据来源与口径说明">
            <ul class="notes">
              <li>
                <b>数据来源</b>：本页 5 组数据均爬取自「老钱日日谈 A股看板」
                （<span class="mono">ashare.laoqianriritan.com</span>），为第三方加工结果，
                本系统只做搬运与展示、不改写数值；每个面板标题右侧标注了我方抓取时间与上游更新时间。
              </li>
              <li>
                <b>更新频率</b>：后端每周六 17:30 定时抓取一次（长期数据非实时行情，周频足够）；
                首次使用或想看最新数据时，可随时点页面右上角「立即采集」。
              </li>
              <li>
                <b>上游停更</b>：若上游站点不可用或停止更新，页面展示最近一次成功抓取的快照，
                「数据来源」处的抓取时间即为数据新鲜度参考。
              </li>
              <li>
                <b>使用边界</b>：以上均为长周期历史统计，用于判断长期配置方向，
                不构成短期择时建议，也不构成任何投资建议。
              </li>
            </ul>
          </n-card>
        </template>
      </div>
    </n-spin>
  </div>
</template>

<style scoped>
.longterm-page {
  padding: 4px;
}

.lt-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty-extra {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  text-align: center;
}

.src-note {
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 46vw;
}

/* ---------------- 面板 1：热力图 ---------------- */
.panel-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.heat-wrap {
  overflow-x: auto;
}

.heat-grid {
  display: grid;
  gap: 3px;
  min-width: 960px;
}

.heat-cell {
  border-radius: 4px;
  padding: 4px 2px;
  font-size: 11px;
  text-align: center;
  font-family: 'JetBrains Mono', monospace;
  min-height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.heat-head {
  font-weight: 700;
  color: var(--text-muted);
  background: transparent;
}

.heat-name-head,
.heat-ytd-head,
.heat-cagr-head {
  color: var(--text-secondary);
}

.heat-name {
  justify-content: flex-start;
  font-family: 'Work Sans', sans-serif;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  background: var(--bg-subtle);
  padding-left: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.heat-val {
  cursor: default;
}

.heat-ytd {
  outline: 1px dashed rgba(127, 127, 127, 0.35);
  outline-offset: -1px;
}

.heat-cagr {
  font-weight: 700;
  background: var(--bg-subtle);
}

.heat-cagr.up { color: var(--color-danger); }
.heat-cagr.down { color: var(--color-success); }

.heat-legend {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.lg-bar {
  width: 120px;
  height: 8px;
  border-radius: 4px;
  background: linear-gradient(90deg,
    rgba(22, 163, 74, 0.85),
    rgba(22, 163, 74, 0.2),
    var(--bg-subtle),
    rgba(220, 38, 38, 0.2),
    rgba(220, 38, 38, 0.85));
}

.lg-up { color: var(--color-danger); }
.lg-down { color: var(--color-success); }

/* ---------------- 面板 2：拆解表 ---------------- */
.table-wrap {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mini-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.mini-table th,
.mini-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-default, rgba(127, 127, 127, 0.15));
  text-align: left;
  white-space: nowrap;
}

.mini-table th {
  color: var(--text-muted);
  font-weight: 600;
}

.mini-table .num {
  text-align: right;
  font-family: 'JetBrains Mono', monospace;
}

.mini-table .strong { font-weight: 700; }
.mini-table .muted { color: var(--text-muted); }
.mini-table .up { color: var(--color-danger); }
.mini-table .down { color: var(--color-success); }

/* ---------------- 面板 3：趋势温度 ---------------- */
.trend-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.trend-block + .trend-block {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed var(--border-default, rgba(127, 127, 127, 0.2));
}

.trend-subtitle {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}

/* ---------------- 说明卡 ---------------- */
.notes {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.notes b {
  color: var(--text-primary);
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}
</style>
