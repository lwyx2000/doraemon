// 全局分位配色单一真源
// 标准（用户约定）：分位越高 → 色温越高 → 越红；分位越低 → 色温越低 → 越蓝。
// 中间过渡：蓝 → 绿 → 黄 → 橙 → 粉 → 红；null/无效 → 灰。
//
// 说明：本模块只按"数值高低"机械映射色温，不携带"贵/便宜/好/坏"语义。
// 例：ERP(股债利差)分位越高=市场越便宜=越好，但按本标准高分位仍显红，
// 属预期内的一致性映射；若该页需反转语义，请在该页单独处理，不要改这里。

/** 分位数值 → 颜色（hex）。null/NaN → 灰。 */
export function pctColor(pct: number | null | undefined): string {
  if (pct == null || Number.isNaN(pct)) return '#8b919e'
  if (pct >= 84) return '#dc2626' // 红（最高 / 最热）
  if (pct >= 67) return '#ec4899' // 粉
  if (pct >= 50) return '#f97316' // 橙
  if (pct >= 34) return '#eab308' // 黄
  if (pct >= 17) return '#16a34a' // 绿
  return '#2b6cff' // 蓝（最低 / 最冷）
}

/** 分位数值 → Naive UI NTag 的 color 配置对象。 */
export function pctColorStyle(pct: number | null | undefined) {
  const c = pctColor(pct)
  return { color: `${c}1f`, textColor: c, borderColor: `${c}59` }
}

/** 图例/说明用分档（与 pctColor 同序，从高热到低热）。 */
export const PCT_LEGEND: { min: number; color: string; label: string }[] = [
  { min: 84, color: '#dc2626', label: '极高 (≥84%)' },
  { min: 67, color: '#ec4899', label: '高 (67–83%)' },
  { min: 50, color: '#f97316', label: '偏高 (50–66%)' },
  { min: 34, color: '#eab308', label: '中 (34–49%)' },
  { min: 17, color: '#16a34a', label: '偏低 (17–33%)' },
  { min: 0, color: '#2b6cff', label: '低 (<17%)' },
]
