<script setup lang="ts">
/**
 * 动量轮动实验室（档 C / 组合层回测）
 *
 * 与「信号实验室」的胜率扫描是两套独立引擎：
 * - 胜率扫描：单标的 · 全仓 0/1 做多 · 固定持有 N 日的入场点统计
 * - 本页：资产池横截面 ROC 排名 → top-K 等权 → 周度再平衡 → 逐日资金曲线
 *
 * 口径对齐用户技能 momentum-buy-signal / weekly-band-workflow：
 * ROC(20)、每 5 交易日再平衡、等权基准、相关性 > 0.5 告警、
 * 可选 BIAS20/60 三档过热降权。生产口径为 T+1 生效（无前视）。
 */
defineOptions({ name: 'RotationLab' })
import { ref, computed, onMounted } from 'vue'
import {
  NButton, NSelect, NInput, NInputNumber, NSwitch, NCard, NTag,
  NAlert, NSpin, NIcon, useMessage,
} from 'naive-ui'
import { TrendingUp, FlashOutline } from '@vicons/ionicons5'
import { rotationApi } from '../utils/api'
import type {
  RotationPreset, RotationResult, RotationRequestPayload, RotationSignal,
} from '../types'
import PageHeader from '../components/PageHeader.vue'
import BaseChart from '../components/BaseChart.vue'

const message = useMessage()

// ---- 参数 ----
const presets = ref<RotationPreset[]>([])
const presetKey = ref<string | null>(null)
const symbolText = ref('510300, 511010, 513100, 518880')
const lookback = ref(20)
const rebalanceDays = ref(5)
const topK = ref(1)
const years = ref(5)
const costBps = ref(0)
const biasOverlay = ref(false)
const minReturnEnabled = ref(false)
const minReturnPct = ref(0)

// ---- 状态 ----
const loading = ref(false)
const result = ref<RotationResult | null>(null)
const errorMsg = ref('')

const presetOptions = computed(() =>
  presets.value.map((p) => ({ label: p.name, value: p.key })),
)

function onPresetChange(key: string | null | undefined) {
  if (!key) return
  const p = presets.value.find((x) => x.key === key)
  if (!p) return
  symbolText.value = p.symbols.join(', ')
  if (topK.value > p.symbols.length) topK.value = 1
}

function fmt(v: number | null | undefined, digits = 2, suffix = ''): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—'
  return Number(v).toFixed(digits) + suffix
}

/** A 股习惯：涨红跌绿 */
function tone(v: number | null | undefined): string {
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return ''
  return n > 0 ? 'val-up' : 'val-down'
}

function onOff(on: boolean): string { return on ? '开启' : '关闭' }

const metricRows = computed(() => {
  const r = result.value
  if (!r) return []
  const a = r.metrics.rotation
  const b = r.metrics.equal_weight
  return [
    { label: '累计收益', a: a.total_return_pct, b: b.total_return_pct, unit: '%', sign: true },
    { label: '年化收益', a: a.annualized_pct, b: b.annualized_pct, unit: '%', sign: true },
    { label: '最大回撤', a: a.max_drawdown_pct, b: b.max_drawdown_pct, unit: '%', sign: true },
    { label: '年化波动', a: a.volatility_pct, b: b.volatility_pct, unit: '%', sign: false },
    { label: 'Sharpe', a: a.sharpe, b: b.sharpe, unit: '', sign: false },
    { label: 'Calmar', a: a.calmar, b: b.calmar, unit: '', sign: false },
  ]
})

