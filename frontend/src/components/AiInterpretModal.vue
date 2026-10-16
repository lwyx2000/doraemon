<script setup lang="ts">
/**
 * AI 解读弹窗 — 挂载在 Dashboard / 恐贪详情页。
 * 后端自行组装真实数据 + 知识库口径，经激活 LLM 渠道流式输出。
 * 无渠道/无 key：SSE error 帧（not_configured）→ 展示配置引导，绝不 500 白屏。
 */
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NModal, NButton, NIcon, NSpace, NSpin } from 'naive-ui'
import { SparklesOutline, StopCircleOutline, SettingsOutline, RefreshOutline } from '@vicons/ionicons5'
import { api } from '../utils/api'
import MdRenderer from './MdRenderer.vue'
import type { AiStreamMeta, AiStreamError } from '../types'

const props = defineProps<{
  show: boolean
  contextType: 'dashboard' | 'fear_greed'
  title?: string
}>()

const emit = defineEmits<{ (e: 'update:show', v: boolean): void }>()
const router = useRouter()

const status = ref<'idle' | 'streaming' | 'done' | 'error'>('idle')
const text = ref('')
const meta = ref<AiStreamMeta | null>(null)
const errorObj = ref<AiStreamError | null>(null)
let abort: AbortController | null = null

function close() {
  abort?.abort()
  emit('update:show', false)
}

function stopStream() {
  abort?.abort()
}

function reset() {
  abort?.abort()
  abort = null
  status.value = 'idle'
  text.value = ''
  meta.value = null
  errorObj.value = null
}

async function run() {
  reset()
  status.value = 'streaming'
  abort = new AbortController()
  try {
    await api.interpretAi(
      props.contextType,
      {
        onMeta: (m) => {
          meta.value = m
        },
        onDelta: (piece) => {
          text.value += piece
        },
        onError: (err) => {
          errorObj.value = err
          status.value = 'error'
        },
        onDone: () => {
          if (status.value === 'streaming') status.value = 'done'
        },
      },
      abort.signal,
    )
    // 流异常结束（网络断）但未收到 done：保留已得文本
    if (status.value === 'streaming') status.value = 'done'
  } catch (e: any) {
    if (e?.name === 'AbortError') return
    errorObj.value = { type: 'error', code: 'network', message: e?.message || '网络错误，请重试' }
    status.value = 'error'
  } finally {
    abort = null
  }
}

// 打开即跑；关闭即中止
watch(
  () => props.show,
  (v) => {
    if (v) run()
    else abort?.abort()
  },
)

function goConfig() {
  close()
  router.push('/ai-decision')
}
</script>

<template>
  <NModal
    :show="props.show"
    preset="card"
    :title="title || 'AI 解读'"
    style="max-width: 760px; width: 92vw"
    :bordered="false"
    size="large"
    :mask-closable="false"
    @update:show="(v: boolean) => !v && close()"
  >
    <template #header-extra>
      <NSpace size="small">
        <NButton v-if="status === 'streaming'" size="small" quaternary @click="stopStream">
          <template #icon><NIcon :component="StopCircleOutline" /></template>
          停止
        </NButton>
        <NButton v-else size="small" quaternary @click="run">
          <template #icon><NIcon :component="RefreshOutline" /></template>
          重新生成
        </NButton>
      </NSpace>
    </template>

    <!-- 数据/引用来源行 -->
    <div v-if="meta" class="ai-meta-line">
      <NIcon :component="SparklesOutline" size="14" />
      <span v-if="meta.context?.generated_at">数据时间 {{ String(meta.context.generated_at).replace('T', ' ').slice(0, 19) }} UTC</span>
      <span v-if="meta.docs?.length" class="ai-meta-docs">
        引用口径：
        <b v-for="d in meta.docs" :key="d.id ?? d.title" class="ai-meta-doc">{{ d.title }}</b>
      </span>
    </div>

    <!-- 流式输出 -->
    <div v-if="status === 'streaming' && !text" class="ai-loading">
      <NSpin size="small" />
      <span>正在获取真实数据并生成解读…</span>
    </div>
    <MdRenderer v-else-if="text" :source="status === 'streaming' ? text + ' ▍' : text" />

    <!-- 无渠道 / 调用失败：引导配置而非报错 -->
    <div v-if="status === 'error'" class="ai-error-box">
      <div class="ai-error-title">
        {{ errorObj?.code === 'not_configured' ? '尚未配置可用的 LLM 渠道' : 'AI 解读生成失败' }}
      </div>
      <div class="ai-error-msg">{{ errorObj?.message }}</div>
      <div v-if="text" class="ai-error-partial">（以上为已生成的部分内容）</div>
      <NSpace style="margin-top: 10px">
        <NButton size="small" type="primary" @click="goConfig">
          <template #icon><NIcon :component="SettingsOutline" /></template>
          去配置渠道
        </NButton>
        <NButton size="small" @click="run">重试</NButton>
      </NSpace>
    </div>

    <template #footer>
      <div class="ai-footer-note">AI 生成内容基于真实数据与项目知识库，仅供参考，不构成投资建议。</div>
    </template>
  </NModal>
</template>

<style scoped>
.ai-meta-line {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 12px; color: var(--text-muted);
  padding-bottom: 10px; margin-bottom: 10px;
  border-bottom: 1px dashed var(--border-default);
}
.ai-meta-docs { display: inline-flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.ai-meta-doc {
  font-weight: 600; color: var(--color-primary);
  background: var(--bg-hover); border-radius: 999px; padding: 1px 8px;
}
.ai-loading {
  display: flex; align-items: center; gap: 10px;
  padding: 32px 0; color: var(--text-muted); font-size: 13px;
}
.ai-error-box {
  margin-top: 12px; padding: 14px 16px;
  background: var(--bg-hover); border: 1px solid var(--border-default);
  border-left: 3px solid var(--color-warning, #f59e0b);
  border-radius: 0 8px 8px 0;
}
.ai-error-title { font-weight: 700; color: var(--text-primary); font-size: 14px; }
.ai-error-msg { font-size: 13px; color: var(--text-secondary); margin-top: 4px; line-height: 1.6; }
.ai-error-partial { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
.ai-footer-note { font-size: 12px; color: var(--text-muted); text-align: center; }
</style>
