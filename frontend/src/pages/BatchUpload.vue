<script setup lang="ts">
import { ref } from 'vue'
import {
  NCard, NTabs, NTabPane, NForm, NFormItem, NInput, NButton, NSpace, NAlert, NText, NCheckbox, useMessage,
} from 'naive-ui'
import { api } from '../utils/api'

defineOptions({ name: 'BatchUpload' })

const message = useMessage()

function localDate(): string {
  const d = new Date()
  const off = d.getTimezoneOffset() * 60000
  return new Date(d.getTime() - off).toISOString().slice(0, 10)
}

type BaseFields = {
  username: string
  account: string
  brokerName: string
  source: string
  terminal: string
  remark: string
}

const base = ref<BaseFields>({
  username: 'trader',
  account: '',
  brokerName: '',
  source: 'manual_batch',
  terminal: '',
  remark: '',
})
const tradeDate = ref(localDate())
const dryRun = ref(false)

const SAMPLES: Record<string, string> = {
  full: JSON.stringify({
    username: 'trader',
    source: 'manual_batch',
    trade_date: localDate(),
    dry_run: 0,
    accounts: [
      {
        account: '666622117166',
        broker_name: '华泰证券',
        holdings: [{ code: '510300', name: '沪深300ETF', type: 'etf', quantity: 10000, cost_price: 3.85 }],
        trades: [],
        orders: [],
        balance: { total_asset: 100000, available: 1000, market_value: 99000 },
        settlements: [],
      },
    ],
  }, null, 2),
  holdings: JSON.stringify([
    { code: '510300', name: '沪深300ETF', type: 'etf', quantity: 10000, cost_price: 3.85, account: '普通' },
  ], null, 2),
  trades: JSON.stringify([
    { code: '510300', name: '沪深300ETF', type: 'etf', direction: 'buy', price: 3.92, quantity: 5000, trade_time: `${localDate()} 09:45:12` },
  ], null, 2),
  orders: JSON.stringify([
    { code: '600519', name: '贵州茅台', type: 'stock', direction: 'sell', price: 1700, quantity: 100, status: '已成', order_time: `${localDate()} 10:10:00` },
  ], null, 2),
  balance: JSON.stringify({
    total_asset: 100000, available: 1200, withdrawable: 1000, market_value: 98800,
    position_profit: 1200, today_profit: 30, today_profit_pct: 0.03,
  }, null, 2),
  settlements: JSON.stringify([
    { code: '510300', name: '沪深300ETF', direction: 'buy', price: 3.92, quantity: 5000, amount: 19600, commission: 5.2 },
  ], null, 2),
}

const raw = ref<Record<string, string>>({ ...SAMPLES })
const loading = ref<Record<string, boolean>>({})
const errors = ref<Record<string, string>>({})
const results = ref<Record<string, any | null>>({})

const KINDS: Array<{ key: string; label: string; field: string; note: string }> = [
  { key: 'holdings', label: '持仓', field: 'holdings', note: '按资金账号覆盖/合并持仓明细；传入空数组会清空该账号持仓。' },
  { key: 'trades', label: '成交', field: 'trades', note: '按 (用户, 交易日) 覆盖写入成交记录，适合券商导出的当日成交。' },
  { key: 'orders', label: '委托', field: 'orders', note: '按交易日写入委托记录；重复上传同一天会覆盖旧数据。' },
  { key: 'balance', label: '资金', field: 'balance', note: '资金余额快照：总资产、可用、市值、当日盈亏等，可传对象或数组。' },
  { key: 'settlements', label: '交割单', field: 'settlements', note: '交割流水：含佣金、印花税、过户费，用于费率反算与做T分析。' },
]

function parse(key: string, expectArray: boolean): any {
  const text = (raw.value[key] || '').trim()
  if (!text) throw new Error('内容不能为空')
  const val = JSON.parse(text)
  if (expectArray && !Array.isArray(val)) throw new Error('必须是 JSON 数组')
  return val
}

function onFile(e: Event, key: string) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    raw.value[key] = String(reader.result || '')
    message.success(`已读取 ${file.name}`)
  }
  reader.readAsText(file, 'utf-8')
  input.value = ''
}