const chartOption = computed(() => {
  const pts = result.value?.equity_curve ?? []
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number | null) => (v == null ? '—' : Number(v).toFixed(4)),
    },
    legend: { data: ['动量轮动', '等权持有'], top: 0 },
    grid: { left: 56, right: 20, top: 34, bottom: 52 },
    xAxis: {
      type: 'category',
      data: pts.map((p) => p.date),
      boundaryGap: false,
      axisLabel: { hideOverlap: true, fontSize: 10 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value', scale: true, name: '净值',
      nameTextStyle: { fontSize: 10 },
      axisLabel: { formatter: (v: number) => Number(v).toFixed(2), fontSize: 10 },
      splitLine: { lineStyle: { type: 'dashed', opacity: 0.45 } },
    },
    dataZoom: [
      { type: 'inside' },
      { type: 'slider', height: 16, bottom: 8, borderColor: 'transparent' },
    ],
    series: [
      {
        name: '动量轮动', type: 'line', showSymbol: false, smooth: false,
        data: pts.map((p) => p.rotation),
        lineStyle: { width: 2, color: '#e05252' },
        itemStyle: { color: '#e05252' },
        areaStyle: { color: '#e05252', opacity: 0.06 },
      },
      {
        name: '等权持有', type: 'line', showSymbol: false, smooth: false,
        data: pts.map((p) => p.equal_weight),
        lineStyle: { width: 1.6, color: '#8a919e', type: 'dashed' },
        itemStyle: { color: '#8a919e' },
      },
    ],
  }
})

const recentSignals = computed(() =>
  (result.value?.signals ?? []).slice(-12).reverse(),
)

function selectedText(s: RotationSignal): string {
  return s.selected.length ? s.selected.join(' + ') : '持现金（空仓）'
}

function rocText(s: RotationSignal): string {
  if (!s.selected.length) return '—'
  return s.selected.map((a) => `${a} ${fmt(s.roc_pct[a], 2, '%')}`).join(' · ')
}

function biasText(s: RotationSignal): string {
  const hit = s.selected
    .map((a) => ({ a, b: s.bias[a] }))
    .filter((x) => x.b && x.b.target_position < 1)
  if (!hit.length) return '—'
  return hit.map((x) => `${x.a} ${x.b!.target_position * 100}%`).join(' · ')
}

async function run() {
  const symbols = symbolText.value
    .split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
  if (symbols.length < 2) {
    message.warning('资产池至少需要 2 只标的（横截面排名才有意义）')
    return
  }
  if (symbols.length > 20) {
    message.warning('单次最多 20 只标的')
    return
  }
  const payload: RotationRequestPayload = {
    symbols,
    lookback: lookback.value,
    rebalance: rebalanceDays.value,
    top: topK.value,
    years: years.value,
    min_return: minReturnEnabled.value ? minReturnPct.value / 100 : null,
    cost_bps: costBps.value,
    bias_overlay: biasOverlay.value,
  }
  loading.value = true
  errorMsg.value = ''
  try {
    result.value = await rotationApi.backtest(payload)
  } catch (e: any) {
    errorMsg.value = e?.message || String(e)
    message.error('回测失败：' + errorMsg.value)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    presets.value = await rotationApi.getPresets()
    if (presets.value.length) {
      presetKey.value = presets.value[0].key
      onPresetChange(presetKey.value)
    }
  } catch (e: any) {
    message.warning('预设池加载失败，可手动填写标的：' + (e?.message || e))
  }
  // 首屏自动跑一次默认四资产，5 分钟进程内缓存，耗时约 1~2s
  await run()
})
</script>

