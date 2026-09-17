"""Strategy library service — 经典实盘策略库 + 回测引擎 + 绩效监控。

定位（区别于 signal_service 的单标的信号实验室）：
- LIBRARY 收录「轮动类」经典实盘策略，标注真实来源与实盘背景：
  * cb_double_low  双低转债轮动 —— 集思录可转债区最经典策略，众多大V长期实盘；
  * two_eight      二八轮动（沪深300 vs 中证500）—— 经久不衰的大小盘轮动实盘策略；
  * index_momentum 指数动量轮动 —— 量化圈广泛实盘的 ETF 动量轮动（指数代理）。
- 回测基于真实指数日 K 线（新浪 stock_zh_index_daily，300 根 ≈ 15 个月），
  T 日收盘产生信号、T+1 生效，换仓计双边费用，杜绝未来函数。
- 双低转债为实时快照策略（转债历史 K 线数据源不可用），提供当日全市场
  双低排名与持仓建议，绩效受数据源限制如实标注，绝不伪造历史。
- 跟踪订阅（biz_library_subscriptions）+ 每日绩效快照（biz_library_snapshots），
  系统按日跟踪用户所关注策略的表现，形成"策略绩效监控"闭环。
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from database.connection import get_db
from services.market_service import get_index_history
from services.convertible_bond_service import get_convertible_bonds

# 年化交易日（A 股）
_TRADING_DAYS = 244
# 轮动换仓单边费率（万5，ETF/转债场内交易的典型水平）
_FEE_RATE = 0.0005


# ============================================================
# 策略库目录
# ============================================================

LIBRARY: list[dict[str, Any]] = [
    {
        "id": "cb_double_low",
        "name": "双低转债轮动",
        "category": "可转债轮动",
        "source": "集思录",
        "source_note": "集思录可转债区最经典的实盘策略，众多大V长期公开实盘跟踪。"
                       "双低值 = 转债价格 + 转股溢价率，兼顾债底安全与股性弹性，"
                       "持有双低最小的前 N 只并定期轮动。",
        "style": "低回撤稳健型",
        "desc": "全市场可转债按双低值升序排名，等权持有前 N 只（默认 10 只），"
                "每周或每月调仓一次：卖出跌出排名的双低券，买入新进入者。"
                "攻守兼备——下有债底保护，上随正股上涨。",
        "params": [
            {"key": "hold_n", "label": "持仓数量", "type": "number", "default": 10, "min": 3, "max": 30},
            {"key": "price_max", "label": "价格上限", "type": "number", "default": 150, "min": 100, "max": 200, "step": 1},
            {"key": "double_low_max", "label": "双低上限", "type": "number", "default": 0, "min": 0, "max": 250, "step": 1,
             "help": "0 表示不限制"},
        ],
        "kind": "cb_snapshot",
        "members": [],
    },
    {
        "id": "two_eight",
        "name": "二八轮动（大盘vs小盘）",
        "category": "指数轮动",
        "source": "经典实盘策略",
        "source_note": "「二八轮动」是 A 股经久不衰的散户实盘策略：比较沪深300（二成大盘蓝筹）"
                       "与中证500（八成中小盘）的近期动量，永远持有强者，弱市空仓。"
                       " ETF 界长期流行，蛋卷/且慢等平台均有对应组合实盘。",
        "style": "趋势轮动型",
        "desc": "每日收盘比较沪深300 与中证500 近 N 日（默认 20 日）涨幅："
                "持有涨幅更大的一方；两者均为负时空仓避险（可关闭）。"
                "追随风格切换，避免满仓扛跌。",
        "params": [
            {"key": "mom_window", "label": "动量窗口(日)", "type": "number", "default": 20, "min": 5, "max": 60},
            {"key": "allow_cash", "label": "弱市空仓", "type": "switch", "default": 1, "min": 0, "max": 1,
             "help": "开启后两者动量均为负时持有现金"},
        ],
        "kind": "index_rotation",
        "members": [
            {"code": "000300", "name": "沪深300"},
            {"code": "000905", "name": "中证500"},
        ],
    },
    {
        "id": "index_momentum",
        "name": "指数动量轮动（四强选一）",
        "category": "指数轮动",
        "source": "经典实盘策略",
        "source_note": "量化圈广泛实盘的「ETF 动量轮动」代表版本：在沪深300 / 中证500 / "
                       "中证1000 / 科创50 四大宽基中持有近 N 日动量最强的一只，"
                       "全部走弱则空仓。指数作为 ETF 代理，逻辑与 ETF 实盘一致。",
        "style": "强动量进攻型",
        "desc": "每日收盘比较四大宽基指数近 N 日（默认 20 日）涨幅，持有最强者；"
                "全部为负时空仓。弹性大于二八轮动，适合趋势市。",
        "params": [
            {"key": "mom_window", "label": "动量窗口(日)", "type": "number", "default": 20, "min": 5, "max": 60},
            {"key": "allow_cash", "label": "弱市空仓", "type": "switch", "default": 1, "min": 0, "max": 1},
        ],
        "kind": "index_rotation",
        "members": [
            {"code": "000300", "name": "沪深300"},
            {"code": "000905", "name": "中证500"},
            {"code": "000852", "name": "中证1000"},
            {"code": "000688", "name": "科创50"},
        ],
    },
]


def get_library() -> list[dict[str, Any]]:
    """策略库目录（静态元数据，不含绩效——绩效按需回测）。"""
    return LIBRARY


def _library_by_id(sid: str) -> Optional[dict[str, Any]]:
    for s in LIBRARY:
        if s["id"] == sid:
            return s
    return None


def _param_value(params: dict | None, key: str, default):
    """读取用户参数，缺失/非法时回退默认值。"""
    params = params or {}
    v = params.get(key, default)
    if v in (None, ""):
        return default
    try:
        if isinstance(default, bool) or key == "allow_cash":
            return int(v) == 1 or v is True
        if isinstance(default, int):
            return int(v)
        if isinstance(default, float):
            return float(v)
    except (ValueError, TypeError):
        return default
    return v


# ============================================================
# 回测引擎（指数轮动）
# ============================================================

def _aligned_close_matrix(codes: list[str]) -> tuple[list[str], dict[str, list[float]]]:
    """拉取各指数日 K 并按日期对齐，返回 (dates, {code: [close...]})。"""
    series: dict[str, dict[str, float]] = {}
    for code in codes:
        pts = get_index_history(code)
        if pts:
            series[code] = {p["date"]: float(p["close"]) for p in pts}
    if not series:
        return [], {}
    # 日期取交集并升序
    common = set.intersection(*(set(s.keys()) for s in series.values()))
    dates = sorted(common)
    matrix = {code: [series[code][d] for d in dates] for code in codes}
    return dates, matrix


def _perf_stats(navs: list[float], dates: list[str]) -> dict[str, Any]:
    """由净值序列计算绩效指标。"""
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs)) if navs[i - 1] > 0]
    cum = navs[-1] / navs[0] - 1 if navs[0] > 0 else 0.0
    days = max(len(navs) - 1, 1)
    annual = (1 + cum) ** (_TRADING_DAYS / days) - 1 if cum > -1 else -1.0
    # 最大回撤
    peak, mdd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    # 夏普（无风险利率按 2% 年化）
    sharpe = 0.0
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        if sd > 0:
            daily_rf = 0.02 / _TRADING_DAYS
            sharpe = (mean - daily_rf) / sd * math.sqrt(_TRADING_DAYS)
    win = sum(1 for r in rets if r > 0) / len(rets) if rets else 0.0
    return {
        "cum_return_pct": round(cum * 100, 2),
        "annual_return_pct": round(annual * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "sharpe": round(sharpe, 2),
        "win_rate_pct": round(win * 100, 1),
    }


def backtest_rotation(strategy: dict[str, Any], params: dict | None) -> dict[str, Any]:
    """指数轮动回测：T 日收盘动量 → T+1 持仓，换仓扣双边费用。"""
    members = strategy["members"]
    codes = [m["code"] for m in members]
    names = {m["code"]: m["name"] for m in members}
    mom_w = _param_value(params, "mom_window", 20)
    allow_cash = _param_value(params, "allow_cash", True)

    dates, matrix = _aligned_close_matrix(codes)
    if not dates or len(dates) <= mom_w + 2:
        return {"error": "指数历史数据不足，无法回测（数据源不可用）"}

    n = len(dates)
    # 每日持仓目标（在 i-1 收盘确定，i 日生效）：target[i] = 基于 i-1 数据的动量最强者
    # i 从 warmup+1 开始为可交易日
    warmup = mom_w
    nav = 1.0
    navs: list[float] = []
    curve_dates: list[str] = []
    held: Optional[str] = None
    trades = 0
    holding_history: list[dict[str, Any]] = []

    for i in range(warmup + 1, n):
        # 动量：closes[i-1] / closes[i-1-mom_w] - 1
        moms = {
            c: matrix[c][i - 1] / matrix[c][i - 1 - mom_w] - 1
            for c in codes
            if matrix[c][i - 1 - mom_w] > 0
        }
        if not moms:
            continue
        best = max(moms, key=moms.get)
        target = best if (moms[best] > 0 or not allow_cash) else None
        # 换仓：T+1 开仓按前收附近成交（以 i-1 收盘近似），扣双边费用
        if held != target:
            if held is not None or target is not None:
                trades += 1
                nav *= (1 - 2 * _FEE_RATE)
            holding_history.append({
                "date": dates[i],
                "holding": names.get(target, "空仓") if target else "空仓",
                "code": target or "",
                "reason": (
                    f"{names[best]} 近{mom_w}日涨幅 {moms[best]*100:.2f}% 领先，切换持有"
                    if target else f"各指数近{mom_w}日涨幅均为负，空仓避险"
                ) if held != target else "",
            })
            held = target
        # 当日收益：持有成员 i-1 → i 的涨幅；空仓收益 0
        if held:
            nav *= (1 + (matrix[held][i] / matrix[held][i - 1] - 1))
        navs.append(round(nav, 6))
        curve_dates.append(dates[i])

    if not navs:
        return {"error": "回测区间不足"}

    perf = _perf_stats([1.0] + navs, curve_dates)

    # 基准：等权买入持有（各成员从回测起点等权持有到底）
    bench_navs: list[float] = []
    bnav = 1.0
    for i in range(warmup + 1, n):
        day_ret = sum(matrix[c][i] / matrix[c][i - 1] - 1 for c in codes) / len(codes)
        bnav *= (1 + day_ret)
        bench_navs.append(round(bnav, 6))
    bench_perf = _perf_stats([1.0] + bench_navs, curve_dates)

    # 当前持仓建议（基于最新收盘）
    moms_now = {
        c: matrix[c][n - 1] / matrix[c][n - 1 - mom_w] - 1
        for c in codes if matrix[c][n - 1 - mom_w] > 0
    }
    current: Optional[dict[str, Any]] = None
    if moms_now:
        best = max(moms_now, key=moms_now.get)
        cash_now = allow_cash and moms_now[best] <= 0
        current = {
            "code": best,
            "name": names[best],
            "mom_pct": round(moms_now[best] * 100, 2),
            "action": "空仓观望（动量均为负）" if cash_now else f"持有 {names[best]}",
        }
        # 各成员动量明细
        current["members_mom"] = [
            {"code": c, "name": names[c], "mom_pct": round(v * 100, 2)}
            for c, v in sorted(moms_now.items(), key=lambda kv: kv[1], reverse=True)
        ]

    return {
        "kind": "index_rotation",
        "start_date": curve_dates[0],
        "end_date": curve_dates[-1],
        "trading_days": len(navs),
        "mom_window": mom_w,
        "allow_cash": allow_cash,
        "trades": trades,
        **perf,
        "benchmark": {
            "name": "等权买入持有",
            **bench_perf,
        },
        "excess_pct": round(perf["cum_return_pct"] - bench_perf["cum_return_pct"], 2),
        "curve": {
            "date": curve_dates,
            "strategy_nav": navs,
            "benchmark_nav": bench_navs,
        },
        "current_holding": current,
        "recent_switches": holding_history[-8:],
        "note": f"基于真实指数日K线回测（{curve_dates[0]} ~ {curve_dates[-1]}，{len(navs)} 个交易日），"
                f"T日信号T+1执行，换仓计万5双边费用；指数为对应ETF的价格代理。",
    }


# ============================================================
# 双低转债组合（实时快照）
# ============================================================

def cb_double_low_portfolio(params: dict | None) -> dict[str, Any]:
    """双低转债轮动的当日实时组合建议（集思录经典策略）。"""
    hold_n = _param_value(params, "hold_n", 10)
    price_max = _param_value(params, "price_max", 150)
    dl_max = _param_value(params, "double_low_max", 0)

    kwargs: dict[str, Any] = {}
    if price_max:
        kwargs["price_max"] = float(price_max)
    if dl_max:
        kwargs["double_low_max"] = float(dl_max)
    bonds = get_convertible_bonds(**kwargs)
    if not bonds:
        return {"error": "可转债实时数据获取失败（数据源不可用）"}

    # 过滤占位数据：未上市/待发行新券东财给 price=100/conv=0/prem=0 的占位行，
    # 会伪装成"双低=100"污染排名，按 conv_value>0（已可转股）剔除
    ranked = sorted(
        (b for b in bonds
         if b.get("double_low_score") is not None and (b.get("conv_value") or 0) > 0),
        key=lambda b: b["double_low_score"],
    )
    portfolio = ranked[:hold_n]

    def _brief(b: dict) -> dict[str, Any]:
        return {
            "code": b.get("code"),
            "name": b.get("name"),
            "price": b.get("price"),
            "premium_pct": b.get("premium_pct"),
            "double_low_score": b.get("double_low_score"),
            "ytm": b.get("ytm"),
            "rating": b.get("rating"),
            "stock_name": b.get("stock_name"),
        }

    avg_dl = sum(b["double_low_score"] for b in portfolio) / len(portfolio) if portfolio else None
    avg_price = sum(b["price"] for b in portfolio) / len(portfolio) if portfolio else None
    avg_prem = sum(b.get("premium_pct") or 0 for b in portfolio) / len(portfolio) if portfolio else None

    return {
        "kind": "cb_snapshot",
        "hold_n": hold_n,
        "universe_count": len(ranked),
        "portfolio": [_brief(b) for b in portfolio],
        "top_ranking": [_brief(b) for b in ranked[:hold_n + 10]],
        "avg_double_low": round(avg_dl, 2) if avg_dl else None,
        "avg_price": round(avg_price, 2) if avg_price else None,
        "avg_premium_pct": round(avg_prem, 2) if avg_prem is not None else None,
        "note": "双低转债为实时快照策略：转债历史K线数据源不可用，故不提供历史回测，"
                "绝不伪造。以下为按当日全市场双低值排序的持仓建议，"
                "实际操作按「每周/每月调仓、卖出跌出前N者、买入新进入者」执行。",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================
# 统一回测入口
# ============================================================

def run_backtest(strategy_id: str, params: dict | None = None) -> dict[str, Any]:
    """按策略类型分发回测/组合计算，返回可直接展示的结果。"""
    strategy = _library_by_id(strategy_id)
    if strategy is None:
        raise ValueError(f"未知策略: {strategy_id}")
    base = {
        "strategy_id": strategy_id,
        "strategy_name": strategy["name"],
        "category": strategy["category"],
        "source": strategy["source"],
        "source_note": strategy["source_note"],
        "params": params or {},
    }
    if strategy["kind"] == "cb_snapshot":
        return {**base, "backtest": cb_double_low_portfolio(params)}
    return {**base, "backtest": backtest_rotation(strategy, params)}


# ============================================================
# 单标的策略绩效（复用信号实验室的策略引擎）
# ============================================================

def backtest_symbol_signal(symbol: str, strategy_id: str, params: dict | None = None) -> dict[str, Any]:
    """对单标的 × 策略（signal_service 的 6 个技术策略）模拟信号执行绩效。

    规则：信号日按收盘价全仓买入/卖出，对比买入持有。
    """
    from services.signal_service import generate_signal, get_catalog

    names = {s["id"]: s["name"] for s in get_catalog()}
    sig = generate_signal(symbol, strategy_id, params)
    if sig.get("error"):
        return {"error": sig["error"]}

    dates = sig["series"]["date"]
    closes = sig["series"]["close"]
    points = sig["signal_points"]
    # 信号日索引
    sig_map = {p["date"]: p["type"] for p in points}

    nav = 1.0
    navs = [1.0]
    curve_dates = [dates[0]]
    position = False
    entry = None
    trades = 0
    win_trades = 0
    for i in range(1, len(dates)):
        t = sig_map.get(dates[i])
        if t == "buy" and not position:
            position, entry = True, closes[i]
            nav *= 1  # 全仓买入，按收盘价
            trades += 1
        elif t == "sell" and position:
            position = False
            trades += 1
            if entry and closes[i] > entry:
                win_trades += 1
        if position:
            nav *= (1 + (closes[i] / closes[i - 1] - 1))
        navs.append(round(nav, 6))
        curve_dates.append(dates[i])

    perf = _perf_stats(navs, curve_dates)
    # 买入持有基准
    bh = [closes[0] and (c / closes[0]) for c in closes]
    bh_perf = _perf_stats(bh, dates)
    closed = sum(1 for p in points if p["type"] == "sell")

    return {
        "symbol": symbol,
        "name": sig.get("name"),
        "strategy_id": strategy_id,
        "strategy_name": names.get(strategy_id, strategy_id),
        "params": params or {},
        **perf,
        "trades": trades,
        "signal_count": sig["signal_count"],
        "round_trip_win_rate_pct": round(win_trades / closed * 100, 1) if closed else None,
        "current_position": sig.get("current_position"),
        "benchmark": {"name": "买入持有", **bh_perf},
        "excess_pct": round(perf["cum_return_pct"] - bh_perf["cum_return_pct"], 2),
        "curve": {
            "date": curve_dates,
            "strategy_nav": navs,
            "benchmark_nav": [round(v, 6) for v in bh],
        },
        "note": f"基于近 {sig['kline_count']} 根真实日K线（{sig['kline_start']} ~ {sig['kline_end']}），信号日收盘价成交。",
    }


# ============================================================
# 跟踪订阅 + 每日绩效快照
# ============================================================

def _ensure_tables() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_library_subscriptions (
            id VARCHAR PRIMARY KEY,
            fk_users UUID,
            library_id VARCHAR,
            params_json VARCHAR,
            created_at VARCHAR,
            updated_at VARCHAR
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_library_snapshots (
            id VARCHAR PRIMARY KEY,
            fk_users UUID,
            library_id VARCHAR,
            snap_date VARCHAR,
            payload_json VARCHAR
        )
        """
    )


