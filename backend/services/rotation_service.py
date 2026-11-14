"""组合层相对动量轮动回测（档 C）——独立模块，不改现有胜率/信号引擎。

## 为什么独立成模块

``winrate_service`` 是「单标的 · 日线 · 全仓 0/1 做多 · 固定持有 N 日」的入场点胜率
统计器，逐 symbol 独立扫描，没有横截面排序、组合权重、再平衡和资金曲线的概念。
动量轮动需要的是**逐日组合账本**：同一天在资产池内横向排名、按权重分配资金、
每 N 个交易日换仓、输出一条连续的权益曲线。把这套逻辑塞进 winrate_service 会
破坏既有 13 个策略的数值口径，因此新建独立模块，只复用 ``market_service.get_kline``
的行情通道（四源容灾链 + 显式 type）。

## 权威口径（不自己编规则）

对齐用户技能 ``momentum-buy-signal`` / ``weekly-band-workflow`` /
``bias-position-strategy`` 的 ``scripts/*.py``：

- ROC(N) = close[i] / close[i-N] - 1，默认 N=20（行情软件内置缺省）。
- 每个再平衡点按 ROC 降序排名，买入 top-K（默认 1），等权持有到下一平衡点。
- 再平衡节奏默认每 5 个交易日（周度，周五收盘定、下周持有）。
- 默认永不空仓（always_pick）；传 ``min_return`` 时全场 ROC 均不达标才持现金。
- 基准 = 等权持有资产池全部标的。
- 两两日收益 Pearson 相关系数 > 0.5 告警（品种过近易触发反转/补涨效应）。
- BIAS 三档降权：BIAS20>10% 减半 → >15% 再减半 → BIAS60>20% 再减半，
  从 1.0 起乘，档位 1 / 0.5 / 0.25 / 0.125；降权部分视为现金（0 收益）。

## 三处刻意的专业加固（不是偏离技能口径，是修技能脚本的已知缺陷）

1. **决策 T+1 生效（默认 ``execution_lag=1``）**：技能脚本 ``rotation_backtest``
   在再平衡点 i 用**当日收盘 ROC** 排名，却把**当日收益**计入新持仓，属于前视偏差，
   会系统性高估动量收益。本模块默认「i 日收盘形成信号 → i+1 日起生效」，对齐
   LEAN/zipline 的 order 在下一 bar 成交。``execution_lag=0`` 仅用于回归测试对拍
   技能脚本原口径（验证除 lag 外数值零差异），**不通过 API 暴露**。
2. **按真实上市日对齐，绝不前向填充**：技能脚本 ``load_long_csv`` 用前向填充补齐
   多资产日期，会让 2023-09 才上市的 563300 在 2021 年就"存在"，污染横截面排名与
   等权基准。本模块按日期并集对齐、缺失记 None，未上市/停牌标的当日不参与排名、
   不计收益，并在 ``coverage`` 里逐标的暴露真实有效区间。
3. **成本按权重变动计**：每次再平衡 turnover = Σ|w_new − w_old| / 2，成本 =
   turnover × cost_bps/10000。默认 cost_bps=0（对齐技能脚本），实盘应显式设置。

## 数据契约（fail-fast）

- 走 ``get_kline(type="ETF", count=0)`` 显式 5 年窗口，前复权 qfq。
- 任一标的取数失败/为空一律抛错，绝不静默剔除后返回一份"看似正常"的结果。
- 公共交易日数 < max(lookback + rebalance, 60) 一律抛错（BIAS60 需要 60 根）。
- 所有对外数值经 ``_safe()`` 过滤 NaN/Inf，绝不写裸 NaN 进 JSON。

## 边界（务必随结果一起告知用户）

结论只覆盖「这段历史窗口 + 这批标的 + 相对等权基准」；未做多重比较校正、
未做 walk-forward、前复权未建模分红再投资差异、未建模涨跌停/停牌不可成交、
整手 100 股、T+1 约束、滑点变化与跨境 ETF 汇率风险。这不是实盘可执行性判定。
"""

