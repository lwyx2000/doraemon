<script setup lang="ts">
import { ref, computed, reactive, h } from 'vue'
import {
  NButton, NSwitch, NIcon, NModal, NInput, NSelect, NRadioGroup, NRadio, NDropdown,
  useMessage, useDialog,
} from 'naive-ui'
import {
  Add,
  EllipsisVertical,
  PlayOutline,
  CopyOutline,
  CreateOutline,
  TrashOutline,
  AddCircleOutline,
  CloseOutline,
} from '@vicons/ionicons5'
import { mockStrategies } from '../composables/useMockData'
import { useAsyncMock } from '../composables/useApi'
import type { Strategy, StrategyRule } from '../types'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import LoadingState from '../components/LoadingState.vue'
import GlossaryPanel from '../components/GlossaryPanel.vue'
import { getFieldTip } from '../composables/helpContent'

const message = useMessage()
const dialog = useDialog()
const { data: strategies, loading, error, refresh: refetch } = useAsyncMock(mockStrategies)
const activeTab = ref<'all' | 'cb' | 'lof' | 'reit'>('all')

const filteredStrategies = computed(() => {
  if (!strategies.value) return []
  if (activeTab.value === 'all') return strategies.value
  return strategies.value.filter(s => s.target_asset === activeTab.value)
})

function filterByType(type: string) {
  activeTab.value = type as any
}

const tabs = [
  { key: 'all', label: '全部策略' },
  { key: 'cb', label: '可转债' },
  { key: 'lof', label: 'LOF / QDII' },
  { key: 'reit', label: 'REITs' },
]

// ---- 策略创建/编辑弹窗 (PRD 5.1 策略创建器) ----
const showBuilder = ref(false)
const builderMode = ref<'create' | 'edit'>('create')
const editingId = ref<string | null>(null)
const builderForm = reactive<{ name: string; target_asset: Strategy['target_asset']; rules: StrategyRule[] }>({
  name: '',
  target_asset: 'cb',
  rules: [],
})

const fieldOptionsByAsset: Record<string, { label: string; value: string }[]> = {
  cb: [
    { label: '双低值', value: '双低值' },
    { label: '价格', value: '价格' },
    { label: '转股溢价率', value: '转股溢价率' },
    { label: 'YTM', value: 'YTM' },
    { label: '信用评级', value: '信用评级' },
    { label: '剩余年限', value: '剩余年限' },
    { label: '剩余规模', value: '剩余规模' },
    { label: '正股Z-Score', value: '正股Z-Score' },
  ],
  lof: [
    { label: '实时折溢价率', value: '实时折溢价率' },
    { label: '历史折溢价分位数', value: '历史折溢价分位数' },
    { label: '净套利收益率', value: '净套利收益率' },
    { label: '日均成交额', value: '日均成交额' },
    { label: '跟踪误差', value: '跟踪误差' },
  ],
  reit: [
    { label: '分红率', value: '分红率' },
    { label: 'IRR', value: 'IRR' },
    { label: '出租率', value: '出租率' },
    { label: '市价', value: '市价' },
  ],
}

const operatorOptions = [
  { label: '>', value: '>' },
  { label: '<', value: '<' },
  { label: '=', value: '=' },
  { label: '属于', value: '属于' },
  { label: '不属于', value: '不属于' },
]

const logicOptions = [
  { label: 'AND', value: 'AND' },
  { label: 'OR', value: 'OR' },
]

const targetAssetOptions = [
  { label: '可转债', value: 'cb' },
  { label: 'LOF / QDII', value: 'lof' },
  { label: 'REITs', value: 'reit' },
]

let ruleIdCounter = 100

function openBuilderCreate() {
  builderMode.value = 'create'
  editingId.value = null
  builderForm.name = ''
  builderForm.target_asset = 'cb'
  builderForm.rules = [{ id: 'r' + (++ruleIdCounter), field: '价格', operator: '<', value: '120', logic: 'AND' }]
  showBuilder.value = true
}

function openBuilderEdit(strategy: Strategy) {
  builderMode.value = 'edit'
  editingId.value = strategy.id
  builderForm.name = strategy.name
  builderForm.target_asset = strategy.target_asset
  builderForm.rules = strategy.rules.map(r => ({ ...r }))
  showBuilder.value = true
}

