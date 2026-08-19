<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  NModal,
  NSpin,
  NEmpty,
  NCheckboxGroup,
  NCheckbox,
  NSpace,
} from 'naive-ui'
import { api } from '../utils/api'
import BaseChart from './BaseChart.vue'

interface KlinePoint {
  date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
}

interface Props {
  show: boolean
  code: string
  name: string
}

const props = defineProps<Props>()
const emit = defineEmits<{ (e: 'update:show', v: boolean): void }>()

const loading = ref(false)
const data = ref<KlinePoint[]>([])
const error = ref<string | null>(null)

const indicators = ref<string[]>(['ma', 'volume'])

const indicatorOptions = [
  { label: '成交量', value: 'volume' },
  { label: 'MA', value: 'ma' },
  { label: 'MACD', value: 'macd' },
  { label: 'KDJ', value: 'kdj' },
  { label: 'RSI', value: 'rsi' },
  { label: 'BOLL', value: 'boll' },
]

watch(() => props.show, (show) => {
  if (show && props.code) {
    fetchHistory()
  }
})

async function fetchHistory() {
  loading.value = true
  error.value = null
  try {
    const res = await api.getIndexHistory(props.code)
    data.value = res.data || []
  } catch (e: any) {
    error.value = e?.message || '获取 K 线失败'
  } finally {
    loading.value = false
  }
}

function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = []
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= period) sum -= values[i - period]
    if (i >= period - 1) {
      out.push(sum / period)
    } else {
      out.push(null)
    }
  }
  return out
}

function ema(values: number[], period: number): number[] {
  const k = 2 / (period + 1)
  const out: number[] = []
  let prev = values[0]
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    prev = i === 0 ? v : v * k + prev * (1 - k)
    out.push(prev)
  }
  return out
}

function max(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = []
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      out.push(null)
      continue
    }
    let m = values[i]
    for (let j = 1; j < period; j++) m = Math.max(m, values[i - j])
    out.push(m)
  }
  return out
}

function min(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = []
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      out.push(null)
      continue
    }
    let m = values[i]
    for (let j = 1; j < period; j++) m = Math.min(m, values[i - j])
    out.push(m)
  }
  return out
}

const dates = computed(() => data.value.map(d => d.date))
const closes = computed(() => data.value.map(d => d.close))
const highs = computed(() => data.value.map(d => d.high))
const lows = computed(() => data.value.map(d => d.low))
const volumes = computed(() => data.value.map(d => d.volume))

const ma5 = computed(() => sma(closes.value, 5))
const ma10 = computed(() => sma(closes.value, 10))
const ma20 = computed(() => sma(closes.value, 20))
const ma60 = computed(() => sma(closes.value, 60))

const macd = computed(() => {
  if (closes.value.length < 35) return null
  const dif = ema(closes.value, 12).map((v, i) => v - ema(closes.value, 26)[i])
  const dea = ema(dif, 9)
  const hist = dif.map((v, i) => v - dea[i])
  return { dif, dea, hist }
})

const kdj = computed(() => {
  const n = 9
  if (data.value.length < n) return null
  const rsv: (number | null)[] = []
  const ln = min(lows.value, n)
  const hn = max(highs.value, n)
  for (let i = 0; i < data.value.length; i++) {
    if (ln[i] == null || hn[i] == null) {
      rsv.push(null)
      continue
    }
    const low = ln[i] as number
    const high = hn[i] as number
    rsv.push(high === low ? 50 : (closes.value[i] - low) / (high - low) * 100)
  }
  const k: (number | null)[] = []
  const d: (number | null)[] = []
  const j: (number | null)[] = []
  let prevK = 50
  let prevD = 50
  for (let i = 0; i < rsv.length; i++) {
    if (rsv[i] == null) {
      k.push(null); d.push(null); j.push(null)
      continue
    }
    const r = rsv[i] as number
    const kk = (2 * prevK + r) / 3
    const dd = (2 * prevD + kk) / 3
    const jj = 3 * kk - 2 * dd
    k.push(kk); d.push(dd); j.push(jj)
    prevK = kk; prevD = dd
  }
  return { k, d, j }
})

