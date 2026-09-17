"""Strategy service — CRUD and execution for quantitative screening strategies.

核心设计：
- 不同标的类型（cb/etf/fund/reit）拥有各自的字段元数据（ASSET_META），前端通过 API 获取字段列表，实现字段联动
- 策略存储为 JSON 规则组（支持多条 AND 逻辑），附加排序+取前N
- 执行时对内存数据集（mock 或由上游 service 注入）做筛选→排序→截断
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from database.connection import get_db
from core.config import USE_MOCK_DATA
from mock_data import (
    MOCK_STRATEGIES,
    MOCK_FUNDS,
    MOCK_CONVERTIBLE_BONDS,
    MOCK_REITS,
    MOCK_ETF_FUNDS,
)

# ============================================================
# 标的类型元数据 — 每种标的的可用字段定义
# ============================================================

ASSET_META: dict[str, dict] = {
    "cb": {
        "label": "可转债",
        "fields": [
            {"key": "price", "label": "价格", "type": "number", "unit": "元"},
            {"key": "premium_pct", "label": "转股溢价率", "type": "number", "unit": "%"},
            {"key": "ytm", "label": "到期收益率", "type": "number", "unit": "%"},
            {"key": "double_low_score", "label": "双低值", "type": "number"},
            {"key": "remaining_years", "label": "剩余年限", "type": "number", "unit": "年"},
            {"key": "iv", "label": "隐含波动率", "type": "number", "unit": "%"},
            {"key": "hv", "label": "历史波动率", "type": "number", "unit": "%"},
            {"key": "rating", "label": "信用评级", "type": "enum", "options": ["AAA", "AA+", "AA", "A+", "A"]},
            {"key": "redemption_days", "label": "赎回触发天数", "type": "number", "unit": "天"},
            {"key": "putback_days", "label": "回售触发天数", "type": "number", "unit": "天"},
            {"key": "stock_change_pct", "label": "正股涨跌幅", "type": "number", "unit": "%"},
            {"key": "altman_z_score", "label": "Z值", "type": "number"},
            {"key": "pledge_rate", "label": "质押率", "type": "number", "unit": "%"},
        ],
    },
    "etf": {
        "label": "ETF",
        "fields": [
            {"key": "price", "label": "价格", "type": "number", "unit": "元"},
            {"key": "premium_pct", "label": "折溢价率", "type": "number", "unit": "%"},
            {"key": "premium_percentile", "label": "溢价百分位", "type": "number"},
            {"key": "net_arbitrage_yield", "label": "净套利收益率", "type": "number", "unit": "%"},
            {"key": "volume", "label": "成交量", "type": "number"},
            {"key": "momentum_score", "label": "动量评分", "type": "number"},
            {"key": "pe", "label": "PE", "type": "number"},
            {"key": "pe_percentile", "label": "PE百分位", "type": "number"},
            {"key": "dividend_rate", "label": "股息率", "type": "number", "unit": "%"},
            {"key": "daily_volatility", "label": "日均波动", "type": "number", "unit": "%"},
            {"key": "grid_yield_est", "label": "网格预估收益", "type": "number", "unit": "%"},
            {"key": "category", "label": "类别", "type": "enum", "options": ["broad", "industry", "theme", "cross_border"]},
            {"key": "val_category", "label": "估值分类", "type": "enum", "options": ["undervalued", "normal", "overvalued"]},
        ],
    },
    "lof": {
        "label": "LOF基金",
        "fields": [
            {"key": "price", "label": "价格", "type": "number", "unit": "元"},
            {"key": "iopv", "label": "IOPV", "type": "number"},
            {"key": "premium_pct", "label": "折溢价率", "type": "number", "unit": "%"},
            {"key": "premium_percentile", "label": "折溢价百分位", "type": "number"},
            {"key": "net_arbitrage_yield", "label": "净套利收益率", "type": "number", "unit": "%"},
            {"key": "volume", "label": "成交量", "type": "number"},
        ],
    },
    "qdii": {
        "label": "QDII基金",
        "fields": [
            {"key": "price", "label": "价格", "type": "number", "unit": "元"},
            {"key": "iopv", "label": "IOPV", "type": "number"},
            {"key": "premium_pct", "label": "折溢价率", "type": "number", "unit": "%"},
            {"key": "premium_percentile", "label": "折溢价百分位", "type": "number"},
            {"key": "net_arbitrage_yield", "label": "净套利收益率", "type": "number", "unit": "%"},
            {"key": "volume", "label": "成交量", "type": "number"},
            {"key": "daily_volatility", "label": "日均波动", "type": "number", "unit": "%"},
            {"key": "holding_days", "label": "持仓天数", "type": "number", "unit": "天"},
        ],
    },
    "fund": {
        "label": "封闭式基金",
        "fields": [
            {"key": "price", "label": "价格", "type": "number", "unit": "元"},
            {"key": "iopv", "label": "IOPV", "type": "number"},
            {"key": "premium_pct", "label": "折溢价率", "type": "number", "unit": "%"},
            {"key": "premium_percentile", "label": "折溢价百分位", "type": "number"},
            {"key": "net_arbitrage_yield", "label": "净套利收益率", "type": "number", "unit": "%"},
            {"key": "volume", "label": "成交量", "type": "number"},
            {"key": "annualized", "label": "年化收益", "type": "number", "unit": "%"},
            {"key": "est_ytm", "label": "预估到期收益", "type": "number", "unit": "%"},
            {"key": "nav", "label": "净值", "type": "number"},
            {"key": "credit_rating", "label": "信用评级", "type": "enum", "options": ["AAA", "AA+", "AA", "A+"]},
            {"key": "underlying_type", "label": "底层类型", "type": "text"},
        ],
    },
    "reit": {
        "label": "REITs",
        "fields": [
            {"key": "market_price", "label": "市场价格", "type": "number", "unit": "元"},
            {"key": "dividend_rate", "label": "分红率", "type": "number", "unit": "%"},
            {"key": "irr", "label": "IRR", "type": "number", "unit": "%"},
            {"key": "nav", "label": "NAV", "type": "number"},
            {"key": "occupancy_rate", "label": "出租率", "type": "number", "unit": "%"},
            {"key": "occupancy_trend", "label": "出租率趋势", "type": "number", "unit": "%"},
            {"key": "dscr", "label": "DSCR", "type": "number"},
            {"key": "leverage_ratio", "label": "杠杆率", "type": "number", "unit": "%"},
            {"key": "annual_distribution", "label": "年度分配", "type": "number"},
            {"key": "asset_type", "label": "资产类型", "type": "enum", "options": ["产业园", "仓储物流", "水务", "高速公路"]},
        ],
    },
}

# target_asset -> mock dataset (lof/qdii/fund 各取 MOCK_FUNDS 中对应 type 子集)
_fund_all = MOCK_FUNDS
DATASET_MAP: dict[str, list[dict]] = {
    "cb": MOCK_CONVERTIBLE_BONDS,
    "etf": MOCK_ETF_FUNDS,
    "lof": [f for f in _fund_all if f.get("type") == "lof"],
    "qdii": [f for f in _fund_all if f.get("type") == "qdii"],
    "fund": [f for f in _fund_all if f.get("type") == "closed"],
    "reit": MOCK_REITS,
    "reits": MOCK_REITS,
}

# mock 模式内存存储
_mock_strategies: list[dict] = [dict(s) for s in MOCK_STRATEGIES]

_TABLES_READY = False


# ============================================================
# DuckDB 懒建表
# ============================================================

def _ensure_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY or USE_MOCK_DATA:
        return
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS biz_strategies (
            id            VARCHAR PRIMARY KEY,
            fk_users       UUID NOT NULL,
            name          VARCHAR(50) NOT NULL,
            target_asset  VARCHAR(10) NOT NULL,
            rules         JSON,
            sort_by       VARCHAR(50),
            sort_order    VARCHAR(4) DEFAULT 'asc',
            limit_count   INTEGER,
            active        BOOLEAN DEFAULT TRUE,
            ai_tracking   BOOLEAN DEFAULT FALSE,
            created_at    TIMESTAMP DEFAULT now()
        )
        """
    )
    # Add missing columns if table was created before schema upgrade
    for col, ddl in [
        ("sort_by", "VARCHAR(50)"),
        ("sort_order", "VARCHAR(4) DEFAULT 'asc'"),
        ("limit_count", "INTEGER"),
    ]:
        try:
            db.execute(f"ALTER TABLE biz_strategies ADD COLUMN {col} {ddl}")
        except Exception:
            pass  # column already exists
    _TABLES_READY = True


