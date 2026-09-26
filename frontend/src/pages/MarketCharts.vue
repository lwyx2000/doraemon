<script setup lang="ts">
defineOptions({ name: 'MarketCharts' })
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { NButton, NEmpty, NTag, NSpin, NIcon, useMessage } from 'naive-ui'
import { RefreshOutline, CloudOfflineOutline } from '@vicons/ionicons5'
import { chartsApi, isGatewayNoData } from '../utils/api'
import type { MarketChart, ChartPanel, ChartSourceMeta } from '../utils/api'
import BaseChart from '../components/BaseChart.vue'
import DataPanel from '../components/DataPanel.vue'
import PageHeader from '../components/PageHeader.vue'

const message = useMessage()
const loading = ref(false)
const charts = ref<MarketChart[]>([])
const meta = ref<Record<string, any> | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null
let pollAttempts = 0

const PALETTE = ['#005ea1', '#dc2626', '#16a34a', '#f97316', '#7c3aed', '#0891b2', '#ca8a04']

async function loadAll(force = false) {
  loading.value = true
  try {
    const res = await chartsApi.all(force)
    charts.value = (res.data || []).filter(Boolean)
    meta.value = res.meta ?? null
  } catch (e: any) {
    message.error('获取市场复盘图表失败: ' + (e?.message || e))
    charts.value = []
  } finally {
    loading.value = false
    maybePoll()
  }
}