from __future__ import annotations

import json
import math
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

from services.market_service import get_kline

# ---- 与技能脚本完全一致的常量 ----
DEFAULT_LOOKBACK = 20
DEFAULT_REBALANCE = 5
DEFAULT_TOP = 1
CORR_WARN = 0.5
TRADING_DAYS = 242

# BIAS 三档（bias-position-strategy / weekly-band-workflow）
BIAS20_H = 0.10
BIAS20_HH = 0.15
BIAS60_H = 0.20
BIAS_LEVELS = (1.0, 0.5, 0.25, 0.125)

# 预设资产池（与 momentum-buy-signal/scripts/momentum_buy.py::PRESETS 完全一致）
PRESETS: dict[str, dict[str, Any]] = {
    "four-asset": {
        "name": "四资产轮动（沪深300 / 国债 / 纳指 / 黄金）",
        "symbols": ["510300", "511010", "513100", "518880"],
    },
    "28": {
        "name": "二八轮动（沪深300 ↔ 中证2000）",
        "symbols": ["510300", "563300"],
    },
    "chuang-hongli": {
        "name": "创业红利（创业板 ↔ 中证红利）",
        "symbols": ["159915", "515080"],
    },
}

# 参数护栏
MIN_BARS = 60
MAX_SYMBOLS = 20
MAX_WORKERS = 6
CACHE_TTL_SEC = 300
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# 数值工具
# --------------------------------------------------------------------------- #
def _safe(x: float | None) -> float | None:
    """出口防 NaN/Inf：json.dumps 会写裸 NaN（非法 JSON），Starlette 直接 500。"""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _roc(series: list[float | None], n: int) -> list[float | None]:
    """ROC(N) = close[i]/close[i-N] - 1；前 n 根为 None。与技能脚本逐点一致。"""
    out: list[float | None] = [None] * len(series)
    for i in range(n, len(series)):
        if series[i] is None or series[i - n] in (None, 0):
            continue
        out[i] = series[i] / series[i - n] - 1.0
    return out


def _daily_returns(series: list[float | None]) -> list[float | None]:
    out: list[float | None] = [None] * len(series)
    for i in range(1, len(series)):
        if series[i] is None or series[i - 1] in (None, 0):
            continue
        out[i] = series[i] / series[i - 1] - 1.0
    return out


def _pearson(x: list[float | None], y: list[float | None]) -> float | None:
    """逐点 Pearson，跳过任一为 None 的点（不前向填充，避免伪造 0 收益）。"""
    px: list[float] = []
    py: list[float] = []
    for a, b in zip(x, y):
        if a is None or b is None:
            continue
        px.append(a)
        py.append(b)
    if len(px) < 3:
        return None
    mx, my = sum(px) / len(px), sum(py) / len(py)
    cov = sum((a - mx) * (b - my) for a, b in zip(px, py))
    vx = sum((a - mx) ** 2 for a in px)
    vy = sum((b - my) ** 2 for b in py)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def _bias_position(b20: float | None, b60: float | None) -> tuple[float, list[str]]:
    """BIAS 三档阶梯 → (目标仓位, 触发档位)。与技能脚本 bias_position 逐点一致。"""
    pos = 1.0
    trig: list[str] = []
    if b20 is not None and b20 > BIAS20_H:
        pos *= 0.5
        trig.append("BIAS20>10%")
    if b20 is not None and b20 > BIAS20_HH:
        pos *= 0.5
        trig.append("BIAS20>15%")
    if b60 is not None and b60 > BIAS60_H:
        pos *= 0.5
        trig.append("BIAS60>20%")
    return pos, trig