def _row_to_dict(row: tuple) -> dict:
    return {
        "id": str(row[0]),
        "name": row[1],
        "target_asset": row[2],
        "rules": json.loads(row[3]) if row[3] else [],
        "sort_by": row[4] if len(row) > 4 else None,
        "sort_order": row[5] if len(row) > 5 else "asc",
        "limit_count": row[6] if len(row) > 6 else None,
        "active": row[7] if len(row) > 7 else True,
        "ai_tracking": row[8] if len(row) > 8 else False,
        "createdAt": row[9].isoformat() if len(row) > 9 and row[9] else "",
    }


# ============================================================
# 字段元数据 API
# ============================================================

def get_asset_meta() -> list[dict]:
    """返回所有标的类型及其字段元数据，供前端构建动态表单。"""
    return [
        {"key": k, "label": v["label"], "fields": v["fields"]}
        for k, v in ASSET_META.items()
    ]


# ============================================================
# 规则评估
# ============================================================

def _get_field_value(item: dict, field_key: str) -> Any:
    """从数据字典中取出字段值。"""
    return item.get(field_key)


def _match_rule(item: dict, rule: dict) -> bool:
    """Return True if *item* satisfies *rule*."""
    field: str = rule.get("field", "")
    operator: str = rule.get("operator", "")
    value: Any = rule.get("value", "")

    item_value = _get_field_value(item, field)
    if item_value is None:
        return False  # field not on the item — doesn't match

    # "属于" (belongs to) — comma-separated membership check
    if operator == "属于":
        allowed = [v.strip() for v in str(value).split(",") if v.strip()]
        return str(item_value) in allowed

    # "包含" — text contains
    if operator == "包含":
        return str(value).lower() in str(item_value).lower()

    # Numeric comparison operators
    try:
        iv = float(item_value)
        rv = float(value)
    except (ValueError, TypeError):
        return False

    if operator == "<":
        return iv < rv
    if operator == ">":
        return iv > rv
    if operator == "<=":
        return iv <= rv
    if operator == ">=":
        return iv >= rv
    if operator == "==":
        return iv == rv
    if operator == "!=":
        return iv != rv

    return False


