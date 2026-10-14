"""贪婪恐惧指数（Fear & Greed Index）——A 股情绪温度计。

配方（用户 2026-10-12 确认）——6 个可量化情绪指标，各自 min-max 归一化到 0-100 后加权合成：

    1. 上涨家数占比 = 上涨 ÷ (上涨+下跌+平盘)              权重 0.25  正向
    2. 涨停家数（剔 ST/新股）                              权重 0.20  正向
    3. 创新高/新低比 → 指数距 52 周高点（收盘 ÷ 250 日最高收盘） 权重 0.15  正向
    4. 量能比 = 当日成交额 ÷ 20 日均成交额                  权重 0.20  正向
    5. 北向资金 → 融资余额 20 日变化率（北向 2024.8 起停止披露） 权重 0.10  正向
    6. 波动率 = 上证指数 20 日年化历史波动率                权重 0.10  反向（100 − 得分）

计分规则：
    - 每个指标对「过去一年（250 个交易日）」窗口做 min-max：得分 = (值−最小) ÷ (最大−最小) × 100
    - 反向指标（波动率）取 100 − 得分
    - 缺失分项按权重归一化：恐贪值 = Σ(wᵢ·sᵢ) ÷ Σ(wᵢ)（只累加有值的分项）
    - 档位：<10 极度恐慌，>90 极度贪婪，其余均衡

数据源与口径（全部 53 实机验证过）：
    - 上涨占比 / 涨停（剔ST口径）：market_stats + 乐咕 stock_market_activity_legu，
      均为**当日快照**，无历史序列 → 从接入日起攒，回填日为 NULL（按权重归一化近似）
    - 指数位置 / 量能比 / 波动率：新浪 stock_zh_index_daily 上证 sh000001 日线
      （1990 年至今全量，本模块只取最近 600 根）；腾讯 stock_zh_index_daily_tx 兜底。
      csindex 中证官网源 2026-10-12 实测网关 500（疑上游反爬），已弃用
    - 涨停回填：东财 stock_zt_pool_em 历史涨停池（按名称剔 ST 后计数）
    - 融资余额：stock_margin_sse 沪市历史（**必须带 start_date/end_date**，不带则网关
      只返回止于约 2023 的陈旧窗口），20 日变化率；深市 szse 仅最新一日无历史，不采用

已知近似（页面上有注明）：
    - 回填日缺「上涨占比」，按权重归一化近似；components_used < 6 即近似日
    - 涨停实盘走乐咕「真实涨停」（剔 ST 权威口径），回填走东财池+名称剔 ST，口径略有差
    - 量能/波动率用上证指数（覆盖沪市全部股票）而非沪深两市，比例口径不受影响
    - 上涨占比积累 <60 天时用先验极值 [0.20, 0.85] 兜底，之后改用实测窗口极值
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

_CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------- 常量
WINDOW_DAYS = 250            # min-max 窗口：过去一年（交易日）
VOL_DAYS = 20                # 波动率 / 量能均线的回看天数
MARGIN_CHG_DAYS = 20         # 融资余额变化率回看天数
POSITION_DAYS = 250          # 52 周高点的回看天数（约一年）

# 上涨占比积累期兜底极值（经验区间，攒够观测后切换为实测）
ADVANCE_FALLBACK_MIN = 0.20
ADVANCE_FALLBACK_MAX = 0.85
ADVANCE_MIN_OBS = 60

WEIGHTS = {
    "advance": 0.25,   # 上涨家数占比
    "limit_up": 0.20,  # 涨停家数（剔 ST）
    "position": 0.15,  # 指数距 52 周高点
    "turnover": 0.20,  # 量能比
    "margin": 0.10,    # 融资余额 20 日变化率
    "vol": 0.10,       # 20 日年化波动率（反向）
}
REVERSE_METRICS = {"vol"}   # 越高越恐慌 → 100 − 得分

_TABLE_READY = False
_UPSERT_SQL = """
INSERT INTO base_fear_greed_daily (
    trade_date, advance_ratio, limit_up_count, index_position,
    turnover_ratio, margin_chg20, vol20, source, captured_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (trade_date) DO UPDATE SET
    advance_ratio  = excluded.advance_ratio,
    limit_up_count = excluded.limit_up_count,
    index_position = excluded.index_position,
    turnover_ratio = excluded.turnover_ratio,
    margin_chg20   = excluded.margin_chg20,
    vol20          = excluded.vol20,
    source         = excluded.source,
    captured_at    = excluded.captured_at
"""

# 合并策略（_upsert_raw）：
#   - 「实盘血统」列（上涨占比/涨停/两融）：live 值优先，backfill 只补 NULL，同源新值覆盖旧值
#   - K 线列（位置/量能/波动）：同一数据源，直接覆盖
#   - source 标注：行被 live 采过就保持 live
_LIVE_PRIORITY_COLS = ("advance_ratio", "limit_up_count", "margin_chg20")

_SCORE_UPDATE_SQL = """
UPDATE base_fear_greed_daily SET
    score_advance = ?, score_limit_up = ?, score_position = ?,
    score_turnover = ?, score_margin = ?, score_vol = ?,
    total_score = ?, components_used = ?
WHERE trade_date = ?
"""


# ---------------------------------------------------------------- 表结构
def _ensure_table() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS base_fear_greed_daily (
                trade_date      DATE PRIMARY KEY,
                advance_ratio   DOUBLE,
                limit_up_count  INTEGER,
                index_position  DOUBLE,
                turnover_ratio  DOUBLE,
                margin_chg20    DOUBLE,
                vol20           DOUBLE,
                score_advance   DOUBLE,
                score_limit_up  DOUBLE,
                score_position  DOUBLE,
                score_turnover   DOUBLE,
                score_margin    DOUBLE,
                score_vol       DOUBLE,
                total_score     DOUBLE,
                components_used INTEGER,
                source          VARCHAR,
                captured_at     TIMESTAMP
            )
            """
        )
        _TABLE_READY = True
    except Exception as e:
        print(f"[FearGreed] 建表失败: {type(e).__name__}: {e}")


