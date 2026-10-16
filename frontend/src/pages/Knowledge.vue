<script setup lang="ts">
/**
 * 知识库页 — 沉淀项目方法论/数据源/策略/工程知识（backend/knowledge/ 单一真源）。
 * 与 AI 解读/问答共用同一内容源：AI 回答引用的口径即本页正文。
 */
import { ref, computed, onMounted } from 'vue'
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

const categories = computed(() => index.value?.categories ?? [])
const docs = computed(() => index.value?.docs ?? [])

const grouped = computed(() =>
  categories.value.map((cat) => ({
    ...cat,
    docs: docs.value.filter((d) => d.category === cat.id),
  })),
)

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
        <div v-for="cat in grouped" :key="cat.id" class="kb-cat">
          <div class="kb-cat-title">{{ cat.name }}</div>
          <button
            v-for="d in cat.docs"
            :key="d.id"
            :class="['kb-doc-item', { active: activeId === d.id }]"
            :aria-current="activeId === d.id ? 'true' : undefined"
            @click="select(d.id)"
          >
            <span class="kb-doc-title">{{ d.title }}</span>
            <span v-for="t in (d.tags || []).slice(0, 2)" :key="t" class="kb-tag">{{ t }}</span>
          </button>
        </div>
      </aside>

      <!-- 右：文档正文（markdown 渲染） -->
      <section class="kb-content">
        <LoadingState v-if="loadingDoc" :loading="true" :min-height="400" text="正在加载文档..." />
        <template v-else-if="doc">
          <div class="kb-doc-head">
            <h2 class="kb-doc-h2">{{ doc.title }}</h2>
            <div class="kb-doc-tags">
              <span v-for="t in (doc.tags || [])" :key="t" class="kb-tag">{{ t }}</span>
            </div>
          </div>
          <MdRenderer :source="doc.content" />
        </template>
      </section>
    </div>
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

.kb-tag {
  font-size: 10px; padding: 1px 6px; border-radius: 999px;
  background: var(--bg-hover); color: var(--text-muted); white-space: nowrap;
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
.kb-doc-tags { display: flex; gap: 6px; flex-wrap: wrap; }

.kb-error { padding: 40px 0; }

@media (max-width: 900px) {
  .kb-layout { grid-template-columns: 1fr; }
  .kb-nav { position: static; max-height: none; flex-direction: row; flex-wrap: wrap; }
  .kb-cat { flex: 1 1 200px; }
}
</style>
