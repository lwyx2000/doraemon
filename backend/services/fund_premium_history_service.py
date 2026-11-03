"""溢价率历史：让「今天溢价高不高」变成可比较的分位（2026-11-03）。

背景
----
``premium_percentile`` 在本项目里一直是 ``None`` —— ``fund_service`` 三处注释都写着
「需逐只历史溢价率序列（fund_rank premium_history），无源」。

但这个源本来就不该等别人给：溢价率 = 现价 ÷ 净值 − 1，两个输入每天都有，
缺的只是**有人每天存一行**。《无敌哥估值说明文档》3.13② 的「均线溢价」和
3.14 的「轮动交易」全部建立在「同一只基金的历史溢价序列」之上，而那套东西的
实现本质就是每日落库 —— 站点能把「当前溢价 7.59% vs 20 日均线对应 −1.57%」
摆出来，靠的不是什么数据源，是它自己攒了几年的每日读数。

所以这里只做三件事：
1. **落快照**：每日盘后（15:30，复用 est_nav 快照那个 job）把当日溢价存两份
   口径 —— 官方口径（现价 ÷ 官方净值）与自算口径（现价 ÷ est_nav）；
2. **算统计**：按历史序列算分位 + 20 日均值；
3. **透出**：挂到 ``/funds``，填掉那个一直为 ``None`` 的字段。

为什么不回填历史
----------------
官方口径的历史溢价 = 历史价格 ÷ 历史净值，两个都能拿到（``base_fund_daily_quotes``
+ 网关净值全历史），理论上可回填。但 QDII/LOF 在 2015 年前的场内流动性极差，
早期"溢价"是**噪声不是信号**，回填进来会把分位分布拉歪，让今天的 3% 溢价看起来
像"历史低位"。所以只从上线日开始攒；样本不足 ``MIN_SAMPLES`` 直接不出数
（铁律：宁可 '-' 也不造数）。

口径选择
--------
同一只基金的同一天有两份溢价读数，混着算分位没有意义。取序列时**整条只用一个口径**：
自算口径样本够就全用自算，否则退回官方口径，并在 ``premium_hist_base`` 里标明，
前端可以据此提示「这是官方口径分位」。自算口径优先的理由：它是本项目的决策口径
（对应文档 5.4「以参考 EST 为准」），且官方口径对跨境 ETF 系统性偏低 0.7~0.8 个点
（文档 5.2），跨基金横向比较会失真。
"""

from __future__ import annotations

import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

CST = timezone(timedelta(hours=8))

DDL = """
CREATE TABLE IF NOT EXISTS base_fund_premium_daily (
    date                  VARCHAR NOT NULL,
    fund_code             VARCHAR NOT NULL,
    price                 DOUBLE,
    nav_actual            DOUBLE,
    premium_official_pct  DOUBLE,
    est_nav               DOUBLE,
    premium_est_pct       DOUBLE,
    nav_date              VARCHAR,
    method                VARCHAR,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, fund_code)
)
"""

#: 算分位至少要多少个交易日样本。15 ≈ 三周：少于这个数，分位每档跨 6.7 个点，
#: 报出来的"85% 分位"其实只说明"比 13 天里的大部分高"，会误导下单。
MIN_SAMPLES = 15
#: 算 20 日均值至少要多少个样本（样本不足时不出均值，避免"两点连线"式假信号）
MIN_MA_SAMPLES = 10
#: 统计回看窗口（自然日）：约 1.5 年，够算一个像样的分位，又不会被早年噪声污染
LOOKBACK_DAYS = 550
#: 统计缓存 TTL（秒）：/funds 每个请求都读，不能每次扫全表
STATS_TTL = 300

_stats_cache: dict = {"ts": 0.0, "data": {}}
_stats_lock = threading.Lock()


def _db():
    from database.connection import get_db

    return get_db()


def _now() -> datetime:
    return datetime.now(CST)


def _today() -> str:
    return _now().strftime("%Y-%m-%d")


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _r(v, nd: int) -> float | None:
    x = _f(v)
    return round(x, nd) if x is not None else None


