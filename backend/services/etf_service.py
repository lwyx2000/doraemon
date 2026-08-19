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

from services.fund_service import _processed_data_request, _pick, _safe_float
from utils.arbitrage import FEASIBILITY_ORDER, analyze_arbitrage


def _classify(name: str, code: str) -> tuple[str, str]:
    """基于名称/代码轻量分类（非虚构数据）。"""
    n = name
    if any(k in n for k in ("纳指", "标普", "道琼斯", "德国", "法国", "日经", "恒生", "港股", "美国", "海外", "中概", "原油", "黄金", "德国", "法国")):
        return "cross_border", "跨境"
    if any(k in n for k in ("沪深300", "中证500", "中证1000", "上证50", "创业板", "科创50", "科创", "中证A500", "深证", "上证")):
        return "broad", "宽基"
    return "industry", "行业"


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
    return {
        "name": name,
        "code": code,
        "category": category,
        "sub_category": sub,
        "price": price,
        "iopv": iopv,
        "premium_pct": premium_pct,
        "volume": 0,  # fund_rank 无成交额列（上游缺字段，属 C 类）
        "premium_percentile": 50,
        # 折溢价套利毛收益 = 溢价率（折价为负即反向套利空间）
        "net_arbitrage_yield": premium_pct,
        "change_pct": change_pct,
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
