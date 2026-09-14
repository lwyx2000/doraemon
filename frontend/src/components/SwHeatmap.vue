<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NModal, NSpin, NEmpty, NText, NSelect } from 'naive-ui'
import type { SwSector, SwSectorHistoryItem, SwSectorValuationItem, SwSectorStrength } from '../types'
import { api } from '../utils/api'
import BaseChart from './BaseChart.vue'

const props = withDefaults(defineProps<{
  sectors: SwSector[]
  title?: string
}>(), { title: 'A股行业热力图（申万一级）' })

// 按涨跌幅降序：领涨行业排在最前
const sorted = computed(() =>
  [...props.sectors].sort((a, b) => (b.change_pct ?? -99) - (a.change_pct ?? -99))
)

// 涨跌幅 → 背景色（红涨绿跌，按 ±3% 截断映射到透明度）
function bg(chg: number | null): string {
  if (chg == null) return 'var(--bg-subtle)'
  const v = Math.max(-3, Math.min(3, chg)) / 3 // -1..1
  if (v >= 0) return `rgba(220,38,38,${(0.12 + v * 0.62).toFixed(3)})`
  return `rgba(22,163,74,${(0.12 + -v * 0.62).toFixed(3)})`
}

function textColor(chg: number | null): string {
  if (chg == null) return 'var(--text-muted)'
  const v = Math.max(-3, Math.min(3, chg)) / 3
  return Math.abs(v) > 0.5 ? '#ffffff' : 'var(--text-primary)'
}

function fmt(n: number | null, d = 2): string {
  if (n == null) return '--'
  return n.toFixed(d)
}

// ==================== 行业详情弹窗 ====================
const modalVisible = ref(false)
const selectedSector = ref<SwSector | null>(null)
const historyLoading = ref(false)
const historyData = ref<SwSectorHistoryItem[]>([])
const valuationLoading = ref(false)
const valuationData = ref<SwSectorValuationItem[]>([])
const strengthLoading = ref(false)
const strengthData = ref<SwSectorStrength[]>([])
const strengthDays = ref(5)

const strengthDaysOptions = [
  { label: '近 3 日', value: 3 },
  { label: '近 5 日', value: 5 },
  { label: '近 10 日', value: 10 },
  { label: '近 20 日', value: 20 },
]

async function openSectorDetail(sector: SwSector) {
  selectedSector.value = sector
  modalVisible.value = true
  await Promise.all([loadHistory(), loadStrength(), loadValuation()])
}

async function loadHistory() {
  if (!selectedSector.value) return
  historyLoading.value = true
  try {
    historyData.value = await api.getSwSectorHistory(selectedSector.value.code, 120)
  } catch {
    historyData.value = []
  } finally {
    historyLoading.value = false
  }
}

async function loadStrength() {
  strengthLoading.value = true
  try {
    strengthData.value = await api.getSwSectorStrength(strengthDays.value)
  } catch {
    strengthData.value = []
  } finally {
    strengthLoading.value = false
  }
}

async function loadValuation() {
  if (!selectedSector.value) return
  valuationLoading.value = true
  try {
    valuationData.value = await api.getSwSectorValuationHistory(selectedSector.value.code)
  } catch {
    valuationData.value = []
  } finally {
    valuationLoading.value = false
  }
}

watch(strengthDays, () => loadStrength())

// 选中行业的相对强度
const selectedStrength = computed(() => {
  if (!selectedSector.value || !strengthData.value.length) return null
  return strengthData.value.find(s => s.code === selectedSector.value!.code) || null
})

// 历史走势图 option
const historyChartOption = computed(() => {
  if (!historyData.value.length) return null
  const dates = historyData.value.map(h => h.date)
  const changePcts = historyData.value.map(h => h.change_pct)
  const prices = historyData.value.map(h => h.price)
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['涨跌幅(%)', '指数点位'] },
    grid: { left: 50, right: 50, top: 40, bottom: 50 },
    xAxis: { type: 'category', data: dates, boundaryGap: false },
    yAxis: [
      { type: 'value', name: '涨跌幅(%)', scale: true, position: 'left' },
      { type: 'value', name: '点位', scale: true, position: 'right' },
    ],
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 10 }],
    series: [
      {
        name: '涨跌幅(%)',
        type: 'bar',
        yAxisIndex: 0,
        data: changePcts,
        itemStyle: {
          color: (p: any) => p.value >= 0 ? 'rgba(220,38,38,0.7)' : 'rgba(22,163,74,0.7)',
        },
      },
      {
        name: '指数点位',
        type: 'line',
        yAxisIndex: 1,
        data: prices,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2 },
      },
    ],
  }
})

