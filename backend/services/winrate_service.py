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

历史统计的 p/b 存在估计误差，半凯利是抵御过拟合的稳健实践。

回看窗口（v3）：
- 扫描显式请求 SCAN_LOOKBACK_YEARS（5 年）前复权日线；信号实验室的 50 根默认
  窗口不受影响。1 年 / 约 243 根不足以让多数策略的单标的触发数达标，
  5 年 / 约 1211 根是「能算出有意义置信区间」的下限，不是可调的观感参数。

可信性口径（v3，重要）：
- MIN_SAMPLES = 20 只作为**单标的显示阈值**（前端「样本不足」灰字、CSV 口径），
  不再作为「结论可信」的判据。n=20、胜率 60% 的 Wilson 95% 区间是
  [38.7, 78.1]，点估计本身没有意义。
- pooled 汇总输出：市场基线胜率、策略胜率、Wilson 95% CI、超额百分点、
  distinct_signal_days、IS/OOS 汇总与结论标签。基线为同批标的**全部交易日**
  的主持有期前向净收益（同窗口、同成本），不是指数涨跌幅。
- 汇总样本**不独立**：同一天多只 ETF 常因政策 / 题材共振同时触发，因此额外
  输出 distinct_signal_days 与 cluster_ratio 暴露共振程度。Wilson 区间基于
  独立同分布假设，强共振下会偏窄，只能作参照，不能当严格假设检验。
- 结论只覆盖「这段历史窗口 + 这批标的」；未做多重比较校正、未做 walk-forward、
  成本固定且未建模滑点变化。统计显著超额 ≠ 策略有效。

防过拟合（P3）：
- 样本内/外拆分：按时间前 70% / 后 30% 切分（HOLDOUT_RATIO），样本外是策略
  "没见过"的验证段——样本外胜率明显劣于样本内时提示过拟合风险
- 分年度胜率：PRIMARY_HORIZON（10日）口径按买入日年份分组，输出近 3 年，
  用于观察策略表现是否在特定市场环境（如单边熊）失效
- 注意：IS/OOS 按**每只标的自身**的前 70% / 后 30% 切分，不是全池统一日期切分

大盘门禁（v4，可选）：
- gate 是请求顶层可选字段，**不塞进 params**（params 是策略参数，混在一起会让
  「同策略不同门禁」被误判成不同策略参数，缓存与前端都要跟着分叉）。
- 门禁指数显式按 type="INDEX" 取数（指数与个股代码段重叠，_kline_asset_type
  不做猜测）；默认沪深300/中证1000/创业板指，10SMA>20SMA，任一满足即放行。
- 判定只用截至信号日当日（含）的收盘价，买入在次日收盘，**无前视偏差**；
  fast/slow 窗口不足的前 slow-1 根一律不放行。
- 全池按**日期集合**对齐过滤触发点，绝不按位置索引对齐（ETF 停牌 / 指数
  交易日不一致会错位）；基线仍取全部交易日，保证策略与基线口径可比。
- 任一门禁指数取数失败或根数不足一律抛错（fail-fast），绝不静默退化成
  「无门禁」返回一份看似正常、实则未过滤的结果。
- gate 配置进缓存键，且 SCAN_SCHEMA_VERSION 升到 4；否则同一天内
  「门禁开 / 门禁关」会命中同一份缓存串味。

分级仓位（v5，可选）：
- 评估器契约扩展为**可选**三元组 (position, signals, exposure)；exposure 是逐日
  目标仓位（0~1），长度必须等于 klines，只用 ≤ i 日数据算出（无未来函数）。
  position 仍为 flat/long 二值，触发点判定、前端 current_position 语义一律不动。
- 既有 12 个策略仍返回二元组 → exposure=None → 走**满仓固定持有**的 v4 原公式
  快速路径，数值逐字节一致。刻意不换成「补成全 1 序列再走逐日账本」的等价实现：
  逐日复利有浮点累积误差，贴近 0 的收益可能被翻转胜负判定。