def _bias_by_date(bars: list[dict]) -> dict[str, tuple[float, float]]:
    """按**资产自身有效交易日序列**算 BIAS20/BIAS60，返回 {date: (b20, b60)}。

    刻意不按全池并集序列算：并集里上市前的 None 会打乱 MA 窗口含义。
    与技能脚本 bias_at(series, i) 的口径一致。
    """
    closes = [float(b["close"]) for b in bars]
    dates = [str(b["date"])[:10] for b in bars]
    out: dict[str, tuple[float, float]] = {}
    for i in range(59, len(closes)):
        ma20 = sum(closes[i - 19:i + 1]) / 20
        ma60 = sum(closes[i - 59:i + 1]) / 60
        if ma20 == 0 or ma60 == 0:
            continue
        out[dates[i]] = (closes[i] / ma20 - 1.0, closes[i] / ma60 - 1.0)
    return out


def _max_drawdown(eq: list[float]) -> float:
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return mdd


def _stats(eq: list[float]) -> dict[str, float | None]:
    n = len(eq)
    total = eq[-1] - 1.0
    ann = eq[-1] ** (TRADING_DAYS / (n - 1)) - 1.0 if n > 1 and eq[-1] > 0 else None
    mdd = _max_drawdown(eq)
    rs = [eq[i] / eq[i - 1] - 1.0 for i in range(1, n) if eq[i - 1] > 0]
    vol = statistics.pstdev(rs) * math.sqrt(TRADING_DAYS) if len(rs) > 1 else None
    mean_daily = sum(rs) / len(rs) if rs else 0.0
    sharpe = (mean_daily * TRADING_DAYS / vol) if (vol and vol > 0) else None
    calmar = (ann / abs(mdd)) if (ann is not None and mdd < 0) else None
    return {
        "total_return_pct": _safe(total * 100),
        "annualized_pct": _safe(ann * 100) if ann is not None else None,
        "max_drawdown_pct": _safe(mdd * 100),
        "volatility_pct": _safe(vol * 100) if vol is not None else None,
        "sharpe": _safe(sharpe),
        "calmar": _safe(calmar),
    }


# --------------------------------------------------------------------------- #
# 取数与对齐
# --------------------------------------------------------------------------- #
def _fetch_pool(symbols: list[str], years: int) -> tuple[dict[str, list[dict]], tuple[str, str]]:
    """并发取全池前复权日线。任一标的失败一律抛错（fail-fast）。"""
    end = datetime.now()
    start = end - timedelta(days=365 * years)
    start_s, end_s = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    out: dict[str, list[dict]] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(symbols))) as ex:
        futs = {
            ex.submit(get_kline, s, "ETF", start_s, end_s, 0): s
            for s in symbols
        }
        for fut in as_completed(futs):
            sym = futs[fut]
            try:
                bars = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"[rotation] {sym} 行情取数异常: {type(e).__name__}: {e}")
                errors.append(f"{sym}: {type(e).__name__}")
                continue
            clean = [
                b for b in (bars or [])
                if b.get("date") and b.get("close") is not None
                and float(b["close"]) > 0
            ]
            clean.sort(key=lambda b: str(b["date"])[:10])
            if not clean:
                errors.append(f"{sym}: 无有效日线")
            out[sym] = clean
    if errors:
        raise ValueError(f"资产池行情取数失败（不静默剔除）: {', '.join(sorted(errors))}")
    # 并发完成顺序不确定，按请求顺序重建，保证 coverage / 排名输入可复现
    return {s: out.get(s, []) for s in symbols}, (start_s, end_s)


