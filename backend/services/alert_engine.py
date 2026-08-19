"""Alert engine — 预警触发引擎。

遍历所有活跃的预警规则，根据规则类型获取对应行情数据，
判断是否触发条件，触发后记录事件并发送通知。

规则类型 (rule.type):
  - price    : 标的价格高于/低于阈值
  - premium  : 折溢价率(%) 高于/低于阈值
  - discount : 折价率(%) (负值) 低于阈值（即折价加深）
  - ytm      : 到期收益率(%) 高于/低于阈值

数据来源: 实时调用 market_service / fund_service / cb_service / reits_service 获取 53 AkShare 数据。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.alert_service import _mock_rules, _mock_events
from services.notification_service import send_notification
from services.fund_service import get_funds
from services.convertible_bond_service import get_convertible_bonds
from services.reits_service import get_reits


# ============================================================
# 辅助函数
# ============================================================

def _check_condition(condition: str, actual: float, threshold: float) -> bool:
    """检查是否满足触发条件。"""
    if condition == "above":
        return actual > threshold
    elif condition == "below":
        return actual < threshold
    elif condition == "crosses":
        # 简化：与 above 相同（穿越 = 从下方升过阈值）
        return actual > threshold
    return False


def _match_target(rule_target: str, item_name: str, item_code: str) -> bool:
    """判断某个标的是否匹配规则的目标。

    rule_target 可以是:
      - 具体代码 (如 "161129.SZ")
      - 具体名称 (如 "TechGrowth CB")
      - 类别 (如 "LOF基金" / "可转债" / "封闭基金" / "REITs")
      - "全部标的" / "" (匹配所有)
    """
    if not rule_target or rule_target in ("全部标的", "全部", "all"):
        return True

    t = rule_target.strip().lower()
    # 类别匹配
    if t in ("lof基金", "lof", "qdii"):
        return True  # 类别匹配由调用方处理
    if t in ("可转债", "转债", "cb"):
        return True
    if t in ("封闭基金", "封基", "closed"):
        return True
    if t in ("reits", "reit"):
        return True

    # 精确匹配代码或名称（不区分大小写）
    return t == item_name.strip().lower() or t == item_code.strip().lower()


def _is_category_target(rule_target: str) -> str | None:
    """判断规则 target 是否为类别匹配，返回类别标识或 None。"""
    t = rule_target.strip().lower()
    if t in ("lof基金", "lof", "qdii"):
        return "fund"
    if t in ("可转债", "转债", "cb"):
        return "cb"
    if t in ("封闭基金", "封基", "closed"):
        return "closed"
    if t in ("reits", "reit"):
        return "reit"
    return None


# ============================================================
# 规则检查
# ============================================================

def _evaluate_rule(rule: dict, items: list[dict], value_key: str) -> list[dict]:
    """对一组标的数据执行单条规则的检查。

    Args:
        rule: 预警规则
        items: 标的数据列表 (每个 dict 至少包含 name, code, 和 value_key 对应的数值)
        value_key: 从 item 中取数值的字段名

    Returns:
        触发的事件列表
    """
    events = []
    condition = rule.get("condition", "above")
    threshold = rule.get("value", 0)
    category = _is_category_target(rule.get("target", ""))

    for item in items:
        item_name = item.get("name", "")
        item_code = item.get("code", "")
        actual_value = item.get(value_key)

        if actual_value is None:
            continue

        # 如果是类别目标，匹配该类别所有标的；否则按名称/代码匹配
        if category:
            # category 已在调用方过滤了，这里直接通过
            pass
        else:
            if not _match_target(rule.get("target", ""), item_name, item_code):
                continue

        if _check_condition(condition, actual_value, threshold):
            event = {
                "id": len(_mock_events) + 1,
                "rule_id": rule["id"],
                "triggered_at": datetime.now(timezone.utc).isoformat(),
                "target_code": item_code,
                "target_name": item_name,
                "actual_value": actual_value,
                "message": (
                    f"预警触发: {rule.get('name', '')} — "
                    f"{item_name}({item_code}) "
                    f"{rule.get('condition', '')} {rule.get('value', '')}, "
                    f"实际值: {actual_value}"
                ),
                "is_read": False,
            }
            _mock_events.append(event)
            events.append(event)

    return events


# ============================================================
# 主入口：执行一次完整的预警扫描
# ============================================================

def run_alert_scan(user_id: str = "demo-user") -> dict[str, Any]:
    """执行一次预警扫描。

    遍历所有活跃规则，获取对应行情数据，检查条件，记录事件并发送通知。

    Returns:
        扫描结果摘要，如:
        {
            "scanned_rules": 4,
            "triggered_events": 3,
            "notifications_sent": {"wechat": 2, "popup": 3},
            "events": [...],
        }
    """
    # 仅扫描活跃的规则
    active_rules = [r for r in _mock_rules if r.get("active")]
    all_events: list[dict] = []
    notification_results: dict[str, int] = {}

    for rule in active_rules:
        rule_type = rule.get("type", "price")
        target = rule.get("target", "")
        category = _is_category_target(target)

        triggered = []

        try:
            if rule_type in ("premium", "discount", "price") and (category or _match_target(target, "", "")):
                # 基金类 (LOF/QDII/封闭)
                funds = get_funds()
                fund_items = [
                    {"name": f.get("name", ""), "code": f.get("code", ""),
                     "premium_pct": f.get("premium_pct"), "price": f.get("price")}
                    for f in (funds or [])
                ]

                if category == "closed":
                    fund_items = [f for f in fund_items if f.get("price") is not None]
                    # 封闭基金用 premium_pct (负值=折价)
                    triggered = _evaluate_rule(rule, fund_items, "premium_pct")
                elif category == "fund":
                    triggered = _evaluate_rule(rule, fund_items, "premium_pct")
                else:
                    # 按名称/代码匹配
                    if rule_type == "premium":
                        triggered = _evaluate_rule(rule, fund_items, "premium_pct")
                    elif rule_type == "price":
                        triggered = _evaluate_rule(rule, fund_items, "price")

            elif rule_type == "ytm" or category == "cb":
                # 可转债
                bonds = get_convertible_bonds()
                cb_items = [
                    {"name": b.get("name", ""), "code": b.get("code", ""),
                     "price": b.get("price"), "ytm": b.get("ytm"),
                     "premium_pct": b.get("premium_pct")}
                    for b in (bonds or [])
                ]
                if rule_type == "ytm":
                    triggered = _evaluate_rule(rule, cb_items, "ytm")
                elif rule_type == "price":
                    triggered = _evaluate_rule(rule, cb_items, "price")
                elif rule_type == "premium":
                    triggered = _evaluate_rule(rule, cb_items, "premium_pct")

            elif category == "reit":
                # REITs
                reits = get_reits()
                reit_items = [
                    {"name": r.get("name", ""), "code": r.get("code", ""),
                     "price": r.get("market_price"),
                     "dividend_rate": r.get("dividend_rate")}
                    for r in (reits or [])
                ]
                if rule_type == "price":
                    triggered = _evaluate_rule(rule, reit_items, "price")

        except Exception as e:
            print(f"[AlertEngine] 规则 {rule.get('name', '')} 执行异常: {e}")
            continue

        all_events.extend(triggered)

        # 发送通知
        if triggered:
            for ev in triggered:
                results = send_notification(
                    channels=rule.get("channels", ["popup"]),
                    rule_name=rule.get("name", ""),
                    target=f"{ev['target_name']}({ev['target_code']})",
                    condition=rule.get("condition", "above"),
                    value=rule.get("value", 0),
                    actual_value=ev.get("actual_value", 0),
                    message=ev.get("message"),
                )
                for ch, ok in results.items():
                    if ok:
                        notification_results[ch] = notification_results.get(ch, 0) + 1

    return {
        "scanned_rules": len(active_rules),
        "triggered_events": len(all_events),
        "notifications_sent": notification_results,
        "events": all_events,
    }