<template>
  <div class="rotation-lab">
    <PageHeader
      title="动量轮动实验室"
      subtitle="资产池内按 ROC 横截面排名，持有最强 top-K 并周度再平衡；与单标的胜率扫描是两套独立引擎"
    />

    <!-- 参数区 -->
    <n-card class="param-card" :bordered="false">
      <div class="card-title">
        <n-icon :component="FlashOutline" size="16" />
        <span>回测参数</span>
        <n-tag size="small" :bordered="false">T+1 生效 · 无前视</n-tag>
      </div>

      <div class="param-grid">
        <div class="param-item span-2">
          <label>预设资产池</label>
          <n-select
            v-model:value="presetKey" :options="presetOptions"
            placeholder="选择预设池" clearable @update:value="onPresetChange"
          />
        </div>
        <div class="param-item span-3">
          <label>资产池代码（逗号分隔，2~20 只）</label>
          <n-input v-model:value="symbolText" placeholder="如 510300, 511010, 513100, 518880" clearable />
        </div>
        <div class="param-item">
          <label>ROC 回看（日）</label>
          <n-input-number v-model:value="lookback" :min="2" :max="250" :step="1" />
        </div>
        <div class="param-item">
          <label>再平衡（交易日）</label>
          <n-input-number v-model:value="rebalanceDays" :min="1" :max="60" :step="1" />
        </div>
        <div class="param-item">
          <label>持有前 K 名</label>
          <n-input-number v-model:value="topK" :min="1" :max="20" :step="1" />
        </div>
        <div class="param-item">
          <label>回看年数</label>
          <n-input-number v-model:value="years" :min="1" :max="10" :step="1" />
        </div>
        <div class="param-item">
          <label>单边换手成本（bp）</label>
          <n-input-number v-model:value="costBps" :min="0" :max="100" :step="1" />
        </div>
      </div>

      <div class="switch-row">
        <div class="switch-item">
          <n-switch v-model:value="biasOverlay" size="small" />
          <span>BIAS 过热分级减仓</span>
          <span class="hint">BIAS20&gt;10%/15%、BIAS60&gt;20% 逐档减半</span>
        </div>
        <div class="switch-item">
          <n-switch v-model:value="minReturnEnabled" size="small" />
          <span>全场走弱时空仓</span>
          <n-input-number
            v-if="minReturnEnabled" v-model:value="minReturnPct"
            :min="-50" :max="50" :step="1" size="small" class="inline-num"
          />
          <span v-if="minReturnEnabled" class="hint">冠军 ROC ≤ {{ minReturnPct }}% 则持现金</span>
          <span v-else class="hint">默认永不空仓，永远持最强</span>
        </div>
        <n-button type="primary" :loading="loading" @click="run">运行回测</n-button>
      </div>
    </n-card>

    <n-alert v-if="errorMsg" type="error" class="mt12" :bordered="false">
      回测失败：{{ errorMsg }}
    </n-alert>

    <n-spin :show="loading">
      <div v-if="!result && !loading" class="empty-hint">
        设置参数后点击「运行回测」，查看资金曲线与本周换仓决策。
      </div>

      <template v-if="result">
        <!-- 窗口与结论条 -->
        <div class="window-bar">
          <span><b>{{ result.window.start }} ~ {{ result.window.end }}</b></span>
          <span>{{ result.window.trading_days }} 个交易日</span>
          <span>再平衡 {{ result.metrics.rebalance_count }} 次</span>
          <span>累计换手 {{ fmt(result.metrics.total_turnover, 2) }}</span>
          <span>成本 {{ fmt(result.metrics.total_cost_pct, 3, '%') }}</span>
          <span class="excess" :class="tone(result.metrics.excess_pp)">
            超额 {{ fmt(result.metrics.excess_pp, 2, 'pp') }}
          </span>
        </div>

        <!-- 指标对比 + 资金曲线 -->
        <div class="result-grid">
          <n-card class="result-card" :bordered="false">
            <div class="card-title"><span>绩效对比</span></div>
            <table class="metric-table">
              <thead>
                <tr><th>指标</th><th>动量轮动</th><th>等权持有</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in metricRows" :key="row.label">
                  <td>{{ row.label }}</td>
                  <td :class="row.sign ? tone(row.a) : ''">{{ fmt(row.a, 2, row.unit) }}</td>
                  <td :class="row.sign ? tone(row.b) : ''">{{ fmt(row.b, 2, row.unit) }}</td>
                </tr>
              </tbody>
            </table>
            <p class="foot-note">
              基准 = 等权持有资产池全部标的；超额 = 轮动累计收益 − 等权累计收益。
              成本默认 0 bp，实盘须按券商费率设置。
            </p>
          </n-card>

          <n-card class="result-card chart-card" :bordered="false">
            <div class="card-title"><span>资金曲线（净值）</span></div>
            <BaseChart :option="chartOption" :height="300" />
          </n-card>
        </div>

        <!-- 本周决策 -->
        <n-card v-if="result.latest" class="result-card mt12" :bordered="false">
          <div class="card-title">
            <n-icon :component="TrendingUp" size="16" />
            <span>最近一次决策（本周该持什么）</span>
            <n-tag size="small" :type="result.latest.stance === 'cash' ? 'warning' : 'success'" :bordered="false">
              {{ result.latest.stance === 'cash' ? '持现金' : '持仓' }}
            </n-tag>
            <span class="hint">信号日 {{ result.latest.date }} · 生效日 {{ result.latest.effective_date || '待下一交易日' }}</span>
          </div>
          <div class="decision-row">
            <div class="decision-main">
              <span class="decision-label">目标持仓</span>
              <span class="decision-value">{{ selectedText(result.latest) }}</span>
            </div>
            <div class="decision-main">
              <span class="decision-label">当期 ROC</span>
              <span class="decision-value small">{{ rocText(result.latest) }}</span>
            </div>
          </div>
          <table class="action-table">
            <thead><tr><th>标的</th><th>动作</th><th>目标仓位</th><th>触发档位</th></tr></thead>
            <tbody>
              <tr v-for="a in result.latest.actions" :key="a.symbol">
                <td><b>{{ a.symbol }}</b></td>
                <td>{{ a.action }}</td>
                <td>{{ (a.target_position * 100).toFixed(1) }}%</td>
                <td>{{ biasText(result.latest) }}</td>
              </tr>
            </tbody>
          </table>
        </n-card>

        <!-- 相关性 / 数据覆盖 -->
        <div class="result-grid mt12">
          <n-card class="result-card" :bordered="false">
            <div class="card-title"><span>资产池相关性诊断</span></div>
            <n-alert
              v-if="result.correlation.warnings.length" type="warning"
              class="mb10" :bordered="false"
            >
              <div v-for="w in result.correlation.warnings" :key="w">{{ w }}</div>
              <div class="hint">品种过近易触发反转/补涨效应，吞噬动量超额，建议替换资产。</div>
            </n-alert>
            <n-alert v-else type="success" class="mb10" :bordered="false">
              所有资产对相关系数 ≤ {{ result.config.corr_warn }}，资产池分化度合格。
            </n-alert>
            <table class="metric-table compact">
              <thead><tr><th>资产对</th><th>日收益相关系数</th><th>判定</th></tr></thead>
              <tbody>
                <tr v-for="p in result.correlation.pairs" :key="p.a + '-' + p.b">
                  <td>{{ p.a }} ~ {{ p.b }}</td>
                  <td>{{ fmt(p.value, 3) }}</td>
                  <td>
                    <n-tag size="tiny" :type="p.warn ? 'warning' : 'success'" :bordered="false">
                      {{ p.warn ? '偏高' : '正常' }}
                    </n-tag>
                  </td>
                </tr>
              </tbody>
            </table>
          </n-card>

          <n-card class="result-card" :bordered="false">
            <div class="card-title"><span>数据覆盖（真实上市日）</span></div>
            <table class="metric-table compact">
              <thead><tr><th>标的</th><th>有效根数</th><th>首日</th><th>末日</th><th>状态</th></tr></thead>
              <tbody>
                <tr v-for="c in result.coverage" :key="c.symbol">
                  <td><b>{{ c.symbol }}</b></td>
                  <td>{{ c.bars }}</td>
                  <td>{{ c.first || '—' }}</td>
                  <td>{{ c.last || '—' }}</td>
                  <td>
                    <n-tag size="tiny" :type="c.listed_late ? 'warning' : 'success'" :bordered="false">
                      {{ c.listed_late ? '窗口内上市' : '全程覆盖' }}
                    </n-tag>
                  </td>
                </tr>
              </tbody>
            </table>
            <p class="foot-note">
              晚上市标的在上市前不参与排名也不计收益，绝不前向填充伪造历史价格；
              等权基准早期覆盖较少，横向对比请留意此列。
            </p>
          </n-card>
        </div>

        <!-- 最近信号 -->
        <n-card class="result-card mt12" :bordered="false">
          <div class="card-title"><span>最近 12 次再平衡信号</span></div>
          <div class="table-scroll">
            <table class="metric-table compact">
              <thead>
                <tr>
                  <th>信号日</th><th>生效日</th><th>上周持仓</th>
                  <th>下周持仓</th><th>当期 ROC</th><th>BIAS 降权</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in recentSignals" :key="s.date">
                  <td>{{ s.date }}</td>
                  <td>{{ s.effective_date || '—' }}</td>
                  <td>{{ s.prev_selected.length ? s.prev_selected.join(' + ') : '—' }}</td>
                  <td><b>{{ selectedText(s) }}</b></td>
                  <td>{{ rocText(s) }}</td>
                  <td>{{ biasText(s) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </n-card>

        <!-- 口径与边界 -->
        <n-card class="result-card mt12" :bordered="false">
          <div class="card-title"><span>口径与能力边界</span></div>
          <ul class="caveats">
            <li v-for="(c, i) in result.caveats" :key="i">{{ c }}</li>
          </ul>
          <p class="foot-note">
            当前生效口径：ROC({{ result.config.lookback }}) · 每 {{ result.config.rebalance }} 交易日再平衡 ·
            持有前 {{ result.config.top }} 名 · {{ result.config.years }} 年窗口 ·
            BIAS 降权{{ onOff(result.config.bias_overlay) }} ·
            空仓阈值{{ result.config.always_pick ? '关闭（永不空仓）' : '开启' }}。
          </p>
        </n-card>
      </template>
    </n-spin>
  </div>
</template>

<style scoped>
.rotation-lab { padding-bottom: 32px; }
.mt12 { margin-top: 12px; }
.mb10 { margin-bottom: 10px; }

.param-card, .result-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 10px;
}
.param-card { margin-bottom: 12px; }

.card-title {
  display: flex; align-items: center; gap: 8px;
  font-weight: 600; font-size: 14px; margin-bottom: 12px;
  color: var(--text-primary);
}
.card-title .hint { margin-left: auto; }

.param-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px 12px;
}
.param-item { min-width: 0; }
.param-item.span-2 { grid-column: span 2; }
.param-item.span-3 { grid-column: span 3; }
.param-item label {
  display: block; font-size: 12px; margin-bottom: 5px;
  color: var(--text-secondary);
}

