"""外部数据上传公共契约（按资金账号）。

brokerAuto 等外部程序把「一个资金账号 = 一个业务主体」的数据推到本服务。
本模块把三个反复出现、且最容易串数据的环节收敛到一个地方：

1. **账号归属**：顶层 ``account`` 是整批默认值；逐条 ``broker_account``
   （兼容 ``fund_account`` / ``_broker_account``）可覆盖它。
   没有顶层 account、但每条都带 broker_account 时同样合法 → 一次请求可传多个账号。
2. **券商解析**：每个资金账号独立解析 / 自动建券商，逐条回填 ``broker``；
   任一账号解析失败只影响该账号分组，不影响其它账号。
3. **业务方向 / 品种**：direction 不再只有 buy/sell（逆回购购回、新股入帐、
   资金流水等），type 也不再是硬白名单（repo / bond_cb / standard_bond 原样保留）。

所有上传端点与统一批量端点都复用这里的函数，保证「按账号传」的口径一致。
局域网单人使用时可以只传一个账号；多账号只是同一个 dict 多几个 key，无需改代码。
"""

from __future__ import annotations

from typing import Any

from services.terminal_broker_service import resolve_or_create_broker_for_upload

# 品种：已知值给中文标签，未知值原样保留并在统计里单独归类（不再整条 failed）
TYPE_LABELS: dict[str, str] = {
    "stock": "股票",
    "etf": "场内基金",
    "fund_otc": "场外基金",
    "option": "期权",
    "future": "期货",
    "hk_stock": "港股",
    "repo": "国债逆回购",
    "bond_cb": "可转债",
    "standard_bond": "标准券",
    "bond": "债券",
    "fund": "基金",
    "other": "其它",
}

# direction -> (规范化方向, entry_type)
# entry_type=trade 参与买卖/盈亏统计；cash / other 只入库展示，不参与做T与胜率。
_DIRECTION_MAP: dict[str, tuple[str, str]] = {
    "buy": ("buy", "trade"), "b": ("buy", "trade"), "1": ("buy", "trade"),
    "sell": ("sell", "trade"), "s": ("sell", "trade"), "2": ("sell", "trade"), "-1": ("sell", "trade"),
    "repo_sell": ("repo_sell", "trade"), "repo_buy": ("repo_buy", "trade"),
    "new_issue": ("new_issue", "trade"),
    "dividend": ("dividend", "cash"), "interest": ("interest", "cash"),
    "cash_in": ("cash_in", "cash"), "cash_out": ("cash_out", "cash"),
    "other": ("other", "other"),
}

# 券商客户端原始业务名 -> 规范化方向（键全部小写）
_BIZ_ALIASES: list[tuple[tuple[str, ...], str]] = [
    (("买入", "买进", "证券买", "证券买入", "申购"), "buy"),
    (("卖出", "卖空", "证券卖", "证券卖出", "赎回"), "sell"),
    (("通用回购逆回购", "逆回购", "国债逆回购", "融出"), "repo_sell"),
    (("购回", "逆回购购回", "通用回购逆回购购回", "回购购回"), "repo_buy"),
    (("新股入帐", "新股入账", "配号", "中签"), "new_issue"),
    (("股息", "红利", "分红", "派息"), "dividend"),
    (("结息", "利息"), "interest"),
    (("银行转存", "银行转入", "资金存入", "转入", "存入"), "cash_in"),
    (("银行转取", "银行转出", "资金取出", "转出", "取出"), "cash_out"),
]


def type_label(htype: str) -> str:
    return TYPE_LABELS.get(htype, htype or "未分类")


def normalize_direction(raw: Any, biz: str = "") -> tuple[str, str]:
    """返回 (direction, entry_type)。无法识别时归为 other（只入库、不参与盈亏）。"""
    s = str(raw or "").strip().lower()
    if s in _DIRECTION_MAP:
        return _DIRECTION_MAP[s]
    text = s or str(biz or "").strip().lower()
    # 购回要先于逆回购匹配（「通用回购逆回购购回」包含「通用回购逆回购」）
    for aliases, direction in sorted(_BIZ_ALIASES, key=lambda x: -max(len(a) for a in x[0])):
        for alias in aliases:
            if alias in text:
                return _DIRECTION_MAP[direction]
    return ("other", "other")


def is_trade_direction(direction: str) -> bool:
    return direction in ("buy", "sell", "repo_sell", "repo_buy", "new_issue")


def account_of(item: dict, default_account: str = "") -> str:
    """逐条资金账号优先，其次顶层默认账号。"""
    for key in ("broker_account", "fund_account", "_broker_account", "brokerAccount"):
        v = item.get(key)
        if v not in (None, ""):
            return str(v).strip()
    return str(default_account or "").strip()


def split_by_account(
    items: list[dict], default_account: str = ""
) -> tuple[dict[str, list[dict]], list[dict]]:
    """把 items 按资金账号分组；没有账号的条目进 failed，不影响其它分组。"""
    groups: dict[str, list[dict]] = {}
    failed: list[dict] = []
    for idx, raw in enumerate(items or []):
        item = dict(raw)
        acc = account_of(item, default_account)
        if not acc:
            failed.append({"index": idx, "code": str(item.get("code") or ""),
                           "reason": "缺少资金账号（顶层 account 或逐条 broker_account）",
                           "item": item})
            continue
        item["broker_account"] = acc
        item["_index"] = idx
        groups.setdefault(acc, []).append(item)
    return groups, failed


def resolve_groups(
    user_id: str,
    groups: dict[str, list[dict]],
    broker_name: str | None = None,
    remark: str | None = None,
    terminal: str | None = None,
) -> tuple[dict[str, dict], list[dict]]:
    """每个资金账号独立解析券商并逐条回填 broker；失败的账号整组进 failed。"""
    resolved: dict[str, dict] = {}
    failed: list[dict] = []
    for acc, items in groups.items():
        # 逐条可带 broker_name 覆盖顶层，便于一次请求里混多个券商
        bname = str(broker_name or "").strip()
        for it in items:
            if str(it.get("broker_name") or "").strip():
                bname = str(it["broker_name"]).strip()
                break
        broker = resolve_or_create_broker_for_upload(
            user_id, acc, name=bname or None, remark=remark, terminal_id=terminal,
        )
        if broker is None:
            for it in items:
                failed.append({"index": it.get("_index"), "code": str(it.get("code") or ""),
                               "account": acc, "reason": "资金账号 / 终端无法解析或创建券商",
                               "item": it})
            continue
        for it in items:
            it["broker"] = broker["name"]
        resolved[acc] = {"broker": broker, "items": items,
                         "broker_name": broker["name"], "account": acc}
    return resolved, failed


def dry_run_result(stats: dict, by_account: list[dict], failed: list[dict]) -> dict:
    """dry_run=1 时统一返回 would_* 字段，不写任何库。"""
    out = {"dry_run": True, "failed": failed, "by_account": by_account}
    for k, v in stats.items():
        out["would_" + k] = v
    return out