def _now_str() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 取数
def _fetch_market_stats() -> Optional[dict]:
    """market_stats 加工接口：涨跌家数 + 沪深成交额（当日快照）。"""
    from services.market_service import _processed_data_request

    data = _processed_data_request("market_stats", {"subtype": "overview"}, retries=2, timeout=10)
    return data if isinstance(data, dict) else None


def _fetch_legu_activity() -> Optional[dict]:
    """乐咕市场活跃度：含「真实涨停」（剔 ST 权威口径）当日快照。"""
    from services.market_service import _akshare_request

    rows = _akshare_request("stock_market_activity_legu", retries=2, timeout=10)
    if not rows or not isinstance(rows, list):
        return None
    out: dict[str, Any] = {}
    for r in rows:
        item = r.get("item")
        if item:
            out[str(item)] = r.get("value")
    return out or None


def _fetch_zt_pool_count(trade_date: Optional[str] = None) -> Optional[int]:
    """东财涨停池计数（剔 ST）。

    trade_date=None 取当日；否则取历史日期 'YYYY-MM-DD'。池为空/接口挂返回 None。
    """
    from services.market_service import _akshare_request

    params: dict[str, Any] = {}
    if trade_date:
        params["date"] = trade_date.replace("-", "")
    rows = _akshare_request("stock_zt_pool_em", params, retries=2, timeout=12)
    if rows is None or not isinstance(rows, list) or not rows:
        return None
    n = 0
    for r in rows:
        name = str(r.get("名称") or r.get("name") or "").upper()
        if "ST" in name:  # ST / *ST / S*ST 全剔除
            continue
        n += 1
    return n


