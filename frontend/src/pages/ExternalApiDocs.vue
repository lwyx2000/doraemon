<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NTabs, NTabPane, NForm, NFormItem, NInput, NButton, NSpace, NAlert, NDivider, NText, useMessage,
} from 'naive-ui'
import MdRenderer from '../components/MdRenderer.vue'
import { api } from '../utils/api'
// 直接引用项目 docs 目录下的权威文档（Vite ?raw 导入，无需额外依赖，单一信息源）
import docSource from '../../../docs/external_upload_api.md?raw'

defineOptions({ name: 'ExternalApiDocs' })

const router = useRouter()
const message = useMessage()

const SAMPLE_HOLDINGS = `[
  { "code": "510300", "name": "沪深300ETF", "type": "etf", "account": "普通", "quantity": 10000, "cost_price": 3.85, "open_date": "2026-01-05", "currency": "CNY" },
  { "code": "600519", "name": "贵州茅台", "type": "stock", "account": "普通", "quantity": 100, "cost_price": 1680.0 }
]`

const SAMPLE_TRADES = `[
  { "code": "510300", "name": "沪深300ETF", "type": "etf", "account": "普通", "direction": "buy", "price": 3.92, "quantity": 5000, "trade_time": "2026-10-28 09:45:12" },
  { "code": "600519", "name": "贵州茅台", "type": "stock", "account": "普通", "direction": "sell", "price": 1700.5, "quantity": 100, "fee": 15.2, "trade_time": "2026-10-28 14:30:08" }
]`

// ---------- 公共字段 ----------
type BaseFields = {
  username: string
  source: string
  account: string
  brokerName: string
  remark: string
  terminal: string
}

function parseItems(raw: string): Array<Record<string, unknown>> {
  const v = raw.trim()
  if (!v) throw new Error('items 不能为空')
  const parsed = JSON.parse(v)
  if (!Array.isArray(parsed)) throw new Error('items 必须是 JSON 数组')
  return parsed as Array<Record<string, unknown>>
}

// ---------- 持仓导入 ----------
const hBase = ref<BaseFields>({ username: '', source: 'my_bot', account: '', brokerName: '', remark: '', terminal: '' })
const hItems = ref(SAMPLE_HOLDINGS)
const hLoading = ref(false)
const hResult = ref<{ added: number; updated: number; failed: Array<{ index: number; code: string; reason: string }> } | null>(null)
const hError = ref('')

async function submitHoldings() {
  hResult.value = null
  hError.value = ''
  const b = hBase.value
  if (!b.username.trim()) { hError.value = '请填写 username（归属用户）'; return }
  if (!b.account.trim()) { hError.value = '请填写 account（券商账号主标识，客户端自传）'; return }
  let items: Array<Record<string, unknown>>
  try {
    items = parseItems(hItems.value)
  } catch (e: any) {
    hError.value = 'items JSON 解析失败：' + (e?.message || e)
    return
  }
  hLoading.value = true
  try {
    const res = await api.importHoldingsApi({
      username: b.username.trim(),
      source: b.source.trim() || 'api',
      account: b.account.trim(),
      broker_name: b.brokerName.trim() || undefined,
      remark: b.remark.trim() || undefined,
      terminal: b.terminal.trim() || undefined,
      items,
    })
    hResult.value = res
    message.success(`持仓导入完成：新增 ${res.added}，更新 ${res.updated}，失败 ${res.failed.length}`)
  } catch (e: any) {
    hError.value = '导入失败：' + (e?.data?.detail || e?.message || '未知错误')
  } finally {
    hLoading.value = false
  }
}

// ---------- 成交导入 ----------
const tBase = ref<BaseFields>({ username: '', source: 'my_bot', account: '', brokerName: '', remark: '', terminal: '' })
const tTradeDate = ref('')
const tItems = ref(SAMPLE_TRADES)
const tLoading = ref(false)
const tResult = ref<{ deleted: number; inserted: number; failed: Array<{ index: number; code: string; reason: string }> } | null>(null)
const tError = ref('')

