<script setup lang="ts">
defineOptions({ name: 'SignalLab' })
import { ref, computed, reactive, onMounted } from 'vue'
import {
  NButton, NInput, NSelect, NInputNumber, NIcon, NTag, NEmpty, NSpin, useMessage, NTooltip,
} from 'naive-ui'
import {
  FlashOutline, AddOutline, TrashOutline, RefreshOutline, TrendingUpOutline, TrendingDownOutline,
} from '@vicons/ionicons5'
import { api, signalApi } from '../utils/api'
import type { StrategyDef, SignalResult, TrackedSignal, SignalPoint } from '../types'
import PageHeader from '../components/PageHeader.vue'
import LoadingState from '../components/LoadingState.vue'

const message = useMessage()

// ---- 策略目录 ----
const strategies = ref<StrategyDef[]>([])
const strategiesLoading = ref(false)
async function loadStrategies() {
  strategiesLoading.value = true
  try {
    const res = await signalApi.getStrategies()
    strategies.value = Array.isArray(res) ? res : ((res as any).data ?? [])
  } catch (e: any) {
    message.error('加载策略失败：' + (e.message || e))
  } finally {
    strategiesLoading.value = false
  }
}

// ---- 表单：标的物 + 策略 + 动态参数 ----
const symbol = ref('')
const symbolName = ref('')
const selectedStrategyId = ref<string | null>(null)
const paramValues = reactive<Record<string, number>>({})

const selectedStrategy = computed(() => strategies.value.find(s => s.id === selectedStrategyId.value) || null)

function onStrategyChange(id: string) {
  selectedStrategyId.value = id
  // 重置参数为默认值
  const s = strategies.value.find(x => x.id === id)
  Object.keys(paramValues).forEach(k => delete paramValues[k])
  if (s) {
    s.params.forEach(p => {
      paramValues[p.key] = p.default ?? 0
    })
  }
}

// ---- 生成信号 ----
const generating = ref(false)
const result = ref<SignalResult | null>(null)
async function generate() {
  if (!symbol.value.trim()) {
    message.warning('请输入标的物代码')
    return
  }
  if (!selectedStrategyId.value) {
    message.warning('请选择策略')
    return
  }
  generating.value = true
  try {
    const params: Record<string, number> = {}
    selectedStrategy.value?.params.forEach(p => {
      params[p.key] = paramValues[p.key]
    })
    const res = await signalApi.generate(symbol.value.trim(), selectedStrategyId.value, params)
    result.value = (res as any).data ?? res
    if ((result.value as any).error) {
      message.warning((result.value as any).error)
    }
  } catch (e: any) {
    message.error('生成信号失败：' + (e.message || e))
  } finally {
    generating.value = false
  }
}

// ---- 当前信号大卡 ----
const latestType = computed(() => {
  if (!result.value) return null
  if (result.value.current_position === 'long') return 'buy'
  if (result.value.current_position === 'flat') return 'sell'
  return null
})

