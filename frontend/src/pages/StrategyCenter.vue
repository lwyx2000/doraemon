<script setup lang="ts">
defineOptions({ name: 'StrategyCenter' })
import { ref, computed, reactive, onMounted } from 'vue'
import {
  NButton, NSwitch, NIcon, NInputNumber, NSpin, NEmpty, NModal, NInput, NSelect, NTag,
  useMessage, useDialog,
} from 'naive-ui'
import {
  PlayOutline,
  AddCircleOutline,
  RefreshOutline,
  TrashOutline,
  ChevronDownOutline,
  RibbonOutline,
  PulseOutline,
  ArrowUpOutline,
  ArrowDownOutline,
} from '@vicons/ionicons5'
import { libraryApi, api } from '../utils/api'
import type { LibraryStrategy, LibraryBacktestResult, TrackedLibrary, Strategy, StrategyRule, AssetMeta, AssetFieldDef } from '../types'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import LoadingState from '../components/LoadingState.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'

const message = useMessage()
const dialog = useDialog()

// ---- 策略库 ----
const library = ref<LibraryStrategy[] | null>(null)
const loadError = ref('')
const loading = ref(true)
const activeTab = ref<'library' | 'tracked'>('library')

async function loadLibrary() {
  loading.value = true
  loadError.value = ''
  try {
    const res = await libraryApi.getLibrary()
    library.value = Array.isArray(res) ? res : ((res as any).data ?? [])
    // 初始化各策略参数（默认值）
    for (const s of library.value) {
      const p: Record<string, any> = {}
      for (const def of s.params) p[def.key] = def.default
      paramState[s.id] = p
    }
    // 默认自动回测第一个轮动策略，让页面一打开就有绩效
    if (library.value.length) runBacktest(library.value[0].id)
  } catch (e: any) {
    loadError.value = e?.message || '策略库加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(loadLibrary)
onMounted(loadTracked)
onMounted(loadAssetMeta)
onMounted(loadMyStrategies)

const paramState: Record<string, Record<string, any>> = reactive({})

// ---- 回测 ----
const backtests = reactive<Record<string, LibraryBacktestResult>>({})
const btLoading = reactive<Record<string, boolean>>({})
const expanded = reactive<Record<string, boolean>>({})

async function runBacktest(id: string) {
  btLoading[id] = true
  expanded[id] = true
  try {
    const res = await libraryApi.backtest(id, paramState[id])
    backtests[id] = (res as any).data ?? res
  } catch (e: any) {
    message.error(`回测失败: ${e?.message || e}`)
  } finally {
    btLoading[id] = false
  }
}

// ---- 我的跟踪 ----
const tracked = ref<TrackedLibrary[] | null>(null)
const trackedLoading = ref(false)

async function loadTracked() {
  try {
    const res = await libraryApi.getTracked()
    tracked.value = Array.isArray(res) ? res : ((res as any).data ?? [])
  } catch {
    tracked.value = []
  }
}
onMounted(loadTracked)

async function refreshTracked() {
  trackedLoading.value = true
  try {
    const res = await libraryApi.refreshTracked()
    tracked.value = Array.isArray(res) ? res : ((res as any).data ?? [])
    message.success('跟踪组合表现已更新（当日绩效快照已保存）')
  } catch (e: any) {
    message.error(`刷新失败: ${e?.message || e}`)
  } finally {
    trackedLoading.value = false
  }
}

async function addTrack(s: LibraryStrategy) {
  try {
    await libraryApi.addTracked(s.id, paramState[s.id])
    message.success(`已加入跟踪: ${s.name}`)
    await loadTracked()
    activeTab.value = 'tracked'
  } catch (e: any) {
    message.error(`加入跟踪失败: ${e?.message || e}`)
  }
}

function removeTrack(t: TrackedLibrary) {
  dialog.warning({
    title: '取消跟踪',
    content: `确定取消跟踪「${t.strategy_name}」吗？其绩效快照历史将一并删除。`,
    positiveText: '取消跟踪',
    negativeText: '保留',
    onPositiveClick: async () => {
      try {
        await libraryApi.removeTracked(t.id)
        tracked.value = (tracked.value || []).filter(x => x.id !== t.id)
        message.success(`已取消跟踪: ${t.strategy_name}`)
      } catch (e: any) {
        message.error(`操作失败: ${e?.message || e}`)
      }
    },
  })
}

// ---- 展示辅助 ----
const sourceColors: Record<string, string> = {
  '集思录': '#c2410c',
  '经典实盘策略': '#005ea1',
}
function fmtPct(v?: number | null, digits = 2): string {
  if (v === null || v === undefined) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`
}
function pctColor(v?: number | null): string {
  if (v === null || v === undefined) return '#717782'
  return v > 0 ? '#16a34a' : v < 0 ? '#ba1a1a' : '#717782'
}

// 净值曲线 SVG path
function navPoints(navs: number[], w: number, h: number, min: number, max: number): string {
  if (!navs.length || max <= min) return ''
  const step = navs.length > 1 ? w / (navs.length - 1) : 0
  return navs.map((v, i) => {
    const x = i * step
    const y = h - ((v - min) / (max - min)) * h
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

function curveBounds(bt: any) {
  const all = [...(bt.curve?.strategy_nav || []), ...(bt.curve?.benchmark_nav || [])]
  if (!all.length) return { min: 0, max: 1 }
  return { min: Math.min(...all), max: Math.max(...all) }
}

const trackedUpdatedCount = computed(
  () => (tracked.value || []).filter(t => t.perf && !t.error).length,
)

// ---- 自定义策略（我的策略） ----
const myStrategies = ref<Strategy[]>([])
const myStratLoading = ref(false)

// 字段元数据
const assetMeta = ref<AssetMeta[]>([])
const TARGET_ASSET_OPTIONS = computed(() =>
  assetMeta.value.map(m => ({ label: m.label, value: m.key })),
)

const TARGET_LABELS: Record<string, string> = {
  cb: '可转债', lof: 'LOF基金', qdii: 'QDII基金', etf: 'ETF', reit: 'REITs', fund: '封闭式基金', reits: 'REITs',
}

const OPERATOR_OPTIONS = ['<', '>', '<=', '>=', '==', '!=', '属于', '包含']

async function loadAssetMeta() {
  try {
    assetMeta.value = await api.getStrategyMeta()
  } catch {
    assetMeta.value = []
  }
}

// 根据当前标的类型返回可选字段列表
function fieldsForTarget(target: string): AssetFieldDef[] {
  const meta = assetMeta.value.find(m => m.key === target)
  return meta?.fields ?? []
}

// 获取字段定义（用于显示 label）
function fieldLabel(target: string, key: string): string {
  const f = fieldsForTarget(target).find(f => f.key === key)
  return f?.label ?? key
}

async function loadMyStrategies() {
  myStratLoading.value = true
  try {
    myStrategies.value = await api.getStrategies()
  } catch {
    myStrategies.value = []
  } finally {
    myStratLoading.value = false
  }
}

// 新建/编辑弹窗
const showStrategyModal = ref(false)
const strategyEditing = ref(false)
const strategySaving = ref(false)
const strategyForm = reactive({
  id: '',
  name: '',
  target_asset: 'cb' as string,
  rules: [] as Array<{ field: string; operator: string; value: string; logic: string }>,
  sort_by: '' as string,
  sort_order: 'asc' as 'asc' | 'desc',
  limit_count: null as number | null,
})

// 当标的类型改变时，重置规则字段为第一个可用字段
function onTargetChange() {
  const fields = fieldsForTarget(strategyForm.target_asset)
  const firstField = fields[0]?.key ?? ''
  for (const r of strategyForm.rules) {
    // 如果当前字段不在新标的的可选列表中，则重置
    if (!fields.find(f => f.key === r.field)) {
      r.field = firstField
      r.value = ''
    }
  }
}

function openCreateStrategy() {
  strategyEditing.value = false
  strategyForm.id = ''
  strategyForm.name = ''
  strategyForm.target_asset = 'cb'
  const firstField = fieldsForTarget('cb')[0]?.key ?? 'price'
  strategyForm.rules = [{ field: firstField, operator: '<', value: '', logic: 'AND' }]
  strategyForm.sort_by = ''
  strategyForm.sort_order = 'asc'
  strategyForm.limit_count = null
  showStrategyModal.value = true
}

function openEditStrategy(s: Strategy) {
  strategyEditing.value = true
  strategyForm.id = s.id
  strategyForm.name = s.name
  strategyForm.target_asset = s.target_asset
  strategyForm.rules = s.rules.map(r => ({ field: r.field, operator: r.operator, value: r.value, logic: r.logic || 'AND' }))
  if (!strategyForm.rules.length) {
    const firstField = fieldsForTarget(s.target_asset)[0]?.key ?? ''
    strategyForm.rules = [{ field: firstField, operator: '<', value: '', logic: 'AND' }]
  }
  strategyForm.sort_by = s.sort_by ?? ''
  strategyForm.sort_order = s.sort_order ?? 'asc'
  strategyForm.limit_count = s.limit_count ?? null
  showStrategyModal.value = true
}

function addRule() {
  const firstField = fieldsForTarget(strategyForm.target_asset)[0]?.key ?? ''
  strategyForm.rules.push({ field: firstField, operator: '<', value: '', logic: 'AND' })
}
function removeRule(idx: number) {
  strategyForm.rules.splice(idx, 1)
}

async function saveStrategy() {
  if (!strategyForm.name.trim()) {
    message.warning('请输入策略名称')
    return
  }
  if (!strategyForm.rules.length) {
    message.warning('至少添加一条规则')
    return
  }
  const rules: StrategyRule[] = strategyForm.rules.map((r, i) => ({
    id: `r${i}`, field: r.field, operator: r.operator, value: r.value, logic: 'AND' as const,
  }))
  const sortBy = strategyForm.sort_by || null
  const sortOrder = strategyForm.sort_order || 'asc'
  const limitCount = strategyForm.limit_count || null
  strategySaving.value = true
  try {
    if (strategyEditing.value) {
      await api.updateStrategy(strategyForm.id, { name: strategyForm.name, rules, sort_by: sortBy, sort_order: sortOrder, limit_count: limitCount })
      message.success('策略已更新')
    } else {
      await api.createStrategy({ name: strategyForm.name, target_asset: strategyForm.target_asset, rules, sort_by: sortBy, sort_order: sortOrder, limit_count: limitCount })
      message.success('策略已创建')
    }
    showStrategyModal.value = false
    await loadMyStrategies()
  } catch (e: any) {
    message.error('保存失败：' + (e?.message || ''))
  } finally {
    strategySaving.value = false
  }
}

function deleteStrategy(s: Strategy) {
  dialog.warning({
    title: '删除策略',
    content: `确定删除策略「${s.name}」吗？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.deleteStrategy(s.id)
        message.success('已删除')
        await loadMyStrategies()
      } catch (e: any) {
        message.error('删除失败：' + (e?.message || ''))
      }
    },
  })
}