.switch-row {
  display: flex; align-items: center; gap: 22px;
  flex-wrap: wrap; margin-top: 14px;
  padding-top: 12px; border-top: 1px solid var(--border-default);
}
.switch-row .n-button { margin-left: auto; }
.switch-item { display: flex; align-items: center; gap: 8px; font-size: 13px; flex-wrap: wrap; }
.hint, .foot-note { color: var(--text-muted); font-size: 12px; font-weight: 400; }
.inline-num { width: 96px; }

.window-bar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 10px 14px; margin-bottom: 12px;
  background: var(--bg-card); border: 1px solid var(--border-default);
  border-left: 3px solid var(--color-primary); border-radius: 8px;
  font-size: 13px; color: var(--text-secondary);
}
.window-bar .excess { margin-left: auto; font-weight: 700; font-size: 15px; }

.result-grid { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 7fr); gap: 12px; }
.chart-card :deep(.base-chart) { width: 100%; }

.metric-table, .action-table {
  width: 100%; border-collapse: collapse; font-size: 13px;
}
.metric-table th, .metric-table td,
.action-table th, .action-table td {
  padding: 7px 8px; text-align: left;
  border-bottom: 1px solid var(--border-default);
  white-space: nowrap;
}
.metric-table th, .action-table th {
  color: var(--text-muted); font-weight: 500; font-size: 12px;
}
.metric-table.compact th, .metric-table.compact td { padding: 5px 7px; font-size: 12px; }
.metric-table td:not(:first-child) { font-variant-numeric: tabular-nums; }
.foot-note { margin: 10px 0 0; line-height: 1.6; }

.val-up { color: #e05252; }
.val-down { color: #2eb37a; }

.decision-row { display: flex; gap: 32px; flex-wrap: wrap; margin-bottom: 12px; }
.decision-main { display: flex; flex-direction: column; gap: 4px; }
.decision-label { font-size: 12px; color: var(--text-muted); }
.decision-value { font-size: 20px; font-weight: 700; color: var(--text-primary); }
.decision-value.small { font-size: 14px; font-weight: 500; }

.caveats { margin: 0; padding-left: 18px; font-size: 12px; line-height: 1.8; color: var(--text-secondary); }
.table-scroll { overflow-x: auto; }
.empty-hint {
  padding: 48px 16px; text-align: center;
  color: var(--text-muted); font-size: 14px;
}

@media (max-width: 1100px) {
  .result-grid { grid-template-columns: 1fr; }
  .param-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .param-item.span-2, .param-item.span-3 { grid-column: span 3; }
}
@media (max-width: 640px) {
  .param-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .param-item.span-2, .param-item.span-3 { grid-column: span 2; }
  .switch-row .n-button { margin-left: 0; width: 100%; }
}
</style>