def _fetch_sh_kline(days: int = 600) -> list[dict]:
    """上证指数 000001 日线，按日期升序，返回最近 days 根。

    主源：新浪 stock_zh_index_daily（symbol=sh000001，秒回，字段 date/open/high/low/close/volume）；
    兜底：腾讯 stock_zh_index_daily_tx（同 symbol，慢约 20s，字段含 amount 成交额）。
    注：csindex 中证官网源 2026-10-12 实测两种调法均网关 500（疑上游反爬），已弃用。
    量能比用「量」的比值（成交量或成交额），单位在比值中抵消，口径等价。
    """
    from services.market_service import _akshare_request

    rows = _akshare_request("stock_zh_index_daily", {"symbol": "sh000001"}, retries=2, timeout=20)
    if not rows or not isinstance(rows, list):
        rows = _akshare_request("stock_zh_index_daily_tx", {"symbol": "sh000001"}, retries=1, timeout=40)
    if not rows or not isinstance(rows, list):
        return []

    bars: list[dict] = []
    for row in rows:
        d = row.get("date") or row.get("日期")
        c = row.get("close") or row.get("收盘")
        if not d or c is None:
            continue
        amount = row.get("volume")
        if amount is None:
            amount = row.get("amount")
        if amount is None:
            amount = row.get("成交量")
        if amount is None:
            amount = row.get("成交额")
        try:
            bars.append({
                "date": str(d)[:10],
                "close": float(c),
                "amount": float(amount or 0.0),
            })
        except (ValueError, TypeError):
            continue
    bars.sort(key=lambda b: b["date"])
    return bars[-days:] if len(bars) > days else bars


def _fetch_margin_series(lookback_days: int = 500) -> list[dict]:
    """沪市融资融券历史（sse，单位元），按日期升序，只保留融资余额。

    ⚠️ 必须显式传 start_date/end_date（YYYYMMDD）：不带日期参数时网关只返回
    2000 行且止于约 2023 年的陈旧默认窗口（2026-10-12 实测），会把 2023 的
    陈旧值当「当日」用。带日期参数返回近端数据（实测 2024-01 起 668 行）。
    深市 stock_margin_szse 只有最新一日、无历史，无法算 20 日变化，故不采用。
    """
    from services.market_service import _akshare_request

    today = datetime.now(_CST)
    start = (today - timedelta(days=lookback_days)).strftime("%Y%m%d")
    rows = _akshare_request(
        "stock_margin_sse",
        {"start_date": start, "end_date": today.strftime("%Y%m%d")},
        retries=2,
        timeout=20,
    )
    if not rows or not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows:
        d = row.get("信用交易日期") or row.get("date")
        bal = row.get("融资余额")
        if bal is None:
            bal = row.get("融资余额(元)")
        if not d or bal is None:
            continue
        s = str(d)[:10]
        if len(s) == 8 and s.isdigit():  # YYYYMMDD -> YYYY-MM-DD
            s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
        try:
            out.append({"date": s, "financing": float(bal)})
        except (ValueError, TypeError):
            continue
    out.sort(key=lambda r: r["date"])
    return out


