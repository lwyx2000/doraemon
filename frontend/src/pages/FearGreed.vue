<script setup lang="ts">
/**
 * 贪婪恐惧指数（Fear & Greed Index）
 *
 * 6 指标 min-max 加权情绪温度计（用户 2026-10-12 确认配方）：
 *   上涨占比 0.25 ｜ 涨停(剔ST) 0.20 ｜ 指数距52周高点 0.15 ｜ 量能比 0.20
 *   ｜ 融资余额20日变化 0.10 ｜ (100−波动率) 0.10
 * 档位：<10 极度恐慌，>90 极度贪婪，50 附近均衡。
 * 每个指标对过去一年窗口 min-max；缺失分项按权重归一化（componentsUsed<6 即回填近似日）。
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import {
  NCard,
  NSpace,
  NButton,
  NTag,
  NText,
  NEmpty,
  NSpin,
  NAlert,
  NGrid,
  NGi,
  NProgress,
  useMessage,
} from 'naive-ui'
import { api } from '../utils/api'
import BaseChart from '../components/BaseChart.vue'
import PageHeader from '../components/PageHeader.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import AiInterpretModal from '../components/AiInterpretModal.vue'
import { useDarkMode } from '../composables/useDarkMode'
import type { FearGreedLatest, FearGreedPoint, FearGreedStatus, SectionSourceMeta } from '../types'
import { buildFearGreedMetrics, labelType, scoreColor } from '../utils/fearGreedDisplay'

const message = useMessage()
const { isDark } = useDarkMode()

const loading = ref(false)
const latest = ref<FearGreedLatest | null>(null)
const history = ref<FearGreedPoint[]>([])
const status = ref<FearGreedStatus | null>(null)
const collecting = ref(false)
const backfilling = ref(false)
const meta = ref<SectionSourceMeta | null>(null)

// AI 解读弹窗（后端组装恐贪真实数据 + 口径知识库）
const showAiInterpret = ref(false)

async function loadAll() {
  loading.value = true
  try {
    const [latestRes, historyRes, statusRes] = await Promise.all([
      api.getFearGreedLatest(),
      api.getFearGreedHistory(250),
      api.getFearGreedStatus(),
    ])
    latest.value = latestRes.data
    history.value = historyRes.data || []
    status.value = statusRes.data
    meta.value = latestRes.meta ?? null
  } catch (e: any) {
    message.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

// ---------------------------------------------------------------- 回填轮询
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
      const res = await api.getFearGreedStatus()
      status.value = res.data
    } catch {
      /* 轮询失败静默，下一轮再试 */
    }
    const running = status.value?.scheduler?.backfill.running ?? false
    if (!running || pollCount >= 120) {
      stopPolling()
      backfilling.value = false
      await loadAll()
      if (!running) message.success('回填已完成，数据已刷新')
    }
  }, 5000)
}

onBeforeUnmount(stopPolling)

async function onCollect() {
  collecting.value = true
  try {
    const res = await api.collectFearGreed()
    if (res.data?.ok) {
      message.success(`采集完成：恐贪值 ${res.data.totalScore ?? '—'}（${res.data.label ?? ''}）`)
      await loadAll()
    } else {
      message.warning(res.data?.label || '采集跳过')
    }
  } catch (e: any) {
    message.error(e?.message || '采集失败')
  } finally {
    collecting.value = false
  }
}

async function onBackfill() {
  backfilling.value = true
  try {
    const res = await api.backfillFearGreed(120)
    message.info(res.data?.message || '回填已开始在后台执行')
    startPolling()
  } catch (e: any) {
    backfilling.value = false
    message.error(e?.message || '回填启动失败')
  }
}

// ---------------------------------------------------------------- 展示辅助
// fmt / scoreColor / labelType / 6 分项定义：与宏观看板面板共用 utils/fearGreedDisplay
const sourceLabel = computed(() => {
  if (!latest.value?.source) return ''
  return latest.value.source === 'live' ? '定时采集' : '历史回填'
})

const partialWarning = computed(
  () => latest.value != null && latest.value.componentsUsed < 6
)

