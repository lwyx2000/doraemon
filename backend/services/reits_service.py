"""REITs service — real-time market data from AkShare, with NAV/sustainability/liquidity analysis.

数据来源：akshare `reits_realtime_em`（场内公募REITs实时行情），提供 名称/代码/最新价/
涨跌幅/成交额 等真实字段。取数失败时返回空列表，不使用 mock。

说明：年化分红 / 分红率 / IRR / 出租率 / 项目名 等基本面字段 AkShare 实时接口无法直接
获取，统一返回 null（前端显式展示“—”，绝不虚构数值）。NAV 溢折价、可持续性、流动性等
深度分析仍由 utils/reits.analyze_reits 基于“无NAV/数据缺失”逻辑给出标注。
"""

from __future__ import annotations

import re
import time
from typing import Any

import requests

from services.akshare_client import akshare_request
from utils.reits import analyze_reits
from core.config import USE_MOCK_DATA
import mock_data

# 腾讯财经行情源(qt.gtimg.cn)兜底清单：53 上的东财源 reits_realtime_em 被掐，
# 改用腾讯实时行情。清单为场内公募 REITs 代码（如有新发请补充，腾讯对无效代码返回空，不影响）。
REITS_TENCENT_CODES = [
    "sh508000", "sh508001", "sh508006", "sh508007", "sh508008", "sh508009", "sh508011",
    "sh508017", "sh508018", "sh508019", "sh508021", "sh508026", "sh508027", "sh508028",
    "sh508056", "sh508058", "sh508066", "sh508068", "sh508077", "sh508086", "sh508087",
    "sh508088", "sh508089", "sh508096", "sh508098",
    "sz180101", "sz180102", "sz180103", "sz180201", "sz180202", "sz180301", "sz180401",
    "sz180501", "sz180601", "sz180602", "sz180801",
]

# 底层资产类型关键词 → 分类（基于名称的轻量识别，非虚构数据）
_ASSET_KEYWORDS = [
    ("高速公路", "高速公路"),
    ("高速", "高速公路"),
    ("仓储", "仓储物流"),
    ("物流", "仓储物流"),
    ("产业园", "产业园"),
    ("水务", "水务"),
    ("水利", "水务"),
    ("环保", "环保"),
    ("能源", "能源"),
    ("发电", "能源"),
    ("保障房", "保障房"),
    ("安居", "保障房"),
    ("消费", "消费基础设施"),
    ("商业", "消费基础设施"),
]


def _asset_type_of(name: str) -> str | None:
    for kw, label in _ASSET_KEYWORDS:
        if kw in name:
            return label
    return None


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _map_reit_tencent(fields: list[str]) -> dict[str, Any] | None:
    """将腾讯 qt.gtimg.cn 行情字段(~ 分隔)映射为与 _map_reit 一致的 REIT 结构。

    关键字段索引：[1]名称 [2]代码 [3]现价 [4]昨收 [31]涨跌额 [32]涨跌幅%
    [33]最高 [34]最低 [35] 现价/成交量(手)/成交额(元)
    """
    if len(fields) < 36:
        return None
    name = str(fields[1] or "")
    try:
        price = float(fields[3])
    except (ValueError, TypeError):
        return None
    if not name or price <= 0:
        return None
    try:
        change_pct = float(fields[32])
    except (ValueError, TypeError):
        change_pct = None
    amount = 0
    try:
        amount = int(float(fields[35].split("/")[2]))
    except Exception:
        amount = 0
    return {
        "name": name,
        "code": str(fields[2] or ""),
        "market_price": price,
        "change_pct": change_pct,
        "volume": amount,
        "asset_type": _asset_type_of(name),
        # 基本面字段腾讯实时行情无源 → null（不虚构）
        "annual_distribution": None,
        "dividend_rate": None,
        "irr": None,
        "occupancy_rate": None,
        "project_name": None,
        "nav": None,
    }


