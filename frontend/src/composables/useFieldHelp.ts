/**
 * 字段帮助工具
 *
 * 提供 titleWithHelp 函数，用于在 NDataTable 列标题中添加字段说明图标。
 */
import { h } from 'vue'
import FieldHelp from '../components/FieldHelp.vue'

export function useFieldHelp() {
  /**
   * 生成带"?"提示图标的列标题渲染函数
   * @param title 列标题文字
   * @param field 字段 key（从 fieldTips 字典获取说明）
   * @param tip 自定义说明文本（优先级高于 field）
   */
  function titleWithHelp(title: string, field?: string, tip?: string) {
    return () => h('span', { style: 'display: inline-flex; align-items: center; gap: 2px' }, [
      title,
      h(FieldHelp, { field, tip }),
    ])
  }

  return { titleWithHelp }
}