function resetExample(key: string) {
  raw.value[key] = SAMPLES[key] || ''
  errors.value[key] = ''
}

function summary(res: any): string {
  if (!res) return ''
  const t = res.totals || {}
  return `账号 ${res.account_count ?? 1} · 新增 ${t.added ?? 0} · 更新 ${t.updated ?? 0} · 移除 ${t.removed ?? 0} · 删除 ${t.deleted ?? 0} · 写入 ${t.inserted ?? 0} · 失败 ${t.failed ?? 0}`
}

async function submit(key: string) {
  errors.value[key] = ''
  results.value[key] = null
  const b = base.value
  if (!b.username.trim()) { errors.value[key] = '请填写归属用户 username'; return }

  let body: Record<string, unknown>
  try {
    if (key === 'full') {
      body = parse('full', false)
      body.username = body.username || b.username.trim()
      body.trade_date = body.trade_date || tradeDate.value
      body.dry_run = dryRun.value ? 1 : 0
    } else {
      const kind = KINDS.find((k) => k.key === key)!
      const items = parse(key, key !== 'balance')
      body = {
        username: b.username.trim(),
        source: b.source.trim() || 'manual_batch',
        trade_date: tradeDate.value,
        dry_run: dryRun.value ? 1 : 0,
        accounts: [{
          account: b.account.trim(),
          broker_name: b.brokerName.trim() || undefined,
          terminal: b.terminal.trim() || undefined,
          remark: b.remark.trim() || undefined,
          [kind.field]: items,
        }],
      }
      if (!b.account.trim()) { errors.value[key] = '请填写资金账号 account'; return }
    }
  } catch (e: any) {
    errors.value[key] = `JSON 解析失败：${e?.message || e}`
    return
  }

  loading.value[key] = true
  try {
    const res = await api.importExternalBatch(body)
    results.value[key] = res
    message.success(dryRun.value ? '试运行完成，未写入数据库' : '上传完成')
  } catch (e: any) {
    errors.value[key] = `上传失败：${e?.data?.detail || e?.message || '未知错误'}`
  } finally {
    loading.value[key] = false
  }
}
</script>