def get_tracked(user_id: str) -> list[dict[str, Any]]:
    _ensure_tables()
    db = get_db()
    rows = db.fetchall(
        "SELECT id, library_id, params_json, created_at FROM biz_library_subscriptions "
        "WHERE fk_users = ? ORDER BY created_at DESC",
        [user_id],
    )
    out = []
    for r in rows:
        try:
            params = json.loads(r[2]) if r[2] else {}
        except Exception:
            params = {}
        lib = _library_by_id(r[1])
        out.append({
            "id": r[0],
            "library_id": r[1],
            "strategy_name": lib["name"] if lib else r[1],
            "category": lib["category"] if lib else "",
            "source": lib["source"] if lib else "",
            "params": params,
            "created_at": r[3],
        })
    return out


def add_tracked(user_id: str, library_id: str, params: dict | None) -> dict[str, Any]:
    _ensure_tables()
    lib = _library_by_id(library_id)
    if lib is None:
        raise ValueError(f"未知策略: {library_id}")
    now = datetime.now(timezone.utc).isoformat()
    rec_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        "INSERT INTO biz_library_subscriptions (id, fk_users, library_id, params_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [rec_id, user_id, library_id, json.dumps(params or {}, ensure_ascii=False), now, now],
    )
    return {"id": rec_id, "library_id": library_id, "strategy_name": lib["name"], "params": params or {}}