// 执行策略结果
const execResults = reactive<Record<string, { items: any[]; total: number; returned: number; strategy: any } | null>>({})
const execLoading = reactive<Record<string, boolean>>({})
async function executeStrategy(s: Strategy) {
  execLoading[s.id] = true
  try {
    const res = await api.executeStrategy(s.id)
    execResults[s.id] = res
  } catch (e: any) {
    message.error('执行失败：' + (e?.message || ''))
    execResults[s.id] = null
  } finally {
    execLoading[s.id] = false
  }
}

// 执行结果的表格列定义 — 根据标的类型动态生成
function execTableColumns(s: Strategy): { key: string; title: string; width?: number }[] {
  const fields = fieldsForTarget(s.target_asset)
  // 前两列固定为 name / code
  const cols: { key: string; title: string; width?: number }[] = [
    { key: 'name', title: '名称', width: 150 },
    { key: 'code', title: '代码', width: 100 },
  ]
  // 其余字段按元数据生成
  for (const f of fields) {
    if (f.key === 'name' || f.key === 'code') continue
    cols.push({ key: f.key, title: f.label + (f.unit ? `(${f.unit})` : '') })
  }
  return cols
}

const tabs = [
  { key: 'library', label: '策略库' },
  { key: 'tracked', label: '我的跟踪' },
  { key: 'mine', label: '我的策略' },
]
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="loadError"
    skeleton
    :min-height="520"
    text="正在加载策略库..."
    @retry="loadLibrary"
  >
    <div class="strategy-page">
    <PageHeader
      title="策略中心"
      subtitle="经典实盘策略库 — 集思录大V实盘与经典轮动策略，一键回测、跟踪绩效监控"
      help-key="strategyCenter"
    />

    <GlossaryPanel page-key="strategyCenter" />

    <!-- Summary Stats -->
    <div class="stat-grid">
      <StatCard label="策略库" :value="library?.length ?? 0" sub="经典实盘策略" />
      <StatCard label="我的跟踪" :value="tracked?.length ?? 0" color="#005ea1" sub="关注的策略组合" />
      <StatCard label="今日已更新" :value="trackedUpdatedCount" color="#16a34a" sub="绩效快照" />
      <StatCard
        label="最佳超额(轮动)"
        :value="fmtPct(Math.max(0, ...((tracked||[]).filter(t=>t.perf?.kind==='index_rotation').map(t=>t.perf?.excess_pct ?? -999))))"
        color="#7c3aed"
        sub="跟踪中轮动策略超额"
      />
    </div>

    <!-- Tab Bar -->
    <div class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :class="['tab-btn', { active: activeTab === tab.key }]"
        @click="activeTab = tab.key as any"
      >
        {{ tab.label }}
        <span v-if="tab.key === 'tracked' && tracked?.length" class="tab-count">{{ tracked.length }}</span>
      </button>
      <div class="tab-spacer" />
      <n-button size="tiny" :loading="trackedLoading" @click="refreshTracked">
        <template #icon><n-icon :component="RefreshOutline" /></template>
        刷新跟踪表现
      </n-button>
    </div>

    <!-- ============ 策略库 ============ -->
    <div v-if="activeTab === 'library'" class="lib-grid">
      <div v-for="s in library" :key="s.id" class="lib-card" :class="{ open: expanded[s.id] }">
        <div class="lib-head">
          <div class="lib-title-row">
            <h3 class="lib-title">{{ s.name }}</h3>
            <span class="lib-style">{{ s.style }}</span>
          </div>
          <div class="lib-badges">
            <span class="src-badge" :style="{ color: sourceColors[s.source] || '#585e6c', borderColor: (sourceColors[s.source] || '#585e6c') + '60' }">
              <n-icon :component="RibbonOutline" size="12" />
              {{ s.source }}实盘
            </span>
            <span class="cat-badge">{{ s.category }}</span>
            <span v-if="s.kind === 'cb_snapshot'" class="cat-badge cb">实时快照</span>
          </div>
        </div>

        <p class="lib-desc">{{ s.desc }}</p>
        <p class="lib-source-note"><b>实盘背景：</b>{{ s.source_note }}</p>

        <div v-if="s.kind === 'index_rotation'" class="lib-members">
          <span v-for="m in s.members" :key="m.code" class="member-chip">{{ m.name }}</span>
        </div>

        <!-- 参数 -->
        <div class="lib-params">
          <div v-for="def in s.params" :key="def.key" class="param-item">
            <template v-if="def.type === 'switch'">
              <label class="param-label">{{ def.label }}</label>
              <n-switch
                size="small"
                :value="!!(paramState[s.id]?.[def.key])"
                @update:value="(v: boolean) => paramState[s.id][def.key] = v ? 1 : 0"
              />
            </template>
            <template v-else>
              <label class="param-label">{{ def.label }}</label>
              <n-input-number
                size="tiny"
                :value="paramState[s.id]?.[def.key] ?? def.default"
                :min="def.min" :max="def.max" :step="def.step || 1"
                :update-value-on-input="false"
                style="width: 110px"
                @update:value="(v: number | null) => paramState[s.id][def.key] = v ?? def.default"
              />
            </template>
            <span v-if="def.help" class="param-help">{{ def.help }}</span>
          </div>
        </div>

        <div class="lib-actions">
          <n-button size="small" type="primary" :loading="btLoading[s.id]" @click="runBacktest(s.id)">
            <template #icon><n-icon :component="PlayOutline" /></template>
            回测详情
          </n-button>
          <n-button size="small" quaternary @click="expanded[s.id] = !expanded[s.id]">
            <template #icon><n-icon :component="ChevronDownOutline" :class="{ flip: expanded[s.id] }" /></template>
            {{ expanded[s.id] ? '收起' : '展开' }}
          </n-button>
          <div style="flex:1" />
          <n-button size="small" type="primary" ghost @click="addTrack(s)">
            <template #icon><n-icon :component="AddCircleOutline" /></template>
            跟踪此策略
          </n-button>
        </div>

        <!-- 回测结果详情 -->
        <div v-if="expanded[s.id] && backtests[s.id]" class="bt-panel">
          <n-spin :show="!!btLoading[s.id]">
            <template v-if="backtests[s.id].backtest?.error">
              <div class="bt-error">{{ backtests[s.id].backtest.error }}</div>
            </template>
            <template v-else>
              <!-- 轮动绩效 -->
              <template v-if="backtests[s.id].backtest?.kind === 'index_rotation'">
                <div class="perf-grid">
                  <div class="perf-item">
                    <span class="pi-label">累计收益</span>
                    <span class="pi-value" :style="{ color: pctColor(backtests[s.id].backtest.cum_return_pct) }">
                      {{ fmtPct(backtests[s.id].backtest.cum_return_pct) }}
                    </span>
                  </div>
                  <div class="perf-item">
                    <span class="pi-label">年化收益</span>
                    <span class="pi-value" :style="{ color: pctColor(backtests[s.id].backtest.annual_return_pct) }">
                      {{ fmtPct(backtests[s.id].backtest.annual_return_pct) }}
                    </span>
                  </div>
                  <div class="perf-item">
                    <span class="pi-label">最大回撤</span>
                    <span class="pi-value" style="color:#ba1a1a">{{ backtests[s.id].backtest.max_drawdown_pct }}%</span>
                  </div>
                  <div class="perf-item">
                    <span class="pi-label">夏普</span>
                    <span class="pi-value">{{ backtests[s.id].backtest.sharpe }}</span>
                  </div>
                  <div class="perf-item">
                    <span class="pi-label">胜率</span>
                    <span class="pi-value">{{ backtests[s.id].backtest.win_rate_pct }}%</span>
                  </div>
                  <div class="perf-item">
                    <span class="pi-label">换仓次数</span>
                    <span class="pi-value">{{ backtests[s.id].backtest.trades }}</span>
                  </div>
                  <div class="perf-item">
                    <span class="pi-label">{{ backtests[s.id].backtest.benchmark?.name }}</span>
                    <span class="pi-value" :style="{ color: pctColor(backtests[s.id].backtest.benchmark?.cum_return_pct) }">
                      {{ fmtPct(backtests[s.id].backtest.benchmark?.cum_return_pct) }}
                    </span>
                  </div>
                  <div class="perf-item">
                    <span class="pi-label">超额收益</span>
                    <span class="pi-value" :style="{ color: pctColor(backtests[s.id].backtest.excess_pct) }">
                      {{ fmtPct(backtests[s.id].backtest.excess_pct) }}
                    </span>
                  </div>
                </div>

                <!-- 净值曲线 -->
                <div class="curve-box" v-if="backtests[s.id].backtest.curve">
                  <div class="curve-legend">
                    <span class="lg strategy">策略净值</span>
                    <span class="lg bench">{{ backtests[s.id].backtest.benchmark?.name }}</span>
                    <span class="curve-range">
                      {{ backtests[s.id].backtest.start_date }} ~ {{ backtests[s.id].backtest.end_date }}
                      （{{ backtests[s.id].backtest.trading_days }} 个交易日）
                    </span>
                  </div>
                  <svg viewBox="0 0 640 150" preserveAspectRatio="none" class="nav-svg">
                    <!-- 基准 -->
                    <polyline fill="none" stroke="#9aa1b0" stroke-width="1.2" stroke-dasharray="4 3"
                      :points="navPoints(backtests[s.id].backtest.curve.benchmark_nav, 640, 150, curveBounds(backtests[s.id].backtest).min, curveBounds(backtests[s.id].backtest).max)" />
                    <!-- 策略 -->
                    <polyline fill="none" stroke="#005ea1" stroke-width="1.8"
                      :points="navPoints(backtests[s.id].backtest.curve.strategy_nav, 640, 150, curveBounds(backtests[s.id].backtest).min, curveBounds(backtests[s.id].backtest).max)" />
                    <line x1="0" y1="150" x2="640" y2="150" stroke="#e2e8f0" stroke-width="1" />
                  </svg>
                </div>

                <!-- 当前持仓建议 -->
                <div class="holding-box" v-if="backtests[s.id].backtest.current_holding">
                  <div class="holding-head">
                    <n-icon :component="PulseOutline" size="14" />
                    <b>当前持仓建议：</b>
                    <span class="holding-action">{{ backtests[s.id].backtest.current_holding.action }}</span>
                    <span class="holding-mom" :style="{ color: pctColor(backtests[s.id].backtest.current_holding.mom_pct) }">
                      近20日 {{ fmtPct(backtests[s.id].backtest.current_holding.mom_pct) }}
                    </span>
                  </div>
                  <div class="mom-row" v-if="backtests[s.id].backtest.current_holding.members_mom">
                    <span v-for="m in backtests[s.id].backtest.current_holding.members_mom" :key="m.code" class="mom-chip">
                      {{ m.name }} <i :style="{ color: pctColor(m.mom_pct) }">{{ fmtPct(m.mom_pct) }}</i>
                    </span>
                  </div>
                </div>

                <!-- 近期切换 -->
                <div class="switch-box" v-if="backtests[s.id].backtest.recent_switches?.length">
                  <div class="switch-title">近期轮动切换</div>
                  <div v-for="(sw, i) in backtests[s.id].backtest.recent_switches" :key="i" class="switch-row">
                    <span class="sw-date">{{ sw.date }}</span>
                    <span class="sw-holding" :class="{ cash: !sw.code }">{{ sw.holding }}</span>
                    <span class="sw-reason">{{ sw.reason }}</span>
                  </div>
                </div>
              </template>

              <!-- 双低转债组合 -->
              <template v-else-if="backtests[s.id].backtest?.kind === 'cb_snapshot'">
                <div class="cb-summary">
                  <div class="perf-item">
                    <span class="pi-label">参与排名</span>
                    <span class="pi-value">{{ backtests[s.id].backtest.universe_count }} 只</span>
                  </div>
                  <div class="perf-item">
                    <span class="pi-label">组合平均双低</span>
                    <span class="pi-value">{{ backtests[s.id].backtest.avg_double_low }}</span>
                  </div>
                  <div class="perf-item">
                    <span class="pi-label">平均价格</span>
                    <span class="pi-value">{{ backtests[s.id].backtest.avg_price }}</span>
                  </div>
                  <div class="perf-item">
                    <span class="pi-label">平均溢价率</span>
                    <span class="pi-value">{{ backtests[s.id].backtest.avg_premium_pct }}%</span>
                  </div>
                </div>
                <table class="cb-table">
                  <thead>
                    <tr><th>排名</th><th>代码</th><th>名称</th><th>价格</th><th>溢价率</th><th>双低值</th><th>YTM</th><th>评级</th><th>正股</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(b, i) in backtests[s.id].backtest.portfolio" :key="b.code" :class="{ top3: i < 3 }">
                      <td class="mono">{{ i + 1 }}</td>
                      <td class="mono">{{ b.code }}</td>
                      <td>{{ b.name }}</td>
                      <td class="mono">{{ b.price }}</td>
                      <td class="mono" :style="{ color: pctColor(b.premium_pct) }">{{ b.premium_pct }}%</td>
                      <td class="mono bold">{{ b.double_low_score }}</td>
                      <td class="mono">{{ b.ytm ?? '—' }}</td>
                      <td>{{ b.rating || '—' }}</td>
                      <td>{{ b.stock_name || '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </template>

              <p class="bt-note">{{ backtests[s.id].backtest.note }}</p>
            </template>
          </n-spin>
        </div>
      </div>
    </div>

    <!-- ============ 我的策略 ============ -->
    <div v-if="activeTab === 'mine'" class="mine-wrap">
      <div class="mine-header">
        <n-button size="small" type="primary" @click="openCreateStrategy">
          <template #icon><n-icon :component="AddCircleOutline" /></template>
          新建策略
        </n-button>
      </div>
      <n-empty v-if="myStrategies.length === 0" description="还没有自定义策略 — 点击「新建策略」创建筛选规则" style="padding: 48px 0" />
      <div v-else class="mine-grid">
        <div v-for="s in myStrategies" :key="s.id" class="mine-card">
          <div class="mine-head">
            <div>
              <h3 class="mine-title">{{ s.name }}</h3>
              <div class="mine-sub">
                <n-tag size="small" :bordered="false" type="info">{{ TARGET_LABELS[s.target_asset] || s.target_asset }}</n-tag>
                <span v-if="s.active" class="mine-active">启用中</span>
                <span v-else class="mine-inactive">已停用</span>
                <span v-if="s.ai_tracking" class="mine-ai">AI跟踪</span>
              </div>
            </div>
            <div class="mine-actions">
              <n-button size="tiny" type="primary" :loading="execLoading[s.id]" @click="executeStrategy(s)">执行</n-button>
              <n-button size="tiny" quaternary @click="openEditStrategy(s)">编辑</n-button>
              <n-button size="tiny" quaternary type="error" @click="deleteStrategy(s)">删除</n-button>
            </div>
          </div>
          <!-- 规则展示 → 使用 fieldLabel 显示中文名 -->
          <div class="mine-rules">
            <div v-for="(r, i) in s.rules" :key="i" class="rule-chip">
              <span class="rule-logic" v-if="i > 0">{{ r.logic || 'AND' }}</span>
              <span class="rule-field">{{ fieldLabel(s.target_asset, r.field) }}</span>
              <span class="rule-op">{{ r.operator }}</span>
              <span class="rule-val">{{ r.value }}</span>
            </div>
          </div>
          <!-- 排序与限制信息 -->
          <div class="mine-sort-info" v-if="s.sort_by || s.limit_count">
            <span v-if="s.sort_by" class="sort-info-item">
              排序: {{ fieldLabel(s.target_asset, s.sort_by) }} {{ s.sort_order === 'desc' ? '↓' : '↑' }}
            </span>
            <span v-if="s.limit_count" class="sort-info-item">取前 {{ s.limit_count }} 名</span>
          </div>
          <!-- 执行结果 -->
          <div v-if="execResults[s.id]" class="mine-exec">
            <div class="mine-exec-title">
              执行结果（{{ execResults[s.id]!.total }} 条匹配，返回 {{ execResults[s.id]!.returned }} 条）
            </div>
            <div v-if="execResults[s.id]!.items.length === 0" class="mine-exec-empty">无匹配标的</div>
            <div v-else class="mine-exec-table-wrap">
              <table class="mine-exec-table">
                <thead>
                  <tr>
                    <th v-for="col in execTableColumns(s)" :key="col.key">{{ col.title }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(item, i) in execResults[s.id]!.items.slice(0, 50)" :key="i">
                    <td v-for="col in execTableColumns(s)" :key="col.key" class="mono">{{ item[col.key] ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
              <div v-if="execResults[s.id]!.items.length > 50" class="mine-exec-more">...仅显示前 50 条，共 {{ execResults[s.id]!.items.length }} 条</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ============ 我的跟踪 ============ -->
    <div v-if="activeTab === 'tracked'" class="tracked-wrap">
      <n-empty v-if="tracked && tracked.length === 0" description="还没有跟踪的策略 — 到「策略库」点击「跟踪此策略」开始监控绩效" style="padding: 48px 0" />
      <div v-else class="tracked-grid">
        <div v-for="t in tracked" :key="t.id" class="tracked-card">
          <div class="tk-head">
            <div>
              <h3 class="tk-title">{{ t.strategy_name }}</h3>
              <div class="tk-sub">
                <span class="src-badge sm" :style="{ color: sourceColors[t.source] || '#585e6c', borderColor: (sourceColors[t.source] || '#585e6c') + '60' }">{{ t.source }}实盘</span>
                <span class="tk-date">跟踪自 {{ (t.created_at || '').slice(0, 10) }}</span>
              </div>
            </div>
            <button class="tk-remove" title="取消跟踪" @click="removeTrack(t)">
              <n-icon :component="TrashOutline" size="15" />
            </button>
          </div>

          <div v-if="t.error" class="bt-error">{{ t.error }}</div>
          <template v-else-if="t.perf">
            <!-- 轮动绩效 -->
            <template v-if="t.perf.kind === 'index_rotation'">
              <div class="tk-perf-row">
                <div class="tk-stat">
                  <span class="pi-label">累计收益</span>
                  <span class="pi-value" :style="{ color: pctColor(t.perf.cum_return_pct) }">{{ fmtPct(t.perf.cum_return_pct) }}</span>
                </div>
                <div class="tk-stat">
                  <span class="pi-label">年化</span>
                  <span class="pi-value" :style="{ color: pctColor(t.perf.annual_return_pct) }">{{ fmtPct(t.perf.annual_return_pct) }}</span>
                </div>
                <div class="tk-stat">
                  <span class="pi-label">回撤</span>
                  <span class="pi-value" style="color:#ba1a1a">{{ t.perf.max_drawdown_pct }}%</span>
                </div>
                <div class="tk-stat">
                  <span class="pi-label">夏普</span>
                  <span class="pi-value">{{ t.perf.sharpe }}</span>
                </div>
                <div class="tk-stat">
                  <span class="pi-label">超额</span>
                  <span class="pi-value" :style="{ color: pctColor(t.perf.excess_pct) }">{{ fmtPct(t.perf.excess_pct) }}</span>
                </div>
              </div>
              <div class="tk-holding" v-if="t.current_holding">
                当前持仓：<b>{{ t.current_holding.action }}</b>
                <span :style="{ color: pctColor(t.current_holding.mom_pct) }">（近20日 {{ fmtPct(t.current_holding.mom_pct) }}）</span>
              </div>
              <!-- 净值曲线 -->
              <div class="curve-box small" v-if="t.curve">
                <svg viewBox="0 0 640 90" preserveAspectRatio="none" class="nav-svg">
                  <polyline fill="none" stroke="#9aa1b0" stroke-width="1.2" stroke-dasharray="4 3"
                    :points="navPoints(t.curve.benchmark_nav, 640, 90, curveBounds({ curve: t.curve }).min, curveBounds({ curve: t.curve }).max)" />
                  <polyline fill="none" stroke="#005ea1" stroke-width="1.8"
                    :points="navPoints(t.curve.strategy_nav, 640, 90, curveBounds({ curve: t.curve }).min, curveBounds({ curve: t.curve }).max)" />
                </svg>
              </div>
            </template>
            <!-- CB 快照绩效 -->
            <template v-else>
              <div class="tk-perf-row">
                <div class="tk-stat">
                  <span class="pi-label">组合平均双低</span>
                  <span class="pi-value">{{ t.perf.avg_double_low }}</span>
                </div>
                <div class="tk-stat">
                  <span class="pi-label">平均价格</span>
                  <span class="pi-value">{{ t.perf.avg_price }}</span>
                </div>
                <div class="tk-stat">
                  <span class="pi-label">平均溢价率</span>
                  <span class="pi-value">{{ t.perf.avg_premium_pct }}%</span>
                </div>
                <div class="tk-stat">
                  <span class="pi-label">参与排名</span>
                  <span class="pi-value">{{ t.perf.universe_count }} 只</span>
                </div>
              </div>
              <div class="tk-cb-list">
                <span v-for="(b, i) in (t.portfolio || []).slice(0, 10)" :key="b.code" class="tk-cb-chip" :title="`双低 ${b.double_low_score}`">
                  <i class="rank">{{ i + 1 }}</i>{{ b.name }} <em>{{ b.double_low_score }}</em>
                </span>
              </div>
            </template>
            <!-- 快照历史 -->
            <div class="tk-history" v-if="t.history && t.history.length > 1">
              <span class="pi-label">绩效快照（{{ t.history.length }} 日）：</span>
              <span v-for="h in t.history" :key="h.date" class="hist-dot"
                :title="`${h.date}: ${h.cum_return_pct !== undefined ? '累计 ' + h.cum_return_pct + '%' : '平均双低 ' + h.avg_double_low}`"
                :style="{
                  background: h.cum_return_pct !== undefined ? pctColor(h.cum_return_pct) : '#005ea1',
                  opacity: 0.35 + 0.65 * (1 - t.history.indexOf(h) / Math.max(t.history.length - 1, 1)),
                }" />
            </div>
          </template>
          <div v-else class="tk-pending">尚未计算绩效 — 点击上方「刷新跟踪表现」</div>
        </div>
      </div>
    </div>
    </div>
    <!-- 新建/编辑策略弹窗 -->
    <n-modal v-model:show="showStrategyModal" preset="card" :title="strategyEditing ? '编辑策略' : '新建策略'" style="width: 640px; max-width: 94vw;" :bordered="false">
      <div class="strat-form">
        <div class="strat-field">
          <label>策略名称</label>
          <n-input v-model:value="strategyForm.name" placeholder="如 低价转债筛选" />
        </div>
        <div class="strat-field">
          <label>标的类型</label>
          <n-select v-model:value="strategyForm.target_asset" :options="TARGET_ASSET_OPTIONS" @update:value="onTargetChange" />
        </div>
        <div class="strat-field">
          <label>筛选规则（AND 逻辑）</label>
          <div class="strat-rules">
            <div v-for="(r, i) in strategyForm.rules" :key="i" class="strat-rule-row">
              <n-select v-model:value="r.field" :options="fieldsForTarget(strategyForm.target_asset).map(f => ({ label: f.label + (f.unit ? ' (' + f.unit + ')' : ''), value: f.key }))" size="small" style="width: 160px;" />
              <n-select v-model:value="r.operator" :options="OPERATOR_OPTIONS.map(o => ({ label: o, value: o }))" size="small" style="width: 80px;" />
              <n-input v-if="r.operator !== '属于' && r.operator !== '包含'" v-model:value="r.value" size="small" placeholder="数值" style="flex: 1;" />
              <n-input v-else v-model:value="r.value" size="small" placeholder="逗号分隔，如 AAA,AA+" style="flex: 1;" />
              <n-button size="tiny" quaternary type="error" @click="removeRule(i)" v-if="strategyForm.rules.length > 1">✕</n-button>
            </div>
          </div>
          <n-button size="tiny" quaternary @click="addRule">+ 添加规则</n-button>
        </div>
        <div class="strat-field">
          <label>排序与取前 N（可选）</label>
          <div class="strat-sort-row">
            <n-select v-model:value="strategyForm.sort_by" :options="[{ label: '不排序', value: '' }, ...fieldsForTarget(strategyForm.target_asset).map(f => ({ label: f.label, value: f.key }))]" size="small" style="width: 180px;" />
            <n-button size="small" quaternary @click="strategyForm.sort_order = strategyForm.sort_order === 'asc' ? 'desc' : 'asc'">
              <template #icon>
                <n-icon :component="strategyForm.sort_order === 'asc' ? ArrowUpOutline : ArrowDownOutline" />
              </template>
              {{ strategyForm.sort_order === 'asc' ? '升序' : '降序' }}
            </n-button>
            <n-input-number v-model:value="strategyForm.limit_count" :min="1" :max="500" size="small" placeholder="取前N名，留空不限制" style="width: 160px;" />
          </div>
        </div>
      </div>
      <template #footer>
        <div class="modal-footer">
          <n-button size="small" @click="showStrategyModal = false">取消</n-button>
          <n-button size="small" type="primary" :loading="strategySaving" @click="saveStrategy">{{ strategyEditing ? '保存' : '创建' }}</n-button>
        </div>
      </template>
    </n-modal>
  </LoadingState>
</template>

<style scoped>
.strategy-page { display: flex; flex-direction: column; gap: 14px; }

/* Tab Bar */
.tab-bar { display: flex; align-items: center; gap: 4px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 4px; }
.tab-btn { padding: 6px 16px; border: none; background: transparent; border-radius: 6px; cursor: pointer; font-family: 'Work Sans', sans-serif; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; color: #717782; transition: all 0.15s; }
.tab-btn:hover { background: #f2f3fa; color: #181c21; }
.tab-btn.active { background: #005ea1; color: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.tab-count { display: inline-block; margin-left: 6px; padding: 0 6px; border-radius: 8px; background: rgba(255,255,255,0.25); font-size: 10px; }
.tab-btn:not(.active) .tab-count { background: #f2f3fa; color: #585e6c; }
.tab-spacer { flex: 1; }

/* 策略库卡片 */
.lib-grid { display: grid; grid-template-columns: 1fr; gap: 14px; }
.lib-card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; display: flex; flex-direction: column; gap: 10px; transition: all 0.2s; }
.lib-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.lib-card.open { border-color: #005ea1; }
.lib-head { display: flex; flex-direction: column; gap: 6px; }
.lib-title-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.lib-title { font-family: 'Work Sans', sans-serif; font-size: 16px; font-weight: 700; color: #181c21; margin: 0; }
.lib-style { font-size: 11px; font-weight: 700; color: #7c3aed; background: #7c3aed15; padding: 2px 8px; border-radius: 4px; white-space: nowrap; }
.lib-badges { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.src-badge { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 700; padding: 2px 8px; border: 1px solid; border-radius: 4px; }
.cat-badge { font-size: 11px; font-weight: 700; color: #585e6c; background: #f2f3fa; padding: 2px 8px; border-radius: 4px; }
.cat-badge.cb { color: #16a34a; background: #16a34a15; }
.lib-desc { font-size: 13px; color: #414751; line-height: 1.55; margin: 0; }
.lib-source-note { font-size: 12px; color: #717782; line-height: 1.5; margin: 0; padding: 8px 10px; background: #f8f9ff; border-left: 3px solid #005ea1; border-radius: 4px; }
.lib-source-note b { color: #005ea1; }
.lib-members { display: flex; gap: 6px; flex-wrap: wrap; }
.member-chip { font-size: 11px; font-weight: 700; color: #005ea1; background: #005ea110; padding: 2px 8px; border-radius: 4px; }

.lib-params { display: flex; gap: 18px; flex-wrap: wrap; padding: 10px 12px; background: #f8f9fb; border-radius: 8px; }
.param-item { display: flex; align-items: center; gap: 8px; }
.param-label { font-size: 12px; font-weight: 700; color: #585e6c; white-space: nowrap; }
.param-help { font-size: 11px; color: #9aa1b0; }

.lib-actions { display: flex; gap: 8px; align-items: center; }
.flip { transform: rotate(180deg); }

/* 回测面板 */
.bt-panel { border-top: 1px dashed #e2e8f0; padding-top: 12px; }
.bt-error { color: #ba1a1a; font-size: 13px; padding: 8px 0; }
.perf-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; margin-bottom: 12px; }
.perf-item { background: #f8f9fb; border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; }
.pi-label { font-size: 10px; font-weight: 700; color: #717782; letter-spacing: 0.05em; }
.pi-value { font-family: 'JetBrains Mono', monospace; font-size: 16px; font-weight: 700; color: #181c21; }

.curve-box { background: #fbfcfe; border: 1px solid #eef1f6; border-radius: 8px; padding: 10px; margin-bottom: 12px; }
.curve-box.small { padding: 6px; }
.curve-legend { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.lg { font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 4px; }
.lg::before { content: ''; width: 14px; height: 3px; border-radius: 2px; display: inline-block; }
.lg.strategy::before { background: #005ea1; }
.lg.bench::before { background: #9aa1b0; }
.curve-range { margin-left: auto; font-size: 11px; color: #9aa1b0; }
.nav-svg { width: 100%; height: 150px; display: block; }
.curve-box.small .nav-svg { height: 90px; }

.holding-box { background: #f0f7ff; border: 1px solid #cce0f5; border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; display: flex; flex-direction: column; gap: 8px; }
.holding-head { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #181c21; flex-wrap: wrap; }
.holding-head b { color: #005ea1; }
.holding-action { font-weight: 700; color: #005ea1; }
.holding-mom { font-size: 12px; font-family: 'JetBrains Mono', monospace; }
.mom-row { display: flex; gap: 8px; flex-wrap: wrap; }
.mom-chip { font-size: 11px; color: #585e6c; background: white; padding: 2px 8px; border-radius: 4px; border: 1px solid #e2e8f0; }
.mom-chip i { font-style: normal; font-family: 'JetBrains Mono', monospace; font-weight: 700; }

.switch-box { margin-bottom: 12px; }
.switch-title { font-size: 11px; font-weight: 700; color: #717782; letter-spacing: 0.05em; margin-bottom: 6px; }
.switch-row { display: flex; gap: 10px; font-size: 12px; padding: 4px 0; border-bottom: 1px dashed #f2f3fa; align-items: baseline; }
.sw-date { font-family: 'JetBrains Mono', monospace; color: #717782; flex-shrink: 0; }
.sw-holding { font-weight: 700; color: #005ea1; flex-shrink: 0; }
.sw-holding.cash { color: #f97316; }
.sw-reason { color: #585e6c; }

.cb-summary { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; margin-bottom: 12px; }
.cb-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.cb-table th { text-align: left; font-size: 10px; font-weight: 700; color: #717782; letter-spacing: 0.05em; padding: 6px 8px; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }
.cb-table td { padding: 6px 8px; border-bottom: 1px solid #f2f3fa; color: #414751; }
.cb-table tr.top3 td { background: #f0f7ff; }
.mono { font-family: 'JetBrains Mono', monospace; }
.bold { font-weight: 700; color: #181c21; }
.bt-note { font-size: 11px; color: #9aa1b0; margin: 8px 0 0; line-height: 1.5; }

/* 我的跟踪 */
.tracked-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(480px, 1fr)); gap: 14px; }
.tracked-card { background: white; border: 1px solid #e2e8f0; border-left: 3px solid #005ea1; border-radius: 10px; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.tk-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.tk-title { font-family: 'Work Sans', sans-serif; font-size: 15px; font-weight: 700; color: #181c21; margin: 0 0 4px; }
.tk-sub { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.src-badge.sm { font-size: 10px; padding: 1px 6px; }
.tk-date { font-size: 11px; color: #9aa1b0; }
.tk-remove { border: none; background: transparent; color: #c1c6d7; cursor: pointer; padding: 4px; border-radius: 4px; transition: all 0.15s; }
.tk-remove:hover { background: #ffdad6; color: #ba1a1a; }
.tk-perf-row { display: flex; gap: 14px; flex-wrap: wrap; }
.tk-stat { display: flex; flex-direction: column; gap: 2px; }
.tk-holding { font-size: 12px; color: #414751; background: #f8f9fb; padding: 6px 10px; border-radius: 6px; }
.tk-holding b { color: #005ea1; }
.tk-cb-list { display: flex; gap: 6px; flex-wrap: wrap; }
.tk-cb-chip { font-size: 11px; color: #414751; background: #f2f3fa; padding: 2px 8px; border-radius: 4px; display: inline-flex; gap: 5px; align-items: center; }
.tk-cb-chip .rank { font-style: normal; font-family: 'JetBrains Mono', monospace; font-weight: 700; color: #005ea1; font-size: 10px; }
.tk-cb-chip em { font-style: normal; font-family: 'JetBrains Mono', monospace; color: #585e6c; }
.tk-pending { font-size: 12px; color: #9aa1b0; }
.tk-history { display: flex; align-items: center; gap: 3px; flex-wrap: wrap; }
.hist-dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }

@media (max-width: 900px) {
  .tracked-grid { grid-template-columns: 1fr; }
  .perf-grid { grid-template-columns: repeat(2, 1fr); }
}

/* 我的策略 */
.mine-wrap { display: flex; flex-direction: column; gap: 14px; }
.mine-header { display: flex; justify-content: flex-end; }
.mine-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 14px; }
.mine-card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.mine-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.mine-title { font-family: 'Work Sans', sans-serif; font-size: 15px; font-weight: 700; color: #181c21; margin: 0 0 4px; }
.mine-sub { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mine-active { font-size: 11px; font-weight: 700; color: #16a34a; background: #16a34a15; padding: 2px 8px; border-radius: 4px; }
.mine-inactive { font-size: 11px; font-weight: 700; color: #717782; background: #f2f3fa; padding: 2px 8px; border-radius: 4px; }
.mine-ai { font-size: 11px; font-weight: 700; color: #7c3aed; background: #7c3aed15; padding: 2px 8px; border-radius: 4px; }
.mine-actions { display: flex; gap: 4px; flex-shrink: 0; }
.mine-rules { display: flex; flex-wrap: wrap; gap: 6px; }
.rule-chip { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; background: #f8f9fb; border-radius: 6px; padding: 4px 8px; }
.rule-logic { font-size: 10px; font-weight: 700; color: #9aa1b0; margin-right: 2px; }
.rule-field { font-weight: 700; color: #005ea1; }
.rule-op { color: #717782; font-family: 'JetBrains Mono', monospace; }
.rule-val { font-family: 'JetBrains Mono', monospace; color: #414751; }
.mine-exec { background: #f8f9fb; border-radius: 8px; padding: 10px 12px; }
.mine-exec-title { font-size: 11px; font-weight: 700; color: #717782; margin-bottom: 6px; }
.mine-exec-empty { font-size: 12px; color: #9aa1b0; }
.mine-exec-list { display: flex; flex-wrap: wrap; gap: 4px; }
.mine-exec-item { font-size: 11px; color: #414751; background: white; padding: 2px 8px; border-radius: 4px; border: 1px solid #e2e8f0; }
.mine-exec-more { font-size: 11px; color: #9aa1b0; align-self: center; }

.mine-sort-info { display: flex; gap: 10px; flex-wrap: wrap; font-size: 11px; color: #717782; background: #f0f7ff; border-radius: 6px; padding: 4px 10px; }
.sort-info-item { display: inline-flex; align-items: center; gap: 4px; }

.mine-exec-table-wrap { overflow-x: auto; }
.mine-exec-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.mine-exec-table th { text-align: left; font-size: 10px; font-weight: 700; color: #717782; letter-spacing: 0.05em; padding: 4px 6px; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }
.mine-exec-table td { padding: 4px 6px; border-bottom: 1px solid #f2f3fa; color: #414751; white-space: nowrap; }
.mine-exec-table tbody tr:hover td { background: #f8f9fb; }

.strat-sort-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

/* 策略表单弹窗 */
.strat-form { display: flex; flex-direction: column; gap: 14px; }
.strat-field { display: flex; flex-direction: column; gap: 4px; }
.strat-field label { font-size: 12px; font-weight: 700; color: #585e6c; }
.strat-rules { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.strat-rule-row { display: flex; gap: 6px; align-items: center; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; }
</style>