const rsi = computed(() => {
  function calc(period: number): (number | null)[] {
    if (closes.value.length < period + 1) return []
    const out: (number | null)[] = []
    for (let i = 0; i < closes.value.length; i++) {
      if (i < period) {
        out.push(null)
        continue
      }
      let gain = 0
      let loss = 0
      for (let j = i - period + 1; j <= i; j++) {
        const diff = closes.value[j] - closes.value[j - 1]
        if (diff >= 0) gain += diff
        else loss -= diff
      }
      const rs = loss === 0 ? 100 : gain / loss
      out.push(100 - 100 / (1 + rs))
    }
    return out
  }
  return { rsi6: calc(6), rsi12: calc(12), rsi24: calc(24) }
})

const boll = computed(() => {
  if (closes.value.length < 20) return null
  const mid = sma(closes.value, 20) as (number | null)[]
  const upper: (number | null)[] = []
  const lower: (number | null)[] = []
  for (let i = 0; i < closes.value.length; i++) {
    if (mid[i] == null) {
      upper.push(null); lower.push(null)
      continue
    }
    const m = mid[i] as number
    let sum = 0
    for (let j = i - 19; j <= i; j++) sum += Math.pow(closes.value[j] - m, 2)
    const std = Math.sqrt(sum / 20)
    upper.push(m + 2 * std)
    lower.push(m - 2 * std)
  }
  return { mid, upper, lower }
})

const chartOption = computed(() => {
  if (data.value.length === 0) return {}

  const candleData = data.value.map(d => [d.open, d.close, d.low, d.high])
  const grids: any[] = []
  const xAxes: any[] = []
  const yAxes: any[] = []
  const series: any[] = []

  let gridIndex = 0
  // 子图(成交量/MACD/KDJ/RSI)从上到下依次堆叠，避免重叠
  let subTop = 275
  const addGrid = (height: number, top: number) => {
    grids.push({ left: 50, right: 20, top, height })
    xAxes.push({ type: 'category', gridIndex, data: dates.value, axisLabel: { show: gridIndex === 0 ? false : true } })
    yAxes.push({ scale: true, gridIndex })
    return gridIndex++
  }
  const addSubGrid = (height: number) => {
    const g = addGrid(height, subTop)
    subTop += height + 10
    return g
  }

  // Main K-line + MA + BOLL
  const mainGrid = addGrid(220, 40)
  series.push({
    name: 'K线',
    type: 'candlestick',
    xAxisIndex: mainGrid,
    yAxisIndex: mainGrid,
    data: candleData,
    itemStyle: {
      color: '#ef4444',
      color0: '#10b981',
      borderColor: '#ef4444',
      borderColor0: '#10b981',
    },
  })

  if (indicators.value.includes('ma')) {
    series.push(
      { name: 'MA5', type: 'line', xAxisIndex: mainGrid, yAxisIndex: mainGrid, data: ma5.value, smooth: true, symbol: 'none', lineStyle: { width: 1 } },
      { name: 'MA10', type: 'line', xAxisIndex: mainGrid, yAxisIndex: mainGrid, data: ma10.value, smooth: true, symbol: 'none', lineStyle: { width: 1 } },
      { name: 'MA20', type: 'line', xAxisIndex: mainGrid, yAxisIndex: mainGrid, data: ma20.value, smooth: true, symbol: 'none', lineStyle: { width: 1 } },
      { name: 'MA60', type: 'line', xAxisIndex: mainGrid, yAxisIndex: mainGrid, data: ma60.value, smooth: true, symbol: 'none', lineStyle: { width: 1 } },
    )
  }

  if (indicators.value.includes('boll') && boll.value) {
    series.push(
      { name: 'BOLL中轨', type: 'line', xAxisIndex: mainGrid, yAxisIndex: mainGrid, data: boll.value.mid, smooth: true, symbol: 'none', lineStyle: { width: 1, type: 'dashed' } },
      { name: 'BOLL上轨', type: 'line', xAxisIndex: mainGrid, yAxisIndex: mainGrid, data: boll.value.upper, smooth: true, symbol: 'none', lineStyle: { width: 1 } },
      { name: 'BOLL下轨', type: 'line', xAxisIndex: mainGrid, yAxisIndex: mainGrid, data: boll.value.lower, smooth: true, symbol: 'none', lineStyle: { width: 1 } },
    )
  }

  // Volume
  if (indicators.value.includes('volume')) {
    const volGrid = addSubGrid(60)
    series.push({
      name: '成交量',
      type: 'bar',
      xAxisIndex: volGrid,
      yAxisIndex: volGrid,
      data: volumes.value.map((v, i) => ({
        value: v,
        itemStyle: { color: candleData[i][1] >= candleData[i][0] ? '#ef4444' : '#10b981' },
      })),
    })
  }

  // MACD
  if (indicators.value.includes('macd') && macd.value) {
    const macdGrid = addSubGrid(70)
    series.push(
      { name: 'DIF', type: 'line', xAxisIndex: macdGrid, yAxisIndex: macdGrid, data: macd.value.dif, symbol: 'none' },
      { name: 'DEA', type: 'line', xAxisIndex: macdGrid, yAxisIndex: macdGrid, data: macd.value.dea, symbol: 'none' },
      { name: 'MACD', type: 'bar', xAxisIndex: macdGrid, yAxisIndex: macdGrid, data: macd.value.hist.map(v => ({ value: v, itemStyle: { color: v >= 0 ? '#ef4444' : '#10b981' } })) },
    )
  }

  // KDJ
  if (indicators.value.includes('kdj') && kdj.value) {
    const kdjGrid = addSubGrid(70)
    series.push(
      { name: 'K', type: 'line', xAxisIndex: kdjGrid, yAxisIndex: kdjGrid, data: kdj.value.k, symbol: 'none' },
      { name: 'D', type: 'line', xAxisIndex: kdjGrid, yAxisIndex: kdjGrid, data: kdj.value.d, symbol: 'none' },
      { name: 'J', type: 'line', xAxisIndex: kdjGrid, yAxisIndex: kdjGrid, data: kdj.value.j, symbol: 'none' },
    )
  }

  // RSI
  if (indicators.value.includes('rsi')) {
    const rsiGrid = addSubGrid(70)
    series.push(
      { name: 'RSI6', type: 'line', xAxisIndex: rsiGrid, yAxisIndex: rsiGrid, data: rsi.value.rsi6, symbol: 'none' },
      { name: 'RSI12', type: 'line', xAxisIndex: rsiGrid, yAxisIndex: rsiGrid, data: rsi.value.rsi12, symbol: 'none' },
      { name: 'RSI24', type: 'line', xAxisIndex: rsiGrid, yAxisIndex: rsiGrid, data: rsi.value.rsi24, symbol: 'none' },
    )
  }

  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    legend: {
      top: 10,
      data: series.map(s => s.name).filter(Boolean),
    },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [
      { type: 'inside', xAxisIndex: xAxes.map((_, i) => i) },
      { type: 'slider', xAxisIndex: xAxes.map((_, i) => i), bottom: 0, height: 16 },
    ],
    series,
  }
})