def _align(pool: dict[str, list[dict]]) -> tuple[list[str], dict[str, list[float | None]], list[dict]]:
    """按日期并集对齐，缺失记 None（**不前向填充**）。"""
    date_set: set[str] = set()
    for bars in pool.values():
        date_set.update(str(b["date"])[:10] for b in bars)
    dates = sorted(date_set)
    idx = {d: i for i, d in enumerate(dates)}

    closes: dict[str, list[float | None]] = {}
    coverage: list[dict] = []
    for sym, bars in pool.items():
        series: list[float | None] = [None] * len(dates)
        for b in bars:
            series[idx[str(b["date"])[:10]]] = float(b["close"])
        closes[sym] = series
        valid = [i for i, v in enumerate(series) if v is not None]
        coverage.append({
            "symbol": sym,
            "bars": len(valid),
            "first": dates[valid[0]] if valid else None,
            "last": dates[valid[-1]] if valid else None,
            "listed_late": bool(valid and valid[0] > 0),
        })
    return dates, closes, coverage


# --------------------------------------------------------------------------- #
# 主引擎
# --------------------------------------------------------------------------- #
def _validate(
    symbols: list[str], lookback: int, rebalance: int, top: int,
    years: int, cost_bps: float, execution_lag: int,
) -> list[str]:
    uniq = list(dict.fromkeys(s.strip() for s in symbols if s and s.strip()))
    if not 2 <= len(uniq) <= MAX_SYMBOLS:
        raise ValueError(f"资产池须为 2~{MAX_SYMBOLS} 只互不相同的标的")
    if not 2 <= lookback <= 250:
        raise ValueError("lookback 须在 2~250 之间")
    if not 1 <= rebalance <= 60:
        raise ValueError("rebalance 须在 1~60 之间")
    if not 1 <= top <= len(uniq):
        raise ValueError("top 须在 1~资产池数量 之间")
    if not 1 <= years <= 10:
        raise ValueError("years 须在 1~10 之间")
    if not 0 <= cost_bps <= 100:
        raise ValueError("cost_bps 须在 0~100 之间")
    if execution_lag not in (0, 1):
        raise ValueError("execution_lag 只能是 0(对拍口径) 或 1(T+1 无前视)")
    return uniq