def ensure_table(db=None) -> None:
    try:
        (db or _db()).execute(DDL)
    except Exception as e:  # pragma: no cover
        print(f"[PremiumHistory] 建表失败: {e}")


# ============================================================
# 1. 落快照
# ============================================================

def record_snapshot(funds: Iterable[dict], run_date: str | None = None) -> dict:
    """把当日溢价读数落库（幂等，同日重跑覆盖当日行）。

    与 ``est_nav_history`` 的关键差别：那边 ``date`` 取 ``est_price_date``（估值赌的
    哪一天），这里取 **运行日** —— 溢价是「今天这个盘口价 vs 今天这个净值锚」的
    静态读数，不是对某一天的预测，回填也没有意义。

    非交易日直接跳过：15:30 的 cron 在周末/节假日照样会触发，那时 ``price`` 还是
    上一交易日的收盘价，写进去等于凭空造出一行"周末溢价"，把序列周期拉歪。
    """
    from services.trading_calendar import is_trading_day

    db = _db()
    ensure_table(db)
    run_date = (run_date or _today())[:10]
    try:
        day = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        return {"ok": False, "error": f"bad run_date: {run_date}", "written": 0}
    if not is_trading_day(day):
        print(f"[PremiumHistory] {run_date} 非交易日，跳过")
        return {"ok": True, "written": 0, "skipped": "non_trading_day"}

    rows: list[list] = []
    for f in funds:
        code = str(f.get("code") or "").strip()
        if not code:
            continue
        price = _f(f.get("price"))
        if not price or price <= 0:
            continue
        nav = _f(f.get("nav"))
        prem_off = _f(f.get("premium_pct"))
        if prem_off is None and nav and nav > 0:
            prem_off = (price / nav - 1.0) * 100.0
        est_nav = _f(f.get("est_nav"))
        prem_est = _f(f.get("est_premium_pct"))
        if prem_est is None and est_nav and est_nav > 0:
            prem_est = (price / est_nav - 1.0) * 100.0
        # 两种口径都没有，存了也没法算分位
        if prem_off is None and prem_est is None:
            continue
        rows.append([
            run_date,
            code,
            round(price, 4),
            _r(nav, 4),
            _r(prem_off, 4),
            _r(est_nav, 4),
            _r(prem_est, 4),
            str(f.get("nav_date") or "")[:10],
            str(f.get("est_method") or ""),
        ])

    if not rows:
        return {"ok": True, "written": 0}

    try:
        db.executemany(
            "INSERT INTO base_fund_premium_daily "
            "(date, fund_code, price, nav_actual, premium_official_pct, est_nav, "
            " premium_est_pct, nav_date, method) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (date, fund_code) DO UPDATE SET "
            " price = EXCLUDED.price, nav_actual = EXCLUDED.nav_actual, "
            " premium_official_pct = EXCLUDED.premium_official_pct, "
            " est_nav = EXCLUDED.est_nav, premium_est_pct = EXCLUDED.premium_est_pct, "
            " nav_date = EXCLUDED.nav_date, method = EXCLUDED.method",
            rows,
        )
    except Exception as e:
        print(f"[PremiumHistory] 落库失败: {type(e).__name__}: {e}")
        return {"ok": False, "error": str(e), "written": 0}

    with _stats_lock:
        _stats_cache["ts"] = 0.0
    print(f"[PremiumHistory] 溢价快照写入 {len(rows)} 行（{run_date}）")
    return {"ok": True, "written": len(rows)}


def catch_up_today() -> dict:
    """启动兜底：进程若在 15:30 那次没起来，收盘后补落一次当日快照。

    只在「今天是交易日 + 已过 15:35 + 当日库里几乎没有行」时触发。当日已有足量
    行说明定时任务跑过了，不再重复全市场扫描（``get_funds`` 是重接口）。
    """
    from services.trading_calendar import is_trading_day

    now = _now()
    if not is_trading_day(now.date()):
        return {"ok": True, "skipped": "non_trading_day"}
    if (now.hour, now.minute) < (15, 35):
        return {"ok": True, "skipped": "before_close_snapshot"}
    today = now.strftime("%Y-%m-%d")
    try:
        db = _db()
        ensure_table(db)
        got = db.fetchall(
            "SELECT COUNT(*) FROM base_fund_premium_daily WHERE date = ?", [today]
        )
        n = int(got[0][0]) if got else 0
    except Exception as e:
        print(f"[PremiumHistory] 补采前置检查失败: {type(e).__name__}: {e}")
        return {"ok": False, "error": str(e)}
    if n >= 100:
        return {"ok": True, "skipped": "already_recorded", "rows": n}

    from services.fund_service import get_funds

    funds, _meta = get_funds("all")
    res = record_snapshot(funds, today)
    print(f"[PremiumHistory] 启动补采: {res}")
    return res