// 自适应图表高度：主图 260 + 各子图区域，保证不裁剪
const chartHeightPx = computed(() => {
  if (data.value.length === 0) return 500
  const hasVolume = indicators.value.includes('volume')
  let top = hasVolume ? 345 : 275
  const subs = ['macd', 'kdj', 'rsi'].filter(k => indicators.value.includes(k)).length
  const needed = top + subs * 80 + 70 + 24
  return Math.max(500, needed)
})
</script>

<template>
  <n-modal
    :show="props.show"
    @update:show="emit('update:show', $event)"
    preset="card"
    :title="`${props.name} (${props.code}) 历史 K 线`"
    style="width: 900px; max-width: 90vw;"
    :mask-closable="false"
    size="large"
  >
    <div class="kline-dialog">
      <n-space align="center" wrap class="indicator-bar">
        <span class="label">技术指标：</span>
        <n-checkbox-group v-model:value="indicators">
          <n-space>
            <n-checkbox v-for="opt in indicatorOptions" :key="opt.value" :value="opt.value" :label="opt.label" />
          </n-space>
        </n-checkbox-group>
      </n-space>

      <n-spin :show="loading" class="chart-wrap">
        <BaseChart v-if="data.length > 0" :option="chartOption" :height="chartHeightPx" />
        <n-empty v-else-if="!loading" description="暂无 K 线数据" />
        <div v-if="error" class="error-text">{{ error }}</div>
      </n-spin>
    </div>
  </n-modal>
</template>

<style scoped>
.kline-dialog {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.indicator-bar {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-default);
}
.label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}
.chart-wrap {
  min-height: 500px;
}
.error-text {
  color: var(--color-danger);
  font-size: 13px;
  padding: 16px;
  text-align: center;
}
</style>
