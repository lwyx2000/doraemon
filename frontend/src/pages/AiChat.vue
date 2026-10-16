<script setup lang="ts">
/**
 * AI 问答页 — 基于知识库（backend/knowledge/）+ 各页面真实数据的 RAG 式问答。
 * 上下文可选：宏观看板 / 贪婪恐惧（后端实时组装）；知识库检索由后端按问题关键词完成。
 * 流式 SSE；无渠道时展示配置引导。
 */
import { ref, computed, nextTick, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NSpace, NSelect, NSpin, NIcon } from 'naive-ui'
import { SendOutline, StopCircleOutline, SettingsOutline, SparklesOutline } from '@vicons/ionicons5'
import { api } from '../utils/api'
import PageHeader from '../components/PageHeader.vue'
import MdRenderer from '../components/MdRenderer.vue'
import type { AiStreamMeta } from '../types'

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  docs?: Array<{ id?: string; title?: string }>
  dataTime?: string
}

const router = useRouter()

const contextOptions = [
  { label: '不附带页面数据', value: '' },
  { label: '宏观看板（实时数据）', value: 'dashboard' },
  { label: '贪婪恐惧指数（实时数据）', value: 'fear_greed' },
]
const contextType = ref<string>('')

const messages = ref<ChatMsg[]>([])
const input = ref('')
const streaming = ref(false)
const streamText = ref('')
const streamDocs = ref<Array<{ id?: string; title?: string }>>([])
const streamDataTime = ref('')
const errorObj = ref<{ code: string; message: string } | null>(null)
let abort: AbortController | null = null
const scrollBox = ref<HTMLElement | null>(null)

const canSend = computed(() => input.value.trim().length > 0 && !streaming.value)

const SUGGESTIONS = [
  '当前 ERP 处于什么水平？意味着什么？',
  '贪婪恐惧指数各分项权重与口径？',
  '跟踪误差是怎么算的？数据从哪来？',
  'DuckDB 单写锁有什么注意事项？',
  'A 股基金版动量策略的门限怎么设？',
]

async function scrollBottom() {
  await nextTick()
  if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight
}

async function send(preset?: string) {
  const question = (preset ?? input.value).trim()
  if (!question || streaming.value) return
  input.value = ''
  errorObj.value = null
  messages.value.push({ role: 'user', content: question })
  await scrollBottom()

  streaming.value = true
  streamText.value = ''
  streamDocs.value = []
  streamDataTime.value = ''
  abort = new AbortController()

  const history = messages.value
    .slice(0, -1)
    .filter((m) => m.content.trim())
    .map((m) => ({ role: m.role, content: m.content }))

  try {
    await api.chatAi(
      question,
      (contextType.value || null) as 'dashboard' | 'fear_greed' | null,
      history,
      {
        onMeta: (m: AiStreamMeta) => {
          streamDocs.value = m.docs || []
          const ctx = m.context as Record<string, unknown> | null | undefined
          if (ctx?.generated_at) streamDataTime.value = String(ctx.generated_at).replace('T', ' ').slice(0, 19)
        },
        onDelta: (piece) => {
          streamText.value += piece
          scrollBottom()
        },
        onError: (err) => {
          errorObj.value = err
        },
        onDone: () => {
          messages.value.push({
            role: 'assistant',
            content: streamText.value || (errorObj.value ? '' : '（无输出）'),
            docs: streamDocs.value,
            dataTime: streamDataTime.value,
          })
          streamText.value = ''
          streaming.value = false
          scrollBottom()
        },
      },
      abort.signal,
    )
    // 异常断流兜底
    if (streaming.value) {
      if (streamText.value) {
        messages.value.push({ role: 'assistant', content: streamText.value, docs: streamDocs.value })
      }
      streaming.value = false
    }
  } catch (e: any) {
    if (e?.name !== 'AbortError') {
      errorObj.value = { code: 'network', message: e?.message || '网络错误，请重试' }
    }
    streaming.value = false
  } finally {
    abort = null
  }
}

function stop() {
  abort?.abort()
  if (streamText.value) {
    messages.value.push({ role: 'assistant', content: streamText.value, docs: streamDocs.value })
  }
  streamText.value = ''
  streaming.value = false
}

function goConfig() {
  router.push('/ai-decision')
}

onBeforeUnmount(() => abort?.abort())

function onInputKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <div class="ai-chat-page">
    <PageHeader title="AI 问答" subtitle="基于项目知识库与页面真实数据 · 回答仅用真实数据，不编造" />

    <div class="chat-shell">
      <!-- 消息区 -->
      <div ref="scrollBox" class="chat-scroll">
        <div v-if="messages.length === 0 && !streaming" class="chat-empty">
          <NIcon :component="SparklesOutline" size="36" />
          <div class="chat-empty-title">问点什么吧</div>
          <div class="chat-empty-sub">可附带宏观看板 / 贪婪恐惧实时数据；口径类问题自动检索知识库</div>
          <div class="chat-suggestions">
            <button v-for="s in SUGGESTIONS" :key="s" class="chat-suggestion" @click="send(s)">{{ s }}</button>
          </div>
        </div>

        <div v-for="(m, i) in messages" :key="i" :class="['chat-msg', m.role]">
          <div class="chat-bubble">
            <MdRenderer v-if="m.role === 'assistant'" :source="m.content" />
            <div v-else class="chat-user-text">{{ m.content }}</div>
            <div v-if="m.role === 'assistant' && (m.docs?.length || m.dataTime)" class="chat-cite">
              <span v-if="m.dataTime" class="chat-cite-time">数据 {{ m.dataTime }} UTC</span>
              <span v-for="d in m.docs" :key="d.id ?? d.title" class="chat-cite-doc">📖 {{ d.title }}</span>
            </div>
          </div>
        </div>

        <!-- 流式中的助手气泡 -->
        <div v-if="streaming" class="chat-msg assistant">
          <div class="chat-bubble">
            <div v-if="!streamText" class="chat-thinking">
              <NSpin size="small" />
              <span>正在检索知识库与实时数据…</span>
            </div>
            <MdRenderer v-else :source="streamText + ' ▍'" />
            <div v-if="streamDocs.length || streamDataTime" class="chat-cite">
              <span v-if="streamDataTime" class="chat-cite-time">数据 {{ streamDataTime }} UTC</span>
              <span v-for="d in streamDocs" :key="d.id ?? d.title" class="chat-cite-doc">📖 {{ d.title }}</span>
            </div>
          </div>
        </div>

        <!-- 错误引导（无渠道等） -->
        <div v-if="errorObj" class="chat-error">
          <div class="chat-error-title">
            {{ errorObj.code === 'not_configured' ? '尚未配置可用的 LLM 渠道' : '请求失败' }}
          </div>
          <div class="chat-error-msg">{{ errorObj.message }}</div>
          <NSpace style="margin-top: 8px" size="small">
            <NButton size="tiny" type="primary" @click="goConfig">
              <template #icon><NIcon :component="SettingsOutline" /></template>
              去配置渠道
            </NButton>
            <NButton size="tiny" @click="errorObj = null">知道了</NButton>
          </NSpace>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="chat-input-bar">
        <NSelect
          v-model:value="contextType"
          :options="contextOptions"
          size="small"
          style="width: 200px; flex-shrink: 0"
        />
        <textarea
          v-model="input"
          class="chat-input"
          rows="2"
          placeholder="输入问题（Enter 发送，Shift+Enter 换行）"
          :disabled="streaming"
          @keydown="onInputKeydown"
        />
        <NButton v-if="!streaming" type="primary" :disabled="!canSend" @click="send()">
          <template #icon><NIcon :component="SendOutline" /></template>
          发送
        </NButton>
        <NButton v-else @click="stop">
          <template #icon><NIcon :component="StopCircleOutline" /></template>
          停止
        </NButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ai-chat-page { display: flex; flex-direction: column; gap: 12px; height: calc(100vh - 130px); }

.chat-shell {
  flex: 1; display: flex; flex-direction: column; min-height: 0;
  background: var(--bg-card, var(--bg-sidebar));
  border: 1px solid var(--border-default); border-radius: 8px;
}

.chat-scroll { flex: 1; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 14px; }

.chat-empty { text-align: center; color: var(--text-muted); padding: 48px 0 24px; display: flex; flex-direction: column; align-items: center; gap: 8px; }
.chat-empty-title { font-size: 17px; font-weight: 700; color: var(--text-primary); font-family: 'Work Sans', sans-serif; }
.chat-empty-sub { font-size: 13px; }
.chat-suggestions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 12px; max-width: 560px; }
.chat-suggestion {
  border: 1px solid var(--border-default); background: var(--bg-hover); color: var(--text-secondary);
  border-radius: 999px; padding: 6px 14px; font-size: 12px; cursor: pointer;
  transition: all 0.15s ease;
}
.chat-suggestion:hover { color: var(--color-primary); border-color: var(--color-primary); }

.chat-msg { display: flex; }
.chat-msg.user { justify-content: flex-end; }
.chat-msg.assistant { justify-content: flex-start; }
.chat-bubble {
  max-width: 82%; padding: 12px 16px; border-radius: 10px; font-size: 14px;
}
.chat-msg.user .chat-bubble { background: var(--color-primary); color: #fff; border-bottom-right-radius: 2px; }
.chat-msg.assistant .chat-bubble {
  background: var(--bg-hover); color: var(--text-secondary);
  border-bottom-left-radius: 2px; border: 1px solid var(--border-default);
}
.chat-user-text { white-space: pre-wrap; line-height: 1.6; }

.chat-cite { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border-default); }
.chat-cite-time { font-size: 11px; color: var(--text-muted); }
.chat-cite-doc {
  font-size: 11px; color: var(--color-primary); background: var(--bg-card, var(--bg-sidebar));
  border: 1px solid var(--border-default); border-radius: 999px; padding: 1px 8px;
}

.chat-error {
  align-self: stretch; padding: 12px 16px; border-radius: 8px;
  background: var(--bg-hover); border: 1px solid var(--border-default);
  border-left: 3px solid var(--color-warning, #f59e0b);
}
.chat-error-title { font-weight: 700; color: var(--text-primary); font-size: 13px; }
.chat-error-msg { font-size: 12px; color: var(--text-secondary); margin-top: 2px; line-height: 1.6; }

.chat-input-bar {
  display: flex; gap: 10px; align-items: flex-end;
  padding: 12px 16px; border-top: 1px solid var(--border-default);
}
.chat-input {
  flex: 1; resize: none; border: 1px solid var(--border-default); border-radius: 8px;
  background: var(--bg-hover); color: var(--text-primary);
  padding: 8px 12px; font-size: 14px; font-family: inherit; line-height: 1.5;
}
.chat-input:focus { outline: none; border-color: var(--color-primary); }
.chat-input:disabled { opacity: 0.6; }

.chat-thinking { display: flex; align-items: center; gap: 8px; color: var(--text-muted); font-size: 13px; }

@media (max-width: 768px) {
  .ai-chat-page { height: calc(100vh - 110px); }
  .chat-bubble { max-width: 94%; }
}
</style>
