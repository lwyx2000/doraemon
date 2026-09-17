"""Signal service — 按策略对单个标的物生成买卖点信号（基于真实日 K 线）。

设计要点：
- 真实优先：行情统一走 market_service.get_kline（东财 stock_zh_a_hist），绝不伪造。
- 策略目录 STRATEGY_CATALOG 为内置可盈利技术策略（趋势/双均线/MACD/布林/RSI/网格），
  每个策略给出参数 schema 与一段 evaluate 逻辑。
- generate_signal(symbol, strategy_id, params) 拉取日 K 线 → 计算指标 → 检测买卖点
  （仓位状态序列 flat/long 的翻转即信号）→ 返回当前信号 + 历史信号点 + 价格走势。
- 订阅（biz_signal_subscriptions）持久化用户“监控的 (标的物×策略)”组合，供系统持续跟踪表现。
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from database.connection import get_db
from services.market_service import get_kline


# ============================================================
# 技术指标
# ============================================================

def _sma(vals: list[float], n: int) -> list[Optional[float]]:
    """简单移动平均；前 n-1 个位置返回 None。"""
    out: list[Optional[float]] = [None] * len(vals)
    if n <= 0:
        return out
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = round(s / n, 4)
    return out


def _ema(vals: list[float], n: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(vals)
    if n <= 0 or not vals:
        return out
    k = 2.0 / (n + 1)
    prev = vals[0]
    out[0] = prev
    for i in range(1, len(vals)):
        prev = vals[i] * k + prev * (1 - k)
        out[i] = round(prev, 4)
    return out


def _macd(vals: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """返回 (dif, dea, hist) 三条列表。"""
    ema_fast = _ema(vals, fast)
    ema_slow = _ema(vals, slow)
    dif = [None if (a is None or b is None) else round(a - b, 4) for a, b in zip(ema_fast, ema_slow)]
    # DEA = DIF 的 9 日 EMA
    valid = [d for d in dif if d is not None]
    dea_valid = _ema(valid, signal)
    dea = [None] * len(vals)
    j = 0
    for i, d in enumerate(dif):
        if d is None:
            continue
        dea[i] = dea_valid[j]
        j += 1
    hist = [None if (a is None or b is None) else round(a - b, 4) for a, b in zip(dif, dea)]
    return dif, dea, hist


def _stddev(vals: list[float], n: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(vals)
    for i in range(len(vals)):
        if i < n - 1:
            continue
        window = vals[i - n + 1:i + 1]
        mean = sum(window) / n
        var = sum((x - mean) ** 2 for x in window) / n
        out[i] = round(math.sqrt(var), 4)
    return out


def _rsi(vals: list[float], n: int = 14) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(vals)
    if len(vals) <= n:
        return out
    gains, losses = [], []
    for i in range(1, len(vals)):
        ch = vals[i] - vals[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    # 初始平均值（Wilder）
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    if avg_l == 0:
        out[n] = 100.0
    else:
        rs = avg_g / avg_l
        out[n] = round(100 - 100 / (1 + rs), 2)
    for i in range(n + 1, len(vals)):
        avg_g = (avg_g * (n - 1) + gains[i - 1]) / n
        avg_l = (avg_l * (n - 1) + losses[i - 1]) / n
        if avg_l == 0:
            out[i] = 100.0
        else:
            rs = avg_g / avg_l
            out[i] = round(100 - 100 / (1 + rs), 2)
    return out


# ============================================================
# 策略目录 + 评估器
# ============================================================

def _transitions(klines, position, buy_reason, sell_reason):
    """根据仓位序列 flat/long 的翻转生成买卖点信号列表。"""
    signals = []
    for i in range(1, len(klines)):
        prev, cur = position[i - 1], position[i]
        if prev == "flat" and cur == "long":
            signals.append({
                "date": klines[i]["date"],
                "price": round(klines[i]["close"], 2),
                "type": "buy",
                "reason": buy_reason(i),
            })
        elif prev == "long" and cur == "flat":
            signals.append({
                "date": klines[i]["date"],
                "price": round(klines[i]["close"], 2),
                "type": "sell",
                "reason": sell_reason(i),
            })
    return signals


def _eval_trend(klines, closes, params):
    ma_short = int(params.get("ma_short", 20))
    ma_long = int(params.get("ma_long", 60))
    s = _sma(closes, ma_short)
    l = _sma(closes, ma_long)
    position = []
    for i in range(len(klines)):
        if s[i] is None or l[i] is None:
            position.append("flat")
            continue
        long = (closes[i] > s[i]) and (s[i] > l[i])
        position.append("long" if long else "flat")

    def buy_reason(i):
        return (f"价格 {closes[i]:.2f} 站上 MA{ma_short}({s[i]:.2f}) 且 "
                f"MA{ma_short} > MA{ma_long}({l[i]:.2f})，趋势向上，触发买入")

    def sell_reason(i):
        if closes[i] <= s[i]:
            return f"价格 {closes[i]:.2f} 跌破 MA{ma_short}({s[i]:.2f})，短线转弱，触发卖出"
        return f"MA{ma_short}({s[i]:.2f}) 下穿 MA{ma_long}({l[i]:.2f})，趋势反转，触发卖出"

    return position, _transitions(klines, position, buy_reason, sell_reason)


def _eval_ma_cross(klines, closes, params):
    f = int(params.get("ma_fast", 5))
    s = int(params.get("ma_slow", 20))
    fa = _sma(closes, f)
    sa = _sma(closes, s)
    position = []
    for i in range(len(klines)):
        if fa[i] is None or sa[i] is None:
            position.append("flat")
            continue
        position.append("long" if fa[i] > sa[i] else "flat")

    def buy_reason(i):
        return f"MA{f}({fa[i]:.2f}) 上穿 MA{s}({sa[i]:.2f})，金叉，触发买入"

    def sell_reason(i):
        return f"MA{f}({fa[i]:.2f}) 下穿 MA{s}({sa[i]:.2f})，死叉，触发卖出"

    return position, _transitions(klines, position, buy_reason, sell_reason)


def _eval_macd(klines, closes, params):
    dif, dea, _ = _macd(closes)
    position = []
    for i in range(len(klines)):
        if dif[i] is None or dea[i] is None:
            position.append("flat")
            continue
        position.append("long" if dif[i] > dea[i] else "flat")

    def buy_reason(i):
        return f"MACD 金叉：DIF({dif[i]:.3f}) 上穿 DEA({dea[i]:.3f})，红柱放大，触发买入"

    def sell_reason(i):
        return f"MACD 死叉：DIF({dif[i]:.3f}) 下穿 DEA({dea[i]:.3f})，绿柱放大，触发卖出"

    return position, _transitions(klines, position, buy_reason, sell_reason)


def _eval_boll(klines, closes, params):
    n = int(params.get("boll_n", 20))
    k = float(params.get("boll_k", 2.0))
    mid = _sma(closes, n)
    sd = _stddev(closes, n)
    upper = [None if (m is None or d is None) else m + k * d for m, d in zip(mid, sd)]
    lower = [None if (m is None or d is None) else m - k * d for m, d in zip(mid, sd)]
    position = []
    for i in range(len(klines)):
        if lower[i] is None or upper[i] is None:
            position.append("flat")
            continue
        long = closes[i] <= lower[i]
        position.append("long" if long else "flat")

    def buy_reason(i):
        return f"价格 {closes[i]:.2f} 触及/跌破布林下轨({lower[i]:.2f})，超卖，触发买入"

    def sell_reason(i):
        return f"价格 {closes[i]:.2f} 触及/突破布林上轨({upper[i]:.2f})，超买，触发卖出"

    return position, _transitions(klines, position, buy_reason, sell_reason)


def _eval_rsi(klines, closes, params):
    n = int(params.get("rsi_n", 14))
    low = float(params.get("rsi_low", 30))
    high = float(params.get("rsi_high", 70))
    r = _rsi(closes, n)
    position = []
    for i in range(len(klines)):
        if r[i] is None:
            position.append("flat")
            continue
        position.append("long" if r[i] <= low else "flat")

    def buy_reason(i):
        return f"RSI({n})={r[i]:.1f} ≤ {low}，进入超卖区，触发买入"

    def sell_reason(i):
        return f"RSI({n})={r[i]:.1f} ≥ {high}，进入超买区，触发卖出"

    return position, _transitions(klines, position, buy_reason, sell_reason)


def _eval_grid(klines, closes, params):
    gl = float(params.get("grid_lower", 0))
    gu = float(params.get("grid_upper", 0))
    gs = float(params.get("grid_step", 0))
    if gs <= 0 or gu <= gl:
        # 参数不合法：无信号
        return ["flat"] * len(klines), []

    # 网格线（含上下沿）
    lines = []
    x = gl
    while x <= gu + 1e-9:
        lines.append(round(x, 4))
        x += gs
    # 当前所在网格层（向下取整到最近下沿）
    position = []
    prev_level = None
    signals = []
    for i in range(len(klines)):
        p = closes[i]
        # 命中层：price 落在 [lines[j], lines[j+1])
        level = 0
        for j in range(len(lines) - 1):
            if lines[j] <= p < lines[j + 1]:
                level = j
                break
        else:
            if p >= lines[-1]:
                level = len(lines) - 1
            elif p < lines[0]:
                level = -1  # 跌破下沿
        position.append("flat")  # 网格为递增买卖，仓位序列不直接用
        # 相对上一层：下降穿越网格线 → 买入；上升穿越 → 卖出
        if prev_level is not None and level != prev_level:
            if level < prev_level:
                signals.append({
                    "date": klines[i]["date"], "price": round(p, 2), "type": "buy",
                    "reason": f"价格 {p:.2f} 下穿至第 {max(level,0)} 格，触发网格买入",
                })
            else:
                signals.append({
                    "date": klines[i]["date"], "price": round(p, 2), "type": "sell",
                    "reason": f"价格 {p:.2f} 上穿至第 {level} 格，触发网格卖出",
                })
        prev_level = level
    return position, signals


EVALUATORS = {
    "trend": _eval_trend,
    "ma_cross": _eval_ma_cross,
    "macd": _eval_macd,
    "boll": _eval_boll,
    "rsi": _eval_rsi,
    "grid": _eval_grid,
}


# 策略目录（前端下拉 + 动态参数表单）
STRATEGY_CATALOG = [
    {
        "id": "trend", "name": "趋势交易", "category": "趋势跟踪",
        "desc": "价格站上短期均线且短期均线上穿长期均线时持有/买入，跌破或均线反转时卖出。适合单边行情。",
        "params": [
            {"key": "ma_short", "label": "短期均线", "type": "number", "default": 20, "min": 3, "max": 120},
            {"key": "ma_long", "label": "长期均线", "type": "number", "default": 60, "min": 5, "max": 250},
        ],
    },
    {
        "id": "ma_cross", "name": "双均线交叉", "category": "趋势跟踪",
        "desc": "短期均线上穿长期均线（金叉）买入，下穿（死叉）卖出。经典均线系统。",
        "params": [
            {"key": "ma_fast", "label": "快线周期", "type": "number", "default": 5, "min": 2, "max": 60},
            {"key": "ma_slow", "label": "慢线周期", "type": "number", "default": 20, "min": 3, "max": 120},
        ],
    },
    {
        "id": "macd", "name": "MACD", "category": "摆动/动能",
        "desc": "DIF 上穿 DEA（金叉）买入，下穿（死叉）卖出。捕捉动能转折。",
        "params": [],
    },
    {
        "id": "boll", "name": "布林带", "category": "均值回归",
        "desc": "价格触及下轨（超卖）买入，触及上轨（超买）卖出。适合震荡行情。",
        "params": [
            {"key": "boll_n", "label": "均线周期", "type": "number", "default": 20, "min": 5, "max": 120},
            {"key": "boll_k", "label": "标准差倍数", "type": "number", "default": 2.0, "step": 0.1, "min": 1.0, "max": 4.0},
        ],
    },
    {
        "id": "rsi", "name": "RSI 超买超卖", "category": "摆动/动能",
        "desc": "RSI 跌破超卖线买入，突破超买线卖出。经典摆动指标。",
        "params": [
            {"key": "rsi_n", "label": "RSI 周期", "type": "number", "default": 14, "min": 2, "max": 60},
            {"key": "rsi_low", "label": "超卖线", "type": "number", "default": 30, "min": 5, "max": 50},
            {"key": "rsi_high", "label": "超买线", "type": "number", "default": 70, "min": 50, "max": 95},
        ],
    },
    {
        "id": "grid", "name": "网格交易", "category": "网格",
        "desc": "在 [下限, 上限] 按间距自动切分网格，价格下穿网格线买入、上穿卖出。适合震荡。",
        "params": [
            {"key": "grid_lower", "label": "网格下限", "type": "number", "default": 0, "step": 0.01},
            {"key": "grid_upper", "label": "网格上限", "type": "number", "default": 0, "step": 0.01},
            {"key": "grid_step", "label": "网格间距", "type": "number", "default": 0, "step": 0.01},
        ],
    },
]


def get_catalog() -> list[dict]:
    return STRATEGY_CATALOG


def _strategy_by_id(sid: str) -> Optional[dict]:
    for s in STRATEGY_CATALOG:
        if s["id"] == sid:
            return s
    return None


# ============================================================
# 信号生成
# ============================================================

def generate_signal(symbol: str, strategy_id: str, params: dict | None = None) -> dict:
    """对单个标的物按指定策略生成买卖点信号。

    返回结构：
    {
      symbol, strategy_id, strategy_name, name,
      current_price, current_position(long/flat),
      latest_signal, latest_reason, last_signal_date, last_signal_type,
      signal_count, kline_start, kline_end, kline_count,
      signal_points: [{date, price, type(buy/sell), reason}],
      series: { date:[], close:[] }   # 供前端绘制价格走势 + 买卖点
    }
    """
    params = params or {}
    strategy = _strategy_by_id(strategy_id)
    if strategy is None:
        raise ValueError(f"未知策略: {strategy_id}")

    klines = get_kline(symbol)
    if not klines:
        return {
            "symbol": symbol, "strategy_id": strategy_id,
            "strategy_name": strategy["name"], "name": None,
            "error": "未获取到行情数据（标的代码可能无效或数据源不可用）",
            "current_price": None, "current_position": None,
            "latest_signal": None, "latest_reason": None,
            "last_signal_date": None, "last_signal_type": None,
            "signal_count": 0, "signal_points": [],
            "series": {"date": [], "close": []},
            "kline_start": None, "kline_end": None, "kline_count": 0,
        }

    closes = [k["close"] for k in klines]
    position, signals = EVALUATORS[strategy_id](klines, closes, params)

    current_price = round(closes[-1], 2)
    current_position = position[-1] if position else "flat"
    latest_signal = "持有/买入" if current_position == "long" else "空仓/卖出"

    last = signals[-1] if signals else None
    latest_reason = last["reason"] if last else (
        "当前处于持有状态，无最新买卖点" if current_position == "long"
        else "当前处于空仓状态，无最新买卖点"
    )

    return {
        "symbol": symbol,
        "strategy_id": strategy_id,
        "strategy_name": strategy["name"],
        "name": None,
        "current_price": current_price,
        "current_position": current_position,
        "latest_signal": latest_signal,
        "latest_reason": latest_reason,
        "last_signal_date": last["date"] if last else None,
        "last_signal_type": last["type"] if last else None,
        "signal_count": len(signals),
        "signal_points": signals,
        "series": {
            "date": [k["date"] for k in klines],
            "close": [round(c, 2) for c in closes],
        },
        "kline_start": klines[0]["date"],
        "kline_end": klines[-1]["date"],
        "kline_count": len(klines),
    }


# ============================================================
# 订阅（监控）持久化
# ============================================================

def _ensure_tables() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_signal_subscriptions (
            id VARCHAR PRIMARY KEY,
            fk_users UUID,
            symbol VARCHAR,
            name VARCHAR,
            strategy_id VARCHAR,
            params_json VARCHAR,
            created_at VARCHAR,
            updated_at VARCHAR
        )
        """
    )


