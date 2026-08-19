"""Holdings service — 多券商统一持仓：CRUD、批量导入、行情盈亏计算、每日快照。

设计原则（与其他服务一致）：
- 行情获取失败时 price 置 None，前端显示“—”，绝不虚构数值；
- mock 模式使用进程内存存储；DuckDB 模式首次使用时懒创建 biz_holdings /
  biz_holding_snapshots 两张表，避免依赖 init_db。
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from database.connection import get_db
from core.config import USE_MOCK_DATA
from services.akshare_client import akshare_request

# ============================================================
# 常量
# ============================================================

HOLDING_TYPES: dict[str, str] = {
    "stock": "股票",
    "etf": "场内基金",
    "fund_otc": "场外基金",
    "option": "期权",
    "future": "期货",
    "hk_stock": "港股",
}

# 行情缓存：{ "ts": float, "quotes": { code: {"price": x, "prev_close": y} } }
_QUOTE_CACHE: dict[str, Any] = {"ts": 0.0, "quotes": {}}
_QUOTE_TTL = 60  # 秒

# mock 模式内存存储
_mock_holdings: dict[str, list[dict]] = {}
_mock_snapshots: dict[str, list[dict]] = {}

_TABLES_READY = False


# ============================================================
# DuckDB 懒建表
# ============================================================

def _ensure_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY or USE_MOCK_DATA:
        return
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_holdings (
            id               VARCHAR PRIMARY KEY,
            user_id          VARCHAR NOT NULL,
            code             VARCHAR(20) NOT NULL,
            name             VARCHAR(100) NOT NULL,
            type             VARCHAR(20) NOT NULL,
            broker           VARCHAR(50) DEFAULT '',
            account          VARCHAR(50) DEFAULT '',
            quantity         DOUBLE NOT NULL,
            cost_price       DOUBLE NOT NULL,
            manual_price     DOUBLE,
            stop_loss_pct    DOUBLE,
            take_profit_pct  DOUBLE,
            open_date        VARCHAR(10),
            currency         VARCHAR(8) DEFAULT 'CNY',
            created_at       VARCHAR,
            updated_at       VARCHAR,
            fair_value       DOUBLE
        )
        """
    )
    # 兼容旧库：缺失新列时增量迁移（DuckDB 不支持 ADD COLUMN IF NOT EXISTS）
    for col, dtype in (("stop_loss_pct", "DOUBLE"), ("take_profit_pct", "DOUBLE"), ("fair_value", "DOUBLE"),
                       ("grid_lower", "DOUBLE"), ("grid_upper", "DOUBLE"), ("grid_step", "DOUBLE")):
        try:
            db.execute(f"ALTER TABLE biz_holdings ADD COLUMN {col} {dtype}")
        except Exception as e:  # noqa: BLE001
            if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                import sys
                print(f"[MIGRATE] ALTER {col} failed: {e!r}", file=sys.stderr, flush=True)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_holding_snapshots (
            id                 VARCHAR PRIMARY KEY,
            user_id            VARCHAR NOT NULL,
            snap_date          VARCHAR(10) NOT NULL,
            total_market_value DOUBLE,
            total_cost         DOUBLE,
            total_pnl          DOUBLE,
            total_pnl_pct      DOUBLE,
            daily_pnl          DOUBLE,
            holding_count      INTEGER,
            priced_count       INTEGER,
            created_at         VARCHAR
        )
        """
    )
    _TABLES_READY = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 持仓 CRUD
# ============================================================

def _load_holdings(user_id: str) -> list[dict]:
    if USE_MOCK_DATA:
        return _mock_holdings.setdefault(user_id, [])
    _ensure_tables()
    db = get_db()
    rows = db.fetchall(
        "SELECT id, code, name, type, broker, account, quantity, cost_price, "
        "manual_price, stop_loss_pct, take_profit_pct, open_date, currency, created_at, updated_at, fair_value, "
        "grid_lower, grid_upper, grid_step "
        "FROM biz_holdings WHERE user_id = ? ORDER BY created_at",
        [user_id],
    )
    return [
        {
            "id": r[0], "code": r[1], "name": r[2], "type": r[3],
            "broker": r[4] or "", "account": r[5] or "", "quantity": float(r[6]), "cost_price": float(r[7]),
            "manual_price": None if r[8] is None else float(r[8]),
            "stop_loss_pct": None if r[9] is None else float(r[9]),
            "take_profit_pct": None if r[10] is None else float(r[10]),
            "open_date": r[11], "currency": r[12] or "CNY",
            "created_at": r[13], "updated_at": r[14],
            "fair_value": None if r[15] is None else float(r[15]),
            "grid_lower": None if r[16] is None else float(r[16]),
            "grid_upper": None if r[17] is None else float(r[17]),
            "grid_step": None if r[18] is None else float(r[18]),
        }
        for r in rows
    ]


def _save_holding(user_id: str, item: dict) -> None:
    if USE_MOCK_DATA:
        holdings = _mock_holdings.setdefault(user_id, [])
        for i, h in enumerate(holdings):
            if h["id"] == item["id"]:
                holdings[i] = item
                return
        holdings.append(item)
        return
    _ensure_tables()
    db = get_db()
    db.execute("DELETE FROM biz_holdings WHERE id = ?", [item["id"]])
    db.execute(
        "INSERT INTO biz_holdings "
        "(id, user_id, code, name, type, broker, account, quantity, cost_price, "
        "manual_price, stop_loss_pct, take_profit_pct, open_date, currency, created_at, updated_at, fair_value, "
        "grid_lower, grid_upper, grid_step) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            item["id"], user_id, item["code"], item["name"], item["type"],
            item["broker"], item["account"], item["quantity"], item["cost_price"],
            item["manual_price"], item.get("stop_loss_pct"), item.get("take_profit_pct"),
            item["open_date"], item["currency"],
            item["created_at"], item["updated_at"], item.get("fair_value"),
            item.get("grid_lower"), item.get("grid_upper"), item.get("grid_step"),
        ],
    )


def import_holdings(user_id: str, items: list[dict]) -> dict:
    """批量导入：按 code+type+account 去重，已存在则覆盖更新。"""
    existing = {f"{h['code']}|{h['type']}|{h.get('broker') or ''}|{h.get('account') or ''}": h for h in _load_holdings(user_id)}
    added = updated = 0
    failed: list[dict] = []

    for idx, raw in enumerate(items):
        code = str(raw.get("code") or "").strip()
        name = str(raw.get("name") or "").strip()
        htype = str(raw.get("type") or "").strip()
        account = str(raw.get("account") or "").strip()
        try:
            quantity = float(raw.get("quantity") or 0)
            cost_price = float(raw.get("cost_price") or 0)
        except (TypeError, ValueError):
            quantity = None  # type: ignore[assignment]
            cost_price = None  # type: ignore[assignment]

        if not code or not name:
            failed.append({"index": idx, "code": code, "reason": "缺少 code 或 name"})
            continue
        if htype not in HOLDING_TYPES:
            failed.append({"index": idx, "code": code, "reason": f"未知 type: {htype}"})
            continue
        if quantity is None or cost_price is None or quantity == 0:
            failed.append({"index": idx, "code": code, "reason": "quantity/cost_price 缺失或为0"})
            continue

        key = f"{code}|{htype}|{account}"
        now = _now_iso()
        if key in existing:
            item = existing[key]
            item.update({
                "name": name,
                "broker": str(raw.get("broker") or item.get("broker") or ""),
                "account": account,
                "quantity": quantity, "cost_price": cost_price,
                "stop_loss_pct": _safe_float(raw.get("stop_loss_pct")) if raw.get("stop_loss_pct") not in (None, "") else item.get("stop_loss_pct"),
                "take_profit_pct": _safe_float(raw.get("take_profit_pct")) if raw.get("take_profit_pct") not in (None, "") else item.get("take_profit_pct"),
                "open_date": str(raw.get("open_date") or item.get("open_date") or "") or None,
                "currency": str(raw.get("currency") or item.get("currency") or "CNY"),
                "updated_at": now,
            })
            updated += 1
        else:
            item = {
                "id": str(uuid.uuid4()), "code": code, "name": name, "type": htype,
                "broker": str(raw.get("broker") or ""),
                "account": account,
                "quantity": quantity, "cost_price": cost_price, "manual_price": None,
                "stop_loss_pct": _safe_float(raw.get("stop_loss_pct")),
                "take_profit_pct": _safe_float(raw.get("take_profit_pct")),
                "open_date": str(raw.get("open_date") or "") or None,
                "currency": str(raw.get("currency") or "CNY"),
                "created_at": now, "updated_at": now,
            }
            existing[key] = item
            added += 1
        _save_holding(user_id, item)

    return {"added": added, "updated": updated, "failed": failed}


def update_holding(user_id: str, holding_id: str, fields: dict) -> Optional[dict]:
    for item in _load_holdings(user_id):
        if item["id"] != holding_id:
            continue
        for key in ("quantity", "cost_price", "manual_price", "broker", "account", "name", "open_date", "currency",
                    "stop_loss_pct", "take_profit_pct", "fair_value",
                    "grid_lower", "grid_upper", "grid_step"):
            if key not in fields:
                continue
            # manual_price / stop_loss_pct / take_profit_pct / fair_value / grid_* 允许显式传 null 以清除；其余字段忽略 null
            if fields[key] is None and key not in ("manual_price", "stop_loss_pct", "take_profit_pct", "fair_value",
                                                    "grid_lower", "grid_upper", "grid_step"):
                continue
            item[key] = fields[key]
        item["updated_at"] = _now_iso()
        _save_holding(user_id, item)
        return item
    return None


def delete_holding(user_id: str, holding_id: str) -> bool:
    holdings = _load_holdings(user_id)
    if USE_MOCK_DATA:
        before = len(holdings)
        holdings[:] = [h for h in holdings if h["id"] != holding_id]
        return len(holdings) < before
    _ensure_tables()
    db = get_db()
    row = db.fetchone(
        "SELECT count(*) FROM biz_holdings WHERE id = ? AND user_id = ?",
        [holding_id, user_id],
    )
    if not row or row[0] == 0:
        return False
    db.execute("DELETE FROM biz_holdings WHERE id = ?", [holding_id])
    return True


# ============================================================
# 行情获取（逐标的轻量接口，失败置 None，缓存 60s）
#
# 53 上东财实时全量接口（stock_zh_a_spot_em / stock_bid_ask_em / fund_etf_hist_em
# 等）长期挂起或 500，不可用；实测可用的轻量源：
# - 腾讯 qt.gtimg.cn：A股/ETF/LOF/港股 实时价+昨收，批量一次请求（<0.1s）
# - 53 futures_zh_daily_sina：期货日线（close/settle）
# - 53 stock_zh_a_hist / stock_hk_daily：腾讯失败时的日线回退
# - 天天基金 pingzhongdata：场外基金最新净值
# ============================================================

def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None  # NaN 过滤
    except (TypeError, ValueError):
        return None


def _digits(code: str) -> str:
    """归一化代码为纯数字/字母（去掉市场前缀与后缀）"""
    c = str(code).split(".")[0]
    for prefix in ("sh", "sz", "bj", "hk"):
        if c.lower().startswith(prefix):
            c = c[len(prefix):]
            break
    return c


def _tencent_symbol(htype: str, code: str) -> Optional[str]:
    """映射为腾讯行情代码；无法判断市场的返回 None"""
    c = _digits(code)
    if htype == "hk_stock":
        return f"hk{c.zfill(5)}"
    if htype == "stock":
        if c.startswith(("6", "9", "5")):
            return f"sh{c}"
        if c.startswith(("0", "2", "3", "1")):
            return f"sz{c}"
        if c.startswith(("4", "8")):
            return f"bj{c}"
        return None
    if htype == "etf":  # 场内基金（ETF/LOF/封基）
        if c.startswith(("5", "6")):
            return f"sh{c}"
        if c.startswith(("1", "0", "3")):
            return f"sz{c}"
        return None
    return None


def _fetch_tencent_quotes(holdings: list[dict]) -> dict[str, dict]:
    """腾讯实时行情批量接口：现价(idx3)/昨收(idx4)。A股 GBK，港股 UTF-8。"""
    syms: dict[str, str] = {}  # tencent_symbol -> code
    for h in holdings:
        sym = _tencent_symbol(h["type"], h["code"])
        if sym:
            syms[sym] = _digits(h["code"])
    if not syms:
        return {}
    out: dict[str, dict] = {}
    try:
        resp = requests.get(
            f"http://qt.gtimg.cn/q={','.join(syms)}", timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        for raw in resp.content.split(b";"):
            raw = raw.strip()
            if not raw.startswith(b"v_"):
                continue
            key = raw[2:raw.find(b"=")].decode("ascii", "ignore")
            code = syms.get(key)
            if not code:
                continue
            text = raw.decode("gbk" if not key.startswith("hk") else "utf-8", "ignore")
            fields = text.split("~")
            if len(fields) < 5:
                continue
            # 港股现价在 idx19（idx3 为开盘价），A股/ETF 现价在 idx3；昨收均在 idx4
            price = _safe_float(fields[19]) if key.startswith("hk") else _safe_float(fields[3])
            out[code] = {"price": price, "prev_close": _safe_float(fields[4])}
    except Exception as exc:  # noqa: BLE001
        print(f"[Holdings] 腾讯行情获取失败: {exc}")
    return out


def _fetch_daily_hist(htype: str, code: str) -> dict:
    """日线回退：取最近两根 K 线，最新收盘作现价，前收作昨收。"""
    c = _digits(code)
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    if htype == "stock":
        rows = akshare_request(
            "stock_zh_a_hist",
            {"symbol": c, "period": "daily", "start_date": start, "end_date": end, "adjust": ""},
            retries=1, timeout=15,
        )
    elif htype == "hk_stock":
        rows = akshare_request(
            "stock_hk_daily", {"symbol": c.zfill(5), "adjust": ""}, retries=1, timeout=15,
        )
        if isinstance(rows, list):
            rows = rows[-30:]
    else:
        rows = None
    if not rows or not isinstance(rows, list) or len(rows) == 0:
        return {}
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else {}
    return {
        "price": _safe_float(last.get("close")),
        "prev_close": _safe_float(prev.get("close")),
    }


def _fetch_future_quote(code: str) -> dict:
    """期货：53 新浪日线，最新收盘作现价，前收作昨收。"""
    rows = akshare_request("futures_zh_daily_sina", {"symbol": code}, retries=1, timeout=15)
    if not rows or not isinstance(rows, list) or len(rows) == 0:
        return {}
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else {}
    return {
        "price": _safe_float(last.get("close", last.get("settle"))),
        "prev_close": _safe_float(prev.get("close", prev.get("settle"))),
    }


def _fetch_otc_fund_quote(code: str) -> dict:
    """场外基金：天天基金最新净值作现价；无昨收（当日盈亏不计入）。"""
    try:
        resp = requests.get(
            f"https://fund.eastmoney.com/pingzhongdata/{_digits(code)}.js",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://fundf10.eastmoney.com/"},
            timeout=12,
        )
        m = re.search(r"var Data_netWorthTrend\s*=\s*(\[.*?\]);", resp.text, re.S)
        if not m:
            return {}
        arr = json.loads(m.group(1))
        if not arr:
            return {}
        return {"price": _safe_float(arr[-1].get("y")), "prev_close": None}
    except Exception as exc:  # noqa: BLE001
        print(f"[Holdings] 场外基金净值获取失败 {code}: {exc}")
        return {}


def _fetch_quotes(holdings: list[dict]) -> dict[str, dict]:
    """按类型逐标的取行情，合并为 {code: {price, prev_close}}。绝不虚构数据。"""
    now = time.time()
    if now - _QUOTE_CACHE["ts"] < _QUOTE_TTL and _QUOTE_CACHE["quotes"]:
        return _QUOTE_CACHE["quotes"]

    quotes: dict[str, dict] = {}
    by_type: dict[str, list[dict]] = {}
    for h in holdings:
        by_type.setdefault(h["type"], []).append(h)

    # A股 / 场内基金 / 港股：腾讯批量实时，失败逐标的回退日线
    tencent_types = [t for t in ("stock", "etf", "hk_stock") if t in by_type]
    if tencent_types:
        batch = [h for t in tencent_types for h in by_type[t]]
        quotes.update(_fetch_tencent_quotes(batch))
        for h in batch:
            code = _digits(h["code"])
            q = quotes.get(code)
            if q and q.get("price") is not None:
                continue
            fb = _fetch_daily_hist(h["type"], code)
            if fb.get("price") is not None:
                quotes[code] = fb

    # 期货：新浪日线
    for h in by_type.get("future", []):
        q = _fetch_future_quote(h["code"])
        if q.get("price") is not None:
            quotes[_digits(h["code"])] = q

    # 场外基金：天天基金净值
    for h in by_type.get("fund_otc", []):
        q = _fetch_otc_fund_quote(h["code"])
        if q.get("price") is not None:
            quotes[_digits(h["code"])] = q

    # 期权：无可用轻量源，依赖手动现价（不虚构）

    _QUOTE_CACHE["ts"] = now
    _QUOTE_CACHE["quotes"] = quotes
    return quotes


# ============================================================
# 盈亏计算与汇总
# ============================================================

def build_holdings_view(
    user_id: str,
    type_filter: str | None = None,
    broker_filter: str | None = None,
    account_filter: str | None = None,
    save_snapshot: bool = True,
) -> dict:
    holdings = _load_holdings(user_id)
    quotes = {} if USE_MOCK_DATA else _fetch_quotes(holdings)

    items: list[dict] = []
    total_mv = total_cost = total_pnl = 0.0
    daily_pnl = 0.0
    priced_count = 0

    for h in holdings:
        quote = quotes.get(_digits(h["code"])) or {}
        auto_price = quote.get("price")
        price = h["manual_price"] if h["manual_price"] is not None else auto_price
        price_source = "manual" if h["manual_price"] is not None else ("auto" if auto_price is not None else None)

        mv = pnl = pnl_pct = daily = daily_pct = None
        alert_status = None
        if price is not None:
            mv = price * h["quantity"]
            pnl = (price - h["cost_price"]) * h["quantity"]
            # 成本 <= 0 时收益率无意义（如分红后成本为负），显示为 None
            if h["cost_price"] and h["cost_price"] > 0:
                pnl_pct = (price - h["cost_price"]) / h["cost_price"] * 100
            else:
                pnl_pct = None
            total_mv += mv
            total_cost += h["cost_price"] * h["quantity"]
            total_pnl += pnl
            priced_count += 1
            prev_close = quote.get("prev_close")
            if prev_close is not None and h["manual_price"] is None:
                daily = (price - prev_close) * h["quantity"]
                daily_pnl += daily
                if prev_close:
                    daily_pct = (price - prev_close) / prev_close * 100
            # 止损/止盈预警状态（基于收益率相对成本）
            sl = h.get("stop_loss_pct")
            tp = h.get("take_profit_pct")
            if pnl_pct is not None:
                if sl is not None and pnl_pct <= sl:
                    alert_status = "stop_loss"
                elif tp is not None and pnl_pct >= tp:
                    alert_status = "take_profit"

            # 估值带：现价 vs 合理价（阈值 10%）
            fv = h.get("fair_value")
            valuation = None
            val_pct = None  # (fair_value - price) / price，正=低估，负=高估
            if fv is not None and price is not None and price > 0:
                val_pct = (fv - price) / price * 100
                if price >= fv * 1.10:
                    valuation = "over"
                elif price <= fv * 0.90:
                    valuation = "under"
                else:
                    valuation = "fair"

            # 网格触线：基于用户设定的 [下限, 上限, 间距] 自动切出买卖网格线
            gl = h.get("grid_lower")
            gu = h.get("grid_upper")
            gs = h.get("grid_step")
            grid = None
            if gl is not None and gu is not None and gs is not None and gs > 0 and gu > gl:
                n = max(2, int(round((gu - gl) / gs)) + 1)  # 网格线数
                cells = n - 1  # 格子数（买卖区间数）
                if price <= gl:
                    g_signal = "buy"
                    g_level = 0
                    g_bound = "low"
                elif price >= gu:
                    g_signal = "sell"
                    g_level = cells - 1
                    g_bound = "high"
                else:
                    g_level = max(0, min(int(math.floor((price - gl) / gs)), cells - 1))
                    g_signal = "hold"
                    g_bound = None
                g_pos = (price - gl) / (gu - gl) * 100
                grid = {
                    "grid_lower": gl, "grid_upper": gu, "grid_step": gs,
                    "grid_level": g_level, "grid_total": cells, "grid_pos_pct": round(g_pos, 2),
                    "grid_signal": g_signal, "grid_at_bound": g_bound,
                }

        items.append({
            **h,
            "type_label": HOLDING_TYPES.get(h["type"], h["type"]),
            "price": price,
            "price_source": price_source,
            "market_value": round(mv, 2) if mv is not None else None,
            "pnl": round(pnl, 2) if pnl is not None else None,
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "daily_pnl": round(daily, 2) if daily is not None else None,
            "daily_pct": round(daily_pct, 2) if daily_pct is not None else None,
            "stop_loss_pct": h.get("stop_loss_pct"),
            "take_profit_pct": h.get("take_profit_pct"),
            "fair_value": h.get("fair_value"),
            "val_pct": round(val_pct, 2) if val_pct is not None else None,
            "valuation": valuation,
            "grid_lower": h.get("grid_lower"),
            "grid_upper": h.get("grid_upper"),
            "grid_step": h.get("grid_step"),
            "grid_signal": grid["grid_signal"] if grid else None,
            "grid_level": grid["grid_level"] if grid else None,
            "grid_total": grid["grid_total"] if grid else None,
            "grid_pos_pct": grid["grid_pos_pct"] if grid else None,
            "grid_at_bound": grid["grid_at_bound"] if grid else None,
            "alert_status": alert_status,
        })

    total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0.0

    # 聚合：按类型 / 按券商（市值口径，仅含有价标的）
    def _alloc(key: str) -> list[dict]:
        agg: dict[str, float] = {}
        for it in items:
            if it["market_value"] is None:
                continue
            k = it[key] or "未分组"
            agg[k] = agg.get(k, 0.0) + it["market_value"]
        out = []
        for k, v in sorted(agg.items(), key=lambda x: -x[1]):
            out.append({
                "key": k,
                "label": HOLDING_TYPES.get(k, k) if key == "type" else k,
                "market_value": round(v, 2),
                "weight_pct": round(v / total_mv * 100, 2) if total_mv else 0.0,
            })
        return out

    # 预警：单标的集中度 > 30%，浮亏 > 15%，止损/止盈触发
    warnings: list[dict] = []
    for it in items:
        if it["market_value"] is None:
            continue
        weight = it["market_value"] / total_mv * 100 if total_mv else 0.0
        if weight > 30:
            warnings.append({"level": "warn", "text": f"集中度过高：{it['name']}({it['code']}) 占比 {weight:.1f}%（>30%）"})
        if it["pnl_pct"] is not None and it["pnl_pct"] <= -15:
            warnings.append({"level": "danger", "text": f"深度浮亏：{it['name']}({it['code']}) 浮亏 {it['pnl_pct']:.1f}%"})
        if it["alert_status"] == "stop_loss":
            sl = it["stop_loss_pct"]
            warnings.append({"level": "danger", "text": f"止损触发：{it['name']}({it['code']}) 收益率 {it['pnl_pct']:.1f}% 已跌破止损线 {sl:.1f}%"})
        elif it["alert_status"] == "take_profit":
            tp = it["take_profit_pct"]
            warnings.append({"level": "warn", "text": f"止盈触发：{it['name']}({it['code']}) 收益率 {it['pnl_pct']:.1f}% 已达止盈线 {tp:.1f}%"})
        # 估值提示：现价相对合理价偏高/偏低
        if it["valuation"] == "over":
            fv = it["fair_value"]
            up = it["val_pct"] or 0
            warnings.append({"level": "warn", "text": f"估值偏高：{it['name']}({it['code']}) 现价 {it['price']:.2f} 高于合理价 {fv:.2f}（高估 {abs(up):.1f}%），可考虑减仓/卖出"})
        elif it["valuation"] == "under":
            fv = it["fair_value"]
            up = it["val_pct"] or 0
            warnings.append({"level": "warn", "text": f"估值偏低：{it['name']}({it['code']}) 现价 {it['price']:.2f} 低于合理价 {fv:.2f}（低估 {up:.1f}%），可考虑关注/买入"})
        # 网格触线提示：现价触下沿/上沿
        if it["grid_at_bound"] == "low":
            gl = it["grid_lower"]
            warnings.append({"level": "warn", "text": f"网格触下沿：{it['name']}({it['code']}) 现价 {it['price']:.2f} 已触及/跌破网格下限 {gl:.2f}，可考虑买入网格仓"})
        elif it["grid_at_bound"] == "high":
            gu = it["grid_upper"]
            warnings.append({"level": "warn", "text": f"网格触上沿：{it['name']}({it['code']}) 现价 {it['price']:.2f} 已触及/突破网格上限 {gu:.2f}，可考虑卖出网格仓"})

    # 每日快照（仅当有任一标的取得价格时落库，每天 upsert 一条）
    if save_snapshot and priced_count > 0:
        _upsert_snapshot(user_id, total_mv, total_cost, total_pnl, total_pnl_pct, daily_pnl, len(items), priced_count)

    filtered = items
    if type_filter:
        filtered = [it for it in filtered if it["type"] == type_filter]
    if broker_filter:
        filtered = [it for it in filtered if (it["broker"] or "未分组") == broker_filter]
    if account_filter:
        filtered = [it for it in filtered if (it["account"] or "未分组") == account_filter]

    return {
        "items": filtered,
        "summary": {
            "total_market_value": round(total_mv, 2),
            "total_cost": round(total_cost, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "daily_pnl": round(daily_pnl, 2),
            "holding_count": len(items),
            "priced_count": priced_count,
            "allocation_by_type": _alloc("type"),
            "allocation_by_broker": _alloc("broker"),
            "allocation_by_account": _alloc("account"),
            "warnings": warnings,
            "quote_time": datetime.now(timezone.utc).isoformat() if quotes else None,
        },
    }


# ============================================================
# 快照
# ============================================================

def _upsert_snapshot(
    user_id: str, mv: float, cost: float, pnl: float, pnl_pct: float,
    daily: float, count: int, priced: int,
) -> dict:
    snap_date = datetime.now().strftime("%Y-%m-%d")
    snap = {
        "id": str(uuid.uuid4()), "user_id": user_id, "snap_date": snap_date,
        "total_market_value": round(mv, 2), "total_cost": round(cost, 2),
        "total_pnl": round(pnl, 2), "total_pnl_pct": round(pnl_pct, 2),
        "daily_pnl": round(daily, 2), "holding_count": count, "priced_count": priced,
        "created_at": _now_iso(),
    }
    if USE_MOCK_DATA:
        snaps = _mock_snapshots.setdefault(user_id, [])
        snaps[:] = [s for s in snaps if s["snap_date"] != snap_date]
        snaps.append(snap)
    else:
        _ensure_tables()
        db = get_db()
        db.execute(
            "DELETE FROM biz_holding_snapshots WHERE user_id = ? AND snap_date = ?",
            [user_id, snap_date],
        )
        db.execute(
            "INSERT INTO biz_holding_snapshots "
            "(id, user_id, snap_date, total_market_value, total_cost, total_pnl, "
            "total_pnl_pct, daily_pnl, holding_count, priced_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [snap["id"], user_id, snap_date, snap["total_market_value"],
             snap["total_cost"], snap["total_pnl"], snap["total_pnl_pct"],
             snap["daily_pnl"], count, priced, snap["created_at"]],
        )
    return snap


def get_snapshots(user_id: str) -> list[dict]:
    if USE_MOCK_DATA:
        return sorted(_mock_snapshots.get(user_id, []), key=lambda s: s["snap_date"])
    _ensure_tables()
    db = get_db()
    rows = db.fetchall(
        "SELECT id, snap_date, total_market_value, total_cost, total_pnl, "
        "total_pnl_pct, daily_pnl, holding_count, priced_count, created_at "
        "FROM biz_holding_snapshots WHERE user_id = ? ORDER BY snap_date",
        [user_id],
    )
    return [
        {
            "id": r[0], "snap_date": r[1], "total_market_value": r[2],
            "total_cost": r[3], "total_pnl": r[4], "total_pnl_pct": r[5],
            "daily_pnl": r[6], "holding_count": r[7], "priced_count": r[8],
            "created_at": r[9],
        }
        for r in rows
    ]


def take_snapshot(user_id: str) -> Optional[dict]:
    """手动快照：重新计算盈亏后落一条当日快照。"""
    view = build_holdings_view(user_id, save_snapshot=True)
    snaps = get_snapshots(user_id)
    return snaps[-1] if snaps else None