// 6 分项定义（顺序 = 权重降序），与 FearGreedPanel 共用
const metrics = computed(() => (latest.value ? buildFearGreedMetrics(latest.value) : []))

// ---------------------------------------------------------------- 图表
const histDates = computed(() => history.value.map((h) => h.date))

const gaugeOption = computed(() => {
  const v = latest.value?.totalScore ?? 0
  return {
    series: [
      {
        type: 'gauge',
        startAngle: 210,
        endAngle: -30,
        min: 0,
        max: 100,
        radius: '100%',
        progress: { show: true, width: 16, roundCap: true },
        axisLine: {
          lineStyle: {
            width: 16,
            color: [
              [0.1, '#16a34a'],
              [0.25, '#4ade80'],
              [0.45, '#9ca3af'],
              [0.75, '#fb923c'],
              [0.9, '#ef4444'],
              [1, '#dc2626'],
            ],
          },
        },
        pointer: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        detail: {
          valueAnimation: true,
          fontSize: 44,
          fontWeight: 600,
          offsetCenter: [0, '8%'],
          formatter: (val: number) => (latest.value ? val.toFixed(1) : '—'),
          color: isDark.value ? '#e5e7eb' : '#181c21',
        },
        title: { show: false },
        data: [{ value: v }],
      },
    ],
  }
})

const historyOption = computed(() => {
  const rawByDate = new Map(history.value.map((h) => [h.date, h]))
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any[]) => {
        if (!params.length) return ''
        const d = params[0].axisValue
        const raw = rawByDate.get(d)
        const lines = [`<b>${d}</b>`]
        const total = params.find((p) => p.seriesName === '恐贪总值')
        if (total) {
          lines.push(
            `恐贪总值：<b>${total.value == null ? '—' : Number(total.value).toFixed(1)}</b>` +
              (raw && raw.componentsUsed < 6 ? `（${raw.componentsUsed}/6 分项·近似）` : '')
          )
        }
        for (const p of params) {
          if (p.seriesName === '恐贪总值' || p.value == null) continue
          lines.push(`${p.marker}${p.seriesName}：${Number(p.value).toFixed(1)}`)
        }
        if (raw) {
          lines.push(
            `<span style="opacity:.7">上涨 ${raw.rawAdvanceRatio == null ? '—' : (raw.rawAdvanceRatio * 100).toFixed(0) + '%'} · ` +
              `涨停 ${raw.rawLimitUp ?? '—'} 家 · 位置 ${raw.rawPosition == null ? '—' : raw.rawPosition.toFixed(0) + '%'} · ` +
              `量能 ${raw.rawTurnoverRatio == null ? '—' : raw.rawTurnoverRatio.toFixed(2) + '×'} · ` +
              `两融 ${raw.rawMarginChg20 == null ? '—' : raw.rawMarginChg20.toFixed(1) + '%'} · ` +
              `波动 ${raw.rawVol20 == null ? '—' : raw.rawVol20.toFixed(1) + '%'}</span>`
          )
        }
        return lines.join('<br/>')
      },
    },
    legend: {
      data: ['恐贪总值', '上涨占比', '涨停', '量能', '位置', '两融', '波动'],
      top: 0,
    },
    grid: { left: 44, right: 16, top: 36, bottom: 60 },
    xAxis: { type: 'category', data: histDates.value, boundaryGap: false },
    yAxis: { type: 'value', min: 0, max: 100, interval: 25 },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20, bottom: 18 }],
    series: [
      {
        name: '恐贪总值',
        type: 'line',
        data: history.value.map((h) => h.totalScore),
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 3 },
        areaStyle: { opacity: 0.08 },
        markLine: {
          symbol: 'none',
          label: { position: 'insideEndTop' },
          lineStyle: { type: 'dashed', opacity: 0.5 },
          data: [
            { yAxis: 50, name: '均衡' },
            { yAxis: 10, name: '极度恐慌' },
            { yAxis: 90, name: '极度贪婪' },
          ],
        },
        markArea: {
          silent: true,
          itemStyle: { opacity: 0.05 },
          data: [
            [{ yAxis: 90, itemStyle: { color: '#dc2626' } }, { yAxis: 100 }],
            [{ yAxis: 0, itemStyle: { color: '#16a34a' } }, { yAxis: 10 }],
          ],
        },
      },
      {
        name: '上涨占比',
        type: 'line',
        data: history.value.map((h) => h.advance),
        showSymbol: false,
        lineStyle: { width: 1.5, opacity: 0.75 },
      },
      {
        name: '涨停',
        type: 'line',
        data: history.value.map((h) => h.limitUp),
        showSymbol: false,
        lineStyle: { width: 1.5, opacity: 0.75 },
      },
      {
        name: '量能',
        type: 'line',
        data: history.value.map((h) => h.turnover),
        showSymbol: false,
        lineStyle: { width: 1.5, opacity: 0.75 },
      },
      {
        name: '位置',
        type: 'line',
        data: history.value.map((h) => h.position),
        showSymbol: false,
        lineStyle: { width: 1.5, opacity: 0.75 },
      },
      {
        name: '两融',
        type: 'line',
        data: history.value.map((h) => h.margin),
        showSymbol: false,
        lineStyle: { width: 1.5, opacity: 0.75 },
      },
      {
        name: '波动',
        type: 'line',
        data: history.value.map((h) => h.vol),
        showSymbol: false,
        lineStyle: { width: 1.5, opacity: 0.75 },
      },
    ],
  }
})
</script>

