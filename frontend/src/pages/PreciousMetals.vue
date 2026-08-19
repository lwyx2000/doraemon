<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NCard,
  NGrid,
  NGi,
  NStatistic,
  NTag,
  NText,
  NEmpty,
  NSpin,
  NAlert,
  NSpace,
} from 'naive-ui'
import { api } from '../utils/api'
import BaseChart from '../components/BaseChart.vue'
import PageHeader from '../components/PageHeader.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import type { PreciousMetals as PreciousMetalsData } from '../types'

const loading = ref(false)
const error = ref<string | null>(null)
const data = ref<PreciousMetalsData | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    const res = await api.getPreciousMetals()
    data.value = res.data as PreciousMetalsData
    if (!data.value || !data.value.available) {
      error.value = '暂无贵金属数据（取数失败）'
    }
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const ratioDates = computed(() => (data.value?.ratio.history || []).map((h) => h.date))
const ratioValues = computed(() => (data.value?.ratio.history || []).map((h) => h.ratio))

// 金银比统计: 均值 + 25/75 分位 + 当前历史分位
const ratioStats = computed(() => {
  const vals = ratioValues.value.filter((v) => v != null).slice().sort((a, b) => a - b)
  if (!vals.length) return null
  const mean = vals.reduce((s, v) => s + v, 0) / vals.length
  const quantile = (p: number) => {
    const pos = (vals.length - 1) * p
    const base = Math.floor(pos)
    const rest = pos - base
    const next = vals[base + 1]
    return next !== undefined ? vals[base] + rest * (next - vals[base]) : vals[base]
  }
  const current = data.value?.ratio.current ?? null
  let currentPct: number | null = null
  if (current != null) {
    const le = vals.filter((v) => v <= current).length
    currentPct = Math.round((le / vals.length) * 100)
  }
  const r2 = (x: number) => Math.round(x * 100) / 100
  return { mean: r2(mean), p25: r2(quantile(0.25)), p75: r2(quantile(0.75)), currentPct }
})

const priceDates = computed(() => (data.value?.gold.history || []).map((h) => h.date))
const goldPriceMap = computed(() => {
  const m: Record<string, number> = {}
  ;(data.value?.gold.history || []).forEach((h) => {
    m[h.date] = h.price
  })
  return m
})
const silverPriceMap = computed(() => {
  const m: Record<string, number> = {}
  ;(data.value?.silver.history || []).forEach((h) => {
    m[h.date] = h.price
  })
  return m
})
const goldPriceSeries = computed(() => priceDates.value.map((d) => goldPriceMap.value[d] ?? null))
const silverPriceSeries = computed(() =>
  priceDates.value.map((d) => silverPriceMap.value[d] ?? null)
)

const ratioOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 50, right: 20, top: 30, bottom: 70 },
  xAxis: { type: 'category', data: ratioDates.value, boundaryGap: false },
  yAxis: { type: 'value', scale: true, name: '金银比' },
  dataZoom: [
    { type: 'inside' },
    { type: 'slider', height: 20, bottom: 20 },
  ],
  series: [
    {
      name: '金银比',
      type: 'line',
      data: ratioValues.value,
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 2 },
      areaStyle: { opacity: 0.08 },
      markLine: {
        symbol: 'none',
        precision: 2,
        label: {
          formatter: (p: any) => `${p.name} ${p.value}`,
          position: 'insideEndTop',
        },
        lineStyle: { type: 'dashed', opacity: 0.6 },
        data: [
          { yAxis: ratioStats.value?.mean ?? undefined, name: '均值' },
          { yAxis: ratioStats.value?.p25 ?? undefined, name: '25分位' },
          { yAxis: ratioStats.value?.p75 ?? undefined, name: '75分位' },
        ].filter((d) => d.yAxis != null),
      },
    },
  ],
}))

const priceOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { data: ['黄金(元/克)', '白银(元/克)'] },
  grid: { left: 60, right: 60, top: 40, bottom: 70 },
  xAxis: { type: 'category', data: priceDates.value, boundaryGap: false },
  yAxis: [
    { type: 'value', scale: true, name: '黄金', position: 'left' },
    { type: 'value', scale: true, name: '白银', position: 'right' },
  ],
  dataZoom: [
    { type: 'inside' },
    { type: 'slider', height: 20, bottom: 20 },
  ],
  series: [
    {
      name: '黄金(元/克)',
      type: 'line',
      yAxisIndex: 0,
      data: goldPriceSeries.value,
      showSymbol: false,
      smooth: true,
    },
    {
      name: '白银(元/克)',
      type: 'line',
      yAxisIndex: 1,
      data: silverPriceSeries.value,
      showSymbol: false,
      smooth: true,
    },
  ],
}))