def get_tracked(user_id: str) -> list[dict]:
    _ensure_tables()
    db = get_db()
    rows = db.fetchall(
        "SELECT id, symbol, name, strategy_id, params_json, created_at FROM "
        "biz_signal_subscriptions WHERE fk_users = ? ORDER BY created_at DESC",
        [user_id],
    )
    out = []
    for r in rows:
        try:
            params = json.loads(r[4]) if r[4] else {}
        except Exception:
            params = {}
        out.append({
            "id": r[0], "symbol": r[1], "name": r[2],
            "strategy_id": r[3], "params": params, "created_at": r[5],
        })
    return out


def add_tracked(user_id: str, symbol: str, name: str | None, strategy_id: str, params: dict) -> dict:
    _ensure_tables()
    sid = _strategy_by_id(strategy_id)
    if sid is None:
        raise ValueError(f"未知策略: {strategy_id}")
    now = datetime.now(timezone.utc).isoformat()
    rec_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        "INSERT INTO biz_signal_subscriptions (id, fk_users, symbol, name, strategy_id, params_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [rec_id, user_id, symbol if name is None else symbol, name or symbol, strategy_id,
         json.dumps(params, ensure_ascii=False), now, now],
    )
    return {"id": rec_id, "symbol": symbol, "name": name or symbol, "strategy_id": strategy_id, "params": params}


