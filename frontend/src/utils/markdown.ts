/**
 * 精简 markdown 渲染器 — VNode 输出，不用 v-html（防 XSS），不引 npm 依赖。
 *
 * 支持：1-4 级标题、段落、粗体/斜体/行内代码、代码块、有序/无序列表、
 * 表格、引用、分割线、http(s) 链接。足以覆盖知识库 md 与 LLM 输出。
 */
import { h, type VNode } from 'vue'

/** 行内标记 → VNode（含裸文本字符串，均可作 h() children） */
function inline(text: string): Array<VNode | string> {
  const nodes: Array<VNode | string> = []
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)\s]+\))/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('`')) {
      nodes.push(h('code', { class: 'md-code' }, { default: () => tok.slice(1, -1) }))
    } else if (tok.startsWith('**')) {
      nodes.push(h('strong', {}, { default: () => tok.slice(2, -2) }))
    } else if (tok.startsWith('*')) {
      nodes.push(h('em', {}, { default: () => tok.slice(1, -1) }))
    } else {
      const lm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok)
      if (lm && /^https?:\/\//.test(lm[2])) {
        nodes.push(
          h('a', { class: 'md-a', href: lm[2], target: '_blank', rel: 'noopener noreferrer' }, { default: () => lm[1] }),
        )
      } else if (lm) {
        nodes.push(lm[1])
      }
    }
    last = m.index + tok.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

const RE_HEADING = /^(#{1,4})\s+(.*)$/
const RE_FENCE = /^```(\w*)\s*$/
const RE_HR = /^\s*(-{3,}|\*{3,})\s*$/
const RE_TABLE_ROW = /^\|.*\|\s*$/
const RE_TABLE_SEP = /^\|[\s:|-]+\|\s*$/
const RE_UL = /^\s*[-*]\s+/
const RE_OL = /^\s*\d+[.、]\s+/
const RE_QUOTE = /^>\s?/
const RE_BLOCK_START = /^(#{1,4}\s|```|>|\s*[-*]\s|\s*\d+[.、]\s|\|.*\|\s*$)/

/** markdown 源码 → VNode 块数组（配合 components/MdRenderer.vue 使用） */
export function renderMarkdown(src: string): VNode[] {
  const lines = (src || '').replace(/\r\n/g, '\n').split('\n')
  const blocks: VNode[] = []
  let i = 0

  const parseRow = (l: string): string[] =>
    l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())

  while (i < lines.length) {
    const line = lines[i]

    // 代码块
    const fence = RE_FENCE.exec(line.trim())
    if (fence) {
      const buf: string[] = []
      i++
      while (i < lines.length && !RE_FENCE.test(lines[i].trim())) {
        buf.push(lines[i])
        i++
      }
      i++ // 跳过收尾 ```
      blocks.push(h('pre', { class: 'md-pre' }, [h('code', {}, buf.join('\n'))]))
      continue
    }

    // 标题
    const hd = RE_HEADING.exec(line)
    if (hd) {
      const level = Math.min(hd[1].length + 1, 6)
      blocks.push(h(`h${level}`, { class: `md-h md-h${hd[1].length}` }, inline(hd[2])))
      i++
      continue
    }

    // 分割线
    if (RE_HR.test(line)) {
      blocks.push(h('hr', { class: 'md-hr' }))
      i++
      continue
    }

    // 表格（表头 + 分隔行 + 数据行）
    if (RE_TABLE_ROW.test(line) && i + 1 < lines.length && RE_TABLE_SEP.test(lines[i + 1])) {
      const header = parseRow(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && RE_TABLE_ROW.test(lines[i])) {
        rows.push(parseRow(lines[i]))
        i++
      }
      blocks.push(
        h('table', { class: 'md-table' }, [
          h('thead', {}, [h('tr', {}, header.map((c) => h('th', {}, inline(c))))]),
          h(
            'tbody',
            {},
            rows.map((r) => h('tr', {}, r.map((c) => h('td', {}, inline(c))))),
          ),
        ]),
      )
      continue
    }

    // 引用
    if (RE_QUOTE.test(line)) {
      const buf: string[] = []
      while (i < lines.length && RE_QUOTE.test(lines[i])) {
        buf.push(lines[i].replace(RE_QUOTE, ''))
        i++
      }
      blocks.push(h('blockquote', { class: 'md-quote' }, inline(buf.join(' '))))
      continue
    }

    // 无序列表
    if (RE_UL.test(line)) {
      const items: VNode[] = []
      while (i < lines.length && RE_UL.test(lines[i])) {
        items.push(h('li', {}, inline(lines[i].replace(RE_UL, ''))))
        i++
      }
      blocks.push(h('ul', { class: 'md-ul' }, items))
      continue
    }

    // 有序列表
    if (RE_OL.test(line)) {
      const items: VNode[] = []
      while (i < lines.length && RE_OL.test(lines[i])) {
        items.push(h('li', {}, inline(lines[i].replace(RE_OL, ''))))
        i++
      }
      blocks.push(h('ol', { class: 'md-ol' }, items))
      continue
    }

    // 空行
    if (!line.trim()) {
      i++
      continue
    }

    // 段落：吃到空行或下一个块级起点
    const buf: string[] = []
    while (i < lines.length && lines[i].trim() && !RE_BLOCK_START.test(lines[i])) {
      buf.push(lines[i])
      i++
    }
    if (buf.length) {
      blocks.push(h('p', { class: 'md-p' }, inline(buf.join(' '))))
    } else {
      i++ // 兜底防死循环
    }
  }
  return blocks
}