<template>
  <div class="fear-greed-page">
    <PageHeader
      title="贪婪恐惧指数"
      subtitle="6 指标加权情绪温度计 · 0 恐慌 ↔ 100 贪婪"
      helpKey="fearGreed"
      :updated-at="meta?.updateTime"
    >
      <template #actions>
        <NButton size="small" quaternary :loading="loading" @click="loadAll">刷新</NButton>
        <NButton size="small" @click="showAiInterpret = true">AI 解读</NButton>
        <NButton size="small" :loading="collecting" @click="onCollect">采集当日</NButton>
        <NButton size="small" type="primary" :loading="backfilling" @click="onBackfill">
          回填历史
        </NButton>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="fearGreed" />

    <n-space vertical :size="16">
      <div v-if="latest?.date" class="data-date">
        <n-text depth="3">
          数据日期 {{ latest.date }}<span v-if="latest.capturedAt">（采集于 {{ latest.capturedAt }}）</span>
          <span v-if="sourceLabel"> · {{ sourceLabel }}</span>
        </n-text>
      </div>

      <n-spin :show="loading">
        <!-- 空状态：尚无数据，引导回填 -->
        <template v-if="!latest">
          <n-empty description="暂无恐贪数据">
            <template #extra>
              <n-space vertical :size="8">
                <n-text depth="3" style="font-size: 13px">
                  首次使用请点右上角「回填历史」生成近 120 个交易日序列；<br />
                  此后每交易日 15:40 会自动采集当日值。
                </n-text>
                <NButton size="small" type="primary" :loading="backfilling" @click="onBackfill">
                  立即回填
                </NButton>
              </n-space>
            </template>
          </n-empty>
        </template>

        <template v-else>
          <n-alert
            v-if="partialWarning"
            type="warning"
            :bordered="false"
            style="margin-bottom: 4px"
          >
            该日仅有 {{ latest.componentsUsed }}/6 个分项（上涨占比无历史源，回填日按权重归一化近似），
            与完整 6 分项的口径存在小幅差异。
          </n-alert>

          <!-- 总分仪表盘 + 分项得分 -->
          <n-grid :cols="9" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
            <n-gi span="9 m:3">
              <n-card title="恐贪总值" style="height: 100%">
                <div class="gauge-wrap">
                  <BaseChart :option="gaugeOption" :height="220" />
                </div>
                <div class="gauge-footer">
                  <n-tag :type="labelType(latest.label)" size="medium" round>
                    {{ latest.label ?? '—' }}
                  </n-tag>
                  <n-text depth="3" style="font-size: 12px">
                    &lt;10 极度恐慌 · &gt;90 极度贪婪 · 50 均衡
                  </n-text>
                </div>
              </n-card>
            </n-gi>

            <n-gi span="9 m:6">
              <n-card title="6 分项得分（权重降序）" style="height: 100%">
                <n-grid :cols="2" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
                  <n-gi v-for="m in metrics" :key="m.key" span="2 s:1">
                    <div class="metric-cell">
                      <div class="metric-head">
                        <span class="metric-name" :title="m.tip">{{ m.name }}</span>
                        <span class="metric-weight">权重 {{ m.weight }}</span>
                      </div>
                      <div class="metric-body">
                        <span class="metric-score" :style="{ color: scoreColor(m.score) }">
                          {{ m.score == null ? '—' : m.score.toFixed(1) }}
                        </span>
                        <span class="metric-raw">原始 {{ m.raw }}</span>
                      </div>
                      <n-progress
                        :percentage="m.score == null ? 0 : Math.round(m.score)"
                        :show-indicator="false"
                        :height="6"
                        :color="scoreColor(m.score)"
                        rail-color="rgba(127,127,127,0.15)"
                      />
                    </div>
                  </n-gi>
                </n-grid>
              </n-card>
            </n-gi>
          </n-grid>

          <!-- 历史曲线 -->
          <n-card title="恐贪值历史走势（含 6 分项，可点图例开关）">
            <BaseChart :option="historyOption" :height="360" />
          </n-card>

          <!-- 口径说明 -->
          <n-card title="口径与近似说明">
            <ul class="notes">
              <li>
                <b>计分</b>：每个指标对「过去一年（250 个交易日）」窗口 min-max 归一化到 0-100；
                波动率为反向指标（得分 = 100 − 归一化）；缺失分项按剩余权重归一化。
              </li>
              <li>
                <b>创新高/新低比</b>：同花顺该系列接口已失效，改用「上证指数距 52 周高点」
                （收盘 ÷ 过去一年最高收盘）。
              </li>
              <li>
                <b>北向资金</b>：2024 年 8 月起停止披露，改用「沪市融资余额 20 日变化率」。
              </li>
              <li>
                <b>涨停</b>：实盘取乐咕「真实涨停」（剔 ST 权威口径）；历史回填取东财涨停池
                按名称剔 ST，两者口径略有差异。
              </li>
              <li>
                <b>量能/波动率</b>：用上证指数（覆盖沪市全部股票，新浪日线全量历史）计算，
                量能比为自身 20 日均量的比值，与沪深两市口径的趋势一致。
              </li>
              <li>
                <b>上涨占比</b>：无免费历史源，从接入日起积累；积累满 60 个交易日前使用先验
                极值区间 [20%, 85%] 兜底，之后切换为实测窗口极值。
              </li>
              <li>
                <b>序列初期</b>：窗口很短时 min-max 极值不稳定，开头若干交易日得分波动偏大
                （甚至出现 0/100），随数据积累自然趋稳，非数据错误。
              </li>
            </ul>
          </n-card>
        </template>
      </n-spin>
    </n-space>

    <!-- AI 解读（真实恐贪数据 + 口径知识库 → LLM 流式） -->
    <AiInterpretModal v-model:show="showAiInterpret" context-type="fear_greed" title="AI 解读 · 贪婪恐惧指数" />
  </div>
</template>

<style scoped>
.fear-greed-page {
  padding: 4px;
}
.data-date {
  font-size: 13px;
}
.gauge-wrap {
  display: flex;
  justify-content: center;
}
.gauge-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
}
.metric-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  background: var(--bg-hover, rgba(127, 127, 127, 0.06));
  border-radius: 8px;
  height: 100%;
}
.metric-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.metric-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  cursor: help;
}
.metric-weight {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
.metric-body {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.metric-score {
  font-family: 'JetBrains Mono', monospace;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.1;
}
.metric-raw {
  font-size: 12px;
  color: var(--text-muted);
}
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
</style>