async function submitTrades() {
  tResult.value = null
  tError.value = ''
  const b = tBase.value
  if (!b.username.trim()) { tError.value = '请填写 username（归属用户）'; return }
  if (!b.account.trim()) { tError.value = '请填写 account（券商账号主标识，客户端自传）'; return }
  if (!tTradeDate.value.trim()) { tError.value = '请填写 trade_date（格式 YYYY-MM-DD）'; return }
  let items: Array<Record<string, unknown>>
  try {
    items = parseItems(tItems.value)
  } catch (e: any) {
    tError.value = 'items JSON 解析失败：' + (e?.message || e)
    return
  }
  tLoading.value = true
  try {
    const res = await api.importTrades({
      username: b.username.trim(),
      source: b.source.trim() || 'api',
      account: b.account.trim(),
      broker_name: b.brokerName.trim() || undefined,
      remark: b.remark.trim() || undefined,
      terminal: b.terminal.trim() || undefined,
      trade_date: tTradeDate.value.trim(),
      items,
    })
    tResult.value = res
    message.success(`成交导入完成：删除 ${res.deleted}，写入 ${res.inserted}，失败 ${res.failed.length}`)
  } catch (e: any) {
    tError.value = '导入失败：' + (e?.data?.detail || e?.message || '未知错误')
  } finally {
    tLoading.value = false
  }
}
</script>