function addRule() {
  builderForm.rules.push({
    id: 'r' + (++ruleIdCounter),
    field: fieldOptionsByAsset[builderForm.target_asset][0].value,
    operator: '<', value: '', logic: 'AND',
  })
}

function removeRule(idx: number) {
  builderForm.rules.splice(idx, 1)
}

function saveStrategy() {
  if (!builderForm.name.trim()) { message.warning('请输入策略名称'); return }
  if (builderForm.rules.length === 0) { message.warning('请至少添加一条规则'); return }
  if (!strategies.value) return
  const today = new Date().toISOString().slice(0, 10)
  if (builderMode.value === 'edit' && editingId.value) {
    const idx = strategies.value.findIndex(s => s.id === editingId.value)
    if (idx > -1) {
      strategies.value[idx] = {
        ...strategies.value[idx],
        name: builderForm.name.trim(),
        target_asset: builderForm.target_asset,
        rules: builderForm.rules.map(r => ({ ...r })),
      }
      message.success(`已更新: ${builderForm.name}`)
    }
  } else {
    strategies.value.push({
      id: String(Date.now()),
      name: builderForm.name.trim(),
      target_asset: builderForm.target_asset,
      rules: builderForm.rules.map(r => ({ ...r })),
      active: true,
      createdAt: today,
    })
    message.success(`已创建: ${builderForm.name}`)
  }
  showBuilder.value = false
}

// ---- 策略模板库弹窗 (PRD 5.1.3) ----
const showTemplates = ref(false)
const strategyTemplates: Array<{ name: string; target_asset: Strategy['target_asset']; desc: string; rules: StrategyRule[] }> = [
  { name: '经典双低轮动', target_asset: 'cb', desc: '价格<120 且 转股溢价率<20% 的双低策略', rules: [
    { id: 'tr1', field: '价格', operator: '<', value: '120', logic: 'AND' },
    { id: 'tr2', field: '转股溢价率', operator: '<', value: '20', logic: 'AND' },
  ]},
  { name: 'QDII溢价套利', target_asset: 'lof', desc: '折溢价率>3% 且 净套利收益>1.5%', rules: [
    { id: 'tr3', field: '实时折溢价率', operator: '>', value: '3', logic: 'AND' },
    { id: 'tr4', field: '净套利收益率', operator: '>', value: '1.5', logic: 'AND' },
  ]},
  { name: '高分红REITs筛选', target_asset: 'reit', desc: '分红率>5% 且 出租率>85%', rules: [
    { id: 'tr5', field: '分红率', operator: '>', value: '5', logic: 'AND' },
    { id: 'tr6', field: '出租率', operator: '>', value: '85', logic: 'AND' },
  ]},
  { name: '低估值宽基定投', target_asset: 'lof', desc: 'PE分位数<20% 且 跟踪误差<0.5%', rules: [
    { id: 'tr7', field: '历史折溢价分位数', operator: '<', value: '20', logic: 'AND' },
    { id: 'tr8', field: '跟踪误差', operator: '<', value: '0.5', logic: 'AND' },
  ]},
]

function importTemplate(tpl: typeof strategyTemplates[0]) {
  if (!strategies.value) return
  strategies.value.push({
    id: String(Date.now()),
    name: tpl.name + ' (副本)',
    target_asset: tpl.target_asset,
    rules: tpl.rules.map(r => ({ ...r, id: 'r' + (++ruleIdCounter) })),
    active: false,
    createdAt: new Date().toISOString().slice(0, 10),
  })
  message.success(`已导入: ${tpl.name}`)
  showTemplates.value = false
}

// ---- 卡片操作 ----
function cloneStrategy(strategy: Strategy) {
  if (!strategies.value) return
  strategies.value.push({
    ...strategy,
    id: String(Date.now()),
    name: strategy.name + ' (副本)',
    rules: strategy.rules.map(r => ({ ...r, id: 'r' + (++ruleIdCounter) })),
    active: false,
    createdAt: new Date().toISOString().slice(0, 10),
  })
  message.success(`已克隆: ${strategy.name}`)
}

