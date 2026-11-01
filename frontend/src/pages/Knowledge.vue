<script setup lang="ts">
/**
 * 知识库页 — 沉淀项目方法论/数据源/策略/工程知识（backend/knowledge/ 内置单一真源）
 * + 用户导入文档（SQLite 持久化，可粘贴/上传 md/txt，可启停/删除）。
 * 与 AI 解读/问答共用同一内容源：AI 回答引用的口径即本页正文。
 */
import { ref, computed, onMounted } from 'vue'
import { NModal, NInput, NButton, NSwitch, useMessage, useDialog } from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import LoadingState from '../components/LoadingState.vue'
import MdRenderer from '../components/MdRenderer.vue'
import { api } from '../utils/api'
import type { KnowledgeIndex, KnowledgeDoc } from '../types'

const index = ref<KnowledgeIndex | null>(null)
const doc = ref<KnowledgeDoc | null>(null)
const loadingList = ref(true)
const loadingDoc = ref(false)
const activeId = ref<string | null>(null)
const error = ref('')

const message = useMessage()
const dialog = useDialog()

const categories = computed(() => index.value?.categories ?? [])
const docs = computed(() => index.value?.docs ?? [])

const grouped = computed(() =>
  categories.value.map((cat) => ({
    ...cat,
    docs: docs.value.filter((d) => d.category === cat.id),
  })),
)

// ---------- 导入弹窗 ----------
const showImport = ref(false)
const importTitle = ref('')
const importContent = ref('')
const importTags = ref('')
const importing = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const importChars = computed(() => importContent.value.length)

function pickFile() {
  fileInput.value?.click()
}

function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    message.error('文件过大（≤2MB）')
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    importContent.value = String(reader.result ?? '')
    if (!importTitle.value) {
      importTitle.value = file.name.replace(/\.(md|markdown|txt)$/i, '')
    }
    message.success(`已读取 ${file.name}`)
  }
  reader.onerror = () => message.error('文件读取失败')
  reader.readAsText(file, 'utf-8')
}

function openImport() {
  importTitle.value = ''
  importContent.value = ''
  importTags.value = ''
  showImport.value = true
}

async function submitImport() {
  const title = importTitle.value.trim()
  const content = importContent.value.trim()
  if (!title) {
    message.warning('请填写标题')
    return
  }
  if (!content) {
    message.warning('请填写或上传内容')
    return
  }
  importing.value = true
  try {
    const tags = importTags.value
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter(Boolean)
      .slice(0, 10)
    const created = await api.importKnowledgeDoc({ title, content, tags })
    message.success('导入成功，AI 解读将自动引用该知识')
    showImport.value = false
    await reloadList()
    if (created?.id) await select(created.id)
  } catch (e: any) {
    message.error(e?.message || '导入失败')
  } finally {
    importing.value = false
  }
}

async function reloadList() {
  try {
    index.value = await api.getKnowledge()
  } catch (e: any) {
    error.value = e?.message || '知识库加载失败'
  }
}

// ---------- 导入文档管理（启停/删除） ----------
async function toggleDoc(d: { id: string; enabled?: boolean }, enabled: boolean) {
  try {
    await api.toggleKnowledgeDoc(d.id, enabled)
    await reloadList()
    message.success(enabled ? '已启用，AI 解读将引用' : '已停用，AI 解读不再引用')
  } catch (e: any) {
    message.error(e?.message || '操作失败')
  }
}