# ============================================================
# 2. 统计
# ============================================================

def _pct_rank(series: list[float], cur: float) -> float:
    """``cur`` 在 ``series`` 中的分位（0~100，中位秩法）。

    用「小于的算 0、等于的算 0.5」而不是简单 ``<=``：溢价序列里 0.00 反复出现
    （大量平价品种），全算作"高于"会把一堆基金顶到 100% 分位。
    """
    n = len(series)
    if not n:
        return 0.0
    less = sum(1 for v in series if v < cur)
    eq = sum(1 for v in series if v == cur)
    return round(100.0 * (less + 0.5 * eq) / n, 1)


def _load_stats() -> dict[str, dict]:
    """{code: {premium_percentile, premium_ma20, premium_hist_n, premium_hist_base}}"""
    since = (_now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    try:
        rows = _db().fetchall(
            "SELECT fund_code, date, premium_official_pct, premium_est_pct "
            "FROM base_fund_premium_daily WHERE date >= ? "
            "ORDER BY fund_code, date",
            [since],
        )
    except Exception as e:
        print(f"[PremiumHistory] 统计读取失败: {type(e).__name__}: {e}")
        return {}

    by_code: dict[str, list[tuple[float | None, float | None]]] = {}
    for code, _date, off, est in rows:
        by_code.setdefault(str(code), []).append((_f(off), _f(est)))

    out: dict[str, dict] = {}
    for code, pairs in by_code.items():
        est_s = [e for _o, e in pairs if e is not None]
        off_s = [o for o, _e in pairs if o is not None]
        # 整条序列只用一个口径（混算没有意义，见模块 docstring）
        if len(est_s) >= MIN_SAMPLES:
            series, base = est_s, "est"
        elif len(off_s) >= MIN_SAMPLES:
            series, base = off_s, "official"
        else:
            continue
        cur = series[-1]
        rec: dict = {
            "premium_percentile": _pct_rank(series, cur),
            "premium_hist_n": len(series),
            "premium_hist_base": base,
        }
        if len(series) >= MIN_MA_SAMPLES:
            rec["premium_ma20"] = round(statistics.fmean(series[-20:]), 2)
        out[code] = rec
    return out


def get_premium_stats(force: bool = False) -> dict[str, dict]:
    """带 TTL 缓存的分位统计。空字典 = 还没攒够样本（上线首月很正常）。"""
    with _stats_lock:
        fresh = (time.time() - float(_stats_cache["ts"] or 0)) < STATS_TTL
        if fresh and not force:
            return _stats_cache["data"]
    data = _load_stats()
    with _stats_lock:
        _stats_cache["ts"] = time.time()
        _stats_cache["data"] = data
    return data


def attach_premium_stats(funds: Iterable[dict]) -> None:
    """给 /funds 每行填 premium_percentile / premium_ma20 / premium_hist_*。

    覆盖之前 ``fund_service`` 里硬编码的 ``None``。没有样本的基金保持 ``None``
    （前端显示 '-'）—— 不写 0，0 会被读成"历史最低溢价"，是反向信号。
    """
    try:
        stats = get_premium_stats()
    except Exception as e:
        print(f"[PremiumHistory] 挂载失败（忽略）: {type(e).__name__}: {e}")
        return
    if not stats:
        return
    funds = list(funds)
    hit = 0
    for f in funds:
        rec = stats.get(str(f.get("code") or ""))
        if not rec:
            continue
        f.update(rec)
        hit += 1
    if hit:
        print(f"[PremiumHistory] 溢价分位命中 {hit}/{len(funds)} 只")
