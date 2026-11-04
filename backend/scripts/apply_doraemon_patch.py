# -*- coding: utf-8 -*-
"""把篮子自算估值落地到 doraemon：复制新文件 + 对既有文件做精确替换。
任何锚点找不到即整体报错退出(不半写)。修改前逐文件备份 .bak_valuation。"""
import shutil
import sys
from pathlib import Path

STAGE = Path(r"d:\workspace\lofarb\.stage_doraemon")
BE = Path(r"D:\workspace\doraemon\backend")
FE = Path(r"D:\workspace\doraemon\frontend\src")

edits = []

def patch(path: Path, old: str, new: str, desc: str, count: int = 1):
    edits.append((path, old, new, desc, count))

# ---------------- 1. 新文件复制 ----------------
copies = [
    (STAGE / "qdii_baskets.json", BE / "config" / "qdii_baskets.json", True),
    (STAGE / "cross_border_valuation.py", BE / "services" / "cross_border_valuation.py", False),
]

# ---------------- 2. models.py: FundItem 增字段 ----------------
patch(
    BE / "models.py",
    "    underlying_type: Optional[str] = None\n    arbitrage_analysis: Optional[ArbitrageAnalysis] = None\n",
    "    underlying_type: Optional[str] = None\n"
    "    # 篮子自算估值（跨境 LOF/QDII，参考 lofarb；数据不足时后端不写→前端显示 -）\n"
    "    nav_date: Optional[str] = None\n"
    "    est_nav: Optional[float] = None\n"
    "    est_premium_pct: Optional[float] = None\n"
    "    est_base_date: Optional[str] = None\n"
    "    est_price_date: Optional[str] = None\n"
    "    est_position: Optional[float] = None\n"
    "    arbitrage_analysis: Optional[ArbitrageAnalysis] = None\n",
    "models.py FundItem est_* 字段",
)

# ---------------- 3. fund_service.py: 导入 + 挂接 ----------------
patch(
    BE / "services" / "fund_service.py",
    "from services.akshare_client import get_session\n",
    "from services.akshare_client import get_session\nfrom services.cross_border_valuation import attach_estimated_valuations\n",
    "fund_service.py 导入",
)
patch(
    BE / "services" / "fund_service.py",
    "            \"change_pct\": _safe_float(_pick(item, \"涨跌幅\", \"增长率\")),\n        })\n",
    "            \"change_pct\": _safe_float(_pick(item, \"涨跌幅\", \"增长率\")),\n"
    "            # 净值日期：跨境篮子自算估值的基准日（53 fund_rank 提供）\n"
    "            \"nav_date\": _pick(item, \"净值日期\"),\n        })\n",
    "fund_service.py 基金dict增nav_date",
)
patch(
    BE / "services" / "fund_service.py",
    "    if fund_subtype == \"etf\":\n        _attach_kline_metrics(funds)\n",
    "    if fund_subtype == \"etf\":\n        _attach_kline_metrics(funds)\n"
    "    # 跨境 LOF/QDII 篮子自算估值（est_nav/est_premium_pct，参考 lofarb；缺数据不写）\n"
    "    if fund_subtype in (\"etf\", \"lof\", \"all\"):\n        attach_estimated_valuations(funds)\n",
    "fund_service.py 挂接估值",
)

# ---------------- 4. etf_service.py: _map_etf 补 nav_date + 挂接（延迟导入避免循环） ----------------
patch(
    BE / "services" / "etf_service.py",
    '        "change_pct": change_pct,\n        "subscribe_limit": subscribe_limit,\n',
    '        "change_pct": change_pct,\n        "nav": nav,\n        "nav_date": _pick(item, "净值日期"),\n'
    '        "subscribe_limit": subscribe_limit,\n',
    "etf_service.py _map_etf 增 nav/nav_date",
)
patch(
    BE / "services" / "etf_service.py",
    "    attach_subscription(result)\n    _attach_fee_info(result)\n    return result\n",
    "    attach_subscription(result)\n    _attach_fee_info(result)\n"
    "    # 跨境 ETF 篮子自算估值（513100/513300 等，参考 lofarb；缺数据不写）\n"
    "    from services.cross_border_valuation import attach_estimated_valuations\n\n"
    "    attach_estimated_valuations(result)\n    return result\n",
    "etf_service.py 挂接(两处)",
    count=2,
)

