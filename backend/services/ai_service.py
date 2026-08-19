"""AI service — report generation and configuration.

基于真实行情数据生成 AI 报告：宏观判断取自真实 ERP（失败则如实说明数据缺失），
套利告警取自真实 ETF 数据（取数失败时为空，不使用 mock）。报告状态为内存态。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from utils.arbitrage import analyze_arbitrage
from services.strategy_service import get_strategies, execute_strategy
from services.market_service import get_macro_indicators_with_meta
from services.etf_service import get_etfs

# ============================================================
# In-memory state
# ============================================================

_mock_reports: list[dict] = []

_ai_config: dict = {
    "provider": "openai",
    "api_key": "",
    "endpoint": "",
    "temperature": 0.7,
    "cron_expression": "0 8 * * 1-5",
    "enabled": False,
}

# Premium threshold for flagging ETF arbitrage alerts
_PREMIUM_ALERT_THRESHOLD = 5.0


# ============================================================
# Reports
# ============================================================

def get_ai_reports(user_id: str, date: str | None, page: int) -> dict:
    """Return paginated AI reports.

    Generates a mock report automatically when the list is empty.
    """
    if not _mock_reports:
        generate_ai_report(user_id)

    reports = list(_mock_reports)

    if date:
        reports = [r for r in reports if r["date"] == date]

    total = len(reports)
    page_size = 20
    start = (page - 1) * page_size
    end = start + page_size
    items = reports[start:end]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def generate_ai_report(user_id: str) -> dict:
    """Generate a mock AI report by analysing current market data.

    The report includes:
      * macro_assessment   — derived from the equity risk premium (ERP)
      * strategy_matches   — items matching each active strategy's rules
      * arbitrage_alerts   — high-premium ETFs with feasibility assessment
    """
    # ---- Macro assessment based on ERP (真实数据) ------------------
    macro_data, macro_meta = get_macro_indicators_with_meta()
    erp = (macro_data or {}).get("erp")
    if erp is None:
        macro_assessment = (
            "当前股权风险溢价(ERP)数据暂不可用（取数失败），"
            "无法给出基于 ERP 的估值判断，请稍后重试或检查数据源。"
        )
    elif erp > 4:
        macro_assessment = (
            f"当前股权风险溢价(ERP)为 {erp}%，处于历史较高水平，"
            f"市场整体估值偏低，具备中长期配置价值。"
            f"建议关注低估值板块及折价套利机会。"
        )
    elif erp > 3:
        macro_assessment = (
            f"当前股权风险溢价(ERP)为 {erp}%，处于中等水平，"
            f"市场估值基本合理，建议均衡配置，关注结构性机会。"
        )
    else:
        macro_assessment = (
            f"当前股权风险溢价(ERP)为 {erp}%，处于较低水平，"
            f"市场估值偏高，建议谨慎操作，注意控制仓位风险。"
        )

    # ---- Strategy matches (只跟踪 ai_tracking=True 的策略) -----------
    strategy_matches: list[dict[str, Any]] = []
    strategies = get_strategies(user_id)
    for s in strategies:
        if not s.get("active") or not s.get("ai_tracking"):
            continue
        items = execute_strategy(user_id, s["id"], None)
        strategy_matches.append({
            "strategy_name": s["name"],
            "items": items[:5],
        })

    # ---- Arbitrage alerts (high-premium ETFs, 真实数据) ------------
    arbitrage_alerts: list[dict[str, Any]] = []
    try:
        etfs = get_etfs()
    except Exception:
        etfs = []
    for etf in etfs:
        premium = etf.get("premium_pct", 0)
        if premium > _PREMIUM_ALERT_THRESHOLD:
            analysis = analyze_arbitrage(etf)
            arbitrage_alerts.append({
                "name": etf["name"],
                "premium": premium,
                "net_yield": analysis["net_yield_after_costs"],
                "assessment": analysis["feasibility_label"],
            })

    report = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "macro_assessment": macro_assessment,
        "strategy_matches": strategy_matches,
        "arbitrage_alerts": arbitrage_alerts,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _mock_reports.insert(0, report)
    return report


# ============================================================
# Config
# ============================================================

def get_ai_config(user_id: str) -> dict:
    """Return the current AI configuration."""
    return dict(_ai_config)


def update_ai_config(
    user_id: str,
    provider: str,
    api_key: str | None,
    endpoint: str | None,
    temperature: float,
    cron_expression: str | None,
    enabled: bool,
) -> dict:
    """Update and return the AI configuration."""
    _ai_config["provider"] = provider
    _ai_config["api_key"] = api_key or ""
    _ai_config["endpoint"] = endpoint or ""
    _ai_config["temperature"] = temperature
    _ai_config["cron_expression"] = cron_expression or ""
    _ai_config["enabled"] = enabled
    return dict(_ai_config)
