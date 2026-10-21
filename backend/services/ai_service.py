"""AI service — report generation and configuration.

基于真实行情数据生成 AI 报告：宏观判断取自真实 ERP（失败则如实说明数据缺失），
套利告警取自真实 ETF 数据（取数失败时为空，不使用 mock）。报告状态为内存态。

AI 解读/问答（interpret / chat）：后端自行组装真实数据上下文 + 知识库检索，
经 llm_service 多渠道（OpenAI 兼容）流式输出；无渠道时由路由层返回配置引导帧。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from utils.arbitrage import analyze_arbitrage
from services.strategy_service import get_strategies, execute_strategy
from services.market_service import get_macro_indicators_with_meta
from services.etf_service import get_etfs
from services import llm_service
from services import knowledge_service
from services.fear_greed_service import get_latest as _fg_latest, get_history as _fg_history

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

def _mask_key(key: str | None) -> str:
    """与 llm_service._mask_key 同口径：只回 ****last4。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return "****" + key[-4:]


def get_ai_config(user_id: str) -> dict:
    """Return the current AI configuration（api_key 脱敏回显）。

    2026-10-14 审计 P2-3：旧版 GET 明文回显 api_key，与渠道列表
    ****last4 脱敏机制不一致。注意前端保存配置会原样回传该字段，
    因此 update_ai_config 必须把 **** 开头视为「不修改」。
    """
    cfg = dict(_ai_config)
    cfg["api_key"] = _mask_key(cfg.get("api_key"))
    return cfg


def update_ai_config(
    user_id: str,
    provider: str,
    api_key: str | None,
    endpoint: str | None,
    temperature: float,
    cron_expression: str | None,
    enabled: bool,
) -> dict:
    """Update and return the AI configuration.

    api_key 语义：空串 = 清除；**** 开头的脱敏回显值 = 不修改（GET 原样
    回传的场景）；其余 = 写入新值。
    """
    _ai_config["provider"] = provider
    if api_key is not None and not str(api_key).startswith("****"):
        _ai_config["api_key"] = api_key or ""
    _ai_config["endpoint"] = endpoint or ""
    _ai_config["temperature"] = temperature
    _ai_config["cron_expression"] = cron_expression or ""
    _ai_config["enabled"] = enabled
    return get_ai_config(user_id)


# ============================================================
# AI 解读 / 问答（真实数据 + 知识库 → LLM 流式）
# ============================================================

_SYSTEM_PROMPT = (
    "你是 QuantTerminal（量化投资终端）的 AI 分析助手，服务对象是只交易基金/ETF 的个人投资者。\n"
    "铁律：\n"
    "1. 只基于下方提供的真实数据与知识库内容作答，禁止编造任何数据、数字或结论；"
    "数据缺失或过期时如实说明「数据暂不可用」，并给出可能的排查方向。\n"
    "2. 引用数据时带上数据时间戳；涉及估值分位/贪婪恐惧等指标时，说明其口径（知识库中有）。\n"
    "3. 建议必须可执行、有边界（仓位/止损/时间维度），不做收益承诺。\n"
    "4. 用简体中文、markdown 格式输出，重点先行，控制在 600 字以内。"
)

# context_type → 固定挂载的知识库文档
_CONTEXT_KNOWLEDGE: dict[str, list[str]] = {
    "dashboard": ["erp-pe-pb", "fear-greed", "datasource-map"],
    "fear_greed": ["fear-greed", "datasource-map"],
}

# 单条 chat 问题的字数上限（history 侧为 2000 字/条 × 8 条）
_MAX_CHAT_MESSAGE = 4000

# AI 解读时用户导入知识的挂载预算（总量上限，超出按更新时间倒序截断）
_IMPORT_KB_BUDGET = 8000


def _compact(value: Any, limit: int = 1500) -> str:
    """JSON 序列化并截断，防止 prompt 超长。"""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        text = str(value)
    return text[:limit] + ("…[截断]" if len(text) > limit else "")


def _collect_dashboard_context() -> dict:
    """宏观看板上下文：ERP、指数快照、板块/资金流/涨停、贪婪恐惧。全部真实取数。"""
    ctx: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat()}

    try:
        macro, _meta = get_macro_indicators_with_meta()
        ctx["macro"] = {
            "erp": (macro or {}).get("erp"),
            "dr007": (macro or {}).get("dr007"),
            "gc001": (macro or {}).get("gc001"),
        }
    except Exception as e:  # noqa: BLE001
        ctx["macro"] = {"error": f"宏观指标取数失败: {e}"}

    try:
        from services.market_service import get_realtime_indices, get_zt_stats_with_meta, get_fund_flows_with_meta

        indices = get_realtime_indices() or []
        ctx["indices"] = [
            {"name": i.get("name"), "price": i.get("price"), "chg_pct": i.get("chg_pct")}
            for i in indices[:10]
        ]
        zt, _ = get_zt_stats_with_meta()
        ctx["zt_stats"] = zt
        flows, _ = get_fund_flows_with_meta()
        ctx["fund_flows"] = flows
    except Exception as e:  # noqa: BLE001
        ctx["market_detail_error"] = f"行情分区取数失败: {e}"

    try:
        fg = _fg_latest()
        if fg:
            ctx["fear_greed"] = {
                "trade_date": fg.get("trade_date"),
                "score": fg.get("score"),
                "label": fg.get("label"),
                "components_used": fg.get("components_used"),
            }
    except Exception as e:  # noqa: BLE001
        ctx["fear_greed"] = {"error": f"贪婪恐惧取数失败: {e}"}
    return ctx