def remove_tracked(user_id: str, rec_id: str) -> bool:
    _ensure_tables()
    db = get_db()
    db.execute(
        "DELETE FROM biz_library_subscriptions WHERE id = ? AND fk_users = ?",
        [rec_id, user_id],
    )
    db.execute(
        "DELETE FROM biz_library_snapshots WHERE id = ? AND fk_users = ?",
        [rec_id, user_id],
    )
    return True


def _save_snapshot(user_id: str, rec_id: str, library_id: str, payload: dict) -> None:
    """保存当日绩效快照（同日覆盖），供长期走势跟踪。"""
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    db.execute(
        "INSERT OR REPLACE INTO biz_library_snapshots (id, fk_users, library_id, snap_date, payload_json) "
        "VALUES (?, ?, ?, ?, ?)",
        [rec_id, user_id, library_id, today,
         json.dumps(payload, ensure_ascii=False)],
    )


def _load_snapshot_history(user_id: str, rec_id: str, limit: int = 30) -> list[dict]:
    db = get_db()
    rows = db.fetchall(
        "SELECT snap_date, payload_json FROM biz_library_snapshots "
        "WHERE id = ? AND fk_users = ? ORDER BY snap_date DESC LIMIT ?",
        [rec_id, user_id, limit],
    )
    out = []
    for r in rows:
        try:
            p = json.loads(r[1])
        except Exception:
            p = {}
        out.append({"date": r[0], **p})
    out.reverse()
    return out