# ---------------------------------------------------------------- 指标计算
def _metrics_from_kline(bars: list[dict], idx: int) -> dict:
    """由 K 线序列计算截至 bars[idx] 的三个指标：52 周高点位置 / 量能比 / 20 日波动率。"""
    bar = bars[idx]
    out: dict[str, Optional[float]] = {"index_position": None, "turnover_ratio": None, "vol20": None}

    # 指数距 52 周高点：过去 250 个交易日（含当日）最高收盘
    win = bars[max(0, idx - POSITION_DAYS + 1): idx + 1]
    hi = max((b["close"] for b in win), default=0.0)
    if hi > 0:
        out["index_position"] = round(bar["close"] / hi * 100, 4)

    # 量能比：当日量 ÷ 过去 20 日均量（含当日；新浪源为成交量、腾讯源为成交额，比值等价）
    amounts = [b["amount"] for b in bars[max(0, idx - VOL_DAYS + 1): idx + 1]]
    avg = sum(amounts) / len(amounts) if amounts else 0.0
    if avg > 0:
        out["turnover_ratio"] = round(bar["amount"] / avg, 4)

    # 20 日年化历史波动率：20 个日收益率样本标准差 × √252
    closes = [b["close"] for b in bars[max(0, idx - VOL_DAYS): idx + 1]]
    rets = [
        closes[i] / closes[i - 1] - 1
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    if len(rets) >= 10:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        out["vol20"] = round(math.sqrt(var) * math.sqrt(252) * 100, 4)
    return out


def _margin_chg_at(series: list[dict], idx: int) -> Optional[float]:
    """融资余额 20 日变化率（%）：series[idx] 相对 idx-20 的余额。"""
    if idx < MARGIN_CHG_DAYS or idx >= len(series):
        return None
    prev = series[idx - MARGIN_CHG_DAYS]["financing"]
    cur = series[idx]["financing"]
    if prev <= 0:
        return None
    return round((cur / prev - 1) * 100, 4)


def _find_index(series: list[dict], trade_date: str) -> Optional[int]:
    """序列中与 trade_date 精确匹配的下标；无则返回 None（调用方可选最近一日）。"""
    for i, r in enumerate(series):
        if r["date"] == trade_date:
            return i
    return None


def _latest_index_on_or_before(series: list[dict], trade_date: str) -> Optional[int]:
    """序列中 <= trade_date 的最后一个下标。"""
    idx = None
    for i, r in enumerate(series):
        if r["date"] <= trade_date:
            idx = i
        else:
            break
    return idx


# ---------------------------------------------------------------- 计分
def _minmax(value: Optional[float], lo: Optional[float], hi: Optional[float]) -> Optional[float]:
    if value is None or lo is None or hi is None:
        return None
    if hi <= lo:
        return 50.0
    s = (value - lo) / (hi - lo) * 100.0
    return round(max(0.0, min(100.0, s)), 2)


def _label(score: float) -> str:
    if score < 10:
        return "极度恐慌"
    if score > 90:
        return "极度贪婪"
    return "均衡"


# 原始指标在查询行元组中的列下标（见 _SELECT_SQL / _recompute_scores 的 SELECT）
_COL_IDX = {"advance": 1, "limit_up": 2, "position": 3, "turnover": 4, "margin": 5, "vol": 6}


def _recompute_scores() -> int:
    """对全表按「过去一年窗口」重算 6 分项得分与恐贪总值（幂等）。

    每个指标独立取「截至当日、往前 250 行」的实测 min/max；
    上涨占比观测不足 ADVANCE_MIN_OBS 行时用先验极值兜底。
    """
    _ensure_table()
    from database.connection import get_db

    db = get_db()
    rows = db.fetchall(
        "SELECT trade_date, advance_ratio, limit_up_count, index_position, "
        "turnover_ratio, margin_chg20, vol20 FROM base_fear_greed_daily ORDER BY trade_date"
    )
    if not rows:
        return 0

    updates: list[list] = []
    for i, r in enumerate(rows):
        trade_date = str(r[0])
        win_rows = rows[max(0, i - WINDOW_DAYS + 1): i + 1]
        scores: dict[str, Optional[float]] = {}
        for metric in WEIGHTS:
            val = _to_float(r[_COL_IDX[metric]])
            if val is None:
                scores[metric] = None
                continue
            win_vals = [
                v for v in (_to_float(rr[_COL_IDX[metric]]) for rr in win_rows)
                if v is not None
            ]
            if metric == "advance" and len(win_vals) < ADVANCE_MIN_OBS:
                # 积累期：实测样本太少，用先验经验区间兜底
                lo, hi = ADVANCE_FALLBACK_MIN, ADVANCE_FALLBACK_MAX
            elif win_vals:
                lo, hi = min(win_vals), max(win_vals)
            else:
                scores[metric] = None
                continue
            s = _minmax(val, lo, hi)
            if s is not None and metric in REVERSE_METRICS:
                s = round(100.0 - s, 2)
            scores[metric] = s

        num = 0.0
        den = 0.0
        for metric, s in scores.items():
            if s is not None:
                num += WEIGHTS[metric] * s
                den += WEIGHTS[metric]
        total = round(num / den, 2) if den > 0 else None
        used = sum(1 for s in scores.values() if s is not None)
        updates.append([
            scores["advance"], scores["limit_up"], scores["position"],
            scores["turnover"], scores["margin"], scores["vol"],
            total, used, trade_date,
        ])

    db.executemany(_SCORE_UPDATE_SQL, updates)
    return len(updates)


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- 落库
def _upsert_raw(trade_date: str, metrics: dict, source: str) -> None:
    """落库当日原始指标（来源感知合并，见 _LIVE_PRIORITY_COLS 注释）。"""
    _ensure_table()
    from database.connection import get_db

    db = get_db()
    final: dict[str, Any] = {
        "advance_ratio": metrics.get("advance_ratio"),
        "limit_up_count": metrics.get("limit_up_count"),
        "index_position": metrics.get("index_position"),
        "turnover_ratio": metrics.get("turnover_ratio"),
        "margin_chg20": metrics.get("margin_chg20"),
        "vol20": metrics.get("vol20"),
    }
    src = source
    row = db.fetchone(
        "SELECT advance_ratio, limit_up_count, index_position, turnover_ratio, "
        "margin_chg20, vol20, source FROM base_fear_greed_daily WHERE trade_date = ?",
        [trade_date],
    )
    if row is not None:
        exist = {
            "advance_ratio": _to_float(row[0]),
            "limit_up_count": int(row[1]) if row[1] is not None else None,
            "index_position": _to_float(row[2]),
            "turnover_ratio": _to_float(row[3]),
            "margin_chg20": _to_float(row[4]),
            "vol20": _to_float(row[5]),
        }
        exist_src = str(row[6] or "")
        for col in _LIVE_PRIORITY_COLS:
            inc, cur = final[col], exist[col]
            if inc is None:
                final[col] = cur                      # 新值缺失 → 保留旧值
            elif cur is None:
                pass                                  # 旧值缺失 → 新值胜出
            elif source == "live" and exist_src != "live":
                pass                                  # 实盘值覆盖回填值
            elif source == "backfill" and exist_src == "live":
                final[col] = cur                      # 实盘值不被回填覆盖
            # else：同源 → 新值覆盖旧值
        if exist_src == "live":
            src = "live"                              # 行有实盘血统就保持 live 标注
    db.execute(
        _UPSERT_SQL,
        [
            trade_date,
            _to_float(final["advance_ratio"]),
            int(final["limit_up_count"]) if final["limit_up_count"] is not None else None,
            _to_float(final["index_position"]),
            _to_float(final["turnover_ratio"]),
            _to_float(final["margin_chg20"]),
            _to_float(final["vol20"]),
            src,
            _now_str(),
        ],
    )


# ---------------------------------------------------------------- 对外主流程
def collect_today() -> dict:
    """采集当日原始指标并重算得分（收盘后调用；定时任务 15:40 触发）。"""
    from services.trading_calendar import is_trading_day

    today = date.today()
    if not is_trading_day(today):
        return {"ok": False, "skipped": True, "message": f"非交易日（{today}），跳过采集"}

    trade_date = today.strftime("%Y-%m-%d")
    metrics: dict[str, Any] = {}
    warnings: list[str] = []

    # 1) 上涨占比（market_stats）
    stats = _fetch_market_stats()
    advance_ratio = None
    if stats:
        adv = _to_float(stats.get("advance_count")) or 0.0
        dec = _to_float(stats.get("decline_count")) or 0.0
        flat = _to_float(stats.get("flat_count")) or 0.0
        total = adv + dec + flat
        if total > 0:
            advance_ratio = round(adv / total, 6)
    else:
        warnings.append("market_stats 获取失败")
    metrics["advance_ratio"] = advance_ratio

    # 2) 涨停家数（乐咕「真实涨停」= 剔 ST 口径；失败退东财当日池）
    limit_up = None
    legu = _fetch_legu_activity()
    if legu:
        v = _to_float(legu.get("真实涨停"))
        if v is not None:
            limit_up = int(v)
    if limit_up is None:
        limit_up = _fetch_zt_pool_count()
        if limit_up is None:
            warnings.append("涨停数获取失败（乐咕+东财池均不可用）")
    metrics["limit_up_count"] = limit_up

    # 3-6) 指数位置 / 量能比 / 波动率（K 线）；融资余额变化（sse）
    bars = _fetch_sh_kline()
    if bars:
        idx = _find_index(bars, trade_date)
        if idx is None:
            idx = len(bars) - 1
            if bars[idx]["date"] != trade_date:
                warnings.append(f"K 线最新日期为 {bars[idx]['date']}，非当日（上游滞后）")
        metrics.update(_metrics_from_kline(bars, idx))
    else:
        warnings.append("上证 K 线获取失败")

    margin = _fetch_margin_series()
    if margin:
        idx = _find_index(margin, trade_date)
        if idx is None:
            idx = _latest_index_on_or_before(margin, trade_date)
        if idx is not None:
            matched = date.fromisoformat(margin[idx]["date"])
            lag = (today - matched).days
            if lag > 5:
                # 上游停更/严重滞后：宁缺勿假，不用陈旧值冒充当日
                warnings.append(
                    f"两融最新日期为 {margin[idx]['date']}（滞后 {lag} 天），本日不计入该分项"
                )
            else:
                if matched != today:
                    warnings.append(f"两融最新日期为 {margin[idx]['date']}，非当日（小幅滞后）")
                chg = _margin_chg_at(margin, idx)
                if chg is None:
                    warnings.append("两融历史不足 20 日，无法计算融资余额变化率")
                metrics["margin_chg20"] = chg
        else:
            warnings.append("两融序列无当日及之前数据")
    else:
        warnings.append("两融数据获取失败")

    _upsert_raw(trade_date, metrics, source="live")
    _recompute_scores()

    latest = get_latest()
    return {
        "ok": True,
        "skipped": False,
        "date": trade_date,
        "metrics": metrics,
        "totalScore": (latest or {}).get("totalScore"),
        "label": (latest or {}).get("label"),
        "warnings": warnings,
    }


def backfill(days: int = 120, progress_cb=None) -> dict:
    """回填最近 N 个交易日的历史原始指标（可重复执行，不清空已有 live 值）。

    - 指数位置/量能比/波动率：K 线直接算（250+ 日可用）
    - 融资余额变化：sse 全量历史
    - 涨停：东财历史池逐日拉取（仅近数月，空/失败记 NULL）
    - 上涨占比：无免费历史源，记 NULL（该日按权重归一化近似）
    """
    from services.trading_calendar import is_trading_day

    _ensure_table()
    days = max(5, min(int(days), 400))

    bars = _fetch_sh_kline(days=days + POSITION_DAYS + 10)
    if not bars:
        return {"ok": False, "message": "上证 K 线获取失败，无法回填"}

    margin = _fetch_margin_series()
    if not margin:
        return {"ok": False, "message": "两融数据获取失败，无法回填"}

    target_dates = [b["date"] for b in bars][-days:]
    done = 0
    filled_zt = 0
    warnings: list[str] = []
    for d in target_dates:
        if not is_trading_day(date.fromisoformat(d)):
            continue
        metrics: dict[str, Any] = {}
        bidx = _find_index(bars, d)
        if bidx is None:
            continue
        metrics.update(_metrics_from_kline(bars, bidx))
        midx = _find_index(margin, d)
        if midx is not None:
            metrics["margin_chg20"] = _margin_chg_at(margin, midx)

        zt = _fetch_zt_pool_count(d)
        if zt is not None:
            metrics["limit_up_count"] = zt
            filled_zt += 1
        else:
            warnings.append(f"{d} 涨停池为空/不可用（该日按剩余权重归一化）")
        time.sleep(0.3)  # 东财池限流，温和一点

        _upsert_raw(d, metrics, source="backfill")
        done += 1
        if progress_cb:
            try:
                progress_cb(done, len(target_dates), d)
            except Exception:
                pass

    _recompute_scores()
    stats = snapshot_stats()
    return {
        "ok": True,
        "days": done,
        "ztFilled": filled_zt,
        "warnings": warnings[:10],
        "table": stats,
    }


# ---------------------------------------------------------------- 查询
def _row_to_dict(r: tuple) -> dict:
    def f(v):
        return _to_float(v)
    return {
        "date": str(r[0]),
        "rawAdvanceRatio": f(r[1]),
        "rawLimitUp": int(r[2]) if r[2] is not None else None,
        "rawPosition": f(r[3]),
        "rawTurnoverRatio": f(r[4]),
        "rawMarginChg20": f(r[5]),
        "rawVol20": f(r[6]),
        "advance": f(r[7]),
        "limitUp": f(r[8]),
        "position": f(r[9]),
        "turnover": f(r[10]),
        "margin": f(r[11]),
        "vol": f(r[12]),
        "totalScore": f(r[13]),
        "componentsUsed": int(r[14]) if r[14] is not None else 0,
        "source": r[15],
        "capturedAt": str(r[16]) if r[16] else None,
    }


_SELECT_SQL = (
    "SELECT trade_date, advance_ratio, limit_up_count, index_position, "
    "turnover_ratio, margin_chg20, vol20, score_advance, score_limit_up, "
    "score_position, score_turnover, score_margin, score_vol, total_score, "
    "components_used, source, captured_at FROM base_fear_greed_daily"
)


def get_latest() -> Optional[dict]:
    """最新一日完整指标（含分项得分与档位）。无数据返回 None。"""
    try:
        _ensure_table()
        from database.connection import get_db

        db = get_db()
        row = db.fetchone(_SELECT_SQL + " ORDER BY trade_date DESC LIMIT 1")
        if not row:
            return None
        d = _row_to_dict(row)
        if d["totalScore"] is not None:
            d["label"] = _label(d["totalScore"])
        return d
    except Exception as e:
        print(f"[FearGreed] get_latest 失败: {type(e).__name__}: {e}")
        return None


def get_history(days: int = 120) -> list[dict]:
    """最近 N 个交易日的恐贪序列（升序，供历史曲线）。"""
    try:
        _ensure_table()
        from database.connection import get_db

        db = get_db()
        rows = db.fetchall(
            _SELECT_SQL + " ORDER BY trade_date DESC LIMIT ?", [max(1, min(int(days), 500))]
        )
        out = [_row_to_dict(r) for r in rows]
        out.reverse()
        return out
    except Exception as e:
        print(f"[FearGreed] get_history 失败: {type(e).__name__}: {e}")
        return []


def snapshot_stats() -> dict:
    """落库情况：已有交易日数 / 日期范围 / 最新恐贪值。"""
    try:
        _ensure_table()
        from database.connection import get_db

        db = get_db()
        row = db.fetchone(
            "SELECT count(*), min(trade_date), max(trade_date) FROM base_fear_greed_daily"
        )
        return {
            "rows": int(row[0]) if row else 0,
            "firstDate": str(row[1]) if row and row[1] else None,
            "lastDate": str(row[2]) if row and row[2] else None,
        }
    except Exception as e:
        print(f"[FearGreed] snapshot_stats 失败: {type(e).__name__}: {e}")
        return {"rows": 0, "firstDate": None, "lastDate": None}