function maybePoll() {
  const anyEmpty = charts.value.some((c) => !c.primary?.dates?.length)
  if (anyEmpty && pollAttempts < 12) {
    if (!pollTimer) {
      pollTimer = setInterval(async () => {
        pollAttempts++
        try {
          const res = await chartsApi.all(false)
          const next = (res.data || []).filter(Boolean)
          // 仅用非空结果覆盖，避免回退到空
          charts.value = charts.value.map((old) => {
            const fresh = next.find((n) => n.id === old.id)
            return fresh && fresh.primary?.dates?.length ? fresh : old
          })
        } catch {
          /* ignore */
        }
        if (!charts.value.some((c) => !c.primary?.dates?.length) || pollAttempts >= 12) {
          stopPoll()
        }
      }, 15000)
    }
  } else {
    stopPoll()
  }
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function refresh() {
  pollAttempts = 0
  stopPoll()
  loadAll(true)
}

onMounted(() => loadAll(false))
onUnmounted(stopPoll)

// 降采样：序列过长时抽稀到 ≤240 点（保留末点）
function downsample(
  dates: string[],
  series: { name: string; color?: string; data: (number | null)[] }[],
) {
  const len = dates.length
  if (len <= 240) return { dates, series: series.map((s) => ({ ...s })) }
  const step = Math.max(1, Math.floor(len / 240))
  const idx = new Set<number>()
  for (let i = 0; i < len; i += step) idx.add(i)
  idx.add(len - 1)
  const d = dates.filter((_, i) => idx.has(i))
  const s = series.map((x) => ({
    name: x.name,
    color: x.color,
    data: x.data.filter((_, i) => idx.has(i)),
  }))
  return { dates: d, series: s }
}

function buildOption(panel: ChartPanel, height: number) {
  const ds = downsample(panel.dates, panel.series)
  const dates = ds.dates
  const series = (ds.series as any[]).map((s, i) => {
    const color = s.color || PALETTE[i % PALETTE.length]
    const isFirst = i === 0
    const opt: any = {
      type: 'line',
      smooth: false,
      showSymbol: false,
      name: s.name,
      data: s.data,
      lineStyle: { width: isFirst ? 2.2 : 1.4, color },
      itemStyle: { color },
    }
    if (panel.thresholds && isFirst) {
      opt.markLine = {
        symbol: 'none',
        silent: true,
        lineStyle: { type: 'dashed', width: 1 },
        data: panel.thresholds.map((t) => ({
          yAxis: t.yAxis,
          lineStyle: { color: t.color },
          label: { formatter: t.label, position: 'end', fontSize: 9, color: t.color },
        })),
      }
    }
    if (isFirst && (s.name.includes('回归') || s.name.includes('利差') || s.name.includes('股息率'))) {
      opt.areaStyle = { opacity: 0.06, color }
    }
    return opt
  })
  return {
    tooltip: { trigger: 'axis' },
    grid: { top: 18, right: 48, bottom: 28, left: 48 },
    xAxis: {
      type: 'category',
      data: dates,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#c1c6d7' } },
      axisLabel: { fontSize: 10, color: '#717782' },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { fontSize: 10, color: '#717782' },
      splitLine: { lineStyle: { type: 'dashed', color: 'rgba(0,0,0,0.06)' } },
    },
    series,
  }
}

const loadingCount = computed(
  () => charts.value.filter((c) => !c.primary?.dates?.length).length,
)

// 新鲜度标签：根据后端 meta 的 stale / ageMinutes / breakerOpen / gatewayEmpty / updateTime 判别"活的"还是"旧的"
function staleText(m: ChartSourceMeta | undefined): string {
  if (!m) return ''
  if (m.gatewayEmpty) return '网关无数据'
  if (m.breakerOpen) return '网关熔断 · 回退缓存'
  if (m.updateTime == null) return '数据缺失'
  if (m.stale) return `缓存较旧（约 ${m.ageMinutes ?? '?'} 分钟前更新）`
  if (m.ageMinutes != null) return `数据正常（${m.ageMinutes} 分钟前更新）`
  return '数据正常'
}
function staleType(m: ChartSourceMeta | undefined): 'success' | 'warning' | 'error' | 'default' {
  if (!m) return 'default'
  if (m.gatewayEmpty || m.breakerOpen || m.updateTime == null) return 'error'
  if (m.stale) return 'warning'
  return 'success'
}
</script>

<template>
  <div class="charts-page">
    <PageHeader title="市场复盘图表" subtitle="公众号「每周市场复盘」11 图 · 数据全部经 AkShare 网关" helpKey="marketCharts">
      <template #actions>
        <n-button size="tiny" :loading="loading" @click="refresh">
          <template #icon><n-icon :component="RefreshOutline" /></template>
          刷新（强制）
        </n-button>
      </template>
    </PageHeader>

    <div v-if="meta?.note" class="page-note">
      {{ meta.note }}
      <span v-if="loadingCount">（尚{{ loadingCount }} 图后台刷新中，将自动补齐）</span>
    </div>

    <div class="charts-grid">
      <DataPanel
        v-for="chart in charts"
        :key="chart.id"
        class="chart-card"
        :title="chart.title"
        :meta="chart.meta?.note || chart.description"
      >
        <div class="chart-body">
          <n-tag v-if="chart.meta" size="small" :bordered="false" :type="staleType(chart.meta)">
            {{ staleText(chart.meta) }}
          </n-tag>
          <p class="chart-desc">{{ chart.description }}</p>

          <template v-if="chart.primary?.dates?.length">
            <BaseChart :option="buildOption(chart.primary, 240)" :height="240" />
          </template>
          <div v-else-if="isGatewayNoData(chart.meta)" class="chart-gateway-empty">
            <n-icon :component="CloudOfflineOutline" size="28" class="gw-icon" />
            <span>网关无数据（上游未返回该图表数据）</span>
            <n-button size="tiny" type="primary" ghost @click="refresh">
              <template #icon><n-icon :component="RefreshOutline" /></template>
              重试
            </n-button>
          </div>
          <div v-else class="chart-loading">
            <n-spin size="small" />
            <span>数据后台刷新中…（首次加载需数分钟，请稍候或点刷新）</span>
          </div>

          <template v-if="chart.layout === 'prism' && chart.secondary?.dates?.length">
            <div class="sub-title">40日收益差（轮动信号二）</div>
            <BaseChart :option="buildOption(chart.secondary, 180)" :height="180" />
          </template>

          <div v-if="chart.meta?.note && chart.primary?.dates?.length" class="signal-note">
            <n-tag size="small" :bordered="false" type="warning">{{ chart.meta.note }}</n-tag>
          </div>
        </div>
      </DataPanel>
    </div>

    <n-empty v-if="!loading && charts.length === 0" description="暂无图表数据（上游取数失败）" />
  </div>
</template>

<style scoped>
.charts-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.page-note {
  padding: 8px 14px;
  background: var(--bg-subtle);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.charts-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
@media (max-width: 1024px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }
}
.chart-card {
  display: flex;
  flex-direction: column;
}
.chart-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px;
}
.chart-desc {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
}
.sub-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-top: 4px;
}
.chart-loading {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 12px;
  color: var(--text-muted);
  border: 1px dashed var(--border-default);
  border-radius: 6px;
}
.chart-gateway-empty {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 12px;
  color: var(--tag-orange-text, #874d00);
  background: #fff7e6;
  border: 1px dashed #ffd591;
  border-radius: 6px;
}
.chart-gateway-empty .gw-icon {
  color: var(--tag-orange-text, #d46b08);
}
.signal-note {
  margin-top: 4px;
}
</style>