<template>
  <div class="ext-wrap">
    <div class="ext-inner">
      <header class="ext-head">
        <div>
          <h1 class="ext-title">持仓 / 成交 外部上传接口</h1>
          <p class="ext-sub">无鉴权（机器 / 程序）批量上传接口文档与在线试用页</p>
        </div>
        <n-space>
          <n-button quaternary @click="router.push('/login')">前往登录</n-button>
        </n-space>
      </header>

      <n-tabs type="line" animated>
        <n-tab-pane name="docs" tab="接口文档">
          <n-card :bordered="false" class="doc-card">
            <MdRenderer :source="docSource" />
          </n-card>
        </n-tab-pane>

        <n-tab-pane name="holdings" tab="持仓在线导入">
          <n-card :bordered="false" title="持仓上传（增量合并）">
            <n-alert type="info" :show-icon="true" style="margin-bottom: 16px">
              无需登录。按 <n-text code>code + type + account</n-text> 去重：已存在则覆盖更新，新增则插入；
              旧行自动归档到历史表留痕。<n-text code>account</n-text> 为券商账号主标识（客户端自传），
              命中已有券商则复用，否则按 <n-text code>broker_name</n-text> 自动建券商并挂到指定终端（缺省自动建默认终端）。
            </n-alert>
            <n-form label-placement="top">
              <n-space vertical :size="12">
                <n-form-item label="username（归属用户，必填）">
                  <n-input v-model:value="hBase.username" placeholder="如 sos" clearable />
                </n-form-item>
                <n-space :wrap="true" :size="12" style="width: 100%">
                  <n-form-item label="account（券商账号主标识，必填）" style="flex: 1 1 220px">
                    <n-input v-model:value="hBase.account" placeholder="如 HUAXIA-12345678" clearable />
                  </n-form-item>
                  <n-form-item label="broker_name（券商名，可选）" style="flex: 1 1 220px">
                    <n-input v-model:value="hBase.brokerName" placeholder="如 华泰证券" clearable />
                  </n-form-item>
                  <n-form-item label="terminal（终端名，可选）" style="flex: 1 1 220px">
                    <n-input v-model:value="hBase.terminal" placeholder="如 主终端" clearable />
                  </n-form-item>
                  <n-form-item label="remark（备注，可选）" style="flex: 1 1 220px">
                    <n-input v-model:value="hBase.remark" placeholder="如 自动化脚本" clearable />
                  </n-form-item>
                  <n-form-item label="source（来源标记，可选）" style="flex: 1 1 220px">
                    <n-input v-model:value="hBase.source" placeholder="my_bot" clearable />
                  </n-form-item>
                </n-space>
                <n-form-item label="items（每行一条持仓，JSON 数组）">
                  <n-input
                    v-model:value="hItems"
                    type="textarea"
                    :autosize="{ minRows: 8, maxRows: 20 }"
                    placeholder="粘贴 JSON 数组"
                  />
                </n-form-item>
              </n-space>
            </n-form>
            <n-space style="margin-top: 8px">
              <n-button type="primary" :loading="hLoading" @click="submitHoldings">提交持仓导入</n-button>
            </n-space>
            <n-alert v-if="hError" type="error" :show-icon="true" style="margin-top: 14px">{{ hError }}</n-alert>
            <n-alert
              v-if="hResult"
              :type="hResult.failed.length ? 'warning' : 'success'"
              :show-icon="true"
              style="margin-top: 14px"
            >
              <template #header>导入结果</template>
              新增 <n-text strong>{{ hResult.added }}</n-text> · 更新 <n-text strong>{{ hResult.updated }}</n-text>
              · 失败 <n-text strong>{{ hResult.failed.length }}</n-text>
              <template v-if="hResult.failed.length">
                <n-divider style="margin: 8px 0" />
                <ul class="fail-list">
                  <li v-for="(f, i) in hResult.failed" :key="i">
                    #{{ f.index }} <n-text code>{{ f.code }}</n-text> — {{ f.reason }}
                  </li>
                </ul>
              </template>
            </n-alert>
          </n-card>
        </n-tab-pane>

        <n-tab-pane name="trades" tab="成交在线导入">
          <n-card :bordered="false" title="成交上传（按交易日覆盖）">
            <n-alert type="info" :show-icon="true" style="margin-bottom: 16px">
              无需登录。按 <n-text code>(user, trade_date)</n-text> 维度：先删除该用户该日全部旧记录，再全量写入；
              新交易日直接新增，互不干扰。<n-text code>account</n-text> 为券商账号主标识（客户端自传）。
            </n-alert>
            <n-form label-placement="top">
              <n-space vertical :size="12">
                <n-form-item label="username（归属用户，必填）">
                  <n-input v-model:value="tBase.username" placeholder="如 sos" clearable />
                </n-form-item>
                <n-space :wrap="true" :size="12" style="width: 100%">
                  <n-form-item label="account（券商账号主标识，必填）" style="flex: 1 1 220px">
                    <n-input v-model:value="tBase.account" placeholder="如 HUAXIA-12345678" clearable />
                  </n-form-item>
                  <n-form-item label="trade_date（交易日，必填）" style="flex: 1 1 220px">
                    <n-input v-model:value="tTradeDate" placeholder="2026-10-28" clearable />
                  </n-form-item>
                  <n-form-item label="broker_name（券商名，可选）" style="flex: 1 1 220px">
                    <n-input v-model:value="tBase.brokerName" placeholder="如 华泰证券" clearable />
                  </n-form-item>
                  <n-form-item label="terminal（终端名，可选）" style="flex: 1 1 220px">
                    <n-input v-model:value="tBase.terminal" placeholder="如 主终端" clearable />
                  </n-form-item>
                  <n-form-item label="remark（备注，可选）" style="flex: 1 1 220px">
                    <n-input v-model:value="tBase.remark" placeholder="如 自动化脚本" clearable />
                  </n-form-item>
                  <n-form-item label="source（来源标记，可选）" style="flex: 1 1 220px">
                    <n-input v-model:value="tBase.source" placeholder="my_bot" clearable />
                  </n-form-item>
                </n-space>
                <n-form-item label="items（每行一条成交，JSON 数组）">
                  <n-input
                    v-model:value="tItems"
                    type="textarea"
                    :autosize="{ minRows: 8, maxRows: 20 }"
                    placeholder="粘贴 JSON 数组"
                  />
                </n-form-item>
              </n-space>
            </n-form>
            <n-space style="margin-top: 8px">
              <n-button type="primary" :loading="tLoading" @click="submitTrades">提交成交导入</n-button>
            </n-space>
            <n-alert v-if="tError" type="error" :show-icon="true" style="margin-top: 14px">{{ tError }}</n-alert>
            <n-alert
              v-if="tResult"
              :type="tResult.failed.length ? 'warning' : 'success'"
              :show-icon="true"
              style="margin-top: 14px"
            >
              <template #header>导入结果</template>
              删除 <n-text strong>{{ tResult.deleted }}</n-text> · 写入 <n-text strong>{{ tResult.inserted }}</n-text>
              · 失败 <n-text strong>{{ tResult.failed.length }}</n-text>
              <template v-if="tResult.failed.length">
                <n-divider style="margin: 8px 0" />
                <ul class="fail-list">
                  <li v-for="(f, i) in tResult.failed" :key="i">
                    #{{ f.index }} <n-text code>{{ f.code }}</n-text> — {{ f.reason }}
                  </li>
                </ul>
              </template>
            </n-alert>
          </n-card>
        </n-tab-pane>
      </n-tabs>
    </div>
  </div>
</template>

<style scoped>
.ext-wrap {
  min-height: 100vh;
  background: var(--bg-subtle);
  padding: 28px 16px 48px;
}
.ext-inner {
  max-width: 980px;
  margin: 0 auto;
}
.ext-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.ext-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 4px;
}
.ext-sub {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}
.doc-card {
  border-radius: 12px;
  box-shadow: var(--shadow-card);
}
.fail-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
