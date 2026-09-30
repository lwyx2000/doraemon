<template>
  <div class="rank-trend-panel">
    <div class="panel-header">
      <h3 class="panel-title">A股行业热力图趋势（申万一级 · 每日排名）</h3>
      <div class="panel-tools">
        <span v-if="data && data.meta.trade_days > 0" class="meta-note">
          已积累 {{ data.meta.trade_days }} 个交易日
        </span>
        <n-select
          v-model:value="days"
          size="tiny"
          :options="dayOptions"
          class="days-select"
          :consistent-menu-width="false"
        />
        <n-button size="tiny" quaternary @click="load">刷新</n-button>
      </div>
    </div>

    <div v-if="loading" class="panel-state">加载中...</div>

    <div v-else-if="errorMsg" class="panel-state error">
      {{ errorMsg }}
      <n-button size="tiny" quaternary type="primary" @click="load">重试</n-button>
    </div>

    <div v-else-if="!data || data.dates.length === 0" class="panel-state">
      暂无行业快照数据（每日收盘后自动落库，积累中）
    </div>

    <template v-else>
      <div v-if="data.dates.length < 5" class="accum-hint">
        行业每日快照仍在积累（当前 {{ data.dates.length }} 个交易日），趋势会随交易日增加而变长
      </div>

      <div class="grid-wrap">
        <table class="rank-grid">
          <thead>
            <tr>
              <th class="col-name">行业</th>
              <th class="col-avg">均排名</th>
              <th class="col-trend">趋势</th>
              <th v-for="d in data.dates" :key="d" class="col-date">{{ shortDate(d) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="sec in data.sectors" :key="sec.code">
              <td class="col-name" :title="`${sec.name}（${sec.code}）`">{{ sec.name }}</td>
              <td class="col-avg">{{ sec.avg_rank ?? '—' }}</td>
              <td class="col-trend" :title="trendMap.get(sec.code)?.title">
                <span v-if="trendMap.get(sec.code)" :class="['trend-tag', trendMap.get(sec.code)!.dir]">{{ trendMap.get(sec.code)!.text }}</span>
                <span v-else class="trend-na">—</span>
              </td>
              <td
                v-for="d in data.dates"
                :key="d"
                class="cell"
                :style="cellStyle(sec, d)"
                :title="cellTitle(sec, d)"
              >
                {{ cellText(sec, d) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="legend">
        <span class="legend-item"><span class="legend-box" :style="swatch(2.5)" />涨 ≥2.5%</span>
        <span class="legend-item"><span class="legend-box" :style="swatch(1)" />涨 ~1%</span>
        <span class="legend-item"><span class="legend-box" :style="swatch(0)" />平盘</span>
        <span class="legend-item"><span class="legend-box" :style="swatch(-1)" />跌 ~1%</span>
        <span class="legend-item"><span class="legend-box" :style="swatch(-2.5)" />跌 ≥2.5%</span>
        <span class="legend-note">格内数字 = 当日涨幅排名（1 = 当日最强）；趋势列 = 前后半窗平均排名对比，排名持续前移 = 相对走强</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'SwRankTrend' })
import { ref, computed, watch, onMounted } from 'vue'
import { NButton, NSelect } from 'naive-ui'
import { api } from '../utils/api'
import type { SwRankTrendData, SwRankTrendSector } from '../types'

const days = ref(20)
const dayOptions = [
  { label: '近10日', value: 10 },
  { label: '近20日', value: 20 },
  { label: '近40日', value: 40 },
  { label: '近60日', value: 60 },
]

const data = ref<SwRankTrendData | null>(null)
const loading = ref(false)
const errorMsg = ref<string | null>(null)

async function load() {
  loading.value = true
  errorMsg.value = null
  try {
    data.value = await api.getSwSectorRankTrend(days.value)
  } catch {
    errorMsg.value = '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

watch(days, load)

// ---- 排名趋势判定：排名 1 = 最强（相对强弱），前后半窗平均排名对比 ----
// delta = 前半窗均排名 − 后半窗均排名；delta > 0 = 排名持续前移 = 资金持续流入该行业（走强）
interface TrendInfo {
  dir: 'up' | 'flat' | 'down'
  text: string
  title: string
}

const RANK_TREND_MIN_SAMPLES = 6   // 有效样本不足 6 个交易日不做判定
const RANK_TREND_THRESHOLD = 2.5   // 前后半窗平均排名差 ≥ 2.5 位才视为趋势，避免噪声

const trendMap = computed(() => {
  const m = new Map<string, TrendInfo>()
  for (const sec of data.value?.sectors ?? []) {
    const ranks = [...sec.daily]
      .sort((a, b) => a.date.localeCompare(b.date))
      .map(x => x.rank)
      .filter((r): r is number => r != null)
    if (ranks.length < RANK_TREND_MIN_SAMPLES) continue
    const half = Math.floor(ranks.length / 2)
    const avg = (a: number[]) => a.reduce((s, v) => s + v, 0) / a.length
    const firstAvg = avg(ranks.slice(0, half))
    const secondAvg = avg(ranks.slice(ranks.length - half))
    const delta = firstAvg - secondAvg
    const dir = delta >= RANK_TREND_THRESHOLD ? 'up' : delta <= -RANK_TREND_THRESHOLD ? 'down' : 'flat'
    const arrow = dir === 'up' ? '↗' : dir === 'down' ? '↘' : '→'
    const label = dir === 'up' ? '走强' : dir === 'down' ? '走弱' : '震荡'
    const move = `${delta >= 0 ? '前移' : '后移'} ${Math.abs(delta).toFixed(1)} 位`
    m.set(sec.code, {
      dir,
      text: `${arrow} ${label}`,
      title: `${sec.name}：前半窗均排名 ${firstAvg.toFixed(1)} → 后半窗 ${secondAvg.toFixed(1)}（${move}，基于近 ${ranks.length} 个交易日）`,
    })
  }
  return m
})

function shortDate(d: string): string {
  // "2026-09-22" -> "09-22"
  const parts = d.split('-')
  return parts.length >= 3 ? `${parts[1]}-${parts[2]}` : d
}

function dailyOf(sec: SwRankTrendSector, date: string) {
  return sec.daily.find(x => x.date === date)
}

/** 涨跌幅 → 颜色强度（红涨绿跌，±3% 封顶） */
function swatch(pct: number | null | undefined): Record<string, string> {
  if (pct == null) return { background: 'var(--bg-surface)' }
  const alpha = Math.min(Math.abs(pct) / 3, 1) * 0.75 + 0.06
  return pct >= 0
    ? { background: `rgba(216, 62, 62, ${alpha.toFixed(3)})` }
    : { background: `rgba(30, 142, 96, ${alpha.toFixed(3)})` }
}

function cellStyle(sec: SwRankTrendSector, date: string): Record<string, string> {
  const item = dailyOf(sec, date)
  return swatch(item?.change_pct)
}

function cellText(sec: SwRankTrendSector, date: string): string {
  const item = dailyOf(sec, date)
  return item ? String(item.rank) : ''
}

function cellTitle(sec: SwRankTrendSector, date: string): string {
  const item = dailyOf(sec, date)
  if (!item) return `${sec.name} · ${date} · 无数据`
  const pct = item.change_pct >= 0 ? `+${item.change_pct.toFixed(2)}%` : `${item.change_pct.toFixed(2)}%`
  return `${sec.name} · ${date} · ${pct} · 当日排名第 ${item.rank}`
}
</script>

<style scoped>
.rank-trend-panel {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 14px 16px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.panel-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong, #1f2329);
}

.panel-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.meta-note {
  font-size: 11px;
  color: var(--text-muted, #717782);
}

.days-select {
  width: 88px;
}

.panel-state {
  padding: 28px 0;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted, #717782);
}

.panel-state.error {
  color: var(--color-danger, #d83e3e);
}

.accum-hint {
  margin-bottom: 8px;
  padding: 6px 10px;
  border-radius: 4px;
  background: var(--tag-blue-bg, #eef4fb);
  color: var(--tag-blue-text, #005ea1);
  font-size: 11px;
}

.grid-wrap {
  max-height: 560px;
  overflow: auto;
  border: 1px solid var(--border-default);
  border-radius: 4px;
}

.rank-grid {
  border-collapse: separate;
  border-spacing: 0;
  font-size: 11px;
}

.rank-grid th,
.rank-grid td {
  padding: 0 6px;
  height: 24px;
  line-height: 24px;
  white-space: nowrap;
  text-align: center;
  border-bottom: 1px solid var(--border-default);
  border-right: 1px solid var(--border-default);
}

.rank-grid thead th {
  position: sticky;
  top: 0;
  z-index: 3;
  background: var(--bg-surface, #f5f6f7);
  font-weight: 600;
  color: var(--text-muted, #717782);
  font-size: 10px;
}

.rank-grid .col-name {
  position: sticky;
  left: 0;
  z-index: 2;
  min-width: 96px;
  padding-left: 10px;
  text-align: left;
  background: var(--bg-card, #fff);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--text-strong, #1f2329);
}

.rank-grid thead .col-name {
  z-index: 4;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: normal;
}

.rank-grid .col-avg {
  min-width: 52px;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-muted, #717782);
  background: var(--bg-card, #fff);
}

.rank-grid .col-trend {
  min-width: 68px;
  background: var(--bg-card, #fff);
}

.trend-tag {
  display: inline-block;
  padding: 0 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.02em;
  line-height: 16px;
  white-space: nowrap;
}

/* 与热力图色彩语义一致：红=走强（涨），绿=走弱（跌） */
.trend-tag.up { color: var(--tag-red-text, #c0392b); background: var(--tag-red-bg, #fdeceb); }
.trend-tag.down { color: var(--tag-green-text, #1e8e60); background: var(--tag-green-bg, #e7f5ee); }
.trend-tag.flat { color: var(--text-muted, #717782); background: var(--bg-surface, #f5f6f7); }

.trend-na { color: var(--text-muted, #717782); }

.rank-grid .col-date {
  min-width: 52px;
}

.rank-grid .cell {
  min-width: 52px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-strong, #1f2329);
}

.rank-grid tbody tr:hover .col-name {
  background: var(--bg-surface, #f5f6f7);
}

.legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-muted, #717782);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.legend-box {
  display: inline-block;
  width: 14px;
  height: 12px;
  border-radius: 2px;
  border: 1px solid var(--border-default);
}

.legend-note {
  margin-left: auto;
}
</style>
