/**
 * Shared export utilities for downloading data as files.
 */

/**
 * Export an array of objects to a CSV file and trigger browser download.
 *
 * @param filename - Output file name (without extension is OK; .csv will be appended if missing).
 * @param headers - Column headers in display order.
 * @param rows - Array of row arrays; each row's values correspond to headers.
 */
export function exportToCSV(
  filename: string,
  headers: string[],
  rows: Array<Array<string | number | null | undefined>>,
): void {
  const escape = (v: string | number | null | undefined) => {
    const s = v === null || v === undefined ? '' : String(v)
    // Quote if it contains comma, quote, or newline
    if (/[",\n\r]/.test(s)) {
      return `"${s.replace(/"/g, '""')}"`
    }
    return s
  }
  const csv = [headers, ...rows].map(r => r.map(escape).join(',')).join('\n')
  // Prepend BOM for Excel UTF-8 compatibility
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  triggerDownload(blob, ensureExtension(filename, '.csv'))
}

/**
 * Export a plain text string as a file download.
 */
export function exportToText(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8;' })
  triggerDownload(blob, ensureExtension(filename, '.txt'))
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  // Revoke in next tick to ensure download starts
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

function ensureExtension(name: string, ext: string): string {
  return name.toLowerCase().endsWith(ext) ? name : name + ext
}