function fmt(v: number | null | undefined, digits = 2) {
  return v == null ? '—' : v.toFixed(digits)
}
function tagType(pct: number | null | undefined): 'error' | 'success' | 'default' {
  if (pct == null) return 'default'
  return pct >= 0 ? 'error' : 'success'
}
</script>

<template>
  <div class="precious-page">
    <PageHeader title="贵金属 · 黄金 / 白银 / 金银比" subtitle="SGE 现货 Au99.99 / Ag99.99" helpKey="preciousMetals" />

    <GlossaryPanel page-key="preciousMetals" />

    <n-space vertical :size="16">
      <div v-if="data?.updatedAt" class="data-date">
        <n-text depth="3">数据日期：{{ data.updatedAt }}</n-text>
      </div>

      <n-spin :show="loading">
        <template v-if="error">
          <n-alert type="warning" :title="error" />
        </template>

        <template v-else-if="data && data.available">
          <n-grid :cols="3" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
            <n-gi span="3 m:1">
              <n-card title="黄金现货 Au99.99">
                <n-statistic :value="data.gold.price ?? 0" :precision="2" tabular-nums>
                  <template #prefix>¥</template>
                  <template #suffix>元/克</template>
                </n-statistic>
                <n-space :size="8" style="margin-top: 8px">
                  <n-tag :type="tagType(data.gold.changePct)" size="small">
                    {{ (data.gold.changePct ?? 0) >= 0 ? '▲' : '▼' }}
                    {{ fmt(data.gold.changePct, 2) }}%
                  </n-tag>
                  <n-text depth="3" style="font-size: 12px">SGE 现货</n-text>
                </n-space>
              </n-card>
            </n-gi>

            <n-gi span="3 m:1">
              <n-card title="白银现货 Ag99.99">
                <n-statistic :value="data.silver.price ?? 0" :precision="2" tabular-nums>
                  <template #prefix>¥</template>
                  <template #suffix>元/克</template>
                </n-statistic>
                <n-space :size="8" style="margin-top: 8px">
                  <n-tag :type="tagType(data.silver.changePct)" size="small">
                    {{ (data.silver.changePct ?? 0) >= 0 ? '▲' : '▼' }}
                    {{ fmt(data.silver.changePct, 2) }}%
                  </n-tag>
                  <n-text depth="3" style="font-size: 12px" v-if="data.silver.rawPrice">
                    原始 {{ fmt(data.silver.rawPrice, 0) }} 元/千克
                  </n-text>
                </n-space>
              </n-card>
            </n-gi>

            <n-gi span="3 m:1">
              <n-card title="金银比 (金 ÷ 银)">
                <n-statistic :value="data.ratio.current ?? 0" :precision="2" tabular-nums>
                  <template #suffix>倍</template>
                </n-statistic>
                <n-space :size="8" style="margin-top: 8px">
                  <n-tag size="small" :bordered="false" :type="ratioStats ? (ratioStats.currentPct != null && ratioStats.currentPct >= 80 ? 'error' : ratioStats.currentPct != null && ratioStats.currentPct <= 20 ? 'success' : 'default') : 'default'">
                    历史分位 {{ ratioStats?.currentPct ?? '—' }}%
                  </n-tag>
                  <n-text depth="3" style="font-size: 12px" v-if="ratioStats">
                    均值 {{ ratioStats.mean }} · 25/75分位 {{ ratioStats.p25 }}/{{ ratioStats.p75 }}
                  </n-text>
                </n-space>
              </n-card>
            </n-gi>
          </n-grid>

          <n-card title="金银比历史走势（近10年）" style="margin-top: 16px">
            <BaseChart :option="ratioOption" :height="320" />
          </n-card>

          <n-card title="黄金 / 白银价格走势（近10年）" style="margin-top: 16px">
            <BaseChart :option="priceOption" :height="320" />
          </n-card>
        </template>

        <template v-else>
          <n-empty description="暂无数据" />
        </template>
      </n-spin>
    </n-space>
  </div>
</template>

<style scoped>
.precious-page {
  padding: 4px;
}
.data-date {
  font-size: 13px;
}
</style>
