"""胜率扫描服务：全市场 ETF × 策略条件 × 持有期的历史胜率统计 + 凯利仓位建议。

统计口径（固定，避免口径漂移）：
- 触发 = 策略评估器的仓位由 flat 翻转为 long 的当日（信号日）
- 买入 = 信号日**次日收盘价**（贴近 T+1 实际可成交价；用触发日收盘买入是常见
  的未来函数作弊，历史胜率会被系统性高估）
- 卖出 = 买入日后第 N 个交易日收盘价（N ∈ {5, 10, 20}）
- 净收益 = (卖出价 / 买入价 − 1) × 100 − 单次成本（默认双边佣金 0.06% + 冲击 0.05%）
- 胜率 = 净收益 > 0 的样本占比；赔率 b = 平均单次盈利 / |平均单次亏损|
- 凯利 f* = p − (1−p)/b；无亏损样本时 f* = p；一律封顶 20%，负期望记 0
- 对外输出半凯利（f*/2）为建议仓位，满凯利仅作理论参考

历史统计的 p/b 存在估计误差，半凯利是抵御过拟合的稳健实践；
样本数 < 阈值（默认 20）的统计不可靠，由前端标记"样本不足"不下结论。

防过拟合（P3）：
- 样本内/外拆分：按时间前 70% / 后 30% 切分（HOLDOUT_RATIO），样本外是策略
  "没见过"的验证段——样本外胜率明显劣于样本内时提示过拟合风险
- 分年度胜率：PRIMARY_HORIZON（10日）口径按买入日年份分组，输出近 3 年，
  用于观察策略表现是否在特定市场环境（如单边熊）失效

结果当日缓存于 biz_winrate_scan（键：scan_date + strategy_id + params_json，
params_json 内嵌 SCAN_SCHEMA_VERSION 版本号），缓存命中时返回交集；
请求标的超出缓存范围的部分不做增量补算（P2 简化）。
"""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from database.connection import get_db
from services.market_service import get_kline
from services.signal_service import EVALUATORS

# 回测成本口径（%）：双边佣金 0.06% + 冲击 0.05%
DEFAULT_COST_PCT = 0.11
# 凯利仓位封顶：历史统计的 p/b 误差大，满凯利极危险
KELLY_CAP = 0.20
# 默认持有期（交易日）
DEFAULT_HORIZONS = (5, 10, 20)
# 触发样本少于该值时统计不可靠
MIN_SAMPLES = 20
# 样本外验证：后 30% 时段为"策略未见过的"验证段（防过拟合）
HOLDOUT_RATIO = 0.3
# 分年度胜率与凯利采用的主持有期口径
PRIMARY_HORIZON = 10
# 缓存键版本：统计结构升级时 +1，旧缓存自动失效
SCAN_SCHEMA_VERSION = 2


def _ensure_tables() -> None:
    get_db().execute(
        """
        CREATE TABLE IF NOT EXISTS biz_winrate_scan (
            id VARCHAR PRIMARY KEY,
            scan_date VARCHAR,
            strategy_id VARCHAR,
            params_json VARCHAR,
            result_json VARCHAR,
            created_at VARCHAR
        )
        """
    )


def _kelly(p: float, b: float | None) -> tuple[float, float]:
    """凯利仓位：p=胜率(0-1)，b=赔率(平均盈利/|平均亏损|，None=无亏损样本)。

    返回 (f*, f*/2)，单位 %；f* ≤ 0 记 0（负期望），一律封顶 KELLY_CAP。
    """
    if b is None:
        # 无亏损样本：b→∞，f* = p，封顶
        f = min(p, KELLY_CAP)
    else:
        f = p - (1 - p) / b
        f = 0.0 if f <= 0 else min(f, KELLY_CAP)
    return round(f * 100, 1), round(f * 50, 1)


def _stats(rets: list[float]) -> dict:
    """单持有期统计：样本数/胜率/平均盈亏/赔率/凯利。"""
    m = len(rets)
    if m == 0:
        return {"samples": 0, "win_rate": None, "avg_gain": None,
                "avg_loss": None, "payoff": None, "kelly": None, "half_kelly": None}
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    p = len(wins) / m
    avg_gain = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    payoff = (avg_gain / abs(avg_loss)) if avg_loss < 0 else None
    kelly, half = _kelly(p, payoff)
    return {
        "samples": m,
        "win_rate": round(p * 100, 1),
        "avg_gain": round(avg_gain, 3),
        "avg_loss": round(avg_loss, 3),
        "payoff": round(payoff, 2) if payoff is not None else None,
        "kelly": kelly,
        "half_kelly": half,
    }


