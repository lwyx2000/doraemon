"""Signal service — 按策略对单个标的物生成买卖点信号（基于真实日 K 线）。

设计要点：
- 真实优先：行情统一走 market_service.get_kline（东财 stock_zh_a_hist），绝不伪造。
- 策略目录 STRATEGY_CATALOG 为内置技术策略（趋势/双均线/MACD/布林/RSI/BIAS/网格
  + 动量突破类：海龟/旗形/放量上涨/回踩均线/区间放大），每项给出参数 schema 与
  一段 evaluate 逻辑；EVALUATORS 注册后 winrate_service 自动纳入胜率扫描。
- 评估器契约：返回 (position, signals)，或**可选**多返回一个 exposure 序列
  (position, signals, exposure)；position 是逐日 flat/long 状态序列，长度必须
  等于 klines；exposure 是逐日目标仓位（0~1），同样等长、只用 ≤ i 的数据。
  所有计算只引用 ≤ i 的数据（无未来函数）。行情层字段仅
  {date,open,close,high,low,volume}，无成交额，禁止估算金额冒充真实字段。
  winrate_service 对二元组按「满仓固定持有」统计（数值与旧版逐字节一致），
  对三元组按逐日账本撮合；generate_signal 只透出当前仓位，不做数值校验。
- generate_signal(symbol, strategy_id, params) 拉取日 K 线 → 计算指标 → 检测买卖点
  （仓位状态序列 flat/long 的翻转即信号）→ 返回当前信号 + 历史信号点 + 价格走势。
- 订阅（biz_signal_subscriptions）持久化用户“监控的 (标的物×策略)”组合，供系统持续跟踪表现。
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from database.sqlite_connection import get_biz_db
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


def _eval_bias(klines, closes, params):
    """均线偏离度(BIAS)：BIAS = (close − MA_n) / MA_n × 100，低于阈值为超卖。"""
    n = int(params.get("bias_n", 20))
    threshold = float(params.get("bias_threshold", -3.0))
    ma = _sma(closes, n)
    position = []
    for i in range(len(klines)):
        if ma[i] in (None, 0):
            position.append("flat")
            continue
        bias = (closes[i] - ma[i]) / ma[i] * 100
        position.append("long" if bias <= threshold else "flat")

    def buy_reason(i):
        bias = (closes[i] - ma[i]) / ma[i] * 100
        return (f"价格 {closes[i]:.2f} 低于 MA{n}({ma[i]:.2f})，"
                f"偏离度 {bias:.2f}% ≤ 阈值 {threshold}%，负偏离超卖，触发买入")

    def sell_reason(i):
        if ma[i] in (None, 0):
            return "偏离度修复，超卖状态解除，触发卖出"
        bias = (closes[i] - ma[i]) / ma[i] * 100
        return f"偏离度修复至 {bias:.2f}%（高于阈值 {threshold}%），超卖状态解除，触发卖出"

    return position, _transitions(klines, position, buy_reason, sell_reason)


def _eval_bias_ladder(klines, closes, params):
    """BIAS 乖离分级减仓（仓位管理）：超卖入场 + 持仓期按正偏离逐级减半。

    档位口径严格来自用户技能 bias-position-strategy，不自己编：
        BIAS(N) = (close − MA_N) / MA_N × 100%
        BIAS20 > 10%  → 仓位减半    (1.0 → 0.5)
        BIAS20 > 15%  → 再减半      (0.5 → 0.25)
        BIAS60 > 20%  → 再减半，独立触发（补两波行情里 BIAS20 背离不触发的漏）
    三档从 1.0 起各自 *= 0.5，最低 0.125；只触发 BIAS60 时留 0.5。

    与本系统「入场点胜率统计器」契约的衔接：
    - position 仍是 flat/long 二值，入场/出场复用 _eval_bias 的负偏离超卖
      口径（bias_n / bias_threshold），保证触发点与 bias 策略完全可比，
      可直接对比「满仓持有 vs 分级减仓」的胜率与净收益。
    - 第三个返回值 exposure 是逐日目标仓位（0~1），只用截至当日（含）的
      收盘价与均线计算，无未来函数；winrate_service 用 T-1 目标仓位决定
      T 日收益（1 日滞后），与技能 backtest() 的 pos=target[i-1] 一致。
    - MA 数据不足的前 n-1 根不触发任何减仓档，保守记满仓 1.0。

    已知取舍：BIAS 是左侧信号，主升浪里会卖飞；这是「少赚换安稳」，
    不是 bug。策略只做多头仓位管理，不做空、不加杠杆。
    """
    n = int(params.get("bias_n", 20))
    threshold = float(params.get("bias_threshold", -3.0))
    long_n = int(params.get("ladder_long", 60))
    t1 = float(params.get("ladder_t1", 10.0))
    t2 = float(params.get("ladder_t2", 15.0))
    t3 = float(params.get("ladder_t3", 20.0))
    ma = _sma(closes, n)
    ma_long = _sma(closes, long_n)

    def bias_at(i, m):
        return (closes[i] - m[i]) / m[i] * 100 if m[i] not in (None, 0) else None

    position, exposure = [], []
    for i in range(len(klines)):
        b = bias_at(i, ma)
        position.append("flat" if b is None else ("long" if b <= threshold else "flat"))
        factor = 1.0
        if b is not None:
            if b > t1:
                factor *= 0.5
            if b > t2:
                factor *= 0.5
        bl = bias_at(i, ma_long)
        if bl is not None and bl > t3:
            factor *= 0.5
        exposure.append(factor)

    def buy_reason(i):
        b = bias_at(i, ma)
        btxt = f"BIAS{n} {b:.2f}%" if b is not None else "偏离度数据不足"
        return (f"{btxt} ≤ 阈值 {threshold}%（负偏离超卖）触发买入；"
                f"当日目标仓位 {exposure[i] * 100:.1f}%")

    def sell_reason(i):
        b = bias_at(i, ma)
        cur = (f"BIAS{n} 修复至 {b:.2f}%（高于阈值 {threshold}%）"
               if b is not None else "偏离度数据不足")
        return (f"{cur}，超卖状态解除；当日目标仓位 {exposure[i] * 100:.1f}%")

    return position, _transitions(klines, position, buy_reason, sell_reason), exposure


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


# ============================================================
# 动量/突破类策略（源自 InStock 策略条件清单，按本项目 K 线字段与
# 「状态型仓位 + 无未来函数」契约重写，不引入 TA-Lib / 成交额字段）
# ============================================================

def _series(klines, key: str) -> list[float]:
    """把 K 线的 OHLCV 字段取成 float 序列，缺失字段记 0 由策略自行判有效性。

    行情层只提供 {date, open, close, high, low, volume}，**没有成交额**。
    股票与 ETF 的 volume 单位不统一，因此禁止用 close*volume 之类估算值
    冒充成交额；需要金额门槛的策略一律改用相对量比并如实标注。
    """
    return [float(k.get(key) or 0.0) for k in klines]


def _state_signals(klines, state, buy_reason, sell_reason):
    """布尔状态序列 -> (position, signals)，统一走既有的翻转检测契约。"""
    position = ["long" if s else "flat" for s in state]
    return position, _transitions(klines, position, buy_reason, sell_reason)


def _eval_turtle_breakout(klines, closes, params):
    """唐奇安突破（海龟法则）：收盘价创「前 N 日」新高则持有。

    参照上界取 closes[i-N:i]（不含当日），避免把当日自己算进最高价造成
    自证突破；所有引用都 ≤ i，不触碰未来 K 线。
    """
    n = int(params.get("breakout_n", 60))
    state = [False] * len(closes)
    prev_high: list[Optional[float]] = [None] * len(closes)
    if n > 0:
        for i in range(n, len(closes)):
            prev_high[i] = max(closes[i - n:i])
            state[i] = closes[i] >= prev_high[i]

    def buy_reason(i):
        h = prev_high[i]
        return (f"收盘 {closes[i]:.2f} 突破前 {n} 日最高收盘 {h:.2f}，"
                f"通道突破，触发买入")

    def sell_reason(i):
        h = prev_high[i]
        if h is None:
            return "历史数据不足，突破状态解除，触发卖出"
        return (f"收盘 {closes[i]:.2f} 未再刷新前 {n} 日高点 {h:.2f}，"
                f"突破状态解除，触发卖出")

    return _state_signals(klines, state, buy_reason, sell_reason)


def _eval_high_tight_flag(klines, closes, params):
    """高而窄旗形：前 24~10 日出现连续两日急涨，当前价站上旗杆基准 ratio 倍。"""
    min_bars = int(params.get("flag_min_bars", 60))
    far = int(params.get("flag_far", 24))
    near = int(params.get("flag_near", 10))
    ratio = float(params.get("flag_base_ratio", 1.9))
    gain = float(params.get("flag_gain_pct", 9.5))
    lows = _series(klines, "low")
    state = [False] * len(closes)
    # near ≥ 1 是硬约束：否则 b = i，下面的 j+1 会读到 i+1（未来数据/越界）
    if far > near >= 1 and ratio > 0:
        for i in range(len(closes)):
            if i < max(min_bars, far):
                continue
            a, b = i - far, i - near
            base_win = [x for x in lows[a:b + 1] if x > 0]   # b+1 ≤ i，不含当日
            if not base_win or closes[i] < ratio * min(base_win):
                continue
            # 急涨只取 [a, b] 窗口内相邻两日；j+1 ≤ b ≤ i-near < i，无未来函数
            for j in range(a, b):
                if j < 1 or closes[j - 1] <= 0 or closes[j] <= 0:
                    continue
                g1 = (closes[j] / closes[j - 1] - 1) * 100
                g2 = (closes[j + 1] / closes[j] - 1) * 100
                if g1 >= gain and g2 >= gain:
                    state[i] = True
                    break

    def buy_reason(i):
        return (f"旗形确认：收盘 {closes[i]:.2f} ≥ 基准低点 ×{ratio}，"
                f"且前 {far}~{near} 日出现连续两日涨幅 ≥{gain}%，触发买入")

    def sell_reason(i):
        return "旗形条件不再满足，形态失效，触发卖出"

    return _state_signals(klines, state, buy_reason, sell_reason)


def _eval_volume_breakout(klines, closes, params):
    """放量上涨：涨幅达标 + 收阳 + 相对量比放大。

    InStock 原版另有「成交额 ≥ 2 亿」的绝对门槛；本系统 K 线不含成交额，
    且股票/ETF 的 volume 单位不统一，故改为「相对前 N 日均量」的量比条件，
    **不估算、不伪造绝对金额**（项目设计要点：真实优先、绝不伪造）。
    """
    gain = float(params.get("vol_gain_pct", 2.0))
    ratio = float(params.get("vol_ratio", 2.0))
    ma_n = int(params.get("vol_ma", 5))
    opens = _series(klines, "open")
    vols = _series(klines, "volume")
    state = [False] * len(closes)
    if ma_n > 0 and ratio > 0:
        for i in range(1, len(closes)):
            if i < ma_n or closes[i - 1] <= 0:
                continue
            avg = sum(vols[i - ma_n:i]) / ma_n   # 前 ma_n 根均量，不含当日
            if avg <= 0:
                continue
            if (closes[i] / closes[i - 1] - 1) * 100 < gain:
                continue
            if opens[i] > 0 and closes[i] <= opens[i]:   # 收阳；open 缺失时不判
                continue
            if vols[i] < ratio * avg:
                continue
            state[i] = True

    def buy_reason(i):
        return (f"放量上涨：涨幅 ≥{gain}%、收阳、量比 ≥{ratio}×"
                f"前 {ma_n} 日均量，触发买入")

    def sell_reason(i):
        return "放量上涨条件不再满足，触发卖出"

    return _state_signals(klines, state, buy_reason, sell_reason)


def _eval_pullback_ma(klines, closes, params):
    """回踩长期均线：上穿均线后回踩不破 + 缩量，典型的 continuation setup。

    原版用 250 日年线并含「后段最低/最高 < 0.8」等 A 股个股口径；本系统
    胜率扫描窗口约 1 年（~242 根），故默认降到 120 日并全部参数化，ETF
    波动小的时候需自行下调回撤/缩量阈值，不做隐式口径漂移。
    """
    ma_n = int(params.get("pullback_ma", 120))
    lookback = int(params.get("pullback_lookback", 60))
    min_gap = int(params.get("pullback_min_gap", 10))
    max_gap = int(params.get("pullback_max_gap", 50))
    shrink = float(params.get("pullback_shrink", 2.0))
    retrace = float(params.get("pullback_retrace", 0.8))
    ma = _sma(closes, ma_n) if ma_n > 0 else [None] * len(closes)
    vols = _series(klines, "volume")
    state = [False] * len(closes)
    for i in range(len(closes)):
        if ma[i] is None:
            continue
        start = max(0, i - lookback + 1)
        if i - start < min_gap:
            continue
        h = max(range(start, i + 1), key=lambda j: closes[j])
        # 前段（上穿点至高点）必须出现过由均线下方上穿
        crossed = any(
            ma[j] is not None and ma[j - 1] is not None
            and closes[j - 1] <= ma[j - 1] and closes[j] > ma[j]
            for j in range(start + 1, h + 1)
        )
        if not crossed:
            continue
        after = list(range(h, i + 1))       # 后段：高点当日及之后，全在均线上
        if any(ma[j] is None or closes[j] < ma[j] for j in after):
            continue
        low_i = min(after, key=lambda j: closes[j])
        gap = low_i - h
        if gap < min_gap or gap > max_gap:
            continue
        if closes[h] <= 0 or vols[low_i] <= 0:
            continue
        if closes[low_i] / closes[h] >= retrace:     # 回撤够深
            continue
        if vols[h] / vols[low_i] <= shrink:          # 回踩缩量
            continue
        state[i] = True

    def buy_reason(i):
        return (f"回踩 MA{ma_n} 确认：上穿后缩量回踩不破均线，"
                f"回撤 <{retrace}、缩量 >{shrink}×，触发买入")

    def sell_reason(i):
        return "回踩形态条件不再满足，触发卖出"

    return _state_signals(klines, state, buy_reason, sell_reason)


def _eval_tight_range(klines, closes, params):
    """N 日收盘区间放大（对应 InStock「低 ATR 成长」的实际条件）。

    原版名为「低ATR成长」，但条件里并未使用 ATR，只是「最高收盘 / 最低收盘
    ≥ ratio」且要求标的已上市足够久。这里按原义实现并保留映射说明，不擅自
    塞入 ATR 公式改变策略语义。
    """
    n = int(params.get("tight_window", 10))
    ratio = float(params.get("tight_ratio", 1.1))
    min_bars = int(params.get("tight_min_bars", 60))
    state = [False] * len(closes)
    if n > 0 and ratio > 0:
        for i in range(len(closes)):
            if i < max(min_bars, n - 1):
                continue
            w = closes[i - n + 1:i + 1]
            lo = min(w)
            if lo > 0 and max(w) / lo >= ratio:
                state[i] = True

    def buy_reason(i):
        return (f"近 {n} 日最高/最低收盘 ≥{ratio}，区间放大确认，触发买入")

    def sell_reason(i):
        return f"近 {n} 日收盘区间比回落至 {ratio} 以下，触发卖出"

    return _state_signals(klines, state, buy_reason, sell_reason)


EVALUATORS = {
    "trend": _eval_trend,
    "ma_cross": _eval_ma_cross,
    "macd": _eval_macd,
    "boll": _eval_boll,
    "rsi": _eval_rsi,
    "bias": _eval_bias,
    # 仓位管理：唯一返回三元组（含 exposure）的策略，winrate_service 自动走逐日账本
    "bias_ladder": _eval_bias_ladder,
    "grid": _eval_grid,
    # 动量/突破类（winrate_service 直接按本字典取评估器，注册即自动纳入扫描）
    "turtle_breakout": _eval_turtle_breakout,
    "high_tight_flag": _eval_high_tight_flag,
    "volume_breakout": _eval_volume_breakout,
    "pullback_ma": _eval_pullback_ma,
    "tight_range": _eval_tight_range,
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
        "id": "bias", "name": "均线偏离度", "category": "均值回归",
        "desc": "价格相对 MA 均线的偏离度(BIAS)低于阈值时买入（超卖负偏离），偏离修复后卖出。适合急跌反弹场景。",
        "params": [
            {"key": "bias_n", "label": "均线周期", "type": "number", "default": 20, "min": 5, "max": 120},
            {"key": "bias_threshold", "label": "偏离阈值%", "type": "number", "default": -3, "step": 0.5, "min": -30, "max": 0},
        ],
    },
    {
        "id": "bias_ladder", "name": "BIAS 乖离分级减仓", "category": "仓位管理",
        "desc": "档位来自 bias-position-strategy：BIAS20>10% 减半、>15% 再减半、"
                "BIAS60>20% 再减半（独立触发），目标仓位 1.0→0.5→0.25→0.125。"
                "入场/出场复用『均线偏离度』的负偏离超卖口径，便于与 bias 策略"
                "直接对比满仓 vs 分级减仓。收益按 T-1 目标仓位逐日复利，不做空、不加杠杆。"
                "注意：BIAS 是左侧信号，主升浪可能卖飞，属『少赚换安稳』。",
        "params": [
            {"key": "bias_n", "label": "入场/短周期", "type": "number", "default": 20, "min": 5, "max": 120},
            {"key": "bias_threshold", "label": "入场偏离阈值%", "type": "number", "default": -3, "step": 0.5, "min": -30, "max": 0},
            {"key": "ladder_long", "label": "长周期均线", "type": "number", "default": 60, "min": 20, "max": 250},
            {"key": "ladder_t1", "label": "短周期第一档%", "type": "number", "default": 10, "step": 0.5, "min": 1, "max": 30},
            {"key": "ladder_t2", "label": "短周期第二档%", "type": "number", "default": 15, "step": 0.5, "min": 1, "max": 40},
            {"key": "ladder_t3", "label": "长周期警戒档%", "type": "number", "default": 20, "step": 0.5, "min": 1, "max": 50},
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
    {
        "id": "turtle_breakout", "name": "海龟突破（N日新高）", "category": "动量/突破",
        "desc": "收盘价创前 N 日新高时持有（唐奇安通道）。参照高点不含当日，避免自证突破。"
                "注意：信号实验室默认只取 50 根 K 线，N>40 时需调小周期再看；"
                "胜率扫描用近 1 年约 242 根，N=60 可正常使用。",
        "params": [
            {"key": "breakout_n", "label": "突破回看周期", "type": "number", "default": 60, "min": 5, "max": 120},
        ],
    },
    {
        "id": "high_tight_flag", "name": "高而窄旗形", "category": "动量/突破",
        "desc": "前 24~10 日出现连续两日急涨，当前价站上基准低点的指定倍数。"
                "原版按 A 股个股设 9.5% 涨停口径，ETF 波动小、样本极少，"
                "建议把涨幅阈值调到 3~5%、基准倍数调到 1.1~1.3。",
        "params": [
            {"key": "flag_min_bars", "label": "最少历史K线", "type": "number", "default": 60, "min": 30, "max": 250},
            {"key": "flag_far", "label": "旗杆窗口远端(日前)", "type": "number", "default": 24, "min": 10, "max": 60},
            {"key": "flag_near", "label": "旗杆窗口近端(日前)", "type": "number", "default": 10, "min": 2, "max": 40},
            {"key": "flag_base_ratio", "label": "基准低点倍数", "type": "number", "default": 1.9, "step": 0.1, "min": 1.0, "max": 3.0},
            {"key": "flag_gain_pct", "label": "连续两日涨幅阈值%", "type": "number", "default": 9.5, "step": 0.5, "min": 1.0, "max": 20.0},
        ],
    },
    {
        "id": "volume_breakout", "name": "放量上涨", "category": "动量/突破",
        "desc": "涨幅达标 + 收阳 + 成交量放大到前 N 日均量的指定倍数。"
                "原版的『成交额≥2亿』绝对门槛因本系统 K 线不含成交额字段，"
                "已改为相对量比，绝不伪造金额；股票/ETF 通用。",
        "params": [
            {"key": "vol_gain_pct", "label": "最小涨幅%", "type": "number", "default": 2.0, "step": 0.5, "min": 0.0, "max": 10.0},
            {"key": "vol_ratio", "label": "量比倍数", "type": "number", "default": 2.0, "step": 0.1, "min": 1.0, "max": 10.0},
            {"key": "vol_ma", "label": "均量回看周期", "type": "number", "default": 5, "min": 2, "max": 60},
        ],
    },
    {
        "id": "pullback_ma", "name": "回踩长期均线", "category": "动量/突破",
        "desc": "上穿长期均线后缩量回踩且不破均线，Qullamaggie 类 continuation setup。"
                "原版用 250 日年线 + 20% 回撤（A 股个股口径）；本系统胜率扫描窗口约 1 年，"
                "默认 120 日均线，ETF 需自行下调回撤与缩量阈值。"
                "信号实验室仅 50 根 K 线，均线周期需调到 40 以内才可见。",
        "params": [
            {"key": "pullback_ma", "label": "长期均线周期", "type": "number", "default": 120, "min": 20, "max": 250},
            {"key": "pullback_lookback", "label": "形态回看窗口", "type": "number", "default": 60, "min": 20, "max": 120},
            {"key": "pullback_min_gap", "label": "高点至回踩点最少间隔", "type": "number", "default": 10, "min": 2, "max": 60},
            {"key": "pullback_max_gap", "label": "高点至回踩点最多间隔", "type": "number", "default": 50, "min": 5, "max": 120},
            {"key": "pullback_shrink", "label": "缩量倍数(高点量/低点量)", "type": "number", "default": 2.0, "step": 0.1, "min": 1.0, "max": 10.0},
            {"key": "pullback_retrace", "label": "回撤上限(低点/高点)", "type": "number", "default": 0.8, "step": 0.05, "min": 0.3, "max": 0.99},
        ],
    },
    {
        "id": "tight_range", "name": "N日区间放大（原低ATR成长）", "category": "动量/突破",
        "desc": "最近 N 日最高收盘 / 最低收盘 ≥ 指定倍数时持有。"
                "InStock 原版名为『低ATR成长』，但条件里并未使用 ATR；"
                "此处按原义实现并保留映射说明，不擅自改变策略语义。"
                "原版要求上市满 250 日，本系统窗口约 1 年，默认降到 60 根。",
        "params": [
            {"key": "tight_window", "label": "区间回看周期", "type": "number", "default": 10, "min": 3, "max": 60},
            {"key": "tight_ratio", "label": "最高/最低收盘倍数", "type": "number", "default": 1.1, "step": 0.02, "min": 1.0, "max": 2.0},
            {"key": "tight_min_bars", "label": "最少历史K线", "type": "number", "default": 60, "min": 20, "max": 250},
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
      current_price, current_position(long/flat), current_exposure(0~1),
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
            "current_exposure": None,
            "latest_signal": None, "latest_reason": None,
            "last_signal_date": None, "last_signal_type": None,
            "signal_count": 0, "signal_points": [],
            "series": {"date": [], "close": []},
            "kline_start": None, "kline_end": None, "kline_count": 0,
        }

    closes = [k["close"] for k in klines]
    # v5：评估器可选返回第三个元素 exposure（逐日目标仓位）。这里只做展示
    # 透出，不做数值口径校验（严格校验在 winrate_service._normalize_eval）。
    raw = EVALUATORS[strategy_id](klines, closes, params)
    position, signals = raw[0], raw[1]
    exposure = raw[2] if len(raw) > 2 else None
    current_exposure = (
        round(float(exposure[-1]), 4)
        if exposure and len(exposure) == len(klines)
        else (1.0 if position and position[-1] == "long" else 0.0)
    )

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
        "current_exposure": current_exposure,
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
    db = get_biz_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_signal_subscriptions (
            id VARCHAR PRIMARY KEY,
            fk_user BIGINT,
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
    db = get_biz_db()
    rows = db.fetchall(
        "SELECT id, symbol, name, strategy_id, params_json, created_at FROM "
        "biz_signal_subscriptions WHERE fk_user = ? ORDER BY created_at DESC",
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
    db = get_biz_db()
    db.execute(
        "INSERT INTO biz_signal_subscriptions (id, fk_user, symbol, name, strategy_id, params_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [rec_id, user_id, symbol if name is None else symbol, name or symbol, strategy_id,
         json.dumps(params, ensure_ascii=False), now, now],
    )
    return {"id": rec_id, "symbol": symbol, "name": name or symbol, "strategy_id": strategy_id, "params": params}


def remove_tracked(user_id: str, rec_id: str) -> bool:
    _ensure_tables()
    db = get_biz_db()
    db.execute(
        "DELETE FROM biz_signal_subscriptions WHERE id = ? AND fk_user = ?",
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


# ============================================================
# 批量战术信号快照（ETF 页「战术信号」Tab）
# 返回纯数据快照，"超卖/超买"等信号标签由前端根据阈值渲染。
# ============================================================

_TACTICAL_CACHE: dict[str, tuple[str, dict]] = {}
_TACTICAL_LOCK = threading.Lock()


def _tactical_snapshot(symbol: str) -> dict:
    """单只标的战术快照：MA20 偏离度 / RSI14 / 布林位置(0=下轨, 100=上轨)。

    基于 qfq 前复权日线；50 根 K 线足够 BIAS20 / RSI14 / BOLL(20,2) 计算与预热。
    """
    try:
        klines = get_kline(symbol)
        closes = [k["close"] for k in klines]
        if len(closes) < 21:
            return {"symbol": symbol, "price": None, "bias_20": None, "rsi_14": None,
                    "boll_pos": None, "ma_20": None,
                    "date": klines[-1]["date"] if klines else None,
                    "error": "K线数据不足（至少21根）" if klines else "未获取到行情数据"}

        price = closes[-1]
        ma20 = _sma(closes, 20)[-1]
        bias = round((price - ma20) / ma20 * 100, 2) if ma20 else None
        rsi = _rsi(closes, 14)[-1]
        sd = _stddev(closes, 20)[-1]
        upper = ma20 + 2.0 * sd if (ma20 is not None and sd is not None) else None
        lower = ma20 - 2.0 * sd if (ma20 is not None and sd is not None) else None
        boll_pos = None
        if upper is not None and lower is not None and upper > lower:
            boll_pos = round((price - lower) / (upper - lower) * 100, 1)
        return {
            "symbol": symbol, "price": round(price, 3),
            "bias_20": bias, "rsi_14": rsi, "boll_pos": boll_pos,
            "ma_20": round(ma20, 3) if ma20 is not None else None,
            "date": klines[-1]["date"], "error": None,
        }
    except Exception as e:
        return {"symbol": symbol, "price": None, "bias_20": None, "rsi_14": None,
                "boll_pos": None, "ma_20": None, "date": None, "error": str(e)}


def tactical_batch(symbols: list[str]) -> list[dict]:
    """批量战术信号快照。当日缓存（一天只算一次），行情并发拉取。"""
    today = datetime.now().strftime("%Y-%m-%d")
    out: list[dict] = []
    pending: list[str] = []
    with _TACTICAL_LOCK:
        for s in symbols:
            hit = _TACTICAL_CACHE.get(s)
            if hit and hit[0] == today:
                out.append(hit[1])
            else:
                pending.append(s)
    if pending:
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(_tactical_snapshot, pending))
        with _TACTICAL_LOCK:
            for r in results:
                _TACTICAL_CACHE[r["symbol"]] = (today, r)
        out.extend(results)
    order = {s: i for i, s in enumerate(symbols)}
    out.sort(key=lambda r: order.get(r["symbol"], 1 << 30))
    return out