def _rotation_ledger(
    dates: list[str],
    closes: dict[str, list[float | None]],
    assets: list[str],
    *,
    lookback: int,
    rebalance: int,
    top: int,
    min_return: float | None,
    cost_bps: float,
    bias_overlay: bool,
    bias_maps: dict[str, dict[str, tuple[float, float]]] | None,
    execution_lag: int,
) -> dict:
    """纯计算逐日组合账本：无 IO、无全局状态、无缓存。

    刻意与取数/组装分离，回归测试可以注入合成价格序列，与用户技能脚本
    ``momentum_buy.rotation_backtest()`` 在同一份数据上逐点对拍。
    ``execution_lag=0`` 完整复刻技能脚本口径（含其已知前视偏差与动态重归一），
    ``=1`` 为生产口径（T+1 生效 + 固定权重）。
    """
    n = len(dates)
    bias_maps = bias_maps or {}
    rets = {a: _roc(closes[a], lookback) for a in assets}
    dret = {a: _daily_returns(closes[a]) for a in assets}
    cost_rate = cost_bps / 10000.0
    # 技能脚本写的是 (min_return or -1e9)，min_return=0 会被 falsy 吞掉退化成 -1e9。
    # 这里显式判 None 修掉该 bug；对拍用 min_return=None 的默认值，不受影响。
    always_pick = min_return is None
    threshold = min_return if min_return is not None else -1e9

    # 初始占位为等权全池（与技能脚本 hold_rot = set(assets) 一致）
    hold: set[str] = set(assets)
    weights: dict[str, float] = {a: 1.0 / len(assets) for a in assets}
    ew_weights: dict[str, float] = {a: 1.0 / len(assets) for a in assets}

    eq_rot: list[float] = [1.0]
    eq_ew: list[float] = [1.0]
    curve: list[dict] = [{"date": dates[0], "rotation": 1.0, "equal_weight": 1.0}]
    signals: list[dict] = []
    pending: dict | None = None
    total_turnover = 0.0
    total_cost = 0.0

    def period_return(hold_set: set[str], w: dict[str, float], i: int) -> float:
        if not hold_set:
            return 0.0
        valid = [a for a in hold_set if dret[a][i] is not None]
        if not valid:
            return 0.0
        if execution_lag == 0:
            # 对拍口径：Σr / 有效个数（技能脚本会动态重归一）
            return sum(dret[a][i] for a in valid) / len(valid)
        # 生产口径：固定名义权重；缺失标的当日视为现金，不把份额摊给其它标的
        return sum(w.get(a, 0.0) * dret[a][i] for a in valid)

    def decide(i: int) -> dict:
        ranked = [(a, rets[a][i]) for a in assets if rets[a][i] is not None]
        ranked.sort(key=lambda t: t[1], reverse=True)
        if always_pick or (ranked and ranked[0][1] > threshold):
            sel = [a for a, _ in ranked[:top]]
        else:
            sel = []
        bmap: dict[str, dict] = {}
        w_new: dict[str, float] = {}
        k = max(len(sel), 1)
        for a in sel:
            pos, trig = 1.0, []
            pair: tuple[float, float] | None = None
            if bias_overlay:
                pair = bias_maps.get(a, {}).get(dates[i])
                if pair is not None:
                    pos, trig = _bias_position(pair[0], pair[1])
            w_new[a] = pos / k
            bmap[a] = {
                "bias20_pct": _safe(pair[0] * 100) if pair is not None else None,
                "bias60_pct": _safe(pair[1] * 100) if pair is not None else None,
                "target_position": pos,
                "levels": trig,
            }
        return {
            "date": dates[i],
            "selected": sel,
            "roc_pct": {a: _safe(v * 100) for a, v in ranked},
            "bias": bmap,
            "hold_set": set(sel),
            "weights": w_new,
        }

    def apply(dec: dict) -> float:
        """应用决策，返回本次换手成本。turnover = Σ|Δw| / 2。"""
        nonlocal hold, weights, total_turnover
        w_new = dec["weights"]
        union = set(weights) | set(w_new)
        turnover = sum(abs(w_new.get(a, 0.0) - weights.get(a, 0.0)) for a in union) / 2.0
        total_turnover += turnover
        hold, weights = dec["hold_set"], w_new
        return turnover * cost_rate

    for i in range(1, n):
        day_cost = 0.0
        # ① 应用上一交易日形成、今日生效的信号（T+1）
        if pending is not None and pending["effective_i"] == i:
            day_cost += apply(pending["dec"])
            pending = None

        is_rebal = i >= lookback and (i - lookback) % rebalance == 0
        # ② lag=0：先决策再计当日收益（复刻技能脚本，含其已知前视偏差）
        if execution_lag == 0 and is_rebal:
            dec = decide(i)
            day_cost += apply(dec)
            signals.append(dec)
            _finalize_signal(dec, i, execution_lag, dates)

        # ③ 计当日收益（等权基准始终满仓、不随策略仓位变化、不计换仓成本）
        r_rot = period_return(hold, weights, i)
        r_ew = period_return(set(assets), ew_weights, i)
        eq_rot.append(eq_rot[-1] * (1 + r_rot - day_cost))
        eq_ew.append(eq_ew[-1] * (1 + r_ew))
        total_cost += day_cost
        curve.append({
            "date": dates[i],
            "rotation": _safe(eq_rot[-1]),
            "equal_weight": _safe(eq_ew[-1]),
        })

        # ④ lag=1：i 日收盘形成信号，i+1 日起生效（无前视）
        if execution_lag == 1 and is_rebal:
            dec = decide(i)
            signals.append(dec)
            _finalize_signal(dec, i, execution_lag, dates)
            if i + 1 < n:
                pending = {"effective_i": i + 1, "dec": dec}

    return {
        "eq_rot": eq_rot, "eq_ew": eq_ew, "curve": curve,
        "signals": signals, "dret": dret,
        "total_turnover": total_turnover, "total_cost": total_cost,
    }


