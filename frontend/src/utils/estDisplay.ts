/**
 * 自算估值（est_*）列的前端显示辅助。
 *
 * 后端用「取数腿代号」标识基准指数（hkHSI / hkHSCEI / jpN225cny …），
 * 直接显示给用户等于没解释，这里统一翻成中文，并补一句该腿的口径特点。
 */

const INDEX_LABEL: Record<string, string> = {
  hkHSI: '恒生指数',
  hkHSCEI: '恒生中国企业指数',
  hkHSTECH: '恒生科技指数',
  jpN225cny: '日经225（人民币计价）',
}

export function estIndexLabel(symbol?: string | null): string {
  return (symbol && INDEX_LABEL[symbol]) || symbol || '指数'
}

/**
 * 各取数腿的口径补充说明。
 * 日经：日本 15:00 收盘 = 北京时间 14:00，早于 A 股收盘，所以收盘后拿到的
 * 就是当日收盘（已定盘，不是盘中噪声）；汇率由后端按人民币**中间价**折算。
 * 日经没有实时腿（数据网关无日经实时源），现值一律取日K末根；因此北京时间 14:00 前
 * 日K末根仍等于净值日，后端直接不出数而不是给出 est_nav = nav 的假值 —— 空值属口径设计。
 */
export function estIndexNote(symbol?: string | null): string {
  if (symbol && symbol.startsWith('jp')) {
    return '日本 14:00 收盘早于 A 股，收盘后即用当日收盘（已定盘）；汇率按人民币中间价折算；14:00 前或数据源异常时不出数'
  }
  return ''
}

/** valuationErrorTip 需要的最小字段集（FundItem / EtfFund 均结构兼容）。 */
export interface ValuationErrorLike {
  valuation_error?: number | null
  valuation_error_date?: string | null
  valuation_error_n?: number | null
  valuation_error_mae?: number | null
  valuation_error_max?: number | null
}

/**
 * 「估值误差」单元格的悬浮说明（T3 估值误差自检）。
 *
 * 误差 = 自算净值 / 基金公司公布的真实净值 - 1：正数=自算高估，负数=自算低估。
 * 后端每天 15:30 落当时的 est_nav 快照，次日凌晨等净值公布后回填误差；
 * 因此**刚上线时没有样本是正常的**，此时单元格显示 '-' 而不是 0。
 *
 * 判定口径（lofarb 实战）：长期 ±0.3% 内说明权重/仓位可信；若突然跳到 +3%
 * 并持续数日，多半是标的已调仓、篮子配置过期；单日跳 10%+ 后又回落，
 * 一般是某个成分取到了脏数据。
 */
export function valuationErrorTip(row: ValuationErrorLike): string {
  const parts: string[] = ['误差 = 自算净值/真实净值 - 1（正=高估，负=低估）']
  if (row.valuation_error_date) parts.push(`最近样本 ${row.valuation_error_date}`)
  if (row.valuation_error_n != null) parts.push(`近 20 日样本 ${row.valuation_error_n} 个`)
  if (row.valuation_error_mae != null) parts.push(`平均绝对误差 ${row.valuation_error_mae.toFixed(2)}%`)
  if (row.valuation_error_max != null) parts.push(`最大 ${row.valuation_error_max.toFixed(2)}%`)
  parts.push('长期 ±0.3% 内属正常；持续大于 3% 多为持仓已调、篮子配置过期')
  return parts.join('；')
}