function deleteStrategy(strategy: Strategy) {
  dialog.warning({
    title: '删除策略',
    content: `确定删除「${strategy.name}」吗？此操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => {
      if (!strategies.value) return
      const idx = strategies.value.findIndex(s => s.id === strategy.id)
      if (idx > -1) {
        strategies.value.splice(idx, 1)
        message.success(`已删除: ${strategy.name}`)
      }
    },
  })
}

function toggleStrategy(strategy: Strategy) {
  strategy.active = !strategy.active
  message.success(`${strategy.name}: ${strategy.active ? '已启用' : '已暂停'}`)
}

function runBacktest(strategy: Strategy) {
  message.success(`「${strategy.name}」回测已提交，请稍候查看结果`)
}

// 批量操作下拉菜单
const batchOptions = [
  { label: '全部启用', key: 'enable-all' },
  { label: '全部暂停', key: 'pause-all' },
  { label: '批量回测', key: 'backtest-all' },
  { label: '删除已暂停', key: 'delete-paused' },
]
function handleBatchAction(key: string) {
  if (!strategies.value) return
  if (key === 'enable-all') {
    strategies.value.forEach(s => (s.active = true))
    message.success(`已启用全部 ${strategies.value.length} 个策略`)
  } else if (key === 'pause-all') {
    strategies.value.forEach(s => (s.active = false))
    message.success(`已暂停全部 ${strategies.value.length} 个策略`)
  } else if (key === 'backtest-all') {
    message.success(`已提交 ${strategies.value.length} 个策略的批量回测`)
  } else if (key === 'delete-paused') {
    const paused = strategies.value.filter(s => !s.active)
    if (paused.length === 0) {
      message.info('没有已暂停的策略')
      return
    }
    dialog.warning({
      title: '删除已暂停策略',
      content: `确定删除 ${paused.length} 个已暂停的策略吗？`,
      positiveText: '删除',
      negativeText: '取消',
      onPositiveClick: () => {
        strategies.value = strategies.value!.filter(s => s.active)
        message.success(`已删除 ${paused.length} 个已暂停策略`)
      },
    })
  }
}

const targetLabels: Record<string, string> = {
  cb: '可转债',
  lof: 'LOF / QDII 基金',
  reit: 'REITs',
}

const targetColors: Record<string, string> = {
  cb: '#005ea1',
  lof: '#864f00',
  reit: '#16a34a',
}
</script>

<template>
  <LoadingState
    :loading="loading"
    :error="error"
    :min-height="520"
    text="正在加载策略数据..."
    @retry="refetch"
  >
    <div v-if="strategies" class="strategy-page">
    <!-- Page Header -->
    <PageHeader title="策略管理中心" subtitle="量化策略管理与回测 — 创建、测试和部署你的投资策略" help-key="strategyCenter">
      <template #actions>
        <n-button size="small" @click="showTemplates = true">导入</n-button>
        <n-button size="small" type="primary" @click="openBuilderCreate">
          <template #icon><n-icon :component="Add" /></template>
          新建策略
        </n-button>
      </template>
    </PageHeader>

    <GlossaryPanel page-key="strategyCenter" />

    <!-- Summary Stats -->
    <div class="stat-grid">
      <StatCard label="策略总数" :value="strategies?.length ?? 0" />
      <StatCard label="运行中" :value="strategies?.filter(s => s.active).length ?? 0" color="#16a34a" />
      <StatCard label="已暂停" :value="strategies?.filter(s => !s.active).length ?? 0" color="#f97316" />
      <StatCard label="回测胜率" value="72.4%" sub="全部运行中策略平均" color="#005ea1" :tip="getFieldTip('win_rate')" />
    </div>

    <!-- Tab Bar -->
    <div class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :class="['tab-btn', { active: activeTab === tab.key }]"
        @click="filterByType(tab.key)"
      >
        {{ tab.label }}
      </button>
      <div class="tab-spacer" />
      <n-dropdown :options="batchOptions" trigger="click" @select="handleBatchAction">
        <button class="tab-action" aria-label="批量操作">
          <n-icon :component="EllipsisVertical" size="16" />
        </button>
      </n-dropdown>
    </div>

    <!-- Strategy Cards -->
    <div class="strategy-grid">
      <div
        v-for="strategy in filteredStrategies"
        :key="strategy.id"
        :class="['strategy-card', { active: strategy.active }]"
      >
        <div class="card-top">
          <div class="card-title-row">
            <h3 class="card-title">{{ strategy.name }}</h3>
            <n-switch :value="strategy.active" size="small" @update:value="() => toggleStrategy(strategy)" />
          </div>
          <span class="card-target" :style="{ background: targetColors[strategy.target_asset] + '20', color: targetColors[strategy.target_asset], border: '1px solid ' + targetColors[strategy.target_asset] + '40' }">
            {{ targetLabels[strategy.target_asset] }}
          </span>
        </div>

        <div class="card-rules">
          <div v-for="rule in strategy.rules" :key="rule.id" class="rule-chip">
            <span class="rule-field">{{ rule.field }}</span>
            <span class="rule-operator">{{ rule.operator }}</span>
            <span class="rule-value">{{ rule.value }}</span>
          </div>
        </div>

        <div class="card-meta">
          <span class="meta-created">创建时间: {{ strategy.createdAt }}</span>
        </div>

        <div class="card-actions">
          <button class="card-btn" @click="runBacktest(strategy)">
            <n-icon :component="PlayOutline" size="14" />
            回测
          </button>
          <button class="card-btn" @click="cloneStrategy(strategy)">
            <n-icon :component="CopyOutline" size="14" />
            克隆
          </button>
          <button class="card-btn" @click="openBuilderEdit(strategy)">
            <n-icon :component="CreateOutline" size="14" />
            编辑
          </button>
          <button class="card-btn delete" aria-label="删除策略" @click="deleteStrategy(strategy)">
            <n-icon :component="TrashOutline" size="14" />
          </button>
        </div>
      </div>

      <!-- Empty create card -->
      <div class="create-card" @click="openBuilderCreate">
        <n-icon :component="AddCircleOutline" size="32" />
        <span class="create-text">创建新策略</span>
        <span class="create-sub">定义规则、设置条件、部署到生产环境</span>
      </div>
    </div>

    <!-- Backtest Results / Performance -->
    <div class="bottom-grid">
      <div class="perf-panel">
        <h4>回测表现</h4>
        <div class="perf-chart">
          <div class="perf-bars">
            <div v-for="(p, i) in [12.4, 8.2, 15.1, 5.8, 10.5, 18.2]" :key="i" class="perf-bar-group">
              <div class="perf-bar" :style="{ height: p * 5 + 'px', background: p >= 10 ? '#16a34a' : '#f97316' }" />
              <span class="perf-label">{{ ['CB','LOF','REIT','QDII','CLS','IDX'][i] }}</span>
            </div>
          </div>
        </div>
        <div class="perf-stats">
          <div class="perf-stat"><span class="ps-label">SHARPE</span><span class="ps-value">1.84</span></div>
          <div class="perf-stat"><span class="ps-label">最大回撤</span><span class="ps-value" style="color:#ba1a1a">-6.2%</span></div>
          <div class="perf-stat"><span class="ps-label">CALMAR</span><span class="ps-value">2.15</span></div>
        </div>
      </div>
      <div class="log-panel">
        <h4>执行日志</h4>
        <div class="log-list">
          <div class="log-item"><span class="log-time">14:22:05</span><span class="log-msg">双低策略完成扫描，发现 3 个匹配标的</span></div>
          <div class="log-item"><span class="log-time">14:15:00</span><span class="log-msg">QDII 套利策略: 161129.SZ 触发预警</span></div>
          <div class="log-item"><span class="log-time">13:45:12</span><span class="log-msg">REITs 筛选策略: 新增华安张江至候选列表</span></div>
          <div class="log-item"><span class="log-time">11:30:00</span><span class="log-msg">双低策略轮动: 卖出 AlphaLogic, 买入 SolarEnergy</span></div>
        </div>
      </div>
    </div>

    <!-- 策略创建/编辑弹窗 (PRD 5.1) -->
    <n-modal v-model:show="showBuilder" preset="card" :title="builderMode === 'create' ? '新建策略' : '编辑策略'" style="width: 640px; max-width: 92vw;" :bordered="false">
      <div class="builder-body">
        <div class="builder-field">
          <label class="builder-label">策略名称</label>
          <n-input v-model:value="builderForm.name" placeholder="例如：双低可转债轮动策略" />
        </div>
        <div class="builder-field">
          <label class="builder-label">目标资产</label>
          <n-radio-group v-model:value="builderForm.target_asset">
            <n-radio v-for="opt in targetAssetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</n-radio>
          </n-radio-group>
        </div>
        <div class="builder-field">
          <label class="builder-label">规则配置（逻辑生成器）</label>
          <div class="rule-list">
            <div v-for="(rule, idx) in builderForm.rules" :key="rule.id" class="rule-row">
              <n-select v-if="idx > 0" v-model:value="rule.logic" :options="logicOptions" size="small" style="width: 88px; flex-shrink: 0;" />
              <div v-else class="rule-logic-placeholder">IF</div>
              <n-select v-model:value="rule.field" :options="fieldOptionsByAsset[builderForm.target_asset]" size="small" style="width: 150px; flex-shrink: 0;" />
              <n-select v-model:value="rule.operator" :options="operatorOptions" size="small" style="width: 96px; flex-shrink: 0;" />
              <n-input v-model:value="rule.value" size="small" placeholder="阈值" style="flex: 1;" />
              <button class="rule-remove" aria-label="删除规则" @click="removeRule(idx)"><n-icon :component="CloseOutline" size="14" /></button>
            </div>
          </div>
          <n-button size="small" dashed block @click="addRule" style="margin-top: 8px;">
            <template #icon><n-icon :component="AddCircleOutline" /></template>
            添加条件
          </n-button>
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px;">
          <n-button size="small" @click="showBuilder = false">取消</n-button>
          <n-button size="small" type="primary" @click="saveStrategy">保存策略</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 策略模板库弹窗 (PRD 5.1.3) -->
    <n-modal v-model:show="showTemplates" preset="card" title="策略模板库" style="width: 560px; max-width: 92vw;" :bordered="false">
      <div class="template-list">
        <div v-for="tpl in strategyTemplates" :key="tpl.name" class="template-card">
          <div class="template-info">
            <div class="template-name">
              <span class="template-target" :style="{ background: targetColors[tpl.target_asset] + '20', color: targetColors[tpl.target_asset] }">{{ targetLabels[tpl.target_asset] }}</span>
              {{ tpl.name }}
            </div>
            <div class="template-desc">{{ tpl.desc }}</div>
            <div class="template-rules">
              <span v-for="r in tpl.rules" :key="r.id" class="tpl-rule-chip">{{ r.field }} {{ r.operator }} {{ r.value }}</span>
            </div>
          </div>
          <n-button size="small" type="primary" @click="importTemplate(tpl)">导入</n-button>
        </div>
      </div>
    </n-modal>
    </div>
  </LoadingState>
</template>

<style scoped>
.strategy-page { display: flex; flex-direction: column; gap: 12px; }

/* Tab Bar */
.tab-bar { display: flex; align-items: center; gap: 4px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 4px; }
.tab-btn { padding: 6px 16px; border: none; background: transparent; border-radius: 6px; cursor: pointer; font-family: 'Work Sans', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: #717782; transition: all 0.15s; }
.tab-btn:hover { background: #f2f3fa; color: #181c21; }
.tab-btn.active { background: #005ea1; color: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.tab-spacer { flex: 1; }
.tab-action { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border: none; background: transparent; border-radius: 6px; cursor: pointer; color: #717782; transition: all 0.15s; }
.tab-action:hover { background: #f2f3fa; }

/* Strategy Cards Grid */
.strategy-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 12px; }

.strategy-card {
  background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px;
  display: flex; flex-direction: column; gap: 12px; transition: all 0.2s;
}
.strategy-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); border-color: #c1c6d7; }
.strategy-card.active { border-left: 3px solid #16a34a; }

.card-top { display: flex; flex-direction: column; gap: 8px; }
.card-title-row { display: flex; justify-content: space-between; align-items: center; }
.card-title { font-family: 'Work Sans', sans-serif; font-size: 14px; font-weight: 600; color: #181c21; margin: 0; }
.card-target { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; align-self: flex-start; }

.card-rules { display: flex; flex-wrap: wrap; gap: 4px; }
.rule-chip { display: flex; align-items: center; gap: 4px; padding: 2px 8px; background: #f2f3fa; border-radius: 4px; font-size: 11px; }
.rule-field { color: #585e6c; font-weight: 600; }
.rule-operator { color: #005ea1; font-weight: 700; }
.rule-value { font-family: 'JetBrains Mono', monospace; color: #181c21; font-weight: 600; }

.card-meta { font-size: 11px; color: #717782; }
.card-actions { display: flex; gap: 4px; margin-top: auto; padding-top: 8px; border-top: 1px solid #f2f3fa; }

.card-btn { display: flex; align-items: center; gap: 4px; padding: 4px 10px; border: 1px solid #e2e8f0; border-radius: 4px; background: white; cursor: pointer; font-size: 10px; font-weight: 700; color: #585e6c; transition: all 0.15s; }
.card-btn:hover { background: #f2f3fa; border-color: #c1c6d7; color: #181c21; }
.card-btn .n-icon { font-size: 14px; }
.card-btn.delete:hover { background: #ffdad6; border-color: #ba1a1a; color: #ba1a1a; }

.create-card {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 32px; border: 2px dashed #e2e8f0; border-radius: 8px;
  background: white; cursor: pointer; transition: all 0.2s; min-height: 180px;
}
.create-card:hover { border-color: #005ea1; background: #f8f9ff; }
.create-card .n-icon { color: #c1c6d7; transition: color 0.2s; }
.create-card:hover .n-icon { color: #005ea1; }
.create-text { font-size: 14px; font-weight: 700; color: #717782; transition: color 0.2s; }
.create-card:hover .create-text { color: #005ea1; }
.create-sub { font-size: 11px; color: #c1c6d7; text-align: center; }

/* Bottom Grid */
.bottom-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; height: 200px; }
.perf-panel { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; display: flex; flex-direction: column; }
.perf-panel h4, .log-panel h4 { font-family: 'Work Sans', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: #717782; margin: 0 0 12px; }

.perf-chart { flex: 1; display: flex; align-items: flex-end; }
.perf-bars { display: flex; align-items: flex-end; gap: 16px; width: 100%; height: 100px; }
.perf-bar-group { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; height: 100%; justify-content: flex-end; }
.perf-bar { width: 100%; border-radius: 4px 4px 0 0; min-height: 4px; transition: height 0.3s; }
.perf-label { font-size: 9px; font-weight: 700; color: #717782; letter-spacing: 0.05em; }

.perf-stats { display: flex; gap: 12px; margin-top: 8px; }
.perf-stat { flex: 1; text-align: center; }
.ps-label { display: block; font-size: 9px; font-weight: 700; color: #717782; letter-spacing: 0.05em; }
.ps-value { font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; color: #181c21; }

.log-panel { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; display: flex; flex-direction: column; overflow: hidden; }
.log-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
.log-item { display: flex; gap: 12px; align-items: flex-start; font-size: 12px; }
.log-time { font-family: 'JetBrains Mono', monospace; color: #717782; white-space: nowrap; font-size: 11px; flex-shrink: 0; margin-top: 1px; }
.log-msg { color: #414751; line-height: 1.4; }

/* 策略创建器弹窗 */
.builder-body { display: flex; flex-direction: column; gap: 16px; }
.builder-field { display: flex; flex-direction: column; gap: 6px; }
.builder-label { font-family: 'Work Sans', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: #585e6c; }
.rule-list { display: flex; flex-direction: column; gap: 6px; }
.rule-row { display: flex; align-items: center; gap: 6px; }
.rule-logic-placeholder { width: 88px; flex-shrink: 0; text-align: center; font-size: 10px; font-weight: 700; color: #005ea1; font-family: 'JetBrains Mono', monospace; }
.rule-remove { display: flex; align-items: center; justify-content: center; width: 26px; height: 26px; border: none; background: transparent; border-radius: 4px; cursor: pointer; color: #c1c6d7; flex-shrink: 0; transition: all 0.15s; }
.rule-remove:hover { background: #ffdad6; color: #ba1a1a; }

/* 模板库弹窗 */
.template-list { display: flex; flex-direction: column; gap: 10px; }
.template-card { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px; border: 1px solid #e2e8f0; border-radius: 8px; transition: all 0.15s; }
.template-card:hover { border-color: #005ea1; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
.template-info { flex: 1; min-width: 0; }
.template-name { font-family: 'Work Sans', sans-serif; font-size: 14px; font-weight: 600; color: #181c21; display: flex; align-items: center; gap: 8px; }
.template-target { padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; }
.template-desc { font-size: 12px; color: #717782; margin: 4px 0; }
.template-rules { display: flex; flex-wrap: wrap; gap: 4px; }
.tpl-rule-chip { padding: 1px 6px; background: #f2f3fa; border-radius: 4px; font-size: 10px; color: #585e6c; font-family: 'JetBrains Mono', monospace; }

/* Responsive: collapse multi-column grids on smaller screens */
@media (max-width: 1280px) {
  .strategy-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .strategy-grid { grid-template-columns: 1fr; }
  .bottom-grid { grid-template-columns: 1fr; height: auto; }
  .tab-bar { flex-wrap: wrap; }
  .rule-row { flex-wrap: wrap; }
}
</style>