def run_rotation(
    symbols: list[str],
    lookback: int = DEFAULT_LOOKBACK,
    rebalance: int = DEFAULT_REBALANCE,
    top: int = DEFAULT_TOP,
    years: int = 5,
    min_return: float | None = None,
    cost_bps: float = 0.0,
    bias_overlay: bool = False,
    execution_lag: int = 1,
    use_cache: bool = True,
) -> dict:
    """跑一次组合层动量轮动回测，返回完整结果对象（取数 + 纯计算 + 组装）。

    ``execution_lag=0`` 复刻技能脚本口径（含已知前视偏差），仅供回归对拍；
    生产路径固定 1，router 不暴露该参数。
    """
    uniq = _validate(symbols, lookback, rebalance, top, years, cost_bps, execution_lag)
    cache_key = json.dumps(
        [uniq, lookback, rebalance, top, years, min_return, cost_bps, bias_overlay, execution_lag],
        sort_keys=True, ensure_ascii=False,
    )
    if use_cache:
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
            if hit and time.time() - hit[0] < CACHE_TTL_SEC:
                return hit[1]

    pool, window = _fetch_pool(uniq, years)
    dates, closes, coverage = _align(pool)
    n = len(dates)
    need = max(lookback + rebalance, MIN_BARS)
    if n < need:
        raise ValueError(f"公共交易日仅 {n} 根，少于最低要求 {need} 根，无法形成有效回测")

    # 排序保证 ROC 并列时排名确定，与技能脚本 assets=sorted(...) 一致
    assets = sorted(uniq)
    bias_maps = {a: _bias_by_date(pool[a]) for a in assets} if bias_overlay else None
    ledger = _rotation_ledger(
        dates, closes, assets,
        lookback=lookback, rebalance=rebalance, top=top,
        min_return=min_return, cost_bps=cost_bps,
        bias_overlay=bias_overlay, bias_maps=bias_maps,
        execution_lag=execution_lag,
    )
    eq_rot = ledger["eq_rot"]
    eq_ew = ledger["eq_ew"]
    curve = ledger["curve"]
    signals = ledger["signals"]
    dret = ledger["dret"]
    total_turnover = ledger["total_turnover"]
    total_cost = ledger["total_cost"]

    rot_stats, ew_stats = _stats(eq_rot), _stats(eq_ew)
    excess = (
        rot_stats["total_return_pct"] - ew_stats["total_return_pct"]
        if rot_stats["total_return_pct"] is not None and ew_stats["total_return_pct"] is not None
        else None
    )

    # ---- 资产池相关性诊断 ----
    pairs: list[dict] = []
    warnings: list[str] = []
    for x in range(len(assets)):
        for y in range(x + 1, len(assets)):
            c = _pearson(dret[assets[x]], dret[assets[y]])
            warn = c is not None and c > CORR_WARN
            pairs.append({
                "a": assets[x], "b": assets[y],
                "value": _safe(round(c, 4)) if c is not None else None,
                "warn": bool(warn),
            })
            if warn:
                warnings.append(f"{assets[x]} ~ {assets[y]} 相关系数 {c:.2f} > {CORR_WARN}")

    # ---- 对外信号（去掉内部 hold_set / weights，补上生效日与上周持仓）----
    public_signals: list[dict] = []
    for k, s in enumerate(signals):
        prev = signals[k - 1]["selected"] if k > 0 else []
        public_signals.append({
            "date": s["date"],
            "effective_date": s.get("effective_date"),
            "selected": s["selected"],
            "prev_selected": prev,
            "roc_pct": s["roc_pct"],
            "bias": s["bias"],
        })
    latest = public_signals[-1] if public_signals else None
    if latest:
        cur, prev = set(latest["selected"]), set(latest["prev_selected"])
        actions = [
            {"symbol": a, "action": "轮入/新建仓" if a not in prev else "继续持有",
             "target_position": latest["bias"].get(a, {}).get("target_position", 1.0)}
            for a in latest["selected"]
        ] + [
            {"symbol": a, "action": "轮出", "target_position": 0.0}
            for a in sorted(prev - cur)
        ]
        # 全场走弱时空仓本身就是一个决策，必须显式落一条动作，
        # 否则前端 latest 卡片一片空白，用户看不出「本周应持现金」。
        if not cur:
            actions.append({
                "symbol": "CASH",
                "action": "全场走弱，持现金/空仓",
                "target_position": 0.0,
            })
        latest = {**latest, "stance": "invested" if cur else "cash", "actions": actions}

    caveats = [
        "结论只对「这段历史窗口 + 这批标的 + 相对等权基准」成立，不是策略有效性证明。",
        "默认 T+1 生效：信号日收盘用 ROC 排名，按信号日收盘价近似成交，"
        "次一交易日起计入新持仓收益，无前视偏差；未建模实际集合竞价/开盘成交价与隔夜跳空。",
        "未做多重比较校正、未做 walk-forward / 样本外验证，历史超额可能来自过拟合。",
        "前复权 qfq 未建模分红再投资差异；未建模涨跌停、停牌不可成交、整手 100 股、"
        "A股股票型 ETF 的 T+1 卖出限制、滑点变化与跨境 ETF 汇率风险。",
        f"成本默认 cost_bps={cost_bps:g}（0 表示不计成本，与技能脚本口径一致）；"
        "实盘须按券商费率显式设置，换手成本会显著侵蚀周度轮动收益。",
        "上市较晚的标的在上市前不参与排名也不计收益，等权基准早期覆盖较少，"
        "横向对比请先查看 coverage。",
        "相关性 > 0.5 的资产对提示品种过近、易触发反转/补涨效应吞噬动量超额。",
    ]
    if execution_lag == 0:
        caveats.insert(0, "⚠ 本结果使用 execution_lag=0（复刻技能脚本口径），含已知前视偏差，仅供回归对拍，不可用于决策。")

    result = {
        "config": {
            "symbols": assets, "lookback": lookback, "rebalance": rebalance,
            "top": top, "years": years, "min_return": min_return,
            "cost_bps": cost_bps, "bias_overlay": bias_overlay,
            "execution_lag": execution_lag, "always_pick": min_return is None,
            "corr_warn": CORR_WARN, "benchmark": "等权持有资产池全部标的",
        },
        "window": {"start": dates[0], "end": dates[-1], "trading_days": n,
                   "requested": {"start": window[0], "end": window[1]}},
        "coverage": coverage,
        "metrics": {
            "rotation": rot_stats,
            "equal_weight": ew_stats,
            "excess_pp": _safe(excess),
            "rebalance_count": len(signals),
            "total_turnover": _safe(total_turnover),
            "total_cost_pct": _safe(total_cost * 100),
        },
        "equity_curve": curve,
        "signals": public_signals,
        "correlation": {"pairs": pairs, "warnings": warnings},
        "latest": latest,
        "caveats": caveats,
    }
    if use_cache:
        with _CACHE_LOCK:
            _CACHE[cache_key] = (time.time(), result)
    return result


def _finalize_signal(dec: dict, i: int, execution_lag: int, dates: list[str]) -> None:
    """给内部决策补生效日。lag=0 当日生效，lag=1 次一交易日生效。"""
    if execution_lag == 0:
        dec["effective_date"] = dates[i]
    else:
        dec["effective_date"] = dates[i + 1] if i + 1 < len(dates) else None


def get_presets() -> list[dict]:
    """前端预设池下拉（结构稳定，不随回测结果变化）。"""
    return [{"key": k, **v} for k, v in PRESETS.items()]


def clear_cache() -> int:
    with _CACHE_LOCK:
        n = len(_CACHE)
        _CACHE.clear()
        return n
