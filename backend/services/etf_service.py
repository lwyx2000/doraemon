"""ETF service — ETF fund data with arbitrage analysis and opportunities (real data).

真实数据来源：53 的 /api/processed_data?category=fund_rank&subtype=etf
（akshare mairui 基金排行），覆盖 代码/名称/最新价(实时价)/净值/溢价率/涨跌幅/净值日期。

说明：
- 此前依赖的 akshare `fund_etf_spot_em` 在 53 上长期 500（东财场内ETF实时接口被掐），
  导致整页 No Data。改用 fund_rank（53 可用且含真实 净值/溢价率），与 LOF 页同源。
- 套利毛收益 net_arbitrage_yield 取溢价率（折价为负即反向套利空间），此前硬编码 0 导致
  套利机会页永远被过滤为空。
- 成交额：fund_rank 无此列 → volume 恒为 0（上游缺字段，属 C 类，非代码问题）。
"""

from __future__ import annotations

from typing import Any

from services.fund_service import _classify, _processed_data_request, _pick, _safe_float, _safe_int
from utils.arbitrage import FEASIBILITY_ORDER, analyze_arbitrage


def _map_etf(item: dict[str, Any]) -> dict[str, Any] | None:
    name = str(_pick(item, "名称", "基金名称", default=""))
    code = str(_pick(item, "代码", "基金代码", default=""))
    if not code:
        return None
    nav = _safe_float(_pick(item, "净值"))
    premium_pct = _safe_float(_pick(item, "溢价率"))  # 正数=溢价（与 LOF/套利口径一致）
    price = _safe_float(_pick(item, "最新价", "实时价"))
    change_pct = _safe_float(_pick(item, "涨跌幅"))
    # IOPV 对 ETF≈NAV
    iopv = nav if nav else 0.0
    category, sub = _classify(name, code)
    # 麦蕊 申购状态(sgzt) → subscribe_limit；成交额(元)/成交量(手) 仅新浪兜底源提供，缺失 → None
    subscribe_limit = _pick(item, "申购状态", "sgzt")
    is_suspended = bool(subscribe_limit) and any(k in str(subscribe_limit) for k in ("暂停", "停止"))
    vol_raw = _pick(item, "成交额", "成交量")
    volume = _safe_int(vol_raw) if vol_raw is not None else None
    # 跨境 ETF 份额 T+2 到账，境内 T+1
    holding_days = 2 if category == "cross_border" else 1
    return {
        "name": name,
        "code": code,
        "category": category,
        "sub_category": sub,
        "price": price,
        "iopv": iopv,
        "premium_pct": premium_pct,
        "volume": volume,
        "premium_percentile": None,  # 历史溢价率序列需 premium_history 逐只取，无源 → None
        # 折溢价套利毛收益 = 溢价率（折价为负即反向套利空间）
        "net_arbitrage_yield": premium_pct,
        "change_pct": change_pct,
        "subscribe_limit": subscribe_limit,
        "is_suspended": is_suspended,
        "holding_days": holding_days,
    }


def _fetch_etf_raw() -> list[dict] | None:
    """拉取 ETF 原始数据：53 fund_rank(etf)（fund_etf_spot_em 在 53 上长期 500，弃用）。"""
    raw = _processed_data_request("fund_rank", {"subtype": "etf"}, retries=2)
    if raw and isinstance(raw, list) and raw:
        return raw
    print("[ETF Service] fund_rank(etf) 取数失败，返回空列表")
    return None


def get_etfs(
    category: str | None = None,
    strategy: str | None = None,
    min_premium: float | None = None,
    feasibility: str | None = None,
) -> list[dict]:
    """Return real ETFs with attached arbitrage analysis."""
    raw = _fetch_etf_raw()
    if not raw:
        return []

    result: list[dict] = []
    for item in raw:
        etf = _map_etf(item)
        if not etf:
            continue
        if category and etf.get("category") != category:
            continue
        if min_premium is not None and etf.get("premium_pct", 0) < min_premium:
            continue
        analysis = analyze_arbitrage(etf)
        if feasibility and analysis["feasibility"] != feasibility:
            continue
        item = {**etf, "arbitrage_analysis": analysis}
        result.append(item)

    return result


def get_etf_arbitrage_opportunities() -> list[dict]:
    """Return ETF arbitrage opportunities (net_arbitrage_yield > 0)."""
    raw = _fetch_etf_raw()
    if not raw:
        return []

    result: list[dict] = []
    for item in raw:
        etf = _map_etf(item)
        if not etf:
            continue
        if etf.get("net_arbitrage_yield", 0) <= 0:
            continue
        analysis = analyze_arbitrage(etf)
        item = {**etf, "arbitrage_analysis": analysis}
        result.append(item)

    result.sort(
        key=lambda x: (
            FEASIBILITY_ORDER.get(x["arbitrage_analysis"]["feasibility"], 99),
            -x["arbitrage_analysis"]["net_yield_after_costs"],
        )
    )
    return result