- 分级仓位走逐日账本：第 t 日收益用第 t-1 日收盘决定的目标仓位 w[t-1]
  （1 日滞后，对齐 bias-position-strategy 的 target_positions[i-1]），
  equity *= (1 + w × (P[t]/P[t-1] − 1))。w≡1 时望远镜积恒等于
  P[sell]/P[buy]，即满仓是分级仓位的特例，口径只有一套。
- 成本按 turnover 计：一次完整往返（建仓 + 平仓）总成本 = cost_pct，故单边
  = cost_pct/2，每次调仓按 |Δw| 计费。单调减仓路径总 turnover 恒为
  2×w[buy]，因此「只减不加」不额外增加成本，只有回补加仓才增加。
- 市场基线**保持满仓**（全部交易日的前向收益），它是「什么都不做」的对照，
  不随策略仓位变化；这条同时保证 v4 基线数值零变化、策略与基线仍可比。
- SCAN_SCHEMA_VERSION 升到 5；顶层新增 exposure 摘要（口径 / 实际档位 /
  平均仓位）。results、pooled、caveats、CSV、表格列结构一律不动。

结果当日缓存于 biz_winrate_scan（键：scan_date + strategy_id + params_json，
params_json 内嵌 SCAN_SCHEMA_VERSION 版本号与 gate 配置），缓存命中时返回交集；
请求标的超出缓存范围的部分不做增量补算（P2 简化）。
"""

from __future__ import annotations

import json
import math
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from database.sqlite_connection import get_biz_db
from services.market_service import get_kline
from services.signal_service import EVALUATORS

# 回测成本口径（%）：双边佣金 0.06% + 冲击 0.05%
DEFAULT_COST_PCT = 0.11
# 凯利仓位封顶：历史统计的 p/b 误差大，满凯利极危险
KELLY_CAP = 0.20
# 默认持有期（交易日）
DEFAULT_HORIZONS = (5, 10, 20)
# 触发样本少于该值时统计不可靠（仅用于单标的显示，不代表 pooled 结论可信）
MIN_SAMPLES = 20
# 样本外验证：后 30% 时段为"策略未见过的"验证段（防过拟合）
HOLDOUT_RATIO = 0.3
# 分年度胜率与凯利采用的主持有期口径（pooled 汇总也用这个口径）
PRIMARY_HORIZON = 10
# 胜率扫描的历史回看年数：1 年样本严重不足，实测 5 年约 1211 根
SCAN_LOOKBACK_YEARS = 5
# 缓存键版本：统计结构/语义升级时 +1，旧缓存自动失效
# v2 = 样本内外 + 分年度；v3 = 5 年窗口 + pooled 可信统计；v4 = 可选大盘门禁；
# v5 = 可选分级仓位 exposure（逐日账本撮合 + 顶层口径摘要）
SCAN_SCHEMA_VERSION = 5
# 大盘门禁默认口径：沪深300 / 中证1000 / 创业板指，10SMA > 20SMA 任一满足放行
DEFAULT_GATE_INDICES = ("000300", "000852", "399006")
GATE_FAST = 10
GATE_SLOW = 20
GATE_MAX_INDICES = 5


def _ensure_tables() -> None:
    get_biz_db().execute(
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


def _scan_window(years: int = SCAN_LOOKBACK_YEARS) -> tuple[str, str]:
    """胜率扫描的历史窗口；显式传 start/end，不吃行情层 1 年默认值。

    用 365*years 天近似（含闰年多出的天数），网关按日期字符串取数，
    多出 1~2 天不影响口径；比 ``replace(year=...)`` 在 2/29 上更安全。
    """
    end = datetime.now()
    start = end - timedelta(days=365 * years)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _normalize_gate(gate: dict | None) -> dict | None:
    """校验并规范化门禁配置；未启用返回 None（行为与 v3 完全一致）。

    gate 是请求顶层字段，不塞进 params：params 是策略参数，两套口径混在一起
    会让「同策略不同门禁」被误判成不同策略参数，缓存与前端都要跟着分叉。
    服务层独立校验（不依赖 router 的 pydantic）：测试与内部调用同样受保护。
    """
    if not gate:
        return None
    if not isinstance(gate, dict):
        raise ValueError("gate 必须是对象")
    if not gate.get("enabled"):
        return None
    # 区分「字段缺失」与「显式传空」：后者是错误配置，必须拒绝，
    # 不能用 or 回退成默认三指数（静默篡改调用方意图）。
    raw_indices = gate.get("indices", None)
    if raw_indices is None:
        raw_indices = list(DEFAULT_GATE_INDICES)
    if not isinstance(raw_indices, (list, tuple)) or not raw_indices:
        raise ValueError("门禁指数列表不能为空")
    indices = [str(c).strip() for c in raw_indices if str(c).strip()]
    if not indices or len(indices) > GATE_MAX_INDICES:
        raise ValueError(f"门禁指数数量须在 1~{GATE_MAX_INDICES} 之间")
    if len(set(indices)) != len(indices):
        raise ValueError("门禁指数不能重复")
    fast, slow = gate.get("fast", GATE_FAST), gate.get("slow", GATE_SLOW)
    if (not isinstance(fast, int) or isinstance(fast, bool)
            or not isinstance(slow, int) or isinstance(slow, bool)):
        raise ValueError("门禁均线周期必须是整数")
    if fast < 1 or slow < 2 or fast >= slow:
        raise ValueError("门禁均线须满足 1 <= fast < slow")
    require = gate.get("require", "any")
    if require not in ("any", "all"):
        raise ValueError("门禁 require 只能是 any / all")
    return {"enabled": True, "indices": indices, "fast": fast,
            "slow": slow, "require": require}


def _sma_allowed_dates(klines: list[dict], fast: int, slow: int) -> set[str]:
    """指数日线上 fast SMA > slow SMA 的交易日集合（前缀和 O(n)）。

    - 只用截至当日（含）的收盘价，信号日收盘后即可判定；买入在次日收盘，
      因此没有前视偏差。
    - 前 slow-1 根不足窗口，一律不放行（保守，绝不外推）。
    - 返回日期字符串集合，供全池按日期对齐，不返回位置索引。
    """
    closes = [k["close"] for k in klines]
    dates = [str(k["date"])[:10] for k in klines]
    if len(closes) < slow:
        return set()
    prefix = [0.0]
    for c in closes:
        prefix.append(prefix[-1] + c)
    out: set[str] = set()
    for i in range(slow - 1, len(closes)):
        fast_ma = (prefix[i + 1] - prefix[i + 1 - fast]) / fast
        slow_ma = (prefix[i + 1] - prefix[i + 1 - slow]) / slow
        if fast_ma > slow_ma:
            out.add(dates[i])
    return out


def _build_gate(cfg: dict, window: tuple[str, str]) -> tuple[set[str], dict]:
    """按配置取门禁指数日线，算出全池统一的放行日期集合 + 可展示摘要。

    fail-fast：任一指数取数失败 / 根数不足直接抛 ValueError，绝不静默退化成
    「无门禁」——那会返回一份看似正常、实则未过滤的结果。
    """
    sets: list[set[str]] = []
    per_index: list[dict] = []
    all_days: set[str] = set()
    for code in cfg["indices"]:
        # 指数与个股代码段重叠，必须显式 type="INDEX"（_kline_asset_type 不做猜测）
        klines = get_kline(code, type="INDEX", count=0,
                           start_date=window[0], end_date=window[1])
        if len(klines) < cfg["slow"]:
            raise ValueError(
                f"大盘门禁指数 {code} 日线不足（{len(klines)} 根 < {cfg['slow']} 根），"
                "无法计算门禁均线；请检查网关 /api/quote/kline?type=INDEX"
            )
        all_days |= {str(k["date"])[:10] for k in klines}
        allowed = _sma_allowed_dates(klines, cfg["fast"], cfg["slow"])
        sets.append(allowed)
        per_index.append({"code": code, "bars": len(klines), "allowed_days": len(allowed)})
    final = set.intersection(*sets) if cfg["require"] == "all" else set.union(*sets)
    mode = "全部指数同时满足" if cfg["require"] == "all" else "任一指数满足"
    summary = {
        "enabled": True,
        "indices": cfg["indices"],
        "fast": cfg["fast"], "slow": cfg["slow"], "require": cfg["require"],
        "allowed_days": len(final),
        "total_days": len(all_days),
        "blocked_days": len(all_days - final),
        "per_index": per_index,
        "note": (
            f"{mode} {cfg['fast']}SMA>{cfg['slow']}SMA 才放行信号；"
            "按交易日期对齐各标的，未取到门禁状态的日期保守过滤；"
            "基线仍为全部交易日，保证与策略口径可比。"
        ),
    }
    return final, summary


def _wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """Wilson score 95% 置信区间（百分数），小样本比 Wald 区间稳健。"""
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z / den * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(max(0.0, center - half) * 100, 1),
            round(min(1.0, center + half) * 100, 1)]


def _pool_stats(rets: list[float]) -> dict:
    """一组净收益的池化统计：n / 胜数 / 胜率 / Wilson CI / 平均收益。"""
    n = len(rets)
    if n == 0:
        return {"n": 0, "wins": 0, "win_rate": None, "ci95": None, "avg_ret": None}
    wins = sum(1 for r in rets if r > 0)
    return {
        "n": n,
        "wins": wins,
        "win_rate": round(wins / n * 100, 1),
        "ci95": _wilson(wins, n),
        "avg_ret": round(sum(rets) / n, 3),
    }


def _pooled_summary(details: list[dict], requested: int, pool_hz: int,
                    window: tuple[str, str], cost_pct: float) -> dict:
    """把各标的的明细汇总成一份「能不能下结论」的统计对象。

    results（单标的数组）结构完全不动，pooled 是新增的并列字段，
    前端表格列与 CSV 导出口径因此零改动。
    """
    valid = [d for d in details if not d["error"]]
    baseline = [r for d in valid for r in d["baseline"]]
    strategy = [r for d in valid for r in d["strategy"]]
    is_rets = [r for d in valid for r in d["is_rets"]]
    oos_rets = [r for d in valid for r in d["oos_rets"]]
    signal_days = {day for d in valid for day in d["signal_days"]}
    bars = sorted(d["bars"] for d in valid)

    st = _pool_stats(strategy)
    ba = _pool_stats(baseline)
    is_st = _pool_stats(is_rets)
    oos_st = _pool_stats(oos_rets)
    base_wr = ba["win_rate"]
    ci = st["ci95"]

    excess = (round(st["win_rate"] - base_wr, 1)
              if st["win_rate"] is not None and base_wr is not None else None)
    direction = "none"
    if ci is not None and base_wr is not None:
        if ci[0] > base_wr:
            direction = "above"
        elif ci[1] < base_wr:
            direction = "below"

    n_days = len(signal_days)
    if st["n"] == 0:
        verdict = "无触发样本，不下结论"
    elif st["n"] < MIN_SAMPLES:
        verdict = "样本不足，不下结论"
    elif n_days < MIN_SAMPLES:
        verdict = "信号集中在少数交易日，样本不独立"
    elif base_wr is None:
        verdict = "基线不可用，仅可看点估计"
    elif direction == "above":
        verdict = "相对基线有统计显著超额（仅本样本）"
    elif direction == "below":
        verdict = "相对基线显著偏弱"
    else:
        verdict = "与基线无统计显著差异"

    decay = (round(oos_st["win_rate"] - is_st["win_rate"], 1)
             if oos_st["win_rate"] is not None and is_st["win_rate"] is not None else None)

    return {
        "horizon": pool_hz,
        "data_window": {
            "start": window[0], "end": window[1],
            "years": SCAN_LOOKBACK_YEARS,
            "bars_median": bars[len(bars) // 2] if bars else 0,
        },
        "symbols": {
            "requested": requested,
            "valid": len(valid),
            "failed": len(details) - len(valid),
        },
        "strategy": st,
        "baseline": ba,
        "excess_pp": excess,
        "direction": direction,
        "significant": direction != "none",
        "distinct_signal_days": n_days,
        "cluster_ratio": round(st["n"] / n_days, 2) if n_days else None,
        "is_oos": {"is": is_st, "oos": oos_st, "decay_pp": decay},
        "verdict": verdict,
        "caveats": [
            f"基线 = 同批标的全部交易日的 {pool_hz} 日前向净收益（同窗口、同成本 {cost_pct}%），非指数涨幅。",
            "汇总样本不独立：同日多只 ETF 常共振，强共振下 Wilson 区间偏窄，请参照 cluster_ratio。",
            "IS/OOS 按每只标的自身前 70% / 后 30% 时间切分，不是全池统一日期切分。",
            "结论仅覆盖这段历史窗口与这批标的；未做多重比较校正、未做 walk-forward。",
            "成本固定、未建模滑点变化；统计显著超额不等于策略可实盘有效。",
        ],
    }


def _kelly(p: float, b: float | None) -> tuple[float, float]:
    """凯利仓位：p=胜率(0-1)，b=赔率(平均盈利/|平均亏损|，None=无亏损样本)。

    返回 (f*, f*/2)，单位 %；f* ≤ 0 记 0（负期望），一律封顶 KELLY_CAP。
    b=0 表示「无盈利样本」（_stats 里 wins 为空时 avg_gain=0），此时必输，
    直接记 0——不能落到 (1-p)/b 上抛 ZeroDivisionError 把整只标的标成 error。
    """
    if b is None:
        # 无亏损样本：b→∞，f* = p，封顶
        f = min(p, KELLY_CAP)
    elif b <= 0:
        f = 0.0
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


def _error_result(symbol: str, msg: str) -> dict:
    """单标的失败项：字段形状与成功项一致，避免前端取字段时炸掉。"""
    return {"symbol": symbol, "error": msg, "yearly_10d": None,
            "triggers": 0, "stats_5d": None, "stats_10d": None, "stats_20d": None}


def _normalize_eval(raw: Any, n: int) -> tuple[list, list[float] | None]:
    """统一评估器返回值 -> (position, exposure)。

    既有 12 个策略返回 (position, signals) 二元组，exposure 记 None：表示
    「该策略不管理仓位，按满仓固定持有统计」，_holding_return 走精确原公式
    快速路径，数值与 v4 逐字节一致。刻意不改成「补成全 1 序列再走逐日账本」
    的等价实现：浮点累积误差可能翻转贴近 0 的胜负判定。

    bias_ladder 返回 (position, signals, exposure) 三元组：长度必须等于 klines、
    取值 ∈ [0,1] 且为有限数值，否则 fail-fast 标成单标的错误，绝不静默夹紧或
    丢弃——错误仓位会直接污染胜率结论，比少一只标的危险得多。
    """
    if not isinstance(raw, (tuple, list)) or len(raw) not in (2, 3):
        raise ValueError("评估器须返回 (position, signals) 或 (position, signals, exposure)")
    position = raw[0]
    if len(position) != n:
        raise ValueError(f"评估器 position 长度 {len(position)} != K线 {n}")
    if len(raw) == 2:
        return position, None
    exposure = raw[2]
    if exposure is None or len(exposure) != n:
        raise ValueError(f"评估器 exposure 长度须等于 K线 {n}")
    out: list[float] = []
    for w in exposure:
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            # 元素类型不对是 TypeError；取值越界才是 ValueError（数据校验）
            raise TypeError("exposure 元素必须是数值")
        v = float(w)
        if not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise ValueError("exposure 须为 0~1 的有限数值")
        out.append(v)
    return position, out


def _holding_return(closes: list[float], buy: int, sell: int,
                    exposure: list[float] | None, cost_pct: float) -> float:
    """单笔 [buy, sell] 净收益（%）。满仓与分级仓位共用一处出口。

    exposure is None（既有 12 策略）：走 v4 原公式，保证逐字节零变化。
    exposure 给定（bias_ladder）：第 t 日收益用第 t-1 日收盘决定的目标仓位
    w[t-1]（1 日滞后，无前视），逐日复利；w≡1 时望远镜积 = P[sell]/P[buy]，
    满仓因此是分级仓位的特例，口径只有一套，不是两套。

    成本 = cost_pct × turnover / 2：一次完整往返（建仓 + 平仓）= cost_pct，
    故单边按 cost_pct/2，每次调仓按 |Δw| 计费。单调减仓路径
    w[buy] + Σ|Δw| + w[sell-1] ≡ 2×w[buy]，即「只减不加」不额外收费。
    """
    if exposure is None:
        return (closes[sell] / closes[buy] - 1) * 100 - cost_pct
    equity = 1.0
    for t in range(buy + 1, sell + 1):
        w = exposure[t - 1]
        equity *= 1.0 + w * (closes[t] / closes[t - 1] - 1.0)
    turnover = exposure[buy]
    for t in range(buy + 1, sell):
        turnover += abs(exposure[t] - exposure[t - 1])
    turnover += exposure[sell - 1]
    return (equity - 1.0) * 100 - cost_pct * turnover / 2.0


def _exposure_summary(details: list[dict], strategy_id: str) -> dict:
    """顶层仓位口径摘要：本次扫描是满仓还是分级、实际档位与平均仓位。

    results / pooled 结构一律不动，新增字段只在前端做一张轻量说明卡片。
    旧缓存（v4 及更早）无 exposure 字段时调用方返回 None，前端隐藏卡片。
    """
    valid = [d for d in details if not d["error"]]
    ladder = any(d.get("exposure_mode") == "ladder" for d in valid)
    levels = sorted({lv for d in valid for lv in d["exposure_levels"]}, reverse=True)
    total_bars = sum(d["exposure_bars"] for d in valid)
    avg = (round(sum(d["exposure_sum"] for d in valid) / total_bars, 4)
           if total_bars else None)
    if ladder:
        note = ("该策略输出逐日目标仓位：收益按 T-1 目标仓位逐日复利、成本按 turnover 计；"
                "触发点仍由 flat→long 翻转决定，市场基线保持满仓，口径与满仓结果可比。")
    else:
        note = "该策略不管理仓位，按满仓固定持有统计（次日收盘买入、持有 N 日收盘卖出、扣单次成本）。"
    return {
        "mode": "ladder" if ladder else "full",
        "strategy_id": strategy_id,
        "levels": levels if ladder else [],
        "avg_exposure": avg,
        "note": note,
    }


def _scan_symbol(symbol: str, strategy_id: str, params: dict,
                 horizons: tuple[int, ...], cost_pct: float,
                 window: tuple[str, str], pool_hz: int,
                 allowed_dates: set[str] | None = None) -> tuple[dict, dict]:
    """单标的历史触发点统计（基于 qfq 前复权日线）。

    返回 ``(result, detail)``：result 进 results（形状与 v2 完全一致），
    detail 是 pooled 汇总所需的原始收益序列，只在服务内部聚合，
    不进 results、不进缓存对外结构、不进 CSV。

    allowed_dates 非 None 时按**信号日日期**过滤触发点（大盘门禁）；
    None 表示无门禁，行为与 v3 完全一致。基线始终取全部交易日，不受门禁影响。

    v5：评估器可选返回 exposure（逐日目标仓位）。二元组策略 exposure=None，
    走 _holding_return 的满仓快速路径，数值与 v4 逐字节一致；三元组策略
    走逐日账本。基线两种情况下都保持满仓，不改变。
    """
    detail: dict[str, Any] = {
        "symbol": symbol, "bars": 0, "error": None,
        "baseline": [], "strategy": [], "is_rets": [], "oos_rets": [],
        "signal_days": [],
        # 顶层 exposure 摘要所需（fail 时也有默认值，汇总不会 KeyError）
        "exposure_mode": "full", "exposure_levels": [],
        "exposure_sum": 0.0, "exposure_bars": 0,
    }

    def fail(msg: str) -> tuple[dict, dict]:
        detail["error"] = msg
        return _error_result(symbol, msg), detail

    try:
        klines = get_kline(symbol, count=0, start_date=window[0], end_date=window[1])
        closes = [k["close"] for k in klines]
        n = len(closes)
        detail["bars"] = n
        if n < 40:
            return fail("K线数据不足（至少40根）")
        evaluate = EVALUATORS.get(strategy_id)
        if evaluate is None:
            return fail(f"未知策略 {strategy_id}")

        position, exposure = _normalize_eval(evaluate(klines, closes, params), n)
        # 仓位口径摘要（顶层 exposure 用）：二元组策略按满仓固定持有统计，
        # 三元组策略按实际逐日目标仓位。基线始终保持满仓，不受此影响。
        detail["exposure_mode"] = "ladder" if exposure is not None else "full"
        detail["exposure_levels"] = (sorted({round(w, 4) for w in exposure})
                                     if exposure is not None else [])
        detail["exposure_sum"] = sum(exposure) if exposure is not None else float(n)
        detail["exposure_bars"] = n
        # 样本内/外拆分：前 70% 时段为样本内，后 30% 为策略"没见过"的验证段
        split_idx = int(n * (1 - HOLDOUT_RATIO))
        # 触发点 = 仓位由空翻多的当日（信号日）
        trigger_idx = [i for i in range(1, n) if position[i] == "long" and position[i - 1] != "long"]
        if allowed_dates is not None:
            # 大盘门禁：按日期集合对齐（ETF 停牌 / 指数交易日不一致时位置索引会错位）。
            # 门禁状态只用信号日当日收盘价判定，买入在次日收盘，无前视偏差。
            trigger_idx = [i for i in trigger_idx
                           if str(klines[i]["date"])[:10] in allowed_dates]
        out: dict[str, Any] = {"symbol": symbol, "error": None, "triggers": len(trigger_idx)}

        # 市场基线：同窗口、同成本、全部交易日的 pool_hz 日前向净收益。
        # 与策略样本共用 buy=i+1 / sell=buy+hz 的可成交假设，保证可比。
        detail["baseline"] = [
            (closes[i + 1 + pool_hz] / closes[i + 1] - 1) * 100 - cost_pct
            for i in range(1, n - pool_hz - 1)
        ]

        for hz in horizons:
            rets, is_rets, oos_rets = [], [], []
            yearly: dict[str, list[float]] = {}
            for i in trigger_idx:
                buy = i + 1        # 次日收盘买入（T+1 实际可成交）
                sell = buy + hz    # 持有 hz 个交易日后收盘卖出
                if sell >= n:
                    continue
                r = _holding_return(closes, buy, sell, exposure, cost_pct)
                rets.append(r)
                if buy < split_idx:
                    is_rets.append(r)
                else:
                    oos_rets.append(r)
                if hz == PRIMARY_HORIZON:
                    yearly.setdefault(klines[buy]["date"][:4], []).append(r)
                if hz == pool_hz:
                    detail["strategy"].append(r)
                    (detail["is_rets"] if buy < split_idx else detail["oos_rets"]).append(r)
                    detail["signal_days"].append(str(klines[i]["date"])[:10])
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
        return out, detail
    except Exception as e:  # 单只失败不影响整体，但必须留痕（禁止静默吞掉）
        msg = f"{type(e).__name__}: {e}"
        print(f"[Winrate] {symbol} 扫描异常: {msg}")
        return fail(msg)


def scan_winrate(symbols: list[str], strategy_id: str, params: dict | None = None,
                 horizons: tuple[int, ...] = DEFAULT_HORIZONS,
                 cost_pct: float = DEFAULT_COST_PCT,
                 gate: dict | None = None) -> dict:
    """批量胜率扫描。当日 + 同策略 + 同参数 + 同门禁命中缓存直接返回。"""
    if not horizons:
        # fail-fast：空持有期会让 results 缺 stats_* 且 pooled 拿不到任何样本，
        # 静默返回「无触发样本」比报错更危险，直接拒绝。
        raise ValueError("horizons 不能为空")
    # 门禁配置先校验：非法参数绝不触达数据库或行情层
    cfg = _normalize_gate(gate)
    _ensure_tables()
    today = datetime.now().strftime("%Y-%m-%d")
    # 缓存键带结构版本号 + 门禁配置：版本升级让 v3 旧缓存失效，
    # 带 gate 让同一天「门禁开 / 门禁关」不会串味。
    params_json = json.dumps({"v": SCAN_SCHEMA_VERSION, "p": params or {}, "g": cfg},
                             sort_keys=True, ensure_ascii=False)
    db = get_biz_db()
    row = db.fetchone(
        "SELECT result_json FROM biz_winrate_scan "
        "WHERE scan_date = ? AND strategy_id = ? AND params_json = ?",
        [today, strategy_id, params_json],
    )
    if row:
        cached = json.loads(row[0])
        if isinstance(cached, list):
            # 兼容 v2 及更早的裸数组缓存（版本号已升，正常不会命中）
            cached = {"results": cached, "pooled": None, "gate": None}
        by_sym = {r["symbol"]: r for r in cached.get("results", [])}
        results = [by_sym[s] for s in symbols if s in by_sym]
        return {"scan_date": today, "from_cache": True, "results": results,
                "pooled": cached.get("pooled"), "gate": cached.get("gate"),
                "exposure": cached.get("exposure")}

    window = _scan_window()
    pool_hz = (PRIMARY_HORIZON if PRIMARY_HORIZON in horizons
               else (horizons[0] if horizons else PRIMARY_HORIZON))
    # 门禁指数每只只拉一次，算出全池统一的放行日期集合后再并发扫标的
    allowed_dates, gate_summary = _build_gate(cfg, window) if cfg else (None, None)
    # 网关 K 线并发闸门 _KLINE_MAX_INFLIGHT=10，8 并发刚好在容量内，禁止盲目加并发
    with ThreadPoolExecutor(max_workers=8) as ex:
        pairs = list(ex.map(
            lambda s: _scan_symbol(s, strategy_id, params or {}, horizons, cost_pct,
                                   window, pool_hz, allowed_dates),
            symbols,
        ))
    results = [p[0] for p in pairs]
    details = [p[1] for p in pairs]
    pooled = _pooled_summary(details, len(symbols), pool_hz, window, cost_pct)
    exposure = _exposure_summary(details, strategy_id)
    if exposure["mode"] == "ladder":
        print(
            f"[Winrate] 分级仓位 exposure: 实际档位 {exposure['levels']} "
            f"平均仓位 {exposure['avg_exposure']}（逐日账本撮合，基线仍满仓）"
        )
    print(
        f"[Winrate] {strategy_id} 扫描完成: 有效 {pooled['symbols']['valid']}/"
        f"{pooled['symbols']['requested']} 只, 中位K线 {pooled['data_window']['bars_median']} 根, "
        f"n={pooled['strategy']['n']} wr={pooled['strategy']['win_rate']}% "
        f"CI={pooled['strategy']['ci95']} 基线={pooled['baseline']['win_rate']}% "
        f"独立信号日={pooled['distinct_signal_days']} → {pooled['verdict']}"
    )
    if gate_summary:
        print(
            f"[Winrate] 大盘门禁 {gate_summary['fast']}/{gate_summary['slow']}SMA "
            f"require={gate_summary['require']} indices={gate_summary['indices']} "
            f"放行 {gate_summary['allowed_days']}/{gate_summary['total_days']} 交易日 "
            f"（拦截 {gate_summary['blocked_days']} 天）"
        )
    db.execute(
        "INSERT INTO biz_winrate_scan (id, scan_date, strategy_id, params_json, result_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [str(uuid.uuid4()), today, strategy_id, params_json,
         json.dumps({"results": results, "pooled": pooled, "gate": gate_summary,
                     "exposure": exposure}, ensure_ascii=False),
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
    )
    return {"scan_date": today, "from_cache": False, "results": results,
            "pooled": pooled, "gate": gate_summary, "exposure": exposure}