def _collect_fear_greed_context() -> dict:
    """恐贪详情上下文：最新分数 + 分项 + 近 90 日走势摘要。"""
    ctx: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat()}
    try:
        fg = _fg_latest()
        if not fg:
            ctx["latest"] = {"error": "暂无贪婪恐惧数据（未采集或回补未跑）"}
        else:
            ctx["latest"] = fg
        hist = _fg_history(90) or []
        ctx["history_90d"] = [
            {"trade_date": h.get("trade_date"), "score": h.get("score")} for h in hist
        ]
        if hist:
            scores = [h.get("score") for h in hist if h.get("score") is not None]
            if scores:
                ctx["summary"] = {
                    "count": len(scores),
                    "min": min(scores),
                    "max": max(scores),
                    "avg": round(sum(scores) / len(scores), 1),
                }
    except Exception as e:  # noqa: BLE001
        ctx["error"] = f"贪婪恐惧取数失败: {e}"
    return ctx


def build_interpret(context_type: str) -> dict:
    """组装 AI 解读请求：messages + 元信息（供前端 meta 帧展示用了哪些数据/文档）。"""
    if context_type == "dashboard":
        context = _collect_dashboard_context()
    elif context_type == "fear_greed":
        context = _collect_fear_greed_context()
    else:
        raise ValueError(f"不支持的 context_type: {context_type}")

    doc_ids = _CONTEXT_KNOWLEDGE.get(context_type, [])
    docs = knowledge_service.docs_by_ids(doc_ids)

    # 用户导入的知识：启用态全部参与（用户主动导入即期望被解读引用），
    # 总量预算 8000 字防 prompt 爆炸；meta 帧列出所用文档（含来源标记）。
    imported = knowledge_service.imported_for_interpret(max_chars=_IMPORT_KB_BUDGET)

    user_parts = [
        f"请基于以下「{context_type}」页面的真实数据给出解读：\n{_compact(context)}",
    ]
    if docs:
        kb = "\n\n".join(f"### {d['title']}\n{d['content']}" for d in docs)
        user_parts.append(f"相关口径知识库（解释指标含义时引用）：\n{_compact(kb, 3000)}")
    if imported:
        kb_i = "\n\n".join(f"### {d['title']}（用户导入知识）\n{d['content']}" for d in imported)
        user_parts.append(f"用户导入的知识库（解读时优先参考）：\n{_compact(kb_i, _IMPORT_KB_BUDGET)}")
    user_parts.append("请按：结论先行 → 数据依据（带时间戳）→ 风险提示 → 可执行建议 的结构输出。")

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
    doc_meta = [{"id": d.get("id"), "title": d.get("title")} for d in docs]
    doc_meta.extend({"id": d.get("id"), "title": d.get("title"), "source": "import"} for d in imported)
    return {
        "messages": messages,
        "context": context,
        "docs": doc_meta,
    }


def build_chat(message: str, context_type: str | None, history: list[dict] | None) -> dict:
    """组装 AI 问答请求：问题 → 知识库检索接地 +（可选）当前页面真实数据。"""
    message = (message or "").strip()
    if not message:
        raise ValueError("问题不能为空")
    # message 本体同样要有上限：history 已有 [-8:]+2000 字截断，唯独当前问题
    # 无约束，一条超长粘贴可撑爆 prompt（2026-10-14 审计 P2-2 修复）。
    if len(message) > _MAX_CHAT_MESSAGE:
        message = message[:_MAX_CHAT_MESSAGE] + "…[问题超长已截断]"

    docs = knowledge_service.search(message, top_k=3)
    user_parts: list[str] = []
    if context_type in _CONTEXT_KNOWLEDGE:
        context = (
            _collect_dashboard_context() if context_type == "dashboard"
            else _collect_fear_greed_context()
        )
        user_parts.append(f"用户当前正在查看「{context_type}」页面，其真实数据：\n{_compact(context)}")
    if docs:
        kb = "\n\n".join(
            f"### {d['title']}（相关度 {d['score']}）\n{d['snippet']}" for d in docs
        )
        user_parts.append(f"知识库检索结果（回答涉及口径/坑位时引用）：\n{_compact(kb, 3000)}")

    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for item in (history or [])[-8:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:2000]})
    if user_parts:
        messages.append({"role": "user", "content": "\n\n".join(user_parts)})
    messages.append({"role": "user", "content": message})

    return {
        "messages": messages,
        "docs": [{"id": d.get("id"), "title": d.get("title"), "snippet": d.get("snippet")} for d in docs],
        "context_type": context_type,
    }