def remove_tracked(user_id: str, rec_id: str) -> bool:
    _ensure_tables()
    db = get_db()
    db.execute(
        "DELETE FROM biz_signal_subscriptions WHERE id = ? AND fk_users = ?",
        [rec_id, user_id],
    )
    return True


def compute_tracked_signals(user_id: str) -> list[dict]:
    """重算所有订阅组合的当前信号，供系统持续监控表现。"""
    tracked = get_tracked(user_id)
    result = []
    for t in tracked:
        try:
            sig = generate_signal(t["symbol"], t["strategy_id"], t.get("params", {}))
        except Exception as e:  # 单条失败不影响其余
            sig = {"error": str(e), "current_price": None, "current_position": None,
                   "latest_signal": None, "latest_reason": None, "last_signal_date": None,
                   "last_signal_type": None, "signal_count": 0}
        result.append({
            "id": t["id"], "symbol": t["symbol"], "name": t["name"],
            "strategy_id": t["strategy_id"], "strategy_name": _strategy_by_id(t["strategy_id"])["name"],
            "current_price": sig.get("current_price"),
            "current_position": sig.get("current_position"),
            "latest_signal": sig.get("latest_signal"),
            "latest_reason": sig.get("latest_reason"),
            "last_signal_date": sig.get("last_signal_date"),
            "last_signal_type": sig.get("last_signal_type"),
            "signal_count": sig.get("signal_count", 0),
            "error": sig.get("error"),
        })
    return result
