"""交易台账服务 — 券商交割单为唯一事实源，派生每日成交 / 已清仓 / 做T / 胜率 / 费用 / 对账。

设计要点（2026-11-07）：
- 交割单是「成交流水的超集」：含成交编号、成交时间、佣金/印花税/过户费、实际收付金额。
  历史上 `biz_trades` 只存每日成交且没有费用，本服务把它作为**补充源**（交割单优先，按指纹去重）。
- 去重键：成交编号优先；无编号时用 (日期|代码|方向|价|量|时间|成交额) 的指纹，重复导入不会重复计入。
- 净收益一律「成交额 − 费用」，不用收盘价/持仓成本价估算；来自每日成交、费用缺失的记录
  标 `fee_estimated=True`，统计里单独计数并在对账 warnings 里提示。
- 做T口径：同日 + 同账户 + 同标的的买卖按 min(买量, 卖量) 配对，用当日买卖均价算毛利，
  按成交量占比分摊双边费用。A股 T+1 的「先卖后买」（用昨仓）与 T+0 品种的「先买后卖」分开标注。
- 已清仓回合：按 (账户, 代码) FIFO 配对，费用摊入买卖两侧，得到含费用的真实已实现盈亏。
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from core.config import USE_MOCK_DATA
from database.sqlite_connection import get_biz_db
from services.trades_service import get_trades

_TABLES_READY = False

# ============================================================
# 建表
# ============================================================

_SETTLEMENT_DDL = """
CREATE TABLE IF NOT EXISTS biz_settlements (
    id            TEXT PRIMARY KEY,
    fk_user       TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    settle_date   TEXT,
    trade_id      TEXT,
    code          TEXT DEFAULT '',
    name          TEXT DEFAULT '',
    type          TEXT DEFAULT 'stock',
    broker        TEXT DEFAULT '',
    account       TEXT DEFAULT '',
    direction     TEXT NOT NULL,
    entry_type    TEXT DEFAULT 'trade',
    price         REAL,
    quantity      REAL,
    amount        REAL,
    commission    REAL DEFAULT 0,
    stamp_tax     REAL DEFAULT 0,
    transfer_fee  REAL DEFAULT 0,
    other_fee     REAL DEFAULT 0,
    fee_total     REAL DEFAULT 0,
    net_amount    REAL,
    trade_time    TEXT,
    currency      TEXT DEFAULT 'CNY',
    source        TEXT DEFAULT '',
    created_at    TEXT
)
"""

_SETTLEMENT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_biz_settle_user_date ON biz_settlements(fk_user, trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_biz_settle_user_code ON biz_settlements(fk_user, code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_biz_settle_user_tradeid ON biz_settlements(fk_user, trade_id)",
]


def _ensure_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY or USE_MOCK_DATA:
        return
    db = get_biz_db()
    db.execute(_SETTLEMENT_DDL)
    for sql in _SETTLEMENT_INDEXES:
        try:
            db.execute(sql)
        except Exception as e:  # noqa: BLE001
            print(f"[trading] index skipped: {e}")
    _TABLES_READY = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 文件解析
# ============================================================

# 表头别名（已小写、去空格）。按具体 → 泛化排列，解析时优先精确匹配、再按别名长度做包含匹配。
_HEADER_ALIASES: dict[str, list[str]] = {
    "code": ["证券代码", "股票代码", "基金代码", "证券编号", "代码", "code", "symbol"],
    "name": ["证券名称", "股票名称", "证券简称", "基金名称", "名称", "name"],
    "trade_date": ["成交日期", "交易日期", "委托日期", "发生日期", "日期", "tradedate", "date"],
    "settle_date": ["交割日期", "交收日期", "结算日期", "settledate"],
    "trade_id": ["成交编号", "合同编号", "成交序号", "成交号", "委托编号", "流水号", "tradeid", "orderid"],
    "direction": ["买卖标志", "买卖方向", "业务标志", "业务名称", "摘要", "交易类别", "方向", "操作", "direction", "side"],
    "price": ["成交价格", "成交均价", "成交价", "价格", "price"],
    "quantity": ["成交数量", "成交股数", "成交手数", "数量", "quantity", "qty", "volume"],
    "amount": ["成交金额", "成交总额", "成交额", "amount"],
    "commission": ["佣金", "commission"],
    "stamp_tax": ["印花税", "印花税费"],
    "transfer_fee": ["过户费", "交易经手费", "经手费"],
    "other_fee": ["其他费用", "其它费用", "附加费", "结算费", "杂费"],
    "fee_total": ["费用合计", "手续费合计", "手续费", "费用总额", "总费用"],
    "net_amount": ["发生金额", "资金变动", "收付金额", "清算金额", "实际收付", "净额"],
    "trade_time": ["成交时间", "委托时间", "时间", "tradetime"],
    "account": ["股东账号", "股东代码", "资金账号", "资金帐号", "账户", "账号", "account"],
    "broker": ["券商名称", "营业部", "券商"],
    "currency": ["币种", "货币", "currency"],
    "type": ["证券类别", "品种", "类型", "type"],
}


def _norm_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _norm_header(v: Any) -> str:
    return _norm_text(v).lower().replace(" ", "").replace("\u3000", "").replace("\n", "")


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f if f == f else None
    s = str(v).strip().replace(",", "").replace("¥", "").replace("￥", "").replace(" ", "")
    if s in ("", "-", "--", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _norm_code(v: Any) -> str:
    s = _norm_text(v).strip().strip("'\"")
    if s.endswith(".0"):
        s = s[:-2]
    if s.isdigit() and len(s) < 6:
        s = s.zfill(6)
    return s


def _norm_date(v: Any) -> str:
    """兼容 datetime / Excel 序列号 / YYYYMMDD / YYYY-MM-DD / YYYY/MM/DD。"""
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float)) and 20000 < float(v) < 80000:
        return (date(1899, 12, 30) + timedelta(days=int(v))).strftime("%Y-%m-%d")
    s = _norm_text(v)
    if not s:
        return ""
    s = s.split(" ")[0].replace("/", "-").replace(".", "-")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if len(s) >= 10:
        candidate = s[:10]
        if candidate[4:5] == "-" and candidate[7:8] == "-":
            return candidate
    return ""


def _norm_time(v: Any) -> str:
    if isinstance(v, datetime):
        return v.strftime("%H:%M:%S")
    s = _norm_text(v)
    if not s:
        return ""
    if " " in s and len(s) >= 16:
        return s.split(" ", 1)[1][:8]
    return s[:8] if ":" in s else ""


def _parse_direction(raw: str) -> tuple[str, str]:
    """返回 (direction, entry_type)。业务名称里含「证券买入」等中文时优先按关键词判断。"""
    t = _norm_text(raw).replace(" ", "")
    low = t.lower()
    # 非交易流水（出入金 / 分红 / 利息）
    if any(k in t for k in ("股息", "红利", "分红", "派息")):
        return "dividend", "cash"
    if any(k in t for k in ("结息", "利息")):
        return "interest", "cash"
    if any(k in t for k in ("银行转存", "银行转入", "资金存入", "转入", "存入")):
        return "cash_in", "cash"
    if any(k in t for k in ("银行转取", "银行转出", "资金取出", "转出", "取出")):
        return "cash_out", "cash"
    # 买卖方向：先判卖，避免「证券买入卖出」之类误判
    if any(k in t for k in ("卖出", "卖空", "证券卖", "赎回", "sell", "sale")) or low in ("卖", "s", "2", "-1"):
        return "sell", "trade"
    if any(k in t for k in ("买入", "买进", "证券买", "申购", "buy")) or low in ("买", "b", "1"):
        return "buy", "trade"
    return "other", "other"


def _map_header(cells: list[Any]) -> dict[str, int]:
    norm = [_norm_header(c) for c in cells]
    mapping: dict[str, int] = {}
    # 1) 精确匹配
    for field, aliases in _HEADER_ALIASES.items():
        for i, c in enumerate(norm):
            if c and c in aliases and field not in mapping and i not in mapping.values():
                mapping[field] = i
                break
    # 2) 包含匹配：长别名优先，避免「手续费」抢占「手续费合计」
    pairs = sorted(
        ((a, f) for f, aliases in _HEADER_ALIASES.items() for a in aliases),
        key=lambda x: -len(x[0]),
    )
    for alias, field in pairs:
        if field in mapping:
            continue
        for i, c in enumerate(norm):
            if c and alias in c and i not in mapping.values():
                mapping[field] = i
                break
    return mapping


def _find_header(rows: list[list[Any]]) -> tuple[int, list[Any]]:
    """跳过券商导出的标题/合并单元格行，定位真正的表头。"""
    for i, row in enumerate(rows[:25]):
        mapping = _map_header(row)
        if "code" in mapping and len(mapping) >= 4:
            return i, row
    # 退而求其次：含「成交日期」+ 至少 3 列
    for i, row in enumerate(rows[:25]):
        mapping = _map_header(row)
        if "trade_date" in mapping and len(mapping) >= 3:
            return i, row
    return -1, []


def _read_rows(content: bytes, filename: str) -> list[list[Any]]:
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm")):
        try:
            from openpyxl import load_workbook
        except ImportError as e:  # pragma: no cover
            raise ValueError("服务端缺少 openpyxl，无法读取 .xlsx，请先安装依赖或另存为 CSV") from e
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            ws = wb[wb.sheetnames[0]]
            return [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    text = None
    for enc in ("utf-8-sig", "gbk", "gb2312", "utf-8"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("无法识别文件编码（支持 UTF-8 / GBK）")
    return [list(r) for r in csv.reader(io.StringIO(text))]


def _fingerprint(r: dict[str, Any]) -> str:
    raw = "|".join(
        str(r.get(k) or "")
        for k in ("trade_date", "code", "direction", "price", "quantity", "trade_time", "amount")
    )
    return "fp:" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:20]


def _parse_file_rows(
    rows: list[list[Any]], default_broker: str, default_account: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    header_idx, header = _find_header(rows)
    if header_idx < 0:
        return [], [{"row": 0, "code": "", "reason": "未识别到表头（需含证券代码、成交日期、买卖标志等列）"}]
    mapping = _map_header(header)
    out: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for offset, raw in enumerate(rows[header_idx + 1:]):
        row_no = header_idx + 2 + offset
        if not any(_norm_text(c) for c in raw):
            continue

        def g(field: str) -> Any:
            i = mapping.get(field)
            return raw[i] if i is not None and i < len(raw) else None

        code = _norm_code(g("code"))
        trade_date = _norm_date(g("trade_date"))
        dir_raw = _norm_text(g("direction"))
        direction, entry_type = _parse_direction(dir_raw)
        # 合计 / 说明行
        if not code and not dir_raw:
            continue
        if not trade_date:
            failed.append({"row": row_no, "code": code, "reason": "成交日期无法解析"})
            continue
        if direction == "other":
            failed.append({"row": row_no, "code": code, "reason": f"未识别的业务类型：{dir_raw or '空'}"})
            continue

        price = _safe_float(g("price"))
        quantity = _safe_float(g("quantity"))
        amount = _safe_float(g("amount"))
        commission = _safe_float(g("commission")) or 0.0
        stamp_tax = _safe_float(g("stamp_tax")) or 0.0
        transfer_fee = _safe_float(g("transfer_fee")) or 0.0
        other_fee = _safe_float(g("other_fee")) or 0.0
        fee_total_given = _safe_float(g("fee_total"))
        parts = commission + stamp_tax + transfer_fee + other_fee
        fee_total = parts if parts else (fee_total_given or 0.0)
        net_amount = _safe_float(g("net_amount"))

        if entry_type == "trade":
            if not code:
                failed.append({"row": row_no, "code": code, "reason": "成交行缺少证券代码"})
                continue
            if price is None or quantity is None or price <= 0 or quantity <= 0:
                failed.append({"row": row_no, "code": code, "reason": "成交价/数量须为正数值"})
                continue
            if amount is None:
                amount = round(price * quantity, 2)
            if net_amount is None:
                net_amount = round(-(amount + fee_total) if direction == "buy" else amount - fee_total, 2)
        else:
            price = price or 0.0
            quantity = quantity or 0.0
            amount = amount or 0.0
            if net_amount is None:
                net_amount = 0.0

        trade_id = _norm_text(g("trade_id"))
        account = _norm_text(g("account")) or default_account
        broker = _norm_text(g("broker")) or default_broker
        trade_time = _norm_time(g("trade_time"))
        rec: dict[str, Any] = {
            "trade_date": trade_date,
            "settle_date": _norm_date(g("settle_date")) or None,
            "trade_id": trade_id,
            "code": code,
            "name": _norm_text(g("name")),
            "type": _norm_text(g("type")) or "stock",
            "broker": broker,
            "account": account,
            "direction": direction,
            "entry_type": entry_type,
            "price": price,
            "quantity": quantity,
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "stamp_tax": round(stamp_tax, 2),
            "transfer_fee": round(transfer_fee, 2),
            "other_fee": round(other_fee, 2),
            "fee_total": round(fee_total, 2),
            "net_amount": round(net_amount, 2),
            "trade_time": trade_time,
            "currency": _norm_text(g("currency")) or "CNY",
            "source": "settlement",
        }
        rec["trade_id"] = trade_id or _fingerprint(rec)
        out.append(rec)
    return out, failed


# ============================================================
# 导入 / 查询
# ============================================================

_INSERT_COLS = (
    "id, fk_user, trade_date, settle_date, trade_id, code, name, type, broker, account, "
    "direction, entry_type, price, quantity, amount, commission, stamp_tax, transfer_fee, "
    "other_fee, fee_total, net_amount, trade_time, currency, source, created_at"
)


def import_settlements(
    user_id: str,
    content: bytes,
    filename: str,
    broker: str = "",
    account: str = "",
    mode: str = "merge",
) -> dict[str, Any]:
    """导入券商交割单（.xlsx/.csv/.txt）。merge 跳过重复成交编号，replace 先清空涉及日期再导入。"""
    rows = _read_rows(content, filename)
    parsed, failed = _parse_file_rows(rows, broker, account)
    total = len(parsed) + len(failed)
    if not parsed:
        return {
            "total": total, "inserted": 0, "duplicates": 0, "failed": failed,
            "date_from": None, "date_to": None, "brokers": [],
        }
    if USE_MOCK_DATA:
        return {
            "total": total, "inserted": len(parsed), "duplicates": 0, "failed": failed,
            "date_from": min(r["trade_date"] for r in parsed),
            "date_to": max(r["trade_date"] for r in parsed),
            "brokers": sorted({r["broker"] for r in parsed if r["broker"]}),
        }

    _ensure_tables()
    db = get_biz_db()
    dates = sorted({r["trade_date"] for r in parsed})
    if mode == "replace":
        placeholders = ",".join("?" * len(dates))
        db.execute(
            f"DELETE FROM biz_settlements WHERE fk_user = ? AND trade_date IN ({placeholders})",
            [user_id, *dates],
        )
    existing = {
        r[0]
        for r in db.fetchall(
            "SELECT trade_id FROM biz_settlements WHERE fk_user = ?", [user_id]
        )
    }
    seen: set[str] = set()
    fresh: list[dict[str, Any]] = []
    duplicates = 0
    for rec in parsed:
        key = rec["trade_id"]
        if key in existing or key in seen:
            duplicates += 1
            continue
        seen.add(key)
        fresh.append(rec)
    if fresh:
        now = _now_iso()
        db.executemany(
            f"INSERT OR IGNORE INTO biz_settlements ({_INSERT_COLS}) "
            f"VALUES ({','.join('?' * len(_INSERT_COLS.split(',')))})",
            [
                [
                    str(uuid.uuid4()), user_id, r["trade_date"], r["settle_date"], r["trade_id"],
                    r["code"], r["name"], r["type"], r["broker"], r["account"], r["direction"],
                    r["entry_type"], r["price"], r["quantity"], r["amount"], r["commission"],
                    r["stamp_tax"], r["transfer_fee"], r["other_fee"], r["fee_total"],
                    r["net_amount"], r["trade_time"], r["currency"], r["source"], now,
                ]
                for r in fresh
            ],
        )
    return {
        "total": total,
        "inserted": len(fresh),
        "duplicates": duplicates,
        "failed": failed,
        "date_from": dates[0],
        "date_to": dates[-1],
        "brokers": sorted({r["broker"] for r in fresh if r["broker"]}),
    }


_SETTLEMENT_SELECT = (
    "SELECT id, trade_date, settle_date, trade_id, code, name, type, broker, account, "
    "direction, entry_type, price, quantity, amount, commission, stamp_tax, transfer_fee, "
    "other_fee, fee_total, net_amount, trade_time, currency, source FROM biz_settlements"
)


def _row_to_settlement(r: tuple) -> dict[str, Any]:
    return {
        "id": r[0], "trade_date": r[1], "settle_date": r[2], "trade_id": r[3],
        "code": r[4], "name": r[5] or "", "type": r[6] or "", "broker": r[7] or "",
        "account": r[8] or "", "direction": r[9], "entry_type": r[10] or "trade",
        "price": r[11], "quantity": r[12], "amount": r[13],
        "commission": r[14] or 0, "stamp_tax": r[15] or 0, "transfer_fee": r[16] or 0,
        "other_fee": r[17] or 0, "fee_total": r[18] or 0, "net_amount": r[19],
        "trade_time": r[20], "currency": r[21] or "CNY", "source": r[22] or "",
    }


def list_settlements(
    user_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    code: str | None = None,
    direction: str | None = None,
    limit: int = 5000,
) -> dict[str, Any]:
    if USE_MOCK_DATA:
        return {"items": [], "total": 0, "date_from": None, "date_to": None}
    _ensure_tables()
    where = ["fk_user = ?"]
    args: list[Any] = [user_id]
    if date_from:
        where.append("trade_date >= ?")
        args.append(date_from)
    if date_to:
        where.append("trade_date <= ?")
        args.append(date_to)
    if code:
        where.append("code LIKE ?")
        args.append(f"%{code}%")
    if direction:
        where.append("direction = ?")
        args.append(direction)
    clause = " AND ".join(where)
    db = get_biz_db()
    total = db.fetchone(f"SELECT COUNT(*) FROM biz_settlements WHERE {clause}", args)[0]
    rows = db.fetchall(
        f"{_SETTLEMENT_SELECT} WHERE {clause} ORDER BY trade_date DESC, trade_time DESC, id DESC LIMIT ?",
        [*args, max(1, min(int(limit or 5000), 50000))],
    )
    items = [_row_to_settlement(r) for r in rows]
    bounds = db.fetchone(
        "SELECT MIN(trade_date), MAX(trade_date) FROM biz_settlements WHERE fk_user = ?", [user_id]
    )
    return {
        "items": items,
        "total": int(total),
        "date_from": bounds[0] if bounds else None,
        "date_to": bounds[1] if bounds else None,
    }


def clear_settlements(user_id: str, trade_date: str) -> dict[str, int]:
    if USE_MOCK_DATA:
        return {"deleted": 0}
    _ensure_tables()
    db = get_biz_db()
    cur = db.execute(
        "DELETE FROM biz_settlements WHERE fk_user = ? AND trade_date = ?",
        [user_id, trade_date],
    )
    return {"deleted": max(cur.rowcount, 0)}


def import_daily(
    user_id: str, trade_date: str, items: list[dict[str, Any]], source: str = "web"
) -> dict[str, Any]:
    """JWT 版每日成交导入，复用 trades_service 的按日覆盖语义。"""
    from services.trades_service import import_trades

    return import_trades(user_id, trade_date, items, source=source)


# ============================================================
# 合并流水
# ============================================================


def _norm_record(r: dict[str, Any], is_daily: bool) -> dict[str, Any]:
    amount = float(r.get("amount") or 0)
    price = float(r.get("price") or 0)
    quantity = float(r.get("quantity") or 0)
    if amount <= 0 and price > 0 and quantity > 0:
        amount = price * quantity
    fee = float(r.get("fee_total") if not is_daily else (r.get("fee") or 0) or 0)
    return {
        "trade_date": str(r.get("trade_date") or ""),
        "trade_time": str(r.get("trade_time") or ""),
        "code": str(r.get("code") or ""),
        "name": str(r.get("name") or ""),
        "account": str(r.get("account") or ""),
        "broker": str(r.get("broker") or ""),
        "direction": str(r.get("direction") or ""),
        "price": price,
        "quantity": quantity,
        "amount": amount,
        "fee_total": fee,
        "fee_estimated": is_daily and fee == 0,
        "source": str(r.get("source") or ("daily" if is_daily else "settlement")),
        "trade_id": str(r.get("trade_id") or ""),
    }


def _daily_fingerprint(r: dict[str, Any]) -> str:
    raw = "|".join(
        str(r.get(k) or "")
        for k in ("trade_date", "code", "direction", "price", "quantity", "trade_time", "amount")
    )
    return "fp:" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:20]


def _load_merged(
    user_id: str, date_from: str | None, date_to: str | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """交割单优先；每日成交里与交割单重复的跳过，其余作为补充（费用可能缺失）。"""
    settle_all = list_settlements(user_id, date_from, date_to, limit=50000)["items"]
    settle_trades = [r for r in settle_all if r["entry_type"] == "trade" and r["direction"] in ("buy", "sell")]
    records = [_norm_record(r, False) for r in settle_trades]
    settle_keys = {_fingerprint(r) for r in settle_trades}
    settle_keys |= {r["trade_id"] for r in settle_trades if r["trade_id"] and not r["trade_id"].startswith("fp:")}

    daily_rows = get_trades(user_id) or []
    daily_used = 0
    for r in daily_rows:
        d = str(r.get("trade_date") or "")
        if date_from and d < date_from:
            continue
        if date_to and d > date_to:
            continue
        fp = _daily_fingerprint(r)
        # 每日成交里的 price/amount 与交割单可能略有差异，用 code+date+direction+qty 再兜一层
        loose = f"{d}|{r.get('code')}|{r.get('direction')}|{r.get('quantity')}"
        if fp in settle_keys or loose in settle_keys:
            continue
        settle_keys.add(loose)
        records.append(_norm_record(r, True))
        daily_used += 1

    records.sort(key=lambda x: (x["trade_date"], x["trade_time"], x["code"], x["direction"]))
    meta = {
        "settlement_rows": len(settle_trades),
        "settlement_all_rows": len(settle_all),
        "daily_rows": len(daily_rows),
        "daily_used_rows": daily_used,
        "merged_rows": len(records),
        "fee_estimated_rows": sum(1 for r in records if r["fee_estimated"]),
        "date_from": records[0]["trade_date"] if records else None,
        "date_to": records[-1]["trade_date"] if records else None,
    }
    return records, meta


# ============================================================
# 每日成交
# ============================================================


def get_daily_trades(
    user_id: str, date_from: str | None = None, date_to: str | None = None, code: str | None = None
) -> dict[str, Any]:
    records, meta = _load_merged(user_id, date_from, date_to)
    if code:
        records = [r for r in records if code.lower() in r["code"].lower() or code in r["name"]]
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_day[r["trade_date"]].append(r)
    t_map = {t["trade_date"] + "|" + t["code"] + "|" + t["account"]: t for t in _compute_t_trades(records)["items"]}
    days: list[dict[str, Any]] = []
    for d in sorted(by_day):
        rs = by_day[d]
        buy_amount = sum(r["amount"] for r in rs if r["direction"] == "buy")
        sell_amount = sum(r["amount"] for r in rs if r["direction"] == "sell")
        fee = sum(r["fee_total"] for r in rs)
        t_net = sum(
            v["net_pnl"]
            for k, v in t_map.items()
            if k.startswith(d + "|")
        )
        days.append({
            "trade_date": d,
            "trade_count": len(rs),
            "buy_amount": round(buy_amount, 2),
            "sell_amount": round(sell_amount, 2),
            "net_amount": round(sell_amount - buy_amount, 2),
            "fee_total": round(fee, 2),
            "code_count": len({r["code"] for r in rs}),
            "t_net_pnl": round(t_net, 2),
        })
    items = [
        {
            "trade_date": r["trade_date"], "trade_time": r["trade_time"], "code": r["code"],
            "name": r["name"], "direction": r["direction"], "price": r["price"],
            "quantity": r["quantity"], "amount": round(r["amount"], 2),
            "fee_total": round(r["fee_total"], 2), "account": r["account"], "source": r["source"],
        }
        for r in records
    ]
    return {
        "dates": sorted(by_day),
        "days": days,
        "items": items,
        "settlement_rows": meta["settlement_rows"],
        "daily_rows": meta["daily_used_rows"],
    }


# ============================================================
# 做T / 回合 / 分析
# ============================================================


def _compute_t_trades(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        groups[(r["trade_date"], r["account"], r["code"])].append(r)
    items: list[dict[str, Any]] = []
    for (d, account, code), rs in groups.items():
        buys = [r for r in rs if r["direction"] == "buy"]
        sells = [r for r in rs if r["direction"] == "sell"]
        if not buys or not sells:
            continue
        buy_qty = sum(r["quantity"] for r in buys)
        sell_qty = sum(r["quantity"] for r in sells)
        t_qty = min(buy_qty, sell_qty)
        if t_qty <= 0:
            continue
        buy_amt = sum(r["amount"] for r in buys)
        sell_amt = sum(r["amount"] for r in sells)
        buy_avg = buy_amt / buy_qty
        sell_avg = sell_amt / sell_qty
        gross = (sell_avg - buy_avg) * t_qty
        total_fee = sum(r["fee_total"] for r in rs)
        fee_alloc = total_fee * min(1.0, (2 * t_qty) / (buy_qty + sell_qty))
        first_dir = rs[0]["direction"]
        alternations = sum(
            1 for a, b in zip(rs, rs[1:]) if a["direction"] != b["direction"]
        )
        if alternations >= 2 and len(rs) > 2:
            pattern = "mixed"
        else:
            pattern = "sell_then_buy" if first_dir == "sell" else "buy_then_sell"
        items.append({
            "trade_date": d,
            "code": code,
            "name": next((r["name"] for r in rs if r["name"]), code),
            "account": account,
            "t_quantity": round(t_qty, 4),
            "buy_avg": round(buy_avg, 4),
            "sell_avg": round(sell_avg, 4),
            "gross_pnl": round(gross, 2),
            "fee_alloc": round(fee_alloc, 2),
            "net_pnl": round(gross - fee_alloc, 2),
            "closed": abs(buy_qty - sell_qty) < 1e-6,
            "pattern": pattern,
            "trade_count": len(rs),
        })
    items.sort(key=lambda x: (x["trade_date"], x["code"]))
    wins = [i for i in items if i["net_pnl"] > 0]
    nets = [i["net_pnl"] for i in items]
    summary = {
        "count": len(items),
        "win_count": len(wins),
        "win_rate": round(len(wins) / len(items) * 100, 2) if items else 0.0,
        "total_gross": round(sum(i["gross_pnl"] for i in items), 2),
        "total_fee": round(sum(i["fee_alloc"] for i in items), 2),
        "total_net": round(sum(nets), 2),
        "avg_net": round(sum(nets) / len(nets), 2) if nets else 0.0,
        "best_net": round(max(nets), 2) if nets else 0.0,
        "worst_net": round(min(nets), 2) if nets else 0.0,
        "fee_eroded_count": sum(1 for i in items if i["gross_pnl"] > 0 and i["net_pnl"] <= 0),
        "closed_count": sum(1 for i in items if i["closed"]),
        "sell_then_buy_count": sum(1 for i in items if i["pattern"] == "sell_then_buy"),
        "buy_then_sell_count": sum(1 for i in items if i["pattern"] == "buy_then_sell"),
    }
    return {"items": items, "summary": summary}


def _group_stats(
    items: list[dict[str, Any]], key: str, label_from_key: bool = False
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for i in items:
        groups[str(i.get(key) or "")].append(i)
    out = []
    for k, rs in groups.items():
        net = sum(r.get("net_pnl", r.get("realized_pnl", 0)) or 0 for r in rs)
        wins = sum(1 for r in rs if (r.get("net_pnl", r.get("realized_pnl", 0)) or 0) > 0)
        out.append({
            "key": k,
            "label": k if label_from_key else next((r.get("name") or k for r in rs if r.get("name")), k),
            "count": len(rs),
            "net_pnl": round(net, 2),
            "win_count": wins,
            "win_rate": round(wins / len(rs) * 100, 2) if rs else 0.0,
            "fee": round(sum(r.get("fee_alloc", r.get("fee_total", 0)) or 0 for r in rs), 2),
        })
    out.sort(key=lambda x: x["net_pnl"], reverse=True)
    return out


def _days_between(a: str, b: str) -> int:
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (ValueError, TypeError):
        return 0


def _compute_rounds(records: list[dict[str, Any]]) -> dict[str, Any]:
    """按 (账户, 代码) FIFO 配对，费用摊入买卖两侧；返回已清仓回合与未平仓重建持仓。"""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        groups[(r["account"], r["code"])].append(r)
    rounds: list[dict[str, Any]] = []
    open_positions: list[dict[str, Any]] = []

    for (account, code), rs in groups.items():
        queue: list[dict[str, Any]] = []
        for r in rs:
            qty = r["quantity"]
            if qty <= 0:
                continue
            if r["direction"] == "buy":
                queue.append({
                    "qty": qty, "price": r["price"], "amount": r["amount"],
                    "fee": r["fee_total"], "date": r["trade_date"],
                    "name": r["name"], "broker": r["broker"],
                    "fee_estimated": r["fee_estimated"],
                })
                continue
            if r["direction"] != "sell" or not queue:
                continue
            remaining = qty
            sell_fee_per_qty = r["fee_total"] / qty
            matched_qty = 0.0
            buy_amount = 0.0
            buy_fee = 0.0
            weighted_days = 0.0
            buy_dates: list[str] = []
            fee_estimated = r["fee_estimated"]
            while remaining > 1e-9 and queue:
                lot = queue[0]
                take = min(lot["qty"], remaining)
                ratio = take / lot["qty"]
                buy_amount += lot["amount"] * ratio
                buy_fee += lot["fee"] * ratio
                weighted_days += take * _days_between(lot["date"], r["trade_date"])
                buy_dates.append(lot["date"])
                fee_estimated = fee_estimated or lot["fee_estimated"]
                matched_qty += take
                lot["qty"] -= take
                lot["amount"] -= lot["amount"] * ratio
                lot["fee"] -= lot["fee"] * ratio
                remaining -= take
                if lot["qty"] <= 1e-9:
                    queue.pop(0)
            if matched_qty <= 0:
                continue
            sell_amount = r["amount"] * (matched_qty / qty)
            sell_fee = sell_fee_per_qty * matched_qty
            gross = sell_amount - buy_amount
            fee = buy_fee + sell_fee
            realized = gross - fee
            cost_basis = buy_amount + buy_fee + sell_fee
            rounds.append({
                "code": code,
                "name": r["name"] or next((l["name"] for l in queue), code),
                "account": account,
                "broker": r["broker"],
                "quantity": round(matched_qty, 4),
                "buy_avg_price": round(buy_amount / matched_qty, 4),
                "sell_avg_price": round(sell_amount / matched_qty, 4),
                "buy_date": min(buy_dates) if buy_dates else r["trade_date"],
                "sell_date": r["trade_date"],
                "holding_days": round(weighted_days / matched_qty, 1),
                "gross_pnl": round(gross, 2),
                "fee_total": round(fee, 2),
                "realized_pnl": round(realized, 2),
                "return_pct": round(realized / cost_basis * 100, 2) if cost_basis else 0.0,
                "fee_estimated": fee_estimated,
            })
        if queue:
            total_qty = sum(l["qty"] for l in queue)
            total_cost = sum(l["amount"] + l["fee"] for l in queue)
            open_positions.append({
                "code": code,
                "name": next((l["name"] for l in queue if l["name"]), code),
                "account": account,
                "quantity": round(total_qty, 4),
                "cost_price": round(total_cost / total_qty, 4) if total_qty else 0.0,
                "first_buy_date": min(l["date"] for l in queue),
                "fee_in_cost": round(sum(l["fee"] for l in queue), 2),
            })

    rounds.sort(key=lambda x: (x["sell_date"], x["code"]))
    open_positions.sort(key=lambda x: x["code"])
    return {"rounds": rounds, "open_positions": open_positions}


def _round_summary(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [r["realized_pnl"] for r in rounds]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_win = sum(wins)
    total_loss = abs(sum(losses))
    win_rounds = [r for r in rounds if r["realized_pnl"] > 0]
    loss_rounds = [r for r in rounds if r["realized_pnl"] < 0]
    return {
        "count": len(rounds),
        "win_count": len(wins),
        "win_rate": round(len(wins) / len(rounds) * 100, 2) if rounds else 0.0,
        "total_pnl": round(sum(pnls), 2),
        "avg_win": round(total_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-total_loss / len(losses), 2) if losses else 0.0,
        "profit_factor": round(total_win / total_loss, 2) if total_loss else 0.0,
        "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "best_pnl": round(max(pnls), 2) if pnls else 0.0,
        "worst_pnl": round(min(pnls), 2) if pnls else 0.0,
        "avg_holding_days": round(sum(r["holding_days"] for r in rounds) / len(rounds), 1) if rounds else 0.0,
        "avg_hold_days_win": round(sum(r["holding_days"] for r in win_rounds) / len(win_rounds), 1) if win_rounds else 0.0,
        "avg_hold_days_loss": round(sum(r["holding_days"] for r in loss_rounds) / len(loss_rounds), 1) if loss_rounds else 0.0,
    }


def _imported_positions(user_id: str) -> dict[tuple[str, str], float]:
    if USE_MOCK_DATA:
        return {}
    try:
        db = get_biz_db()
        rows = db.fetchall(
            "SELECT code, COALESCE(account, ''), SUM(quantity) FROM biz_holdings "
            "WHERE fk_user = ? AND COALESCE(is_closed, 0) = 0 GROUP BY code, COALESCE(account, '')",
            [user_id],
        )
        return {(str(r[0]), str(r[1] or "")): float(r[2] or 0) for r in rows}
    except Exception as e:  # noqa: BLE001
        print(f"[trading] imported positions unavailable: {e}")
        return {}


def get_closed_rounds(user_id: str) -> dict[str, Any]:
    records, _ = _load_merged(user_id, None, None)
    computed = _compute_rounds(records)
    rounds = computed["rounds"]
    s = _round_summary(rounds)
    return {
        "items": rounds,
        "open_positions": computed["open_positions"],
        "summary": {
            "round_count": s["count"],
            "win_count": s["win_count"],
            "win_rate": s["win_rate"],
            "total_realized_pnl": s["total_pnl"],
            "total_fee": round(sum(r["fee_total"] for r in rounds), 2),
            "avg_holding_days": s["avg_holding_days"],
        },
    }


def get_analysis(
    user_id: str, date_from: str | None = None, date_to: str | None = None
) -> dict[str, Any]:
    records, meta = _load_merged(user_id, date_from, date_to)
    t_block = _compute_t_trades(records)
    computed = _compute_rounds(records)
    rounds = computed["rounds"]
    r_summary = _round_summary(rounds)
    t_items = t_block["items"]

    settle_all = list_settlements(user_id, date_from, date_to, limit=50000)["items"]
    trade_rows = [r for r in settle_all if r["entry_type"] == "trade"]
    fee_parts = {
        "commission": round(sum(r["commission"] or 0 for r in trade_rows), 2),
        "stamp_tax": round(sum(r["stamp_tax"] or 0 for r in trade_rows), 2),
        "transfer_fee": round(sum(r["transfer_fee"] or 0 for r in trade_rows), 2),
        "other_fee": round(sum(r["other_fee"] or 0 for r in trade_rows), 2),
    }
    total_fee = round(sum(r["fee_total"] or 0 for r in trade_rows), 2)
    gross_abs = abs(sum(i["gross_pnl"] for i in t_items)) or abs(sum(r["gross_pnl"] for r in rounds))
    fees = {
        "total_fee": total_fee,
        **fee_parts,
        "unallocated_fee": round(total_fee - sum(fee_parts.values()), 2),
        "fee_to_gross_pct": round(total_fee / gross_abs * 100, 2) if gross_abs else 0.0,
        "small_order_count": sum(
            1 for r in trade_rows
            if (r["amount"] or 0) < 10000 and (r["commission"] or 0) >= 5
        ),
        "estimated_fee_rows": meta["fee_estimated_rows"],
    }

    trade_days = sorted({r["trade_date"] for r in records})
    code_counts: dict[str, int] = defaultdict(int)
    for r in records:
        code_counts[r["code"]] += 1
    most_code = max(code_counts, key=code_counts.get) if code_counts else ""
    behavior = {
        "avg_hold_days_win": r_summary["avg_hold_days_win"],
        "avg_hold_days_loss": r_summary["avg_hold_days_loss"],
        "disposition_gap": round(r_summary["avg_hold_days_loss"] - r_summary["avg_hold_days_win"], 1),
        "trade_days": len(trade_days),
        "avg_trades_per_day": round(len(records) / len(trade_days), 2) if trade_days else 0.0,
        "most_traded_code": most_code,
        "most_traded_count": code_counts.get(most_code, 0),
    }

    imported = _imported_positions(user_id)
    ledger_map = {
        (p["code"], p["account"]): p["quantity"] for p in computed["open_positions"]
    }
    keys = sorted(set(ledger_map) | set(imported)) if imported else []
    holding_diff = []
    for code, account in keys:
        lq = ledger_map.get((code, account), 0.0)
        iq = imported.get((code, account), 0.0)
        if abs(lq - iq) > 1e-6:
            holding_diff.append({
                "code": code, "account": account,
                "ledger_qty": round(lq, 4), "imported_qty": round(iq, 4),
                "diff": round(lq - iq, 4),
            })
    if USE_MOCK_DATA:
        db = None
        dup = 0
    else:
        db = get_biz_db()
        dup_row = db.fetchone(
            "SELECT COUNT(*) - COUNT(DISTINCT trade_id) FROM biz_settlements WHERE fk_user = ?",
            [user_id],
        )
        dup = int(dup_row[0] or 0) if dup_row else 0
    warnings: list[str] = []
    if meta["settlement_rows"] == 0:
        warnings.append("尚未导入券商交割单；当前分析仅基于每日成交，费用与成交编号可能缺失")
    if meta["fee_estimated_rows"]:
        warnings.append(f"{meta['fee_estimated_rows']} 条成交来自每日成交且无费用明细，净收益不含这部分费用")
    if holding_diff:
        warnings.append(f"{len(holding_diff)} 个标的的持仓数量与流水重建结果不一致，请核对是否漏导成交或持仓未更新")
    if dup:
        warnings.append(f"检测到 {dup} 条重复成交编号，请检查是否重复导入")
    if not records:
        warnings.append("当前筛选区间内没有成交记录")
    if not imported:
        warnings.append("尚未导入当前持仓，已跳过「持仓数量 vs 流水重建」对账")
    if r_summary["count"] and r_summary["win_count"] == r_summary["count"]:
        warnings.append("统计区间内无亏损回合，盈亏比不适用（显示为 0）")

    month_items = [
        {**i, "month": i["sell_date"][:7], "net_pnl": i["realized_pnl"]}
        for i in rounds
    ]
    t_month_items = [{**i, "month": i["trade_date"][:7]} for i in t_items]

    return {
        "meta": {
            "settlement_rows": meta["settlement_rows"],
            "daily_rows": meta["daily_used_rows"],
            "merged_rows": meta["merged_rows"],
            "fee_estimated_rows": meta["fee_estimated_rows"],
            "date_from": meta["date_from"] or date_from,
            "date_to": meta["date_to"] or date_to,
        },
        "t_trades": {
            "items": t_items,
            "summary": t_block["summary"],
            "by_code": _group_stats(t_items, "code"),
            "by_month": _group_stats(t_month_items, "month", label_from_key=True),
        },
        "rounds": {
            "summary": r_summary,
            "by_code": _group_stats(rounds, "code"),
            "by_month": _group_stats(month_items, "month", label_from_key=True),
            "by_account": _group_stats(rounds, "account", label_from_key=True),
        },
        "fees": fees,
        "behavior": behavior,
        "reconciliation": {
            "settlement_rows": meta["settlement_rows"],
            "daily_rows": meta["daily_used_rows"],
            "unmatched_daily": meta["daily_used_rows"],
            "duplicate_ids": dup,
            "holding_diff": holding_diff,
            "warnings": warnings,
        },
    }