# ---------------- 5. 前端 types/index.ts ----------------
patch(
    FE / "types" / "index.ts",
    "  is_lof_convertible?: boolean   // 到期是否转LOF (决定折价收敛路径)\n  underlying_type?: string       // 底层资产类型\n}\n",
    "  is_lof_convertible?: boolean   // 到期是否转LOF (决定折价收敛路径)\n"
    "  // 篮子自算估值（跨境 LOF/QDII，参考 lofarb basket_valuation；null=数据不足未估算）\n"
    "  est_nav?: number | null        // 篮子自算预估净值\n"
    "  est_premium_pct?: number | null // 自算溢价率(%)：(现价-自算净值)/自算净值\n"
    "  est_base_date?: string         // 估值基准日(净值日期)\n"
    "  est_price_date?: string        // 底层行情取数日\n"
    "  est_position?: number          // 篮子仓位(%)\n"
    "  underlying_type?: string       // 底层资产类型\n}\n",
    "types/index.ts FundItem est 字段",
)

# ---------------- 6. LofFunds.vue: 溢价率列后插入自算净值/自算溢价两列 ----------------
patch(
    FE / "pages" / "LofFunds.vue",
    "        return h('span', { class: 'mono right', style: { color } }, text)\n      },\n    },\n    {\n      title: '百分位',\n",
    "        return h('span', { class: 'mono right', style: { color } }, text)\n      },\n    },\n"
    "    {\n"
    "      title: titleWithHelp('篮子自算净值', 'est_nav'),\n"
    "      key: 'est_nav',\n"
    "      align: 'right' as const,\n"
    "      render: (row: FundItem) => {\n"
    "        // 跨境LOF/QDII按底层篮子行情自算；position/篮子/行情缺一 → 后端不写 → '-'\n"
    "        if (row.est_nav == null) return h('span', { class: 'mono right' }, '-')\n"
    "        return h('span', { class: 'mono right' }, row.est_nav.toFixed(3))\n"
    "      },\n"
    "    },\n"
    "    {\n"
    "      title: titleWithHelp('自算溢价', 'est_premium_pct'),\n"
    "      key: 'est_premium_pct',\n"
    "      align: 'right' as const,\n"
    "      render: (row: FundItem) => {\n"
    "        if (row.est_premium_pct == null) return h('span', { class: 'mono right' }, '-')\n"
    "        const color = row.est_premium_pct >= 0 ? 'var(--color-danger)' : 'var(--color-success)'\n"
    "        const text = `${row.est_premium_pct >= 0 ? '+' : ''}${row.est_premium_pct.toFixed(2)}%`\n"
    "        return h('span', { class: 'mono right', style: { color } }, text)\n"
    "      },\n"
    "    },\n"
    "    {\n      title: '百分位',\n",
    "LofFunds.vue 新增两列",
)

# ---------------- 执行 ----------------
failed = False
for path, old, new, desc, count in edits:
    text = path.read_text(encoding="utf-8")
    n = text.count(old)
    if n < 1 or (count > 1 and n != count):
        print(f"[FAIL] {desc}: 锚点匹配 {n} 次(期望 {count}) -> {path}")
        failed = True
if failed:
    sys.exit(1)

for src, dst, mkdir in copies:
    dst = Path(dst)
    if mkdir:
        dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.copy2(dst, dst.with_suffix(dst.suffix + ".bak_valuation"))
    shutil.copy2(src, dst)
    print(f"[COPY] {src} -> {dst}")

for path, old, new, desc, count in edits:
    path = Path(path)
    if not path.with_suffix(path.suffix + ".bak_valuation").exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak_valuation"))
    text = path.read_text(encoding="utf-8")
    text = text.replace(old, new, count)
    path.write_text(text, encoding="utf-8", newline="")
    print(f"[OK] {desc}")

print("ALL DONE")