// ---- 价格走势 SVG（标注买卖点）----
const svgW = 760, svgH = 220, padX = 10, padY = 18
const svgPath = computed(() => {
  const s = result.value
  if (!s || !s.series.close.length) return ''
  const closes = s.series.close
  const min = Math.min(...closes), max = Math.max(...closes)
  const span = max - min || 1
  const n = closes.length
  return closes.map((c, i) => {
    const x = padX + (n === 1 ? svgW / 2 : (i / (n - 1)) * (svgW - 2 * padX))
    const y = padY + (1 - (c - min) / span) * (svgH - 2 * padY)
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})
const svgMarkers = computed(() => {
  const s = result.value
  if (!s || !s.series.close.length) return []
  const closes = s.series.close
  const dates = s.series.date
  const min = Math.min(...closes), max = Math.max(...closes)
  const span = max - min || 1
  const n = closes.length
  const pts = new Map<string, SignalPoint>()
  s.signal_points.forEach(p => pts.set(p.date, p))
  const marks: { x: number; y: number; type: 'buy' | 'sell'; date: string; price: number }[] = []
  dates.forEach((d, i) => {
    const p = pts.get(d)
    if (!p) return
    const x = padX + (n === 1 ? svgW / 2 : (i / (n - 1)) * (svgW - 2 * padX))
    const y = padY + (1 - (closes[i] - min) / span) * (svgH - 2 * padY)
    marks.push({ x, y, type: p.type, date: d, price: p.price })
  })
  return marks
})

// ---- 监控列表 ----
const tracked = ref<TrackedSignal[]>([])
const trackedLoading = ref(false)
async function loadTracked() {
  trackedLoading.value = true
  try {
    const res = await signalApi.getTracked()
    tracked.value = Array.isArray(res) ? res : ((res as any).data ?? [])
  } catch (e: any) {
    message.error('加载监控失败：' + (e.message || e))
  } finally {
    trackedLoading.value = false
  }
}
async function refreshTracked() {
  trackedLoading.value = true
  try {
    const res = await signalApi.refreshTracked()
    tracked.value = Array.isArray(res) ? res : ((res as any).data ?? [])
    message.success('已重算监控信号')
  } catch (e: any) {
    message.error('刷新失败：' + (e.message || e))
  } finally {
    trackedLoading.value = false
  }
}
async function addTracked() {
  if (!symbol.value.trim() || !selectedStrategyId.value) {
    message.warning('请先填写标的物并选择策略')
    return
  }
  try {
    const params: Record<string, number> = {}
    selectedStrategy.value?.params.forEach(p => { params[p.key] = paramValues[p.key] })
    await signalApi.addTracked(symbol.value.trim(), selectedStrategyId.value, symbolName.value.trim() || null, params)
    message.success('已加入监控')
    await loadTracked()
  } catch (e: any) {
    message.error('加入监控失败：' + (e.message || e))
  }
}
async function removeTracked(id: string) {
  try {
    await signalApi.removeTracked(id)
    tracked.value = tracked.value.filter(t => t.id !== id)
    message.success('已取消监控')
  } catch (e: any) {
    message.error('取消失败：' + (e.message || e))
  }
}

// 监控项当前信号徽标类型
function trackedType(t: TrackedSignal): 'buy' | 'sell' | 'none' {
  if (t.current_position === 'long') return 'buy'
  if (t.current_position === 'flat') return 'sell'
  return 'none'
}

onMounted(() => {
  loadStrategies()
  loadTracked()
})
</script>

<template>
  <div class="signal-lab">
    <PageHeader
      title="信号实验室"
      subtitle="输入标的物 + 选择策略，基于真实行情生成买卖点；同一标的物可叠加多个策略并加入监控"
      icon="flash"
    />

    <div class="layout">
      <!-- 左：生成区 -->
      <div class="panel">
        <div class="panel-title">
          <n-icon size="18" color="#005ea1"><FlashOutline /></n-icon>
          <span>生成买卖点信号</span>
        </div>

        <div class="form-row">
          <label>标的物代码</label>
          <n-input v-model:value="symbol" placeholder="如 600519 / 000001（A股代码）" clearable />
        </div>
        <div class="form-row">
          <label>名称（可选）</label>
          <n-input v-model:value="symbolName" placeholder="留空则使用代码" clearable />
        </div>
        <div class="form-row">
          <label>策略</label>
          <n-select
            :options="strategies.map(s => ({ label: s.name + '（' + s.category + '）', value: s.id }))"
            :value="selectedStrategyId"
            :loading="strategiesLoading"
            placeholder="选择策略"
            @update:value="onStrategyChange"
          />
        </div>

        <div v-if="selectedStrategy" class="strategy-desc">
          <n-tooltip trigger="hover">
            <template #trigger><span class="desc-text">{{ selectedStrategy.desc }}</span></template>
            <span>{{ selectedStrategy.desc }}</span>
          </n-tooltip>
        </div>

        <div v-if="selectedStrategy && selectedStrategy.params.length" class="params">
          <div v-for="p in selectedStrategy.params" :key="p.key" class="form-row param-row">
            <label>{{ p.label }}</label>
            <n-input-number
              v-model:value="paramValues[p.key]"
              :min="p.min" :max="p.max" :step="p.step || 1"
              style="width: 100%;"
            />
          </div>
        </div>

        <div class="actions">
          <n-button type="primary" :loading="generating" @click="generate">
            <template #icon><n-icon><FlashOutline /></n-icon></template>
            生成信号
          </n-button>
          <n-button :disabled="!result" @click="addTracked">
            <template #icon><n-icon><AddOutline /></n-icon></template>
            加入监控
          </n-button>
        </div>

        <!-- 结果 -->
        <div v-if="result" class="result">
          <div v-if="result.error" class="error-box">{{ result.error }}</div>
          <template v-else>
            <div class="signal-card" :class="latestType">
              <div class="signal-left">
                <div class="signal-label">当前信号</div>
                <div class="signal-value">{{ result.latest_signal }}</div>
              </div>
              <div class="signal-meta">
                <div>现价 <b>{{ result.current_price }}</b></div>
                <div>策略 {{ result.strategy_name }}</div>
                <div>K线 {{ result.kline_start }} ~ {{ result.kline_end }}（{{ result.kline_count }} 根）</div>
                <div>累计信号 {{ result.signal_count }} 个</div>
              </div>
            </div>
            <div class="reason">{{ result.latest_reason }}</div>

            <!-- 价格走势 + 买卖点 -->
            <div v-if="result.series.close.length" class="chart-wrap">
              <svg :viewBox="`0 0 ${svgW} ${svgH}`" class="chart-svg" preserveAspectRatio="none">
                <path :d="svgPath" fill="none" stroke="#005ea1" stroke-width="1.5" />
                <g v-for="(m, i) in svgMarkers" :key="i">
                  <circle :cx="m.x" :cy="m.y" r="4"
                    :fill="m.type === 'buy' ? '#18a058' : '#d92d20'" stroke="#fff" stroke-width="1" />
                </g>
              </svg>
              <div class="chart-legend">
                <span><i class="dot buy"></i>买入点 {{ result.signal_points.filter(p => p.type==='buy').length }}</span>
                <span><i class="dot sell"></i>卖出点 {{ result.signal_points.filter(p => p.type==='sell').length }}</span>
              </div>
            </div>

            <!-- 信号点历史 -->
            <div class="points-title">买卖点历史（共 {{ result.signal_points.length }} 个）</div>
            <div v-if="!result.signal_points.length" class="empty-hint">该区间未触发买卖点</div>
            <div v-else class="points-table">
              <div class="pt-head">
                <span>日期</span><span>价格</span><span>类型</span><span>触发原因</span>
              </div>
              <div v-for="(p, i) in result.signal_points" :key="i" class="pt-row">
                <span>{{ p.date }}</span>
                <span>{{ p.price }}</span>
                <span>
                  <n-tag size="small" :type="p.type === 'buy' ? 'success' : 'error'" :bordered="false">
                    {{ p.type === 'buy' ? '买入' : '卖出' }}
                  </n-tag>
                </span>
                <span class="reason-cell">{{ p.reason }}</span>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- 右：监控列表 -->
      <div class="panel">
        <div class="panel-title">
          <span>我的监控（标的物 × 策略）</span>
          <n-button text size="small" @click="refreshTracked">
            <template #icon><n-icon><RefreshOutline /></n-icon></template>
            刷新信号
          </n-button>
        </div>
        <div v-if="trackedLoading" class="loading-box"><n-spin size="small" /> 加载中…</div>
        <n-empty v-else-if="!tracked.length" description="还未监控任何组合，生成信号后点击「加入监控」" />
        <div v-else class="tracked-list">
          <div v-for="t in tracked" :key="t.id" class="tracked-item">
            <div class="ti-head">
              <div class="ti-name">
                <b>{{ t.name }}</b> <span class="ti-symbol">{{ t.symbol }}</span>
                <n-tag size="tiny" :bordered="false" style="margin-left:6px">{{ t.strategy_name }}</n-tag>
              </div>
              <n-button text size="small" type="error" @click="removeTracked(t.id)">
                <template #icon><n-icon><TrashOutline /></n-icon></template>
              </n-button>
            </div>
            <div class="ti-body">
              <n-tag v-if="trackedType(t)==='buy'" type="success" :bordered="false" size="small">
                <template #icon><n-icon><TrendingUpOutline /></n-icon></template>
                持有/买入
              </n-tag>
              <n-tag v-else-if="trackedType(t)==='sell'" type="error" :bordered="false" size="small">
                <template #icon><n-icon><TrendingDownOutline /></n-icon></template>
                空仓/卖出
              </n-tag>
              <n-tag v-else :bordered="false" size="small">未知</n-tag>
              <span class="ti-price">现价 {{ t.current_price ?? '—' }}</span>
              <span class="ti-date">末次信号 {{ t.last_signal_date || '无' }}</span>
            </div>
            <div v-if="t.latest_reason" class="ti-reason">{{ t.latest_reason }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.signal-lab { padding: 16px 20px 32px; }
.layout { display: grid; grid-template-columns: 1fr 360px; gap: 16px; margin-top: 14px; }
@media (max-width: 1100px) { .layout { grid-template-columns: 1fr; } }
.panel {
  background: #fff; border: 1px solid #e8eaed; border-radius: 10px; padding: 16px 18px;
}
.panel-title {
  display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 15px; margin-bottom: 14px;
}
.panel-title > span:first-child { flex: 1; }
.form-row { margin-bottom: 12px; }
.form-row > label { display: block; font-size: 12px; color: #6b7280; margin-bottom: 5px; }
.params { border-top: 1px dashed #eee; padding-top: 10px; margin-top: 4px; }
.param-row { margin-bottom: 8px; }
.strategy-desc { font-size: 12px; color: #6b7280; margin: -4px 0 12px; }
.desc-text { border-bottom: 1px dotted #bbb; cursor: help; }
.actions { display: flex; gap: 10px; margin: 14px 0; }
.result { margin-top: 8px; border-top: 1px solid #eee; padding-top: 14px; }
.error-box { background: #fff2f0; border: 1px solid #ffccc7; color: #cf1322; padding: 10px 12px; border-radius: 8px; font-size: 13px; }
.signal-card { display: flex; gap: 18px; align-items: center; border-radius: 10px; padding: 14px 16px; }
.signal-card.buy { background: #e8f7ee; border: 1px solid #aee3c2; }
.signal-card.sell { background: #fdecea; border: 1px solid #f5c2bc; }
.signal-label { font-size: 12px; color: #6b7280; }
.signal-value { font-size: 26px; font-weight: 700; }
.signal-card.buy .signal-value { color: #18a058; }
.signal-card.sell .signal-value { color: #d92d20; }
.signal-meta { font-size: 12px; color: #4b5563; line-height: 1.7; }
.reason { font-size: 13px; color: #374151; margin: 10px 0; background: #f7f8fa; padding: 8px 10px; border-radius: 8px; }
.chart-wrap { margin: 6px 0 10px; }
.chart-svg { width: 100%; height: 200px; background: #fafbfc; border: 1px solid #eef0f3; border-radius: 8px; }
.chart-legend { display: flex; gap: 16px; font-size: 12px; color: #6b7280; margin-top: 6px; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
.dot.buy { background: #18a058; }
.dot.sell { background: #d92d20; }
.points-title { font-size: 13px; font-weight: 600; margin: 12px 0 6px; }
.empty-hint { font-size: 12px; color: #9ca3af; padding: 8px 0; }
.points-table { font-size: 12px; border: 1px solid #eef0f3; border-radius: 8px; overflow: hidden; }
.pt-head, .pt-row { display: grid; grid-template-columns: 88px 70px 56px 1fr; gap: 6px; padding: 6px 10px; align-items: center; }
.pt-head { background: #f7f8fa; color: #6b7280; font-weight: 600; }
.pt-row { border-top: 1px solid #f2f3f5; }
.reason-cell { color: #4b5563; }
.loading-box { padding: 20px; text-align: center; color: #6b7280; font-size: 13px; }
.tracked-list { display: flex; flex-direction: column; gap: 10px; }
.tracked-item { border: 1px solid #eef0f3; border-radius: 8px; padding: 10px 12px; }
.ti-head { display: flex; justify-content: space-between; align-items: center; }
.ti-name { font-size: 14px; }
.ti-symbol { color: #9ca3af; font-size: 12px; margin-left: 4px; }
.ti-body { display: flex; align-items: center; gap: 10px; margin-top: 8px; font-size: 12px; color: #4b5563; }
.ti-reason { font-size: 12px; color: #6b7280; margin-top: 6px; }
</style>
