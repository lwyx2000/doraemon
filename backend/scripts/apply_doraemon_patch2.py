# -*- coding: utf-8 -*-
"""增量补丁2：EtfFunds.vue 套利表加自算净值/溢价两列 + types EtfFund 增 est 字段。
锚点找不到即报错退出，不半写；备份 .bak_valuation（若已存在则不覆盖）。"""
import shutil
import sys
from pathlib import Path

BE = Path(r"D:\workspace\doraemon\backend")
FE = Path(r"D:\workspace\doraemon\frontend\src")

edits = [
    # types: EtfFund 增 est 字段（在 nav_date 行后）
    (
        FE / "types" / "index.ts",
        "  nav_date?: string | null              // 净值披露日期\n  share?: number | null                 // 最新份额(亿份)\n",
        "  nav_date?: string | null              // 净值披露日期\n"
        "  // 篮子自算估值（跨境 ETF/LOF，参考 lofarb basket_valuation；null=数据不足未估算）\n"
        "  est_nav?: number | null               // 篮子自算预估净值\n"
        "  est_premium_pct?: number | null       // 自算溢价率(%)：(现价-自算净值)/自算净值\n"
        "  est_base_date?: string                // 估值基准日(净值日期)\n"
        "  est_price_date?: string               // 底层行情取数日\n"
        "  est_position?: number                 // 篮子仓位(%)\n"
        "  share?: number | null                 // 最新份额(亿份)\n",
        "types EtfFund est 字段",
    ),
    # EtfFunds.vue: arbitrageColumns 折溢价率后插入自算净值/自算溢价两列
    (
        FE / "pages" / "EtfFunds.vue",
        "  {\n    title: titleWithHelp('溢价百分位', 'premium_percentile'), key: 'premium_percentile', align: 'center' as const,\n    render: (row: EtfFund) => h(PercentileIndicator, { value: row.premium_percentile }),\n  },\n",
        "  {\n"
        "    title: titleWithHelp('篮子自算净值', 'est_nav'), key: 'est_nav', align: 'right' as const,\n"
        "    render: (row: EtfFund) => {\n"
        "      // 跨境 ETF/LOF 按底层篮子行情自算；position/篮子/行情缺一 → 后端不写 → '-'\n"
        "      if (row.est_nav == null) return h('span', { class: 'mono' }, '-')\n"
        "      return h('span', { class: 'mono' }, row.est_nav.toFixed(3))\n"
        "    },\n"
        "  },\n"
        "  {\n"
        "    title: titleWithHelp('自算溢价', 'est_premium_pct'), key: 'est_premium_pct', align: 'right' as const,\n"
        "    render: (row: EtfFund) => {\n"
        "      if (row.est_premium_pct == null) return h('span', { class: 'mono' }, '-')\n"
        "      const color = row.est_premium_pct >= 0 ? 'var(--color-danger)' : 'var(--color-success)'\n"
        "      return h('span', { style: { color, fontWeight: 700 } }, `${row.est_premium_pct >= 0 ? '+' : ''}${row.est_premium_pct.toFixed(2)}%`)\n"
        "    },\n"
        "  },\n"
        "  {\n    title: titleWithHelp('溢价百分位', 'premium_percentile'), key: 'premium_percentile', align: 'center' as const,\n    render: (row: EtfFund) => h(PercentileIndicator, { value: row.premium_percentile }),\n  },\n",
        "EtfFunds.vue 自算两列",
    ),
]

failed = False
for path, old, new, desc in edits:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"[SKIP] {desc}: 已应用")
        continue
    if text.count(old) < 1:
        print(f"[FAIL] {desc}: 锚点未找到 -> {path}")
        failed = True
if failed:
    sys.exit(1)

for path, old, new, desc in edits:
    text = path.read_text(encoding="utf-8")
    if new in text:
        continue
    bak = path.with_suffix(path.suffix + ".bak_valuation")
    if not bak.exists():
        shutil.copy2(path, bak)
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")
    print(f"[OK] {desc}")

print("PATCH2 DONE")