// PE / PB 历史估值走势图 option
const valuationChartOption = computed(() => {
  if (!valuationData.value.length) return null
  const dates = valuationData.value.map(h => h.date)
  const peData = valuationData.value.map(h => h.pe)
  const pbData = valuationData.value.map(h => h.pb)
  const divYieldData = valuationData.value.map(h => h.dividend_yield)
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['PE(市盈率)', 'PB(市净率)', '股息率(%)'] },
    grid: { left: 50, right: 60, top: 40, bottom: 50 },
    xAxis: { type: 'category', data: dates, boundaryGap: false },
    yAxis: [
      { type: 'value', name: 'PE / PB', scale: true, position: 'left' },
      { type: 'value', name: '股息率(%)', scale: true, position: 'right' },
    ],
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 10 }],
    series: [
      {
        name: 'PE(市盈率)',
        type: 'line',
        yAxisIndex: 0,
        data: peData,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#3b82f6' },
        itemStyle: { color: '#3b82f6' },
      },
      {
        name: 'PB(市净率)',
        type: 'line',
        yAxisIndex: 0,
        data: pbData,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#f59e0b' },
        itemStyle: { color: '#f59e0b' },
      },
      {
        name: '股息率(%)',
        type: 'line',
        yAxisIndex: 1,
        data: divYieldData,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#10b981', type: 'dashed' },
        itemStyle: { color: '#10b981' },
      },
    ],
  }
})

// 相对强度排行图
const strengthChartOption = computed(() => {
  if (!strengthData.value.length) return null
  const sorted = [...strengthData.value].sort((a, b) => (a.relative_strength ?? -99) - (b.relative_strength ?? -99))
  const names = sorted.map(s => s.name)
  const values = sorted.map(s => s.relative_strength)
  const colors = values.map(v => v != null && v >= 0 ? 'rgba(220,38,38,0.7)' : 'rgba(22,163,74,0.7)')
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 80, right: 20, top: 20, bottom: 20 },
    xAxis: { type: 'value', name: '相对强度' },
    yAxis: { type: 'category', data: names },
    series: [{
      type: 'bar',
      data: values.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
      barWidth: '60%',
    }],
  }
})
</script>