def get_reits_from_tencent() -> list[dict]:
    """腾讯 qt.gtimg.cn 实时行情兜底（53 东财源 reits_realtime_em 不可用时启用）。"""
    results: list[dict] = []
    for i in range(0, len(REITS_TENCENT_CODES), 8):
        batch = REITS_TENCENT_CODES[i : i + 8]
        try:
            resp = requests.get("https://qt.gtimg.cn/q=" + ",".join(batch), timeout=10)
            text = resp.content.decode("gbk", "ignore")
        except Exception as e:
            print(f"[REITs Tencent] 批次请求失败: {e}")
            continue
        for m in re.finditer(r'v_(\w+)="([^"]*)"', text):
            fields = m.group(2).split("~")
            item = _map_reit_tencent(fields)
            if item:
                results.append(item)
    print(f"[REITs Tencent] 获取到 {len(results)} 条 REITs 实时行情")
    return results


def _map_reit(row: dict[str, Any]) -> dict[str, Any]:
    name = str(row.get("名称", "") or "")
    return {
        "name": name,
        "code": str(row.get("代码", "") or ""),
        "market_price": _safe_float(row.get("最新价"), 0.0) or 0.0,
        "change_pct": _safe_float(row.get("涨跌幅")),
        "volume": int(_safe_float(row.get("成交额"), 0) or 0),
        "asset_type": _asset_type_of(name),
        # 基本面字段 AkShare 实时接口无源 → null（不虚构）
        "annual_distribution": None,
        "dividend_rate": None,
        "irr": None,
        "occupancy_rate": None,
        "project_name": None,
        "nav": None,
    }


# 东财源(reits_realtime_em)在 53 上长期超时，失败后进入冷却期直连腾讯，避免每次等待超时
_EASTMONEY_REITS_DEAD_UNTIL = 0.0
_EASTMONEY_REITS_COOLDOWN = 300  # 秒


def get_reits(
    asset_type: str | None = None,
    min_dividend: float | None = None,
    nav_level: str | None = None,
    sustainability: str | None = None,
) -> list[dict]:
    """Return real REITs (实时行情) filtered by the given criteria.

    每个 REIT 经 analyze_reits 深度分析后合并分析结果再过滤。取数失败返回空列表。

    数据源策略：优先 53 东财 reits_realtime_em；失败（53→东财连接被掐）后降级到
    腾讯 qt.gtimg.cn 实时行情，并进入冷却期直连腾讯以避开每次 15s 超时。
    """
    global _EASTMONEY_REITS_DEAD_UNTIL
    if USE_MOCK_DATA:
        results: list[dict] = []
        for row in mock_data.MOCK_REITS:
            item = dict(row)
            analysis = analyze_reits(item)
            item.update(analysis)
            results.append(item)
        return results

    now = time.time()
    if now > _EASTMONEY_REITS_DEAD_UNTIL:
        # 主源：53 东财 reits_realtime_em
        raw = akshare_request("reits_realtime_em", retries=1, timeout=10)
        if raw and isinstance(raw, list) and raw:
            items = [_map_reit(r) for r in raw]
        else:
            _EASTMONEY_REITS_DEAD_UNTIL = now + _EASTMONEY_REITS_COOLDOWN
            print("[REITs Service] 东财源取数失败，降级到腾讯 qt.gtimg.cn（冷却期内直连）")
            items = get_reits_from_tencent()
    else:
        # 冷却期内直连腾讯，跳过已确认不可用的东财源
        items = get_reits_from_tencent()

    if not items:
        print("[REITs Service] 取数失败，返回空列表")
        return []

    results: list[dict] = []
    for item in items:
        analysis = analyze_reits(item)
        item.update(analysis)
        results.append(item)

    filtered: list[dict] = []
    for item in results:
        if asset_type is not None and item.get("asset_type") != asset_type:
            continue
        if min_dividend is not None and (item.get("dividend_rate") or 0) < min_dividend:
            continue
        if nav_level is not None and item.get("nav_level") != nav_level:
            continue
        if sustainability is not None and item.get("sustainability") != sustainability:
            continue
        filtered.append(item)

    return filtered