<template>
  <div class="batch-page">
    <div class="batch-head">
      <div>
        <h1 class="batch-title">批量上传数据</h1>
        <p class="batch-sub">按资金账号批量导入持仓 / 成交 / 委托 / 资金 / 交割单，支持 JSON 粘贴与文件导入</p>
      </div>
    </div>

    <n-card :bordered="false" class="base-card">
      <n-form label-placement="top" size="small">
        <n-space :wrap="true" :size="12" style="width: 100%">
          <n-form-item label="归属用户 username" style="min-width: 180px">
            <n-input v-model:value="base.username" placeholder="trader" clearable />
          </n-form-item>
          <n-form-item label="资金账号 account（单类上传用）" style="min-width: 210px">
            <n-input v-model:value="base.account" placeholder="如 666622117166" clearable />
          </n-form-item>
          <n-form-item label="券商名 broker_name" style="min-width: 170px">
            <n-input v-model:value="base.brokerName" placeholder="如 华泰证券" clearable />
          </n-form-item>
          <n-form-item label="交易日 trade_date" style="min-width: 170px">
            <n-input v-model:value="tradeDate" placeholder="YYYY-MM-DD" clearable />
          </n-form-item>
          <n-form-item label="来源 source" style="min-width: 160px">
            <n-input v-model:value="base.source" placeholder="manual_batch" clearable />
          </n-form-item>
          <n-form-item label="终端 terminal" style="min-width: 150px">
            <n-input v-model:value="base.terminal" placeholder="可选" clearable />
          </n-form-item>
          <n-form-item label="备注 remark" style="min-width: 150px">
            <n-input v-model:value="base.remark" placeholder="可选" clearable />
          </n-form-item>
        </n-space>
      </n-form>
      <n-checkbox v-model:checked="dryRun" style="margin-top: 2px">仅试运行（dry_run，不写库）</n-checkbox>
    </n-card>

    <n-tabs type="line" animated class="upload-tabs">
      <n-tab-pane name="full" tab="全量批量">
        <n-card :bordered="false" title="全量批量上传（多账号 / 五类数据一次提交）">
          <n-alert type="info" :show-icon="true" style="margin-bottom: 14px">
            直接提交 <n-text code>/api/v1/external/batch</n-text> 的完整请求体：可一次带多个
            <n-text code>accounts</n-text>，每个账号可同时带持仓、成交、委托、资金、交割单。省略某类数据 = 不更新该类；传空数组 = 清空该类。
          </n-alert>
          <div class="editor-toolbar">
            <label class="file-btn">
              <n-button size="tiny" quaternary>选择 .json 文件</n-button>
              <input type="file" accept=".json,application/json" hidden @change="onFile($event, 'full')" />
            </label>
            <n-button size="tiny" quaternary @click="resetExample('full')">重置示例</n-button>
          </div>
          <n-input v-model:value="raw.full" type="textarea" class="json-editor" :autosize="{ minRows: 14, maxRows: 30 }" />
          <n-space style="margin-top: 10px">
            <n-button type="primary" :loading="loading.full" @click="submit('full')">提交全量批量</n-button>
          </n-space>
          <n-alert v-if="errors.full" type="error" :show-icon="true" style="margin-top: 12px">{{ errors.full }}</n-alert>
          <div v-if="results.full" class="result-card">
            <n-alert :type="results.full.totals?.failed ? 'warning' : 'success'" :show-icon="true">
              <template #header>上传结果</template>
              {{ summary(results.full) }}
            </n-alert>
            <details class="raw-result">
              <summary>展开完整返回</summary>
              <pre>{{ JSON.stringify(results.full, null, 2) }}</pre>
            </details>
          </div>
        </n-card>
      </n-tab-pane>

      <n-tab-pane v-for="k in KINDS" :key="k.key" :name="k.key" :tab="k.label">
        <n-card :bordered="false" :title="`${k.label}上传（按资金账号）`">
          <n-alert type="info" :show-icon="true" style="margin-bottom: 14px">{{ k.note }}</n-alert>
          <div class="editor-toolbar">
            <label class="file-btn">
              <n-button size="tiny" quaternary>选择 .json 文件</n-button>
              <input type="file" accept=".json,application/json" hidden @change="onFile($event, k.key)" />
            </label>
            <n-button size="tiny" quaternary @click="resetExample(k.key)">重置示例</n-button>
          </div>
          <n-input v-model:value="raw[k.key]" type="textarea" class="json-editor" :autosize="{ minRows: 14, maxRows: 30 }" />
          <n-space style="margin-top: 10px">
            <n-button type="primary" :loading="loading[k.key]" @click="submit(k.key)">提交{{ k.label }}上传</n-button>
          </n-space>
          <n-alert v-if="errors[k.key]" type="error" :show-icon="true" style="margin-top: 12px">{{ errors[k.key] }}</n-alert>
          <div v-if="results[k.key]" class="result-card">
            <n-alert :type="results[k.key].totals?.failed ? 'warning' : 'success'" :show-icon="true">
              <template #header>上传结果</template>
              {{ summary(results[k.key]) }}
            </n-alert>
            <details class="raw-result">
              <summary>展开完整返回</summary>
              <pre>{{ JSON.stringify(results[k.key], null, 2) }}</pre>
            </details>
          </div>
        </n-card>
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<style scoped>
.batch-page { padding: 4px 2px 24px; }
.batch-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 14px; }
.batch-title { font-size: 21px; font-weight: 700; color: var(--text-primary); margin: 0 0 5px; }
.batch-sub { font-size: 13px; color: var(--text-muted); margin: 0; }
.base-card { border-radius: 12px; box-shadow: var(--shadow-card); margin-bottom: 14px; }
.upload-tabs { margin-top: 2px; }
.editor-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.file-btn { display: inline-flex; cursor: pointer; }
.json-editor { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; line-height: 1.55; }
.result-card { margin-top: 12px; }
.raw-result { margin-top: 8px; font-size: 12px; color: var(--text-secondary); }
.raw-result summary { cursor: pointer; }
.raw-result pre {
  margin: 8px 0 0; padding: 10px 12px; max-height: 280px; overflow: auto;
  background: var(--bg-subtle); border-radius: 8px; font-size: 11.5px; line-height: 1.5;
}
</style>