def _matches_all_rules(item: dict, rules: list[dict]) -> bool:
    return all(_match_rule(item, rule) for rule in rules)


# ============================================================
# Public API
# ============================================================

def get_strategies(user_id: str) -> list[dict]:
    """Return all strategies for the user."""
    if USE_MOCK_DATA:
        return list(_mock_strategies)
    _ensure_tables()
    db = get_db()
    rows = db.fetchall(
        "SELECT id, name, target_asset, rules, sort_by, sort_order, limit_count, "
        "active, ai_tracking, created_at "
        "FROM biz_strategies WHERE fk_users = ? ORDER BY created_at",
        [user_id],
    )
    return [_row_to_dict(r) for r in rows]


def create_strategy(
    user_id: str, name: str, target_asset: str, rules: list[dict],
    sort_by: str | None = None, sort_order: str = "asc", limit_count: int | None = None,
) -> dict:
    """Create a new strategy."""
    strategy = {
        "id": str(uuid.uuid4()),
        "name": name,
        "target_asset": target_asset,
        "rules": rules,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "limit_count": limit_count,
        "active": True,
        "ai_tracking": False,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if USE_MOCK_DATA:
        _mock_strategies.append(strategy)
        return strategy
    _ensure_tables()
    db = get_db()
    db.execute(
        "INSERT INTO biz_strategies "
        "(id, fk_users, name, target_asset, rules, sort_by, sort_order, limit_count, active, ai_tracking, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [strategy["id"], user_id, name, target_asset,
         json.dumps(rules), sort_by, sort_order, limit_count,
         True, False, datetime.now(timezone.utc)],
    )
    return strategy