function removeDoc(d: { id: string; title: string }) {
  dialog.warning({
    title: '删除导入文档',
    content: `确定删除「${d.title}」？删除后不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.deleteKnowledgeDoc(d.id)
        message.success('已删除')
        if (activeId.value === d.id) {
          activeId.value = null
          doc.value = null
        }
        await reloadList()
      } catch (e: any) {
        message.error(e?.message || '删除失败')
      }
    },
  })
}

async function select(id: string) {
  if (activeId.value === id) return
  activeId.value = id
  loadingDoc.value = true
  error.value = ''
  try {
    doc.value = await api.getKnowledgeDoc(id)
  } catch (e: any) {
    error.value = e?.message || '文档加载失败'
    doc.value = null
  } finally {
    loadingDoc.value = false
  }
}

function reloadPage() {
  window.location.reload()
}

onMounted(async () => {
  try {
    index.value = await api.getKnowledge()
    if (docs.value.length) await select(docs.value[0].id)
  } catch (e: any) {
    error.value = e?.message || '知识库加载失败'
  } finally {
    loadingList.value = false
  }
})
</script>

<template>
  <div class="knowledge-page">
    <PageHeader title="知识库" subtitle="方法论口径 · 数据源地图 · 策略体系 · 工程踩坑（AI 解读与问答共用此内容源）" />

    <LoadingState v-if="loadingList" :loading="true" :min-height="320" text="正在加载知识库..." />

    <div v-else-if="error && !doc" class="kb-error">
      <LoadingState :loading="false" :error="error" :min-height="240" @retry="reloadPage" />
    </div>

    <div v-else class="kb-layout">
      <!-- 左：分类 + 文档导航 -->
      <aside class="kb-nav">
        <NButton size="small" type="primary" dashed block @click="openImport">+ 导入知识</NButton>
        <div v-for="cat in grouped" :key="cat.id" class="kb-cat">
          <div class="kb-cat-title">{{ cat.name }}</div>
          <div
            v-for="d in cat.docs"
            :key="d.id"
            :class="['kb-doc-item', { active: activeId === d.id }]"
            :aria-current="activeId === d.id ? 'true' : undefined"
            role="button"
            tabindex="0"
            @click="select(d.id)"
            @keydown.enter.prevent="select(d.id)"
            @keydown.space.prevent="select(d.id)"
          >
            <span class="kb-doc-title">{{ d.title }}</span>
            <span v-if="d.source === 'import'" class="kb-src-badge">导入</span>
            <span v-for="t in (d.tags || []).slice(0, 2)" :key="t" class="kb-tag">{{ t }}</span>
            <span v-if="d.source === 'import'" class="kb-doc-ops" @click.stop>
              <NSwitch
                :value="d.enabled !== false"
                size="small"
                @update:value="(v: boolean) => toggleDoc(d, v)"
              />
              <NButton quaternary size="tiny" type="error" @click.stop="removeDoc(d)">删</NButton>
            </span>
          </div>
        </div>
      </aside>

      <!-- 右：文档正文（markdown 渲染） -->
      <section class="kb-content">
        <LoadingState v-if="loadingDoc" :loading="true" :min-height="400" text="正在加载文档..." />
        <template v-else-if="doc">
          <div class="kb-doc-head">
            <h2 class="kb-doc-h2">{{ doc.title }}</h2>
            <div class="kb-doc-tags">
              <span v-if="doc.source === 'import'" class="kb-src-badge">我的导入</span>
              <span v-for="t in (doc.tags || [])" :key="t" class="kb-tag">{{ t }}</span>
            </div>
          </div>
          <MdRenderer :source="doc.content" />
        </template>
      </section>
    </div>

    <!-- 导入弹窗 -->
    <NModal
      v-model:show="showImport"
      preset="card"
      title="导入知识"
      style="width: 640px; max-width: 92vw;"
      :bordered="false"
      size="huge"
      role="dialog"
      aria-modal="true"
    >
      <div class="kb-import-form">
        <label class="kb-import-label">标题</label>
        <NInput v-model:value="importTitle" placeholder="如：我的ERP使用心得" maxlength="100" show-count />
        <label class="kb-import-label">标签（可选，逗号分隔）</label>
        <NInput v-model:value="importTags" placeholder="如：ERP,估值,方法论" />
        <label class="kb-import-label">内容（markdown）</label>
        <NInput
          v-model:value="importContent"
          type="textarea"
          placeholder="粘贴 markdown 内容，或点击下方按钮上传 .md/.txt 文件"
          :rows="14"
        />
        <div class="kb-import-actions">
          <NButton size="small" @click="pickFile">上传文件</NButton>
          <input
            ref="fileInput"
            type="file"
            accept=".md,.markdown,.txt,text/markdown,text/plain"
            style="display: none"
            @change="onFilePicked"
          />
          <span class="kb-import-count">{{ importChars }} 字</span>
          <NButton
            size="small"
            type="primary"
            :loading="importing"
            :disabled="!importTitle.trim() || !importContent.trim()"
            @click="submitImport"
          >
            导入
          </NButton>
        </div>
        <p class="kb-import-hint">导入后 AI 解读宏观看板/贪婪恐惧及 AI 问答时会自动引用该知识（可在左侧停用）。</p>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.knowledge-page { display: flex; flex-direction: column; gap: 16px; }

.kb-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
  align-items: start;
}

.kb-nav {
  background: var(--bg-card, var(--bg-sidebar));
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: sticky;
  top: 68px;
  max-height: calc(100vh - 92px);
  overflow-y: auto;
}

.kb-cat { display: flex; flex-direction: column; gap: 4px; }
.kb-cat-title {
  font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
  color: var(--text-muted); text-transform: uppercase; padding: 0 4px 2px;
}

.kb-doc-item {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  padding: 8px 10px; border: none; border-radius: 6px; cursor: pointer;
  background: transparent; color: var(--text-secondary);
  font-size: 13px; text-align: left; width: 100%;
  transition: background 0.15s ease, color 0.15s ease;
}
.kb-doc-item:hover { background: var(--bg-hover); color: var(--text-primary); }
.kb-doc-item.active { background: var(--bg-active); color: var(--color-primary); font-weight: 600; }
.kb-doc-item:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
.kb-doc-title { flex: 1 1 auto; min-width: 0; }

.kb-doc-ops { display: inline-flex; align-items: center; gap: 4px; }

.kb-tag {
  font-size: 10px; padding: 1px 6px; border-radius: 999px;
  background: var(--bg-hover); color: var(--text-muted); white-space: nowrap;
}

.kb-src-badge {
  font-size: 10px; padding: 1px 6px; border-radius: 4px;
  background: var(--color-primary, #6366f1); color: #fff; white-space: nowrap;
}

.kb-content {
  background: var(--bg-card, var(--bg-sidebar));
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 20px 24px;
  min-height: 420px;
}

.kb-doc-head {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 12px; flex-wrap: wrap; margin-bottom: 12px;
  padding-bottom: 12px; border-bottom: 1px dashed var(--border-default);
}
.kb-doc-h2 { font-family: 'Work Sans', sans-serif; font-size: 20px; font-weight: 700; color: var(--text-primary); margin: 0; }
.kb-doc-tags { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }

.kb-error { padding: 40px 0; }

.kb-import-form { display: flex; flex-direction: column; gap: 8px; }
.kb-import-label { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-top: 4px; }
.kb-import-actions { display: flex; align-items: center; gap: 10px; margin-top: 4px; }
.kb-import-count { font-size: 12px; color: var(--text-muted); margin-left: auto; }
.kb-import-hint { font-size: 12px; color: var(--text-muted); margin: 4px 0 0; }

@media (max-width: 900px) {
  .kb-layout { grid-template-columns: 1fr; }
  .kb-nav { position: static; max-height: none; flex-direction: row; flex-wrap: wrap; }
  .kb-cat { flex: 1 1 200px; }
}
</style>
