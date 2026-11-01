/**
 * 后端时间串解析工具
 *
 * 背景：doraemon 后端容器时钟为 UTC，_build_meta 的 updateTime/mockTime 是
 * `datetime.now().strftime("%Y-%m-%d %H:%M:%S")` —— naive 串、无时区标记，
 * 实际是 UTC 墙钟时间。JS 对 "YYYY-MM-DD HH:mm:ss"（空格分隔）按**本地时间**
 * 解析，导致页面显示的时间比真实本地时间少 8 小时（CST），数据看着像过期了
 * 其实才生成几分钟（2026-10-19 修复）。
 *
 * 用法：所有展示后端 meta.updateTime / mockTime / updated_at 的地方，
 * 先过 parseBackendTime / formatBackendTime，不要直接 new Date(s)。
 */

/** 匹配 "YYYY-MM-DD[ T]HH:mm[:ss][.fff][Z|±HH[:]MM]"，naive（无时区）按 UTC 解释 */
const BACKEND_TIME_RE =
  /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$/

/**
 * 解析后端时间串为 Date（本地时区对象）。
 * 无时区标记的按 UTC 解析（容器时钟 UTC）；带时区标记的尊重原标记。
 * 解析失败返回 null。
 */
export function parseBackendTime(s: string | null | undefined): Date | null {
  if (!s) return null
  const str = String(s).trim()
  if (!str) return null

  const m = str.match(BACKEND_TIME_RE)
  if (m) {
    const [, y, mo, d, h, mi, sec, tz] = m
    let zone = 'Z' // naive 串：容器 UTC，按 UTC 解析
    if (tz && tz !== 'Z') {
      zone = tz.includes(':') ? tz : `${tz.slice(0, 3)}:${tz.slice(3)}`
    }
    const dt = new Date(`${y}-${mo}-${d}T${h}:${mi}:${sec || '00'}${zone}`)
    return Number.isNaN(dt.getTime()) ? null : dt
  }

  // 其他格式（纯日期 / ISO 带 T 等）交给原生解析
  const dt = new Date(str)
  return Number.isNaN(dt.getTime()) ? null : dt
}

/**
 * 格式化为本地时间 "YYYY-MM-DD HH:mm"（可带秒）。
 * 无法解析时返回 ''（由调用方决定占位）。
 */
export function formatBackendTime(
  s: string | null | undefined,
  withSeconds = false
): string {
  const dt = parseBackendTime(s)
  if (!dt) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  const base = `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`
  return withSeconds ? `${base}:${pad(dt.getSeconds())}` : base
}