<template>
  <div class="sw-heatmap">
    <div class="hm-header">
      <h3 class="hm-title">{{ title }}</h3>
      <div class="hm-legend">
        <span class="lg lg-down">-3%</span>
        <span class="lg-bar"></span>
        <span class="lg lg-up">+3%</span>
      </div>
    </div>
    <div class="hm-tip">
      <n-text depth="3" style="font-size: 11px">点击行业查看历史走势和相对强度</n-text>
    </div>

    <div class="hm-grid">
      <div
        v-for="s in sorted"
        :key="s.code"
        class="hm-cell"
        :style="{ background: bg(s.change_pct), color: textColor(s.change_pct) }"
        :title="`${s.name}\n涨跌幅: ${fmt(s.change_pct)}%\nPE(静态): ${fmt(s.pe)}\nPB: ${fmt(s.pb)}\n股息率: ${fmt(s.dividend_yield)}%\n成份数: ${s.count ?? '--'}`"
        @click="openSectorDetail(s)"
      >
        <div class="hm-name">{{ s.name }}</div>
        <div class="hm-chg">
          {{ s.change_pct == null ? '--' : (s.change_pct >= 0 ? '+' : '') + fmt(s.change_pct) + '%' }}
        </div>
      </div>
    </div>

    <!-- 行业详情弹窗 -->
    <n-modal
      v-model:show="modalVisible"
      preset="card"
      :title="selectedSector ? `${selectedSector.name} · 历史走势与相对强度` : '行业详情'"
      style="width: 900px; max-width: 95vw"
      :bordered="false"
    >
      <div v-if="selectedSector" class="detail-content">
        <!-- 当前数据卡片 -->
        <div class="detail-stats">
          <div class="stat-item">
            <span class="stat-label">当日涨跌幅</span>
            <span class="stat-value" :class="{ up: (selectedSector.change_pct ?? 0) >= 0, down: (selectedSector.change_pct ?? 0) < 0 }">
              {{ fmt(selectedSector.change_pct) }}%
            </span>
          </div>
          <div class="stat-item">
            <span class="stat-label">PE(静态)</span>
            <span class="stat-value">{{ fmt(selectedSector.pe) }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">PB</span>
            <span class="stat-value">{{ fmt(selectedSector.pb) }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">股息率</span>
            <span class="stat-value">{{ fmt(selectedSector.dividend_yield) }}%</span>
          </div>
          <div v-if="selectedStrength" class="stat-item">
            <span class="stat-label">相对强度(近{{ strengthDays }}日)</span>
            <span class="stat-value" :class="{ up: (selectedStrength.relative_strength ?? 0) >= 0, down: (selectedStrength.relative_strength ?? 0) < 0 }">
              {{ selectedStrength.relative_strength != null ? (selectedStrength.relative_strength >= 0 ? '+' : '') + fmt(selectedStrength.relative_strength) : '--' }}
            </span>
          </div>
        </div>

        <!-- 历史走势图 -->
        <div class="detail-section">
          <h4 class="section-title">涨跌幅与点位走势（近120日）</h4>
          <n-spin :show="historyLoading">
            <BaseChart v-if="historyChartOption" :option="historyChartOption" :height="300" />
            <n-empty v-else description="暂无历史数据（需积累多个交易日快照）" style="padding: 40px 0" />
          </n-spin>
        </div>

        <!-- PE / PB 历史估值走势图 -->
        <div class="detail-section">
          <h4 class="section-title">PE / PB / 股息率历史走势（近半年，AkShare）</h4>
          <n-spin :show="valuationLoading">
            <BaseChart v-if="valuationChartOption" :option="valuationChartOption" :height="300" />
            <n-empty v-else description="暂无估值历史数据" style="padding: 40px 0" />
          </n-spin>
        </div>

        <!-- 相对强度排行 -->
        <div class="detail-section">
          <div class="section-header">
            <h4 class="section-title">行业相对强度排行</h4>
            <n-select
              v-model:value="strengthDays"
              :options="strengthDaysOptions"
              size="small"
              style="width: 120px"
            />
          </div>
          <n-text depth="3" style="font-size: 11px; display: block; margin-bottom: 8px">
            相对强度 = 近{{ strengthDays }}日累计涨跌幅 - 当日涨跌幅。正值=近期强于当日（趋势性），负值=近期弱于当日（可能超跌反弹）
          </n-text>
          <n-spin :show="strengthLoading">
            <BaseChart v-if="strengthChartOption" :option="strengthChartOption" :height="380" />
            <n-empty v-else description="暂无相对强度数据" style="padding: 40px 0" />
          </n-spin>
        </div>
      </div>
    </n-modal>
  </div>
</template>

<style scoped>
.sw-heatmap {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 16px;
  box-shadow: var(--shadow-card);
}

.hm-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
  gap: 8px;
}

.hm-title {
  font-family: 'Work Sans', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.hm-tip {
  margin-bottom: 10px;
}

.hm-legend {
  display: flex;
  align-items: center;
  gap: 6px;
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

.hm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(116px, 1fr));
  gap: 8px;
}

.hm-cell {
  border-radius: 8px;
  padding: 10px 12px;
  min-height: 56px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
  border: 1px solid rgba(255, 255, 255, 0.04);
}

.hm-cell:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
}

.hm-name {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.2;
}

.hm-chg {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 700;
}

/* 弹窗内容样式 */
.detail-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.detail-stats {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: var(--bg-subtle);
  border-radius: 8px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-label {
  font-size: 11px;
  color: var(--text-muted);
}

.stat-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-value.up { color: var(--color-danger); }
.stat-value.down { color: var(--color-success); }

.detail-section {
  display: flex;
  flex-direction: column;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}
</style>