def update_strategy(
    user_id: str, strategy_id: str,
    name: str | None = None,
    active: bool | None = None,
    ai_tracking: bool | None = None,
    rules: list[dict] | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    limit_count: int | None = None,
) -> dict | None:
    """Update a strategy; return updated or None."""
    # 先拿现有数据
    strategies = get_strategies(user_id)
    target: dict | None = None
    for s in strategies:
        if s["id"] == strategy_id:
            target = s
            break
    if target is None:
        return None

    if USE_MOCK_DATA:
        if name is not None:
            target["name"] = name
        if active is not None:
            target["active"] = active
        if ai_tracking is not None:
            target["ai_tracking"] = ai_tracking
        if rules is not None:
            target["rules"] = rules
        if sort_by is not None:
            target["sort_by"] = sort_by
        if sort_order is not None:
            target["sort_order"] = sort_order
        if limit_count is not None:
            target["limit_count"] = limit_count
        return target

    _ensure_tables()
    db = get_db()
    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if active is not None:
        sets.append("active = ?")
        params.append(active)
    if ai_tracking is not None:
        sets.append("ai_tracking = ?")
        params.append(ai_tracking)
    if rules is not None:
        sets.append("rules = ?")
        params.append(json.dumps(rules))
    if sort_by is not None:
        sets.append("sort_by = ?")
        params.append(sort_by)
    if sort_order is not None:
        sets.append("sort_order = ?")
        params.append(sort_order)
    if limit_count is not None:
        sets.append("limit_count = ?")
        params.append(limit_count)
    if sets:
        params.append(strategy_id)
        params.append(user_id)
        db.execute(
            f"UPDATE biz_strategies SET {', '.join(sets)} WHERE id = ? AND fk_users = ?",
            params,
        )
    # 重新读取
    row = db.fetchone(
        "SELECT id, name, target_asset, rules, sort_by, sort_order, limit_count, "
        "active, ai_tracking, created_at "
        "FROM biz_strategies WHERE id = ? AND fk_users = ?",
        [strategy_id, user_id],
    )
    return _row_to_dict(row) if row else None


def delete_strategy(user_id: str, strategy_id: str) -> bool:
    """Remove a strategy; return True/False."""
    if USE_MOCK_DATA:
        for i, s in enumerate(_mock_strategies):
            if s["id"] == strategy_id:
                _mock_strategies.pop(i)
                return True
        return False
    _ensure_tables()
    db = get_db()
    row = db.fetchone(
        "SELECT count(*) FROM biz_strategies WHERE id = ? AND fk_users = ?",
        [strategy_id, user_id],
    )
    if not row or row[0] == 0:
        return False
    db.execute("DELETE FROM biz_strategies WHERE id = ?", [strategy_id])
    return True


def execute_strategy(user_id: str, strategy_id: str, date: str | None) -> dict:
    """Run a strategy's rules against the appropriate dataset.

    Returns: { "items": [...], "total": N, "strategy": {...} }
    """
    strategies = get_strategies(user_id)
    strategy: dict | None = None
    for s in strategies:
        if s["id"] == strategy_id:
            strategy = s
            break

    if strategy is None:
        return {"items": [], "total": 0, "strategy": None}

    dataset = DATASET_MAP.get(strategy.get("target_asset", ""), [])
    rules = strategy.get("rules", [])

    # 筛选
    matched = [item for item in dataset if _matches_all_rules(item, rules)]

    # 排序
    sort_by = strategy.get("sort_by")
    sort_order = strategy.get("sort_order", "asc")
    if sort_by:
        reverse = (sort_order == "desc")
        try:
            matched.sort(key=lambda x: float(x.get(sort_by, 0)), reverse=reverse)
        except (ValueError, TypeError):
            pass

    total = len(matched)

    # 取前N
    limit = strategy.get("limit_count")
    if limit and limit > 0:
        matched = matched[:limit]

    return {
        "items": matched,
        "total": total,
        "returned": len(matched),
        "strategy": {
            "name": strategy["name"],
            "target_asset": strategy["target_asset"],
            "sort_by": sort_by,
            "sort_order": sort_order,
            "limit_count": limit,
        },
    }
