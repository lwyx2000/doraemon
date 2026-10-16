<script lang="ts">
/**
 * markdown 渲染组件 — render 函数输出 VNode（无 v-html，防 XSS）。
 * 知识库正文、AI 解读、AI 问答输出共用。样式 scoped 随组件走。
 */
import { defineComponent, h } from 'vue'
import { renderMarkdown } from '../utils/markdown'

export default defineComponent({
  name: 'MdRenderer',
  props: {
    source: { type: String, required: true },
  },
  render() {
    return h('div', { class: 'md-body' }, renderMarkdown(this.source))
  },
})
</script>

<style scoped>
.md-body { color: var(--text-secondary); font-size: 14px; }
.md-body :deep(.md-p) { margin: 0 0 10px; line-height: 1.7; }
.md-body :deep(.md-h) { font-family: 'Work Sans', sans-serif; margin: 18px 0 8px; line-height: 1.3; color: var(--text-primary); }
.md-body :deep(.md-h1) { font-size: 20px; }
.md-body :deep(.md-h2) { font-size: 17px; }
.md-body :deep(.md-h3) { font-size: 15px; }
.md-body :deep(.md-h4) { font-size: 14px; }
.md-body :deep(.md-ul),
.md-body :deep(.md-ol) { margin: 0 0 10px; padding-left: 22px; display: flex; flex-direction: column; gap: 4px; }
.md-body :deep(.md-ul li),
.md-body :deep(.md-ol li) { line-height: 1.6; color: var(--text-secondary); }
.md-body :deep(.md-quote) {
  margin: 0 0 10px; padding: 8px 12px; border-left: 3px solid var(--color-primary);
  background: var(--bg-hover); border-radius: 0 6px 6px 0; color: var(--text-secondary);
}
.md-body :deep(.md-pre) {
  margin: 0 0 10px; padding: 12px; background: var(--bg-hover); border-radius: 6px;
  overflow-x: auto; font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.5;
}
.md-body :deep(.md-code) {
  font-family: 'JetBrains Mono', monospace; font-size: 0.9em;
  background: var(--bg-hover); padding: 1px 5px; border-radius: 4px; color: var(--color-primary);
}
.md-body :deep(.md-pre .md-code) { background: transparent; padding: 0; }
.md-body :deep(.md-table) { border-collapse: collapse; width: 100%; margin: 0 0 12px; font-size: 13px; }
.md-body :deep(.md-table th),
.md-body :deep(.md-table td) { border: 1px solid var(--border-default); padding: 6px 10px; text-align: left; }
.md-body :deep(.md-table th) { background: var(--bg-hover); font-weight: 700; color: var(--text-primary); white-space: nowrap; }
.md-body :deep(.md-table td) { color: var(--text-secondary); }
.md-body :deep(.md-hr) { border: none; border-top: 1px solid var(--border-default); margin: 14px 0; }
.md-body :deep(.md-a) { color: var(--color-primary); text-decoration: none; }
.md-body :deep(.md-a:hover) { text-decoration: underline; }
</style>