def _win_rate_of(rets: list[float]) -> float | None:
    if not rets:
        return None
    return round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1)


def _scan_symbol(symbol: str, strategy_id: str, params: dict,
                 horizons: tuple[int, ...], cost_pct: float) -> dict:
    """单只标的历史触发点的前向收益统计（基于 qfq 前复权日线）。"""
    try:
        klines = get_kline(symbol, count=0)
        closes = [k["close"] for k in klines]
        if len(closes) < 40:
            return {"symbol": symbol, "error": "K线数据不足（至少40根）", "yearly_10d": None,
                    "triggers": 0, "stats_5d": None, "stats_10d": None, "stats_20d": None}
        evaluate = EVALUATORS.get(strategy_id)
        if evaluate is None:
            return {"symbol": symbol, "error": f"未知策略 {strategy_id}", "yearly_10d": None,
                    "triggers": 0, "stats_5d": None, "stats_10d": None, "stats_20d": None}
        position, _ = evaluate(klines, closes, params)
        n = len(closes)
        # 样本内/外拆分：前 70% 时段为样本内，后 30% 为策略"没见过"的验证段
        split_idx = int(n * (1 - HOLDOUT_RATIO))
        # 触发点 = 仓位由空翻多的当日（信号日）
        trigger_idx = [i for i in range(1, n) if position[i] == "long" and position[i - 1] != "long"]
        out: dict[str, Any] = {"symbol": symbol, "error": None, "triggers": len(trigger_idx)}
        for hz in horizons:
            rets, is_rets, oos_rets = [], [], []
            yearly: dict[str, list[float]] = {}
            for i in trigger_idx:
                buy = i + 1        # 次日收盘买入（T+1 实际可成交）
                sell = buy + hz    # 持有 hz 个交易日后收盘卖出
                if sell >= n:
                    continue
                r = (closes[sell] / closes[buy] - 1) * 100 - cost_pct
                rets.append(r)
                if buy < split_idx:
                    is_rets.append(r)
                else:
                    oos_rets.append(r)
                if hz == PRIMARY_HORIZON:
                    yearly.setdefault(klines[buy]["date"][:4], []).append(r)
            st = _stats(rets)
            st["is_samples"] = len(is_rets)
            st["is_win_rate"] = _win_rate_of(is_rets)
            st["oos_samples"] = len(oos_rets)
            st["oos_win_rate"] = _win_rate_of(oos_rets)
            out[f"stats_{hz}d"] = st
            if hz == PRIMARY_HORIZON:
                out["yearly_10d"] = [
                    {"year": y, "samples": len(rs), "win_rate": _win_rate_of(rs)}
                    for y, rs in sorted(yearly.items())
                ][-3:]  # 近 3 年
        return out
    except Exception as e:  # 单只失败不影响整体
        return {"symbol": symbol, "error": str(e), "yearly_10d": None,
                "triggers": 0, "stats_5d": None, "stats_10d": None, "stats_20d": None}


def scan_winrate(symbols: list[str], strategy_id: str, params: dict | None = None,
                 horizons: tuple[int, ...] = DEFAULT_HORIZONS,
                 cost_pct: float = DEFAULT_COST_PCT) -> dict:
    """批量胜率扫描。当日 + 同策略 + 同参数命中缓存直接返回。"""
    _ensure_tables()
    today = datetime.now().strftime("%Y-%m-%d")
    # 缓存键带结构版本号：统计结构升级（如 v2 增加样本内外/分年度）时旧缓存自动失效
    params_json = json.dumps({"v": SCAN_SCHEMA_VERSION, "p": params or {}},
                             sort_keys=True, ensure_ascii=False)
    db = get_db()
    row = db.fetchone(
        "SELECT result_json FROM biz_winrate_scan "
        "WHERE scan_date = ? AND strategy_id = ? AND params_json = ?",
        [today, strategy_id, params_json],
    )
    if row:
        by_sym = {r["symbol"]: r for r in json.loads(row[0])}
        results = [by_sym[s] for s in symbols if s in by_sym]
        return {"scan_date": today, "from_cache": True, "results": results}

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(
            ex.map(lambda s: _scan_symbol(s, strategy_id, params or {}, horizons, cost_pct), symbols)
        )
    db.execute(
        "INSERT INTO biz_winrate_scan (id, scan_date, strategy_id, params_json, result_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [str(uuid.uuid4()), today, strategy_id, params_json,
         json.dumps(results, ensure_ascii=False), datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
    )
    return {"scan_date": today, "from_cache": False, "results": results}