def refresh_tracked(user_id: str) -> list[dict[str, Any]]:
    """重算所有跟踪策略的最新表现并落当日快照（策略绩效监控核心）。"""
    tracked = get_tracked(user_id)
    result = []
    for t in tracked:
        try:
            bt = run_backtest(t["library_id"], t.get("params", {}))
            back = bt.get("backtest", {})
            err = back.get("error")
            entry = {
                "id": t["id"],
                "library_id": t["library_id"],
                "strategy_name": t["strategy_name"],
                "category": t["category"],
                "source": t["source"],
                "params": t.get("params", {}),
                "error": err,
            }
            if not err:
                if back.get("kind") == "cb_snapshot":
                    entry["perf"] = {
                        "kind": "cb_snapshot",
                        "universe_count": back.get("universe_count"),
                        "avg_double_low": back.get("avg_double_low"),
                        "avg_price": back.get("avg_price"),
                        "avg_premium_pct": back.get("avg_premium_pct"),
                    }
                    entry["portfolio"] = back.get("portfolio", [])
                    snapshot_payload = {"avg_double_low": back.get("avg_double_low"),
                                        "universe_count": back.get("universe_count")}
                else:
                    entry["perf"] = {
                        "kind": "index_rotation",
                        "cum_return_pct": back.get("cum_return_pct"),
                        "annual_return_pct": back.get("annual_return_pct"),
                        "max_drawdown_pct": back.get("max_drawdown_pct"),
                        "sharpe": back.get("sharpe"),
                        "win_rate_pct": back.get("win_rate_pct"),
                        "trades": back.get("trades"),
                        "excess_pct": back.get("excess_pct"),
                        "end_date": back.get("end_date"),
                    }
                    entry["current_holding"] = back.get("current_holding")
                    entry["curve"] = back.get("curve")
                    snapshot_payload = {
                        "cum_return_pct": back.get("cum_return_pct"),
                        "excess_pct": back.get("excess_pct"),
                        "max_drawdown_pct": back.get("max_drawdown_pct"),
                    }
                try:
                    _save_snapshot(user_id, t["id"], t["library_id"], snapshot_payload)
                except Exception:
                    pass
                entry["history"] = _load_snapshot_history(user_id, t["id"])
        except Exception as e:  # 单条失败不影响其余
            entry = {**t, "error": str(e)}
        result.append(entry)
    return result
