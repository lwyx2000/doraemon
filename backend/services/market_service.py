"""Market data service — macro indicators, index valuations, K-line history.

从 AkShare WebAPI (core.config.AKSHARE_API_BASE) 获取真实数据，无法获取的字段使用 mock 数据填充。
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
import requests
import time

from core.config import AKSHARE_API_BASE, USE_MOCK_DATA
from database.bulk import bulk_insert
from services.akshare_client import get_session
from services.meta_utils import gateway_no_data_meta
import mock_data

# 上游地址的 host 部分（用于前端"数据来源"横幅展示，随配置自动变化）
AKSHARE_HOST = AKSHARE_API_BASE.rstrip("/").split("://")[-1]


def _akshare_request(method: str, params: dict | None = None, retries: int = 1, timeout: int = 8) -> dict | list | None:
    """调用 AkShare WebAPI (/api/ak 通用接口)
    
    注意：此接口容易反爬，超时时间不宜过长
    
    Args:
        method: AkShare 方法名
        params: 方法参数
        retries: 重试次数
        timeout: 超时时间（秒），默认10秒
    
    Returns:
        API 返回的数据，失败返回 None
    """
    url = f"{AKSHARE_API_BASE}/api/ak"
    request_params = {"method": method}
    if params:
        request_params.update(params)
    
    for attempt in range(retries):
        try:
            print(f"[AkShare API] 调用 {method} (尝试 {attempt + 1}/{retries}, 超时{timeout}s)...")
            response = get_session().get(url, params=request_params, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") != 200:
                print(f"[AkShare API] {method} 返回错误: {result.get('message')}")
                return None
            
            data = result.get("data")
            print(f"[AkShare API] {method} 成功，返回 {len(data) if isinstance(data, list) else '对象'} 数据")
            return data
            
        except requests.exceptions.Timeout:
            print(f"[AkShare API] {method} 超时 (attempt {attempt + 1}/{retries})")
        except requests.exceptions.ConnectionError as e:
            print(f"[AkShare API] {method} 连接错误: {e} (attempt {attempt + 1}/{retries})")
        except Exception as e:
            print(f"[AkShare API] {method} 错误: {e} (attempt {attempt + 1}/{retries})")
        
        if attempt < retries - 1:
            time.sleep(1)
    
    print(f"[AkShare API] {method} 所有重试失败")
    return None


_STATUS_CHECK_TIMEOUT = 5


def _check_akshare_reachable(timeout: int = _STATUS_CHECK_TIMEOUT) -> bool:
    """AkShare WebAPI 可达性探测。"""
    try:
        r = get_session().get(
            f"{AKSHARE_API_BASE}/api/processed_data",
            params={"category": "market_stats"},
            timeout=timeout,
        )
        return r.status_code == 200
    except Exception:
        return False


def _fetch_jisilu_auth_detail(timeout: int = _STATUS_CHECK_TIMEOUT) -> dict | None:
    """读取 53 侧 /api/jisilu/auth-status 的**完整**详情。

    上游能区分三种状态（2026-10-08 实测）：
      - ``no_cookie``      : 压根没配 cookie → 需从零配置
      - ``cookie_invalid`` : 配了但已失效     → 只需刷新 cookie
      - ``logged_in``      : 正常             → 不必打扰
    ⚠️ 旧实现只取 ``logged_in`` 一个布尔值，丢掉 ``has_cookie`` /
      ``can_dynamic_login`` / ``status`` / ``message``，导致前端只能显示
      「失效/未配置」这种笼统提示，无法区分「没配」和「过期」，指引方向会错。
    返回 None 表示该接口不可用（调用方回退到旧的推断方式）。
    """
    try:
        r = get_session().get(
            f"{AKSHARE_API_BASE}/api/jisilu/auth-status",
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("data") or {}
        # 显式有 logged_in 字段才采信，缺失视为接口不可用
        if "logged_in" not in data:
            return None
        return {
            "loggedIn": bool(data.get("logged_in")),
            "hasCookie": bool(data.get("has_cookie")),
            "canDynamicLogin": bool(data.get("can_dynamic_login")),
            "status": str(data.get("status") or ""),
            "message": str(data.get("message") or ""),
            "checkedAt": str(data.get("checked_at") or ""),
        }
    except Exception:
        return None


def _fetch_jisilu_login_status(timeout: int = _STATUS_CHECK_TIMEOUT) -> bool | None:
    """（保留旧签名）只要是否登录；不可用返回 None。"""
    d = _fetch_jisilu_auth_detail(timeout)
    return None if d is None else d["loggedIn"]


def get_data_source_status() -> dict:
    """数据源连接状态：AkShare WebAPI 可达性 + 集思录登录态(严格)。

    - akshareConnected: 53 服务是否可达。
    - jisiluLoggedIn: 是否真正登录集思录(严格)。
      优先读取 53 侧新增的 /api/jisilu/auth-status（直接依据 Cookie 配置/动态登录
      能力判定，而非"能否取到数据"——游客态也能取到部分数据，故旧推断不可靠）；
      若该接口不可用则回退到旧推断(能否取到 jisilu 数据)。
    - jisiluStatus / jisiluMessage: 上游给的具体状态与说明（供前端按状态给不同指引；
      上游接口不可用时为 None）。

    两项探测并行执行，超时均缩短为 5s，避免数据源不可达时长时间阻塞设置页。
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        akshare_future = pool.submit(_check_akshare_reachable)
        detail_future = pool.submit(_fetch_jisilu_auth_detail)
        akshare_connected = akshare_future.result()
        detail = detail_future.result()

    jisilu_logged_in = None if detail is None else detail["loggedIn"]

    if jisilu_logged_in is None:
        # 兜底：旧推断（能否取到 jisilu 数据）
        try:
            r = get_session().get(
                f"{AKSHARE_API_BASE}/api/processed_data",
                params={"category": "jisilu", "subtype": "closed_fund"},
                timeout=_STATUS_CHECK_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json().get("data")
                jisilu_logged_in = isinstance(data, list) and len(data) > 0
        except Exception:
            jisilu_logged_in = False

    return {
        "akshareConnected": akshare_connected,
        "jisiluLoggedIn": bool(jisilu_logged_in),
        # 详情（上游不可用时为 None，前端据此退化为通用提示）
        "jisiluStatus": (detail or {}).get("status"),
        "jisiluMessage": (detail or {}).get("message"),
        "jisiluHasCookie": (detail or {}).get("hasCookie"),
        "jisiluCanDynamicLogin": (detail or {}).get("canDynamicLogin"),
        "timestamp": datetime.now().isoformat(),
    }


def _processed_data_request(category: str, params: dict | None = None, retries: int = 1, timeout: int = 10) -> dict | list | None:
    """调用加工数据统一入口 (/api/processed_data)
    
    Args:
        category: 数据大类，如 "index_valuation", "board", "fund_flow", "market_stats", "zt_pool", "fund_rank"
        params: 额外参数，如 {"subtype": "all", "period": 5}
        retries: 重试次数
        timeout: 超时时间（秒），默认30秒
    
    Returns:
        API 返回的数据，失败返回 None
    """
    url = f"{AKSHARE_API_BASE}/api/processed_data"
    request_params = {"category": category}
    if params:
        request_params.update(params)
    
    for attempt in range(retries):
        try:
            print(f"[Processed API] 调用 {category} (尝试 {attempt + 1}/{retries}, 超时{timeout}s)...")
            response = get_session().get(url, params=request_params, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") != 200:
                print(f"[Processed API] {category} 返回错误: {result.get('message')}")
                return None
            
            data = result.get("data")
            data_info = len(data) if isinstance(data, list) else '对象'
            print(f"[Processed API] {category} 成功，返回 {data_info} 数据")
            return data
            
        except requests.exceptions.Timeout:
            print(f"[Processed API] {category} 超时 (attempt {attempt + 1}/{retries})")
        except requests.exceptions.ConnectionError as e:
            print(f"[Processed API] {category} 连接错误: {e} (attempt {attempt + 1}/{retries})")
        except Exception as e:
            print(f"[Processed API] {category} 错误: {e} (attempt {attempt + 1}/{retries})")
        
        if attempt < retries - 1:
            time.sleep(1)
    
    print(f"[Processed API] {category} 所有重试失败")
    return None


def _quote_request(endpoint: str, params: dict | None = None, retries: int = 3) -> dict | list | None:
    """调用行情源直连接口 (/api/quote/* 等专用接口，更稳定)
    
    Args:
        endpoint: 接口路径，如 "quote/realtime", "quote/kline"
        params: 请求参数
        retries: 重试次数
    
    Returns:
        API 返回的数据，失败返回 None
    """
    url = f"{AKSHARE_API_BASE}/api/{endpoint}"
    
    # 自动添加 source=auto 参数（如果未指定）
    request_params = params.copy() if params else {}
    if "source" not in request_params:
        request_params["source"] = "auto"
    
    for attempt in range(retries):
        try:
            print(f"[Quote API] 调用 {endpoint} (尝试 {attempt + 1}/{retries})...")
            response = get_session().get(url, params=request_params, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") != 200:
                print(f"[Quote API] {endpoint} 返回错误: {result.get('message')}")
                return None
            
            data = result.get("data")
            data_info = len(data) if isinstance(data, list) else '对象'
            print(f"[Quote API] {endpoint} 成功，返回 {data_info} 数据")
            return data
            
        except requests.exceptions.Timeout:
            print(f"[Quote API] {endpoint} 超时 (attempt {attempt + 1}/{retries})")
        except requests.exceptions.ConnectionError as e:
            print(f"[Quote API] {endpoint} 连接错误: {e} (attempt {attempt + 1}/{retries})")
        except Exception as e:
            print(f"[Quote API] {endpoint} 错误: {e} (attempt {attempt + 1}/{retries})")
        
        if attempt < retries - 1:
            time.sleep(1)
    
    print(f"[Quote API] {endpoint} 所有重试失败")
    return None


def _fetch_real_kline(method: str, params: dict, count: int = 50) -> list[dict]:
    """从 AkShare 获取真实 K 线并映射为 {date,open,close,high,low,volume}（兼容中英文列名）"""
    df = _akshare_request(method, params)
    if not df or not isinstance(df, list):
        return []
    out = []
    for row in df:
        date = row.get("date") or row.get("日期")
        o = row.get("open") or row.get("开盘")
        c = row.get("close") or row.get("收盘")
        h = row.get("high") or row.get("最高")
        l = row.get("low") or row.get("最低")
        v = row.get("volume") or row.get("成交量")
        if not date or c is None:
            continue
        out.append({
            "date": str(date)[:10],
            "open": _safe_float(o, 0.0),
            "close": _safe_float(c, 0.0),
            "high": _safe_float(h, 0.0),
            "low": _safe_float(l, 0.0),
            "volume": _safe_int(v, 0),
        })
    return out[-count:] if count else out


def _filter_by_date_range(
    points: list[dict],
    start_date: str | None,
    end_date: str | None,
) -> list[dict]:
    """Filter K-line points by an optional [start_date, end_date] range."""
    if not start_date and not end_date:
        return points
    result = points
    if start_date:
        result = [p for p in result if p["date"] >= start_date]
    if end_date:
        result = [p for p in result if p["date"] <= end_date]
    return result


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为 float"""
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _safe_float_or_none(value: Any) -> float | None:
    """安全转换为 float，缺失时保留 None（不伪造为 0，前端显示"—"）"""
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    """安全转换为 int"""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _calc_change(latest_price: float | None, chg_pct: float | None) -> float:
    """由最新价与涨跌幅反算涨跌额: change = latest * chg / (100 + chg)

    上游 index_valuation 只给 latest_price + chg_pct，不给前收盘价/涨跌额，故反算。
    """
    if not latest_price or chg_pct is None:
        return 0.0
    if 100 + chg_pct == 0:
        return 0.0
    return round(latest_price * chg_pct / (100 + chg_pct), 2)


# 北京时区（UTC+8），A股交易时间以此为基准
_CST = timezone(timedelta(hours=8))


def _market_status(now: datetime | None = None) -> str:
    """根据当前时间返回 A 股市场交易状态。

    始终使用北京时间（UTC+8）判断，避免服务器时区非 CST 导致状态错误。
    """
    now = now or datetime.now(_CST)
    if now.weekday() >= 5:  # 周六/周日
        return "休市"
    t = now.hour * 60 + now.minute
    # 上午盘 09:30-11:30，下午盘 13:00-15:00
    if (9 * 60 + 30 <= t < 11 * 60 + 30) or (13 * 60 <= t < 15 * 60):
        return "开盘中"
    if 11 * 60 + 30 <= t < 13 * 60:
        return "午间休市"
    return "已收盘"


# ============================================================
# 真实数据获取函数 (通过 AkShare WebAPI)
# ============================================================

def get_realtime_indices() -> list[dict]:
    """获取实时指数行情 - 使用 /api/processed_data/index_valuation 接口（一次获取全部指数+估值）
    
    返回12个主要指数的实时行情、PE/PB、百分位等数据
    """
    print("[Index] 使用 processed_data/index_valuation 获取指数数据...")
    data = _processed_data_request("index_valuation", {"subtype": "all", "period": 5}, retries=1, timeout=15)
    
    if not data or not isinstance(data, list):
        print("[Index] 获取失败，返回空列表")
        return []
    
    # 映射字段格式
    indices = []
    for item in data:
        indices.append({
            "name": item.get("index_name", ""),
            "code": _get_index_code(item.get("index_name", "")),
            "price": 0,  # index_valuation 不返回价格，需要单独获取
            "change": 0,
            "changePct": _safe_float(item.get("chg_pct")),
            "pe": _safe_float(item.get("pe")),
            "pb": _safe_float(item.get("pb")),
            "pePercentile": _safe_float(item.get("pe_percentile")),
            "pbPercentile": _safe_float(item.get("pb_percentile")),
            "category": item.get("category", ""),
            "change3mPct": _safe_float(item.get("3m_change_pct")),
            "winRate": _safe_float(item.get("win_rate")),
        })
    
    print(f"[Index] 成功获取 {len(indices)} 个指数估值数据")
    return indices


def _get_index_code(name: str) -> str:
    """根据指数名称获取代码"""
    mapping = {
        "上证指数": "000001",
        "深证成指": "399001",
        "创业板指": "399006",
        "上证50": "000016",
        "沪深300": "000300",
        "上证380": "000009",
        "创业板50": "399673",
        "中证500": "000905",
        "上证180": "000010",
        "深证红利": "399324",
        "深证100": "399330",
        "中证1000": "000852",
        "上证红利": "000015",
        "中证100": "000903",
        "中证800": "000906",
        "中证A500": "000510",
        "科创50": "000688",
        # ⚠️ 000699 在腾讯行情里名称是「科创200」，不是科创综指！
        # 科创综指=000680、科创50=000688、科创200=000699（2026-10-13 腾讯名称实证）
        "科创综指": "000680",
        "科创板": "000680",
        "科创200": "000699",
        "北证50": "899050",
    }
    return mapping.get(name, "")


# A股大盘看板期望展示的核心宽基/市场指数（按展示顺序）
_A_SHARE_OVERVIEW_INDICES = [
    ("上证指数", "000001"),
    ("深证成指", "399001"),
    ("创业板指", "399006"),
    ("沪深300", "000300"),
    ("中证500", "000905"),
    ("中证1000", "000852"),
    ("中证A500", "000510"),
    ("上证50", "000016"),
    ("科创50", "000688"),
    ("科创综指", "000680"),
    ("深证100", "399330"),
    ("北证50", "899050"),
]


def _fetch_index_quote(code: str) -> dict | None:
    """从行情直连接口获取单个指数实时快照

    返回: {"name": ..., "code": ..., "price": ..., "change": ..., "changePct": ...}
    """
    if not code:
        return None
    try:
        raw = _quote_request("quote/realtime", {"code": code, "type": "index", "source": "auto"}, retries=1)
        if not raw or not isinstance(raw, dict):
            return None
        return {
            "name": raw.get("name", ""),
            "code": code,
            "price": _safe_float(raw.get("latest_price")),
            "change": _safe_float(raw.get("price_change")),
            "changePct": _safe_float(raw.get("price_change_pct")),
        }
    except Exception as e:
        print(f"[Index Quote] 获取 {code} 实时行情失败: {e}")
        return None


def _ensure_overview_indices(indices: list[dict]) -> list[dict]:
    """补齐/替换大盘看板指数：剔除无数据的上证380，确保科创综指/科创50/中证A500等存在"""
    by_code: dict[str, dict] = {}
    for idx in indices:
        c = idx.get("code", "")
        if c and c not in by_code:
            by_code[c] = idx

    result = []
    for name, code in _A_SHARE_OVERVIEW_INDICES:
        if code in by_code:
            item = by_code[code]
            # 使用期望展示名称（统一为 _A_SHARE_OVERVIEW_INDICES 的规范名）
            item["name"] = name
            result.append(item)
        else:
            # 缺失时尝试实时行情补录
            quote = _fetch_index_quote(code)
            # 跳过无实时行情的指数（如北证50 上游未返回名称/价格）
            if not quote or not quote.get("name") or quote.get("price") in (None, 0):
                continue
            quote["name"] = name
            # 实时行情补录的指数无估值数据，置 None 让前端显示 '—'
            quote["pe"] = None
            quote["pb"] = None
            quote["pePercentile"] = None
            quote["pbPercentile"] = None
            quote.setdefault("category", "")
            # 无历史序列可算的派生指标一律置 None（前端显示"—"），绝不伪造 0
            quote["change3mPct"] = None
            quote["winRate"] = None
            quote["hasValuation"] = False
            result.append(quote)
    return result


def get_board_sectors_real() -> list[dict]:
    """获取板块涨幅数据 - 使用 /api/processed_data/board (industry_spot) 接口

    说明：board 的 concept_list 仅返回 名称/代码，无涨跌幅；
    实时涨跌幅/领涨股在 industry_spot（含 涨跌幅/上涨家数/下跌家数/领涨股/领涨股-涨跌幅）。
    按涨跌幅降序取前 6 个行业板块。
    """
    print("[Board Sector] 使用 processed_data/board(industry_spot) 获取行业板块...")
    data = _processed_data_request("board", {"subtype": "industry_spot"}, retries=2, timeout=10)

    if not data or not isinstance(data, list):
        print("[Board Sector] 获取失败，返回空列表")
        return []

    # 按涨跌幅降序
    data = sorted(data, key=lambda x: _safe_float(x.get("涨跌幅")), reverse=True)

    sectors = []
    for i, item in enumerate(data[:6]):
        sectors.append({
            "rank": i + 1,
            "name": item.get("板块", ""),
            "code": "",
            "price": 0,
            "change": 0,
            "changePct": _safe_float(item.get("涨跌幅")),
            "upCount": _safe_int(item.get("上涨家数")),
            "downCount": _safe_int(item.get("下跌家数")),
            "leadingStock": item.get("领涨股") or "",
            "leadingStockChange": _safe_float(item.get("领涨股-涨跌幅")),
            "type": "industry",
        })

    print(f"[Board Sector] 成功获取 {len(sectors)} 个板块")
    return sectors


def get_fund_flows_real() -> dict | None:
    """获取资金流向数据 - 使用 /api/processed_data/fund_flow 接口。

    降级策略：东财主力净流入(53 上 fund_flow 源不可用)失败时，改用 53 真实可用的
    板块涨跌幅(board-sectors)填充行业排名（changePct 为真实数据；inflow 为东财专有
    指标、无替代源，置 null 由前端标注不可用）。
    """
    print("[Fund Flow] 使用 processed_data/fund_flow 获取市场资金流向...")
    data = _processed_data_request("fund_flow", {"subtype": "market"}, retries=2, timeout=10)

    if not data or not isinstance(data, list) or len(data) == 0:
        # 东财主力净流入(大盘级)源不可用 → 降级：53 board/industry_spot 含真实行业级
        # 净流入/涨跌幅，可填充行业排名；大盘主力净流入为东财专有，无替代源置 null。
        print("[Fund Flow] 东财主力净流入不可用，降级到板块行业净流入排名(board_proxy)")
        industry_raw = _processed_data_request("board", {"subtype": "industry_spot"}, retries=1, timeout=10)
        industry_flows = []
        if industry_raw and isinstance(industry_raw, list):
            for item in industry_raw[:5]:
                industry_flows.append({
                    "name": item.get("板块", ""),
                    "inflow": _safe_float(item.get("净流入")),
                    "inflowPct": None,
                    "changePct": _safe_float(item.get("涨跌幅")),
                })
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "date": today,
            "mainInflow": None, "mainInflowPct": None,
            "superLargeInflow": None, "superLargeInflowPct": None,
            "largeInflow": None, "largeInflowPct": None,
            "mediumInflow": None, "mediumInflowPct": None,
            "smallInflow": None, "smallInflowPct": None,
            "industryFlows": industry_flows,
            "source": "board_proxy",
            "mainFlowAvailable": False,
        }

    # 取最新一条数据
    row = data[0] if isinstance(data, list) else data

    # 获取行业资金流向排名
    industry_flow_data = _processed_data_request("fund_flow", {"subtype": "sector_rank", "indicator": "今日"}, retries=1, timeout=10)
    industry_flows = []
    if industry_flow_data and isinstance(industry_flow_data, list):
        for item in industry_flow_data[:5]:
            industry_flows.append({
                "name": item.get("名称", ""),
                "inflow": _safe_float(item.get("净流入")),
                "inflowPct": _safe_float(item.get("净流入占比")),
                "changePct": _safe_float(item.get("涨跌幅")),
            })

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[Fund Flow] 成功获取资金流向数据")
    return {
        "date": today,
        "mainInflow": _safe_float(row.get("主力净流入")),
        "mainInflowPct": _safe_float(row.get("主力净流入占比")),
        "superLargeInflow": _safe_float(row.get("超大单净流入")),
        "superLargeInflowPct": _safe_float(row.get("超大单净流入占比")),
        "largeInflow": _safe_float(row.get("大单净流入")),
        "largeInflowPct": _safe_float(row.get("大单净流入占比")),
        "mediumInflow": _safe_float(row.get("中单净流入")),
        "mediumInflowPct": _safe_float(row.get("中单净流入占比")),
        "smallInflow": _safe_float(row.get("小单净流入")),
        "smallInflowPct": _safe_float(row.get("小单净流入占比")),
        "industryFlows": industry_flows,
        "source": "eastmoney",
        "mainFlowAvailable": True,
    }


def get_zt_stats_real() -> dict | None:
    """获取涨跌停统计数据 - 使用 /api/processed_data/zt_pool 接口
    
    容灾链：新浪spot自算（非东财），更稳定
    """
    print("[ZT Pool] 使用 processed_data/zt_pool 获取涨跌停数据...")
    
    # 获取涨停池
    zt_data = _processed_data_request("zt_pool", {"subtype": "zt"}, retries=2, timeout=10)
    zt_list = []
    if zt_data and isinstance(zt_data, list):
        for row in zt_data[:10]:
            zt_list.append({
                "code": row.get("代码", ""),
                "name": row.get("名称", ""),
                "price": _safe_float(row.get("最新价")),
                "changePct": _safe_float(row.get("涨跌幅")),
                "turnover": _safe_float(row.get("成交额")) / 100000000 if row.get("成交额") else 0,
                "marketCap": 0,  # 接口不返回市值
                "firstZtTime": "",
                "lastZtTime": "",
                "炸板次数": 0,
                "连板数": _safe_int(row.get("连板数")),
                "industry": "",
            })
    
    # 获取跌停池
    dt_data = _processed_data_request("zt_pool", {"subtype": "dt"}, retries=1, timeout=10)
    dt_list = []
    if dt_data and isinstance(dt_data, list):
        for row in dt_data[:10]:
            dt_list.append({
                "code": row.get("代码", ""),
                "name": row.get("名称", ""),
                "price": _safe_float(row.get("最新价")),
                "changePct": _safe_float(row.get("涨跌幅")),
                "turnover": _safe_float(row.get("成交额")) / 100000000 if row.get("成交额") else 0,
                "marketCap": 0,
                "continuousDt": 0,
                "industry": "",
            })
    
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[ZT Pool] 成功获取 {len(zt_list)} 涨停, {len(dt_list)} 跌停")
    
    return {
        "date": today,
        "ztCount": len(zt_data) if isinstance(zt_data, list) else 0,
        "dtCount": len(dt_data) if isinstance(dt_data, list) else 0,
        "prevZTPerformance": {
            "avgChange": 0.0,
            "topPerformer": "",
            "topPerformerChange": 0.0,
        },
        "ztList": zt_list,
        "dtList": dt_list,
    }


def get_fund_ranking_real() -> list[dict]:
    """获取基金排行数据 - 使用 /api/processed_data/fund_rank 接口
    
    容灾链：新浪ETF基金 → 同花顺 fund_etf_spot_ths（非东财）
    """
    print("[Fund Rank] 使用 processed_data/fund_rank 获取ETF排行...")
    data = _processed_data_request("fund_rank", {"subtype": "etf"}, retries=2, timeout=10)
    
    if not data or not isinstance(data, list):
        print("[Fund Rank] 获取失败，返回空列表")
        return []
    
    funds = []
    for i, row in enumerate(data[:10]):
        funds.append({
            "rank": i + 1,
            "code": row.get("代码", ""),
            "name": row.get("名称", ""),
            "type": "ETF",
            "nav": _safe_float(row.get("最新价")),
            "changePct": _safe_float(row.get("涨跌幅")),
            "change": 0,  # 接口不返回涨跌额
            "volume": _safe_int(row.get("成交额")),
            "premiumPct": None,
        })
    
    print(f"[Fund Rank] 成功获取 {len(funds)} 个ETF")
    return funds


# ============================================================
# 每日成交额快照（本地落库，用于"较上一日"对比）
# 上游 market_stats 不一定返回 yesterday_same_time_turnover，
# 故每次拉取市场概况时把当天成交额 upsert 入表，作为"上一日成交额"的可靠来源。
# 说明：我们只存每个交易日一行（当天最新累计值覆盖），因此"较上一日此时"实为
# 今日实时累计 vs 上一交易日全天总额——这是没有分时历史时最合理的近似。
# ============================================================
_TURNOVER_TABLE_READY = False
_TURNOVER_UPSERT_SQL = """
INSERT INTO base_market_turnover_daily (trade_date, total_turnover, sh_turnover, sz_turnover, captured_at)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (trade_date) DO UPDATE SET
    total_turnover = excluded.total_turnover,
    sh_turnover    = excluded.sh_turnover,
    sz_turnover    = excluded.sz_turnover,
    captured_at    = excluded.captured_at
"""


def _ensure_turnover_table() -> None:
    global _TURNOVER_TABLE_READY
    if _TURNOVER_TABLE_READY:
        return
    try:
        from database.connection import get_db

        db = get_db()
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS base_market_turnover_daily (
                trade_date      DATE PRIMARY KEY,
                total_turnover  BIGINT,
                sh_turnover     BIGINT,
                sz_turnover     BIGINT,
                captured_at     TIMESTAMP
            )
            """
        )
        _TURNOVER_TABLE_READY = True
    except Exception as e:
        print(f"[Turnover] 建表失败: {type(e).__name__}: {e}")


def _save_today_turnover(
    trade_date: str,
    total_yuan: float | None,
    sh_yuan: float | None,
    sz_yuan: float | None,
) -> None:
    """把当天成交额 upsert 入 base_market_turnover_daily（同日期覆盖）。"""
    if total_yuan is None:
        return
    try:
        _ensure_turnover_table()
        from database.connection import get_db

        db = get_db()
        db.execute(
            _TURNOVER_UPSERT_SQL,
            [
                trade_date,
                int(total_yuan),
                int(sh_yuan) if sh_yuan is not None else None,
                int(sz_yuan) if sz_yuan is not None else None,
                datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
            ],
        )
    except Exception as e:
        print(f"[Turnover] 落库失败: {type(e).__name__}: {e}")


def _get_prev_trading_day_turnover(trade_date: str) -> float | None:
    """返回上一交易日的成交额（元），用于"较上一日"对比；无记录返回 None。"""
    try:
        _ensure_turnover_table()
        from database.connection import get_db

        db = get_db()
        row = db.fetchone(
            "SELECT total_turnover FROM base_market_turnover_daily "
            "WHERE trade_date < ? ORDER BY trade_date DESC LIMIT 1",
            [trade_date],
        )
        if row and row[0] is not None:
            return float(row[0])
    except Exception as e:
        print(f"[Turnover] 查询上一交易日失败: {type(e).__name__}: {e}")
    return None


def get_market_stats_real() -> dict | None:
    """获取市场统计数据 - 使用 /api/processed_data/market_stats 接口
    
    返回：总成交额、涨跌家数、涨跌停数等
    """
    print("[Market Stats] 使用 processed_data/market_stats 获取市场统计...")
    data = _processed_data_request("market_stats", {"subtype": "overview"}, retries=2, timeout=10)
    
    if not data or not isinstance(data, dict):
        print("[Market Stats] 获取失败")
        return None
    
    print(f"[Market Stats] 成功获取市场统计")
    # 上游返回成交额单位为"元"，统一转换为"亿元"(1亿 = 10^8 元)
    total_yuan = _safe_float(data.get("total_turnover"))
    sh_yuan = _safe_float(data.get("sh_turnover"))
    sz_yuan = _safe_float(data.get("sz_turnover"))
    yest_yuan = _safe_float(data.get("yesterday_same_time_turnover")) if data.get("yesterday_same_time_turnover") is not None else None
    total_e = round(total_yuan / 1e8, 2) if total_yuan else 0.0
    sh_e = round(sh_yuan / 1e8, 2) if sh_yuan else 0.0
    sz_e = round(sz_yuan / 1e8, 2) if sz_yuan else 0.0

    today = data.get("date") or datetime.now(_CST).strftime("%Y-%m-%d")

    # 每天把当天成交额落库，作为"上一日成交额"的可靠本地来源
    # （上游 market_stats 不保证返回 yesterday_same_time_turnover）
    _save_today_turnover(today, total_yuan, sh_yuan, sz_yuan)

    # 上游未提供"上一日此时"成交额 → 用本地存的上一交易日总额补充
    prev_day_yuan = None
    if yest_yuan is None:
        yest_yuan = _get_prev_trading_day_turnover(today)
        if yest_yuan is not None:
            prev_day_yuan = yest_yuan

    turnover_change_abs = None
    if yest_yuan is not None and yest_yuan > 0:
        turnover_change_abs = round((total_yuan - yest_yuan) / 1e8, 2)
    turnover_change_pct = _safe_float_or_none(data.get("turnover_change_pct"))
    if turnover_change_pct is None and yest_yuan and yest_yuan > 0 and total_yuan:
        turnover_change_pct = round((total_yuan - yest_yuan) / yest_yuan * 100, 2)

    return {
        "date": today,
        "totalTurnover": total_e,
        "shTurnover": sh_e,
        "szTurnover": sz_e,
        "turnoverChangePct": turnover_change_pct,
        "turnoverChangeAbs": turnover_change_abs,
        "prevDayTurnover": round(prev_day_yuan / 1e8, 2) if prev_day_yuan else None,
        "upCount": _safe_int(data.get("advance_count")),
        "downCount": _safe_int(data.get("decline_count")),
        "flatCount": _safe_int(data.get("flat_count")),
        "limitUpCount": _safe_int(data.get("limit_up_count")),
        "limitDownCount": _safe_int(data.get("limit_down_count")),
    }


# ============================================================
# 主接口函数
# ============================================================

def _build_meta(is_mock: bool, data_source: str) -> dict[str, Any]:
    """构建数据来源标记（随 ApiResponse.meta 返回，供前端"模拟/真实数据"横幅展示）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "isMock": is_mock,
        "dataSource": data_source,
        "mockTime": now if is_mock else None,
        "updateTime": now if not is_mock else None,
    }


# 宏观指标缓存(1小时)：DR007/GC001/ERP 日内变化小，避免每次刷新都打 AkShare
_MACRO_CACHE: dict = {"data": None, "ts": 0, "ttl": 0, "lock": threading.Lock()}
_MACRO_TTL = 3600
# ERP 缺失通常只是 10Y 国债历史还在后台刷新，此时用短 TTL，
# 避免把「不完整结果」按 1 小时缓存住，导致刷新完成后还要等满 1 小时才生效。
_MACRO_TTL_INCOMPLETE = 60

# 申万一级行业缓存（2026-10-08 新增）
# ⚠️ 为什么加：实测 `GET /api/v1/market/sw-sectors` **每次调用固定 ~20s**
#   （两次连测20.07s / 20.02s，确认是真在重拉而非偶发），而该接口被
#   **Dashboard.vue（首页）** 使用 → 每次打开首页都要干等 20 秒。
#   原因是它每次都打 2 个上游（index_realtime_sw + sw_index_first_info）且**无缓存**。
#   行业数据日内变化有限，缓存 10 分钟足够；「刷新」按钮仍走 force=True 穿透。
_SW_SECTORS_CACHE: dict = {"data": None, "ts": 0.0, "lock": threading.Lock(), "fail": False}
_SW_SECTORS_TTL = 600
#: 上游拿不到时的短缓存（秒）—— 失败不该被缓存 10 分钟，但也不该让首页每次白等
_SW_SECTORS_TTL_FAIL = 30


# ---------------------------------------------------------------------------
# market/overview 进程内缓存（2026-10-17 P2-3，与 sw-sectors 同款模式）
# ---------------------------------------------------------------------------
# ⚠️ 为什么加：`get_market_overview_with_meta` 每次串行打 2 个**无缓存**上游
#   （index_valuation timeout=15s + market_stats timeout=10s×2 retries），
#   实测 Dashboard 首屏固定 4.6-5.0s。盘中估值/统计日内变化有限，用户
#   2026-10-17 明确接受 5-10 分钟时效性 → 缓存 10 分钟；失败态 30s 短
#   TTL 防错误数据锁死；「刷新」按钮 force=True 穿透（同 sw-sectors）。
#   缓存对象为 (data, meta) 二元组——meta 含 updateTime，一并缓存保持
#   前端时间 chip 语义不变。
_MARKET_OVERVIEW_CACHE: dict = {"data": None, "meta": None, "ts": 0.0, "lock": threading.Lock(), "fail": False}
_MARKET_OVERVIEW_TTL = 600
#: 上游拿不到时的短缓存（秒）—— 失败不该被缓存 10 分钟，但也不该让首页每次白等
_MARKET_OVERVIEW_TTL_FAIL = 30


def _compute_erp() -> tuple[float | None, float | None, float | None, float | None]:
    """股权风险溢价 ERP = 1/CSI300PE_TTM - 10Y 国债收益率；并计算 3Y/5Y/10Y 历史分位

    Returns: (erp_current, pct_3y, pct_5y, pct_10y)，任一不可得为 None
    """
    pe_hist = _akshare_request("stock_index_pe_lg", {"symbol": "沪深300"})
    if not pe_hist:
        return None, None, None, None

    # 10Y 中债国债收益率: 分段(<1年/次, akshare 限制)拉取历史, 日期 -> 值
    yld_map = _fetch_10y_history()
    if not yld_map:
        return None, None, None, None

    # 按日期升序对齐，用指针找"不晚于该日"的最近收益率
    pe_sorted = sorted(
        (str(r.get("日期", ""))[:10], _safe_float(r.get("滚动市盈率"), None))
        for r in pe_hist
        if str(r.get("日期", ""))[:10] and _safe_float(r.get("滚动市盈率"), None)
    )
    yld_items = sorted(yld_map.items())  # (date, rate) 升序
    erp_series: list[tuple[str, float]] = []
    yi = 0
    for d, pe in pe_sorted:
        if pe <= 0:
            continue
        while yi < len(yld_items) - 1 and yld_items[yi + 1][0] <= d:
            yi += 1
        rate = yld_items[yi][1] if yld_items[yi][0] <= d else None
        if rate is None:
            continue
        erp_series.append((d, 1.0 / pe * 100 - rate))

    if not erp_series:
        return None, None, None, None

    cur_date, cur_erp = erp_series[-1]

    def _pct(series_vals: list[tuple[str, float]], years: int) -> float | None:
        if years:
            cutoff = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")
            vals = [v for d, v in series_vals if d >= cutoff]
        else:
            vals = [v for _, v in series_vals]
        if not vals:
            return None
        below = sum(1 for v in vals if v <= cur_erp)
        return round(below / len(vals) * 100, 2)

    return cur_erp, _pct(erp_series, 3), _pct(erp_series, 5), _pct(erp_series, 10)


# 10Y 国债收益率历史缓存。
# 实测网关单次 bond_china_yield 约 12s，拉满 10 年要分 10 段 ≈ 2 分钟，
# 绝不能放在请求线程里同步拉（会长时间占住 AnyIO 工作线程）。
# 改为：命中缓存直返；未命中则后台线程刷新，本次先返回已有数据（首次可能为空）。
_10Y_CACHE: dict = {"data": None, "ts": 0, "loading": False, "lock": threading.Lock()}
_10Y_TTL = 6 * 3600  # 10 年国债历史日内变化极小，缓存 6 小时

# 落盘路径（doraemon 持久卷）：进程重启后直接从磁盘恢复，
# 免去每次冷启动都要分段拉 10 年历史（约 90s，会把宽基估值接口拖超时）。
_10Y_CACHE_FILE = os.environ.get("VALUATION_CACHE_DIR", "/data/valuation_cache") + "/10y_history.json"


def _10y_load_disk() -> dict | None:
    """从磁盘恢复 10Y 国债历史 {date: rate}，失败/为空返回 None。"""
    try:
        with open(_10Y_CACHE_FILE, "r", encoding="utf-8") as f:
            rec = json.load(f)
        data = rec.get("data") or {}
        return data if data else None
    except Exception:
        return None


def _10y_save_disk(data: dict) -> None:
    """原子落盘 10Y 国债历史。"""
    try:
        d = os.path.dirname(_10Y_CACHE_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = _10Y_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "data": data}, f)
        os.replace(tmp, _10Y_CACHE_FILE)
    except Exception as e:  # noqa: BLE001
        print(f"[10Y] 落盘失败: {e}")


def _fetch_10y_history() -> dict[str, float]:
    """10 年中债国债收益率历史 {date: rate}。

    命中缓存直接返回；未命中则触发后台刷新并返回当前已有数据（首次为空）。
    进程重启后优先从磁盘恢复，避免冷启动空窗期。
    """
    now = time.time()
    with _10Y_CACHE["lock"]:
        if _10Y_CACHE["data"] is None:
            disk = _10y_load_disk()
            if disk:
                _10Y_CACHE["data"] = disk
                # 视为“快要过期”：立即对外可用，同时很快会由后台线程刷新到最新
                _10Y_CACHE["ts"] = now - _10Y_TTL + 300
                print(f"[10Y] 从磁盘恢复 {len(disk)} 个交易日")
        if _10Y_CACHE["data"] is not None and (now - _10Y_CACHE["ts"]) < _10Y_TTL:
            return _10Y_CACHE["data"]
        if _10Y_CACHE["loading"]:
            return _10Y_CACHE["data"] or {}
        _10Y_CACHE["loading"] = True

    def _bg() -> None:
        try:
            data = _fetch_10y_history_uncached()
            if data:
                with _10Y_CACHE["lock"]:
                    _10Y_CACHE["data"] = data
                    _10Y_CACHE["ts"] = time.time()
                    _10Y_CACHE["loading"] = False
                _10y_save_disk(data)
                print(f"[10Y] 后台刷新完成，{len(data)} 个交易日")
                return
        except Exception as e:  # noqa: BLE001
            print(f"[10Y] 后台刷新异常: {e}")
        with _10Y_CACHE["lock"]:
            _10Y_CACHE["loading"] = False

    threading.Thread(target=_bg, daemon=True).start()
    return _10Y_CACHE["data"] or {}


def _fetch_10y_history_uncached() -> dict[str, float]:
    """分段(<1年/次, akshare bond_china_yield 限制)拉取中债10Y国债收益率历史。

    两处修正：
      - 超时 6s → 25s：网关实测单次约 12s，原来 6s 必然每次超时；
      - 分段上限 3 → 11 → 20：原来只拉 3 年却要算 10 年分位，结果本身就是错的；现窗口扩到 15 年（数据下界 2008），覆盖 2011 起含 2015/2018/2022 周期。

    网关 bond_china_yield 上游对连续请求不稳定（实测连拉数段后连续 502），因此再加：
      - **增量续传**：以上次落盘的部分历史为底，只补缺失的年份段；后台刷新反复执行
        可逐步补全，不再"一段失败就整年缺失到下个周期"；
      - **段间 1s 间隔 + 失败段重试一次**（间隔 3s），降低被上游连发拒绝的概率。

    Returns: {date: rate}，取数全失败返回空 dict
    """
    end = datetime.now()
    # 窗口扩到 15 年：网关 bond_china_yield 单年分段实测可拉到 2008 起，数据下界即 2008；
    # 15 年窗口覆盖 2011 起，含 2015/2018/2022 周期，稳健超过「尽量到10年」目标。
    start = end.replace(year=end.year - 15)
    result: dict[str, float] = {}
    # 增量续传：合并上次落盘的部分历史
    try:
        result.update(_10y_load_disk() or {})
    except Exception:
        pass

    cur = start
    attempts = 0
    while cur < end and attempts < 20:
        attempts += 1
        nxt = min(cur.replace(year=cur.year + 1), end)
        sd = cur.strftime("%Y%m%d")
        ed = nxt.strftime("%Y%m%d")
        # 该段已有足够数据 → 跳过（增量续传，避免对不稳定上游重复施压）。
        # 注意必须统计段内日期数而非仅判存在：上段末尾的边界日期（如 2025-09-28）
        # 会落入下一段区间，仅判存在会把只差一两天的段误判为已完成。
        sd_norm = f"{sd[:4]}-{sd[4:6]}-{sd[6:]}"
        ed_norm = f"{ed[:4]}-{ed[4:6]}-{ed[6:]}"
        covered = sum(1 for d in result if sd_norm < d <= ed_norm)
        if covered >= 100:  # 一年约 250 个交易日，100 视为该段已基本取全
            cur = nxt
            continue
        df = None
        for seg_attempt in range(2):  # 每段最多 2 次尝试
            if seg_attempt:
                time.sleep(3)
            df = _akshare_request("bond_china_yield", {"start_date": sd, "end_date": ed}, retries=1, timeout=25)
            if df and isinstance(df, list):
                break
        if df and isinstance(df, list):
            for row in df:
                d = str(row.get("日期", ""))[:10]
                v = _safe_float(row.get("10年"), None)
                if d and v is not None:
                    result[d] = v
        time.sleep(1)  # 段间 1s 间隔
        cur = nxt
    return result


def get_macro_indicators_with_meta() -> tuple[dict, dict]:
    """宏观指标（DR007 / GC001 / ERP）— 全部来自 AkShare 真实数据，取数失败返回空(不再伪造)"""
    if USE_MOCK_DATA:
        return {k: v for k, v in mock_data.MOCK_MACRO_DATA.items() if k in ("erp", "erp_percentile_3y", "erp_percentile_5y", "erp_percentile_10y", "dr007", "gc001")}, _build_meta(True, "MOCK(模拟数据)")
    now = time.time()
    with _MACRO_CACHE["lock"]:
        cached_ttl = _MACRO_CACHE.get("ttl") or _MACRO_TTL
        if _MACRO_CACHE["data"] is not None and (now - _MACRO_CACHE["ts"]) < cached_ttl:
            return _MACRO_CACHE["data"], _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")

    result: dict = {}
    # DR007(银行间7天质押式回购, 存款类) + GC001(akshare 无直采, 取存款类1天回购 FDR001 作近似实时利率)
    dr = _akshare_request("repo_rate_query", {"symbol": "DR007"})
    if dr and isinstance(dr, list) and len(dr) > 0:
        last = dr[-1]
        result["dr007"] = _safe_float(last.get("FDR007"), None)
        result["gc001"] = _safe_float(last.get("FDR001"), None)

    # ERP 及其历史分位
    erp, p3, p5, p10 = _compute_erp()
    if erp is not None:
        result["erp"] = round(erp, 2)
        result["erp_percentile_3y"] = p3
        result["erp_percentile_5y"] = p5
        result["erp_percentile_10y"] = p10

    if not result:
        return {}, gateway_no_data_meta()

    # ERP 缺失多半是 10Y 历史尚未就绪，用短 TTL 让它尽快重试
    ttl = _MACRO_TTL if result.get("erp") is not None else _MACRO_TTL_INCOMPLETE
    with _MACRO_CACHE["lock"]:
        _MACRO_CACHE["data"] = result
        _MACRO_CACHE["ts"] = time.time()
        _MACRO_CACHE["ttl"] = ttl
    return result, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")


def get_market_overview_with_meta(force: bool = False) -> tuple[dict, dict]:
    """市场概况：指数行情 + 涨跌家数 + 成交额。

    ⚠️ 带 10 分钟进程内缓存（2026-10-17 P2-3，与 sw-sectors 同款模式）：
    未命中缓存时透传 ``force`` 给底层取数并刷新缓存；命中直接返回
    (data, meta) 二元组。失败态（indices 为空）走 30s 短 TTL。
    """
    if not force:
        with _MARKET_OVERVIEW_CACHE["lock"]:
            c = _MARKET_OVERVIEW_CACHE
            if c["data"] is not None:
                age = time.time() - c["ts"]
                ttl = _MARKET_OVERVIEW_TTL_FAIL if c.get("fail") else _MARKET_OVERVIEW_TTL
                if age <= ttl:
                    return c["data"], c["meta"]
    data, meta = _get_market_overview_uncached()
    ok = bool(data.get("indices"))
    with _MARKET_OVERVIEW_CACHE["lock"]:
        c = _MARKET_OVERVIEW_CACHE
        c["data"] = data
        c["meta"] = meta
        c["ts"] = time.time()
        c["fail"] = not ok
    return data, meta


def _get_market_overview_uncached() -> tuple[dict, dict]:
    """market/overview 无缓存原始实现（缓存包装见 get_market_overview_with_meta）。"""
    if USE_MOCK_DATA:
        return mock_data.MOCK_MACRO_DATA["marketOverview"], _build_meta(True, "MOCK(模拟数据)")
    realtime_indices, _ = _fetch_index_valuation_data()
    market_stats = get_market_stats_real()

    if market_stats:
        # 成交额变化统一使用绝对值(亿元)：上游提供昨日成交额则直接相减；
        # 只有百分比时，按当前成交额反推近似绝对变化；都没有则返回 None（前端显示"—"）。
        total_e = market_stats.get("totalTurnover", 0) or 0
        vol_change = market_stats.get("turnoverChangeAbs")
        if vol_change is None:
            pct = market_stats.get("turnoverChangePct")
            if pct is not None and total_e:
                # pct 相对昨日成交额，正确反推：abs = total * pct / (100 + pct)
                vol_change = round(total_e * pct / (100 + pct), 2)
            # pct 也为 None → 上游未提供变化数据，保持 None
        data = {
            "date": market_stats["date"],
            "status": _market_status(),  # _market_status 内部已使用北京时间
            "indices": realtime_indices,
            "upCount": market_stats["upCount"],
            "downCount": market_stats["downCount"],
            "flatCount": market_stats["flatCount"],
            "totalVolume": market_stats["totalTurnover"],
            "volumeChange": vol_change,
            "prevDayVolume": market_stats.get("prevDayTurnover"),
        }
        return data, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")
    if realtime_indices:
        data = {
            "date": datetime.now(_CST).strftime("%Y-%m-%d"),
            "status": _market_status(),
            "indices": realtime_indices,
            "upCount": 0,
            "downCount": 0,
            "flatCount": 0,
            "totalVolume": 0,
            "volumeChange": 0,
            "prevDayVolume": None,
        }
        return data, _build_meta(False, "AkShare WebAPI (部分数据)")
    # 取数失败：返回空数据(绝不返回伪造数据)，前端走错误/空态
    return {
        "date": datetime.now(_CST).strftime("%Y-%m-%d"),
        "status": "数据获取中",
        "indices": [],
        "upCount": 0,
        "downCount": 0,
            "flatCount": 0,
            "totalVolume": 0,
            "volumeChange": 0,
            "prevDayVolume": None,
        }, gateway_no_data_meta()


def get_sw_sectors(force: bool = False) -> tuple[list[dict], dict]:
    """申万一级行业基础数据（实时涨跌幅 + PE / PB / 股息率），用于行业热力图。

    数据源：远程 AkShare WebAPI 网关（core.config.AKSHARE_API_BASE 的 /api/ak），不依赖本地 akshare。
      - ``index_realtime_sw(symbol='一级行业')`` 取 31 个申万一级行业实时价 → 计算涨跌幅；
      - ``sw_index_first_info()`` 取各行业的 PE / PB / 股息率 / 成份数。
    网关返回 list[dict]，无需 pandas。

    ⚠️ **带 10 分钟进程内缓存**（2026-10-08）：这两个上游合计要 ~20s，
    而本接口是**首页 Dashboard** 的数据源——原来每次打开首页都干等 20 秒。
    ``force=True``（点「刷新」）时穿透缓存。
    """
    if USE_MOCK_DATA:
        return [], _build_meta(True, "MOCK(模拟数据)")

    #缓存命中则直接返回（2026-08 新增）
    if not force:
        with _SW_SECTORS_CACHE["lock"]:
            if _SW_SECTORS_CACHE["data"] is not None:
                age = time.time() - _SW_SECTORS_CACHE["ts"]
                # 失败态用短 TTL，成功态用长 TTL
                ttl = _SW_SECTORS_TTL_FAIL if _SW_SECTORS_CACHE.get("fail") else _SW_SECTORS_TTL
                if age <= ttl:
                    return _SW_SECTORS_CACHE["data"]

    # 1) 实时一级行业（最新价 / 昨收盘）
    # ⚠️ 超时 8s → 30s（2026-10-16 修复热力图空数据）→ 45s（当日二次上调）：
    #   10-08 曾把超时压到 8s 防首页干等，但实测网关 `index_realtime_sw`
    #   稳定返回需 ~18s（源站申万接口慢），8s 永远超时 → 本函数永久走降级
    #   分支（code="" + change_pct=None）→ 前端热力图 31 格全部空 key 撞车、
    #   涨跌幅全空、全灰；同时 15:30 快照 job 自 10-13 起全部失败。
    #   10-16 下午复测网关耗时在 13.2s ~ 42.8s 之间大幅波动，30s 仍会
    #   间歇性超时 → 热力图间歇性退回 PE 降级态；上调到 45s 覆盖波动上限。
    #   现有 10 分钟进程内缓存（成功态）/ 30s 失败态兜底重复打开开销，
    #   不再需要为防干等而砍超时——取不到比等不到更糟。
    rt = _akshare_request("index_realtime_sw", {"symbol": "一级行业"}, timeout=45)

    # 2) 一级行业估值（PE / PB / 股息率 / 成份数）
    #⚠️ 放在 rt 判断**之前**（2026-10-08）：`index_realtime_sw` 挂掉时，
    #   `sw_index_first_info` 往往仍可用（实测返回 31 行）——原来 rt 空就
    #   直接 return，把能拿到的估值也一起丢了，白等 20s 还什么都拿不到。
    #   现在 rt 空时**用估值兜底**（无涨跌幅），至少热力图能显示 PE/PB。
    val_map: dict[str, dict] = {}
    try:
        first = _akshare_request("sw_index_first_info", timeout=8)
        if first:
            for row in first:
                val_map[row.get("行业名称")] = {
                    "count": _safe_int(row.get("成份个数")),
                    "pe": _safe_float(row.get("静态市盈率")),
                    "ttm_pe": _safe_float(row.get("TTM(滚动)市盈率")),
                    "pb": _safe_float(row.get("市净率")),
                    "dividend_yield": _safe_float(row.get("静态股息率")),
                }
    except Exception:
        val_map = {}  # 估值取不到不影响涨跌幅热力图

    if not rt:
        #上游实时行情拿不到 → 用估值数据兜底（至少 PE/PB 能显示），并短缓存
        sectors_fallback = [
            {
                "code": "",
                "name": name,
                "price": None,
                "prev_close": None,
                "change_pct": None,
                "pe": v.get("pe"),
                "ttm_pe": v.get("ttm_pe"),
                "pb": v.get("pb"),
                "dividend_yield": v.get("dividend_yield"),
                "count": v.get("count"),
            }
            for name, v in val_map.items()
        ]
        note = (
            f"网关 index_realtime_sw 无返回 ({AKSHARE_HOST})，已降级为仅估值数据"
            if sectors_fallback
            else f"网关 index_realtime_sw 无返回 ({AKSHARE_HOST})"
        )
        result = (sectors_fallback, _build_meta(False, note))
        # ⚠️ 上游拿不到时也要**短缓存失败态**：否则首页每次打开都要白等
        #   （该接口在 akshare-webapi 侧硬编码 30s 超时 + 重试 2 次）。
        with _SW_SECTORS_CACHE["lock"]:
            _SW_SECTORS_CACHE["data"] = result
            _SW_SECTORS_CACHE["ts"] = time.time()
            _SW_SECTORS_CACHE["fail"] = True
        return result

    rt_map: dict[str, dict] = {}
    for row in rt:
        name = row.get("指数名称")
        last = _safe_float(row.get("最新价"))
        prev = _safe_float(row.get("昨收盘"))
        chg = round((last - prev) / prev * 100, 2) if (last and prev) else None
        rt_map[name] = {
            "code": str(row.get("指数代码", "")),
            "price": last,
            "prev_close": prev,
            "change_pct": chg,
        }

    # 3) 合并（以实时行情为主，估值缺失则补 None）
    #    （第2 步的估值取数已上移到 rt 判断之前，以便实时行情挂掉时仍能兜底）
    sectors: list[dict] = []
    for name, rt_info in rt_map.items():
        v = val_map.get(name, {})
        sectors.append({
            "code": rt_info["code"],
            "name": name,
            "price": rt_info["price"],
            "prev_close": rt_info["prev_close"],
            "change_pct": rt_info["change_pct"],
            "pe": v.get("pe"),
            "ttm_pe": v.get("ttm_pe"),
            "pb": v.get("pb"),
            "dividend_yield": v.get("dividend_yield"),
            "count": v.get("count"),
        })

    # 将当日快照写入 DuckDB（同日去重）
    _save_sw_sector_snapshot(sectors)

    result = (sectors, _build_meta(False, f"网关 {AKSHARE_HOST} (index_realtime_sw)"))
    # 写缓存（仅成功取到数据时用长 TTL）
    if sectors:
        with _SW_SECTORS_CACHE["lock"]:
            _SW_SECTORS_CACHE["data"] = result
            _SW_SECTORS_CACHE["ts"] = time.time()
            _SW_SECTORS_CACHE["fail"] = False
    return result


# ⚠️ 该表同时有 PRIMARY KEY(代理主键) 和 UNIQUE(sector_code, trade_date) 两个唯一约束，
# DuckDB 的 `INSERT OR REPLACE` 无法推断冲突目标，会抛
#   BinderException: Conflict target has to be provided for a DO UPDATE operation
#   when the table has multiple UNIQUE/PRIMARY KEY constraints
# 因此必须显式写 ON CONFLICT 冲突目标。
# 估值列用 COALESCE(excluded.x, 原值)：历史回填拿不到 PE/PB（免费源只有当日快照），
# 传 None 时不能把已落库的真实估值覆盖掉。
_SW_SECTOR_UPSERT_SQL = """
INSERT INTO base_sw_sector_daily
    (sector_code, sector_name, trade_date, price, prev_close, change_pct,
     pe, ttm_pe, pb, dividend_yield, count)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (sector_code, trade_date) DO UPDATE SET
    sector_name    = excluded.sector_name,
    price          = excluded.price,
    prev_close     = excluded.prev_close,
    change_pct     = excluded.change_pct,
    pe             = COALESCE(excluded.pe, base_sw_sector_daily.pe),
    ttm_pe         = COALESCE(excluded.ttm_pe, base_sw_sector_daily.ttm_pe),
    pb             = COALESCE(excluded.pb, base_sw_sector_daily.pb),
    dividend_yield = COALESCE(excluded.dividend_yield, base_sw_sector_daily.dividend_yield),
    count          = COALESCE(excluded.count, base_sw_sector_daily.count)
"""


def _save_sw_sector_snapshot(sectors: list[dict], trade_date: str | None = None) -> int:
    """将申万一级行业快照写入 DuckDB base_sw_sector_daily 表。

    同一行业同一交易日仅保留一条记录（(sector_code, trade_date) 冲突即覆盖）。
    写入失败不影响主流程（热力图照常返回），但会打印错误——曾经的裸 `except: pass`
    让这条写入静默失败了一年多，导致该表常年 0 行。

    Returns:
        实际写入的行数（失败返回 0）。
    """
    if not sectors:
        return 0
    try:
        from database.connection import get_db
        from datetime import date as _date

        db = get_db()
        day = trade_date or _date.today().isoformat()
        rows = [
            [
                s.get("code", ""),
                s.get("name", ""),
                day,
                s.get("price"),
                s.get("prev_close"),
                s.get("change_pct"),
                s.get("pe"),
                s.get("ttm_pe"),
                s.get("pb"),
                s.get("dividend_yield"),
                s.get("count"),
            ]
            for s in sectors
        ]
        # ⚠️ 2026-10-15 历史记录：本处曾因 base_sw_sector_daily 表存储损坏导致
        # duckdb native 段错误（backend 崩溃循环、看板 502），当时误以为是写入形态
        # 问题而改成 executemany。后经生产库副本隔离实验确诊为**表损坏**，已用
        # database.init_db.repair_sw_sector_table（REPAIR_SW_SECTOR_TABLE=1）重建。
        # 31 行/10 分钟的量级，executemany ~0.5s 代价可忽略，保持现状无需改回。
        db.executemany(_SW_SECTOR_UPSERT_SQL, rows)
        print(f"[SW Snapshot] 写入 {len(rows)} 个行业快照 (trade_date={day})")
        return len(rows)
    except Exception as e:
        print(f"[SW Snapshot] 写入 base_sw_sector_daily 失败: {type(e).__name__}: {e}")
        return 0


def get_sw_sector_snapshot_stats() -> dict:
    """base_sw_sector_daily 表的落库情况（交易日数 / 行业数 / 最新日期）。"""
    try:
        from database.connection import get_db

        db = get_db()
        row = db.fetchone(
            """
            SELECT count(DISTINCT trade_date), count(DISTINCT sector_code), MAX(trade_date)
            FROM base_sw_sector_daily
            """
        )
        if not row:
            return {"tradeDays": 0, "sectorCount": 0, "latestDate": None}
        return {
            "tradeDays": row[0] or 0,
            "sectorCount": row[1] or 0,
            "latestDate": str(row[2]) if row[2] else None,
        }
    except Exception as e:
        print(f"[SW Snapshot] 统计 base_sw_sector_daily 失败: {type(e).__name__}: {e}")
        return {"tradeDays": 0, "sectorCount": 0, "latestDate": None}


def _fetch_sw_sector_meta() -> list[dict]:
    """申万一级行业清单（代码 + 名称 + 当日估值），用于历史回填的行业遍历。

    代码形如 `801010.SI`，回填时统一截掉后缀取 `801010`。数据来自远程网关 sw_index_first_info。
    """
    first = _akshare_request("sw_index_first_info", timeout=20)
    if not first:
        raise RuntimeError("网关 sw_index_first_info 无返回")

    out: list[dict] = []
    for r in first:
        code = str(r.get("行业代码", "")).split(".")[0]
        if not code:
            continue
        out.append({
            "code": code,
            "name": str(r.get("行业名称", "")),
            "pe": _safe_float(r.get("静态市盈率")),
            "ttm_pe": _safe_float(r.get("TTM(滚动)市盈率")),
            "pb": _safe_float(r.get("市净率")),
            "dividend_yield": _safe_float(r.get("静态股息率")),
            "count": _safe_int(r.get("成份个数")),
        })
    return out


def backfill_sw_sector_history(days: int = 250) -> dict:
    """回填申万一级行业历史日线到 base_sw_sector_daily。

    数据源：远程网关 `index_hist_sw(symbol=<行业代码>, period='day')`（全历史，约 0.7s/行业）。
    可回填：price（收盘）、prev_close、change_pct。
    无法回填：PE / PB / 股息率 —— 免费源 `sw_index_first_info()` 只有**当日**估值快照，
    没有历史序列，因此历史行的估值列留 NULL（前端历史走势图请选"收盘价/涨跌幅"维度）。

    幂等：同一 (sector_code, trade_date) 冲突即覆盖，重复执行安全。

    Args:
        days: 每个行业回填最近多少个交易日（默认 250 ≈ 一年）

    Returns:
        {"ok": bool, "sectors": int, "rows": int, "days": int, "error": str|None}
    """
    try:
        from database.connection import get_db
    except Exception as e:
        return {"ok": False, "sectors": 0, "rows": 0, "days": days, "error": f"DB 不可用: {e}"}

    try:
        metas = _fetch_sw_sector_meta()
    except Exception as e:
        return {"ok": False, "sectors": 0, "rows": 0, "days": days, "error": f"获取行业清单失败: {e}"}

    db = get_db()
    total_rows = 0
    done_sectors = 0
    failed: list[str] = []

    for meta in metas:
        code, name = meta["code"], meta["name"]
        try:
            hist = _akshare_request("index_hist_sw", {"symbol": code, "period": "day"}, timeout=20)
        except Exception as e:
            failed.append(f"{code}({name}): {e}")
            continue
        if not hist:
            failed.append(f"{code}({name}): 空数据")
            continue

        tail = hist[-(days + 1):]  # 多取一天用于算首日的 prev_close
        closes = [_safe_float(d.get("收盘")) for d in tail]
        dates = [str(d.get("日期"))[:10] for d in tail]

        rows: list[list] = []
        for i in range(1, len(dates)):  # 跳过第一天（它没有前收盘，算不出涨跌幅）
            price, prev = closes[i], closes[i - 1]
            if price is None or prev is None or prev == 0:
                continue
            rows.append([
                code,
                name,
                dates[i],
                price,
                prev,
                round((price - prev) / prev * 100, 2),
                None,  # pe — 无免费历史源
                None,  # ttm_pe
                None,  # pb
                None,  # dividend_yield
                meta.get("count"),
            ])
        if not rows:
            continue

        try:
            # 字面量多行 VALUES（ON CONFLICT 后缀原样拼回）；原 executemany 参数化
            # ~16ms/行（7750 行 ≈ 2 分钟，P2，见 docs/性能病理排查报告-2026-10-14.md）
            bulk_insert(db, _SW_SECTOR_UPSERT_SQL, rows)
            total_rows += len(rows)
            done_sectors += 1
        except Exception as e:
            failed.append(f"{code}({name}) 落库: {e}")

    print(f"[SW Backfill] 完成：{done_sectors}/{len(metas)} 个行业，{total_rows} 行"
          + (f"；失败 {len(failed)}: {failed[:3]}" if failed else ""))
    return {
        "ok": done_sectors > 0,
        "sectors": done_sectors,
        "rows": total_rows,
        "days": days,
        "error": "; ".join(failed[:3]) if failed else None,
    }


def get_sw_sector_history(sector_code: str, days: int = 120) -> list[dict]:
    """获取单个申万一级行业的历史快照（涨跌幅/PE/PB/股息率）。

    Args:
        sector_code: 申万一级行业代码
        days: 返回最近多少个交易日（默认120，约半年）
    """
    try:
        from database.connection import get_db

        db = get_db()
        rows = db.fetchall(
            """
            SELECT sector_code, sector_name, trade_date, price, prev_close, change_pct,
                   pe, ttm_pe, pb, dividend_yield, count
            FROM base_sw_sector_daily
            WHERE sector_code = ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            [sector_code, days],
        )
        result = []
        for r in rows:
            result.append({
                "code": r[0],
                "name": r[1],
                "date": str(r[2]),
                "price": float(r[3]) if r[3] is not None else None,
                "prev_close": float(r[4]) if r[4] is not None else None,
                "change_pct": float(r[5]) if r[5] is not None else None,
                "pe": float(r[6]) if r[6] is not None else None,
                "ttm_pe": float(r[7]) if r[7] is not None else None,
                "pb": float(r[8]) if r[8] is not None else None,
                "dividend_yield": float(r[9]) if r[9] is not None else None,
                "count": r[10],
            })
        # 按日期升序返回（方便前端画图）
        result.reverse()
        return result
    except Exception:
        return []


def get_sw_sector_relative_strength(days: int = 5) -> list[dict]:
    """计算各申万一级行业的相对强度：近期 N 日累计涨跌幅 vs 当日涨跌幅。

    相对强度 = 近N日累计涨跌幅 - 当日涨跌幅
    正值表示近期表现强于当日（可能有持续性），负值表示近期弱于当日（可能是超跌反弹）。

    Args:
        days: 近多少个交易日用于计算累计涨跌幅（默认5日）
    """
    try:
        from database.connection import get_db

        db = get_db()
        # 取最新日期
        latest = db.fetchone(
            "SELECT MAX(trade_date) FROM base_sw_sector_daily"
        )
        if not latest or not latest[0]:
            return []
        latest_date = latest[0]

        # 取最近 days+1 个交易日的数据（用于计算 N 日涨跌幅）
        # 注意：DISTINCT+ORDER BY+LIMIT 在 DuckDB 1.5.x 会漏行，必须用 GROUP BY 写法
        rows = db.fetchall(
            """
            SELECT sector_code, sector_name, trade_date, change_pct, price, pe, pb, dividend_yield
            FROM base_sw_sector_daily
            WHERE trade_date >= (
                SELECT trade_date FROM base_sw_sector_daily
                GROUP BY trade_date ORDER BY trade_date DESC LIMIT ?
            )
            ORDER BY sector_code, trade_date
            """,
            [days + 1],
        )
        if not rows:
            return []

        # 按行业分组计算
        from collections import defaultdict

        grouped: dict[str, list[tuple]] = defaultdict(list)
        for r in rows:
            grouped[r[0]].append(r)

        result = []
        for sector_code, records in grouped.items():
            if len(records) < 2:
                continue
            # 当日（最后一条）涨跌幅
            today_change = records[-1][3] if records[-1][3] is not None else None
            # 近 N 日累计涨跌幅（第一条到最后一条的 price 变化）
            first_price = records[0][4]
            last_price = records[-1][4]
            cum_change = None
            if first_price and last_price and first_price > 0:
                cum_change = round((last_price - first_price) / first_price * 100, 2)

            # 相对强度
            rel_strength = None
            if cum_change is not None and today_change is not None:
                rel_strength = round(cum_change - today_change, 2)

            result.append({
                "code": sector_code,
                "name": records[-1][1],
                "today_change_pct": today_change,
                "cum_change_pct": cum_change,
                "relative_strength": rel_strength,
                "pe": records[-1][5] if records[-1][5] else None,
                "pb": records[-1][6] if records[-1][6] else None,
                "dividend_yield": records[-1][7] if records[-1][7] else None,
                "latest_date": str(records[-1][2]),
            })

        # 按相对强度降序
        result.sort(key=lambda x: x.get("relative_strength") or -999, reverse=True)
        return result
    except Exception:
        return []


def get_sw_sector_rank_trend(days: int = 20) -> dict:
    """A股行业热力图趋势：最近 N 个交易日，每日各申万一级行业的涨跌幅与当日排名。

    数据源：本地 DuckDB base_sw_sector_daily（每日快照落库，见 jobs/sw_snapshot_job.py）。
    排名规则：每日按 change_pct 降序，第 1 名 = 当日最强。
    行业排序：按窗口内平均排名升序（持续强势的行业排在最上面）。

    Returns:
        {
          "dates": ["2026-09-22", ...],                  # 交易日，升序
          "sectors": [
            {"code": "801010", "name": "农林牧渔", "avg_rank": 12.3,
             "daily": [{"date": "...", "change_pct": 1.23, "rank": 5}, ...]},
          ],
          "meta": {"trade_days": N, "latest_date": "YYYY-MM-DD"}
        }
    """
    empty = {"dates": [], "sectors": [], "meta": {"trade_days": 0, "latest_date": None}}
    try:
        from database.connection import get_db

        days = max(2, min(int(days or 20), 120))
        db = get_db()
        rows = db.fetchall(
            """
            SELECT sector_code, sector_name, trade_date, change_pct
            FROM base_sw_sector_daily
            WHERE trade_date IN (
                -- 注意：不要用 SELECT DISTINCT ... LIMIT（DuckDB 1.5.x 该组合会漏行），
                -- 也不要用 >= (子查询)（1.5.x 按标量子查询处理，多行报错），用 IN + GROUP BY
                SELECT trade_date FROM base_sw_sector_daily
                GROUP BY trade_date ORDER BY trade_date DESC LIMIT ?
            )
            ORDER BY trade_date, sector_code
            """,
            [days],
        )
        if not rows:
            return empty

        # 按日期聚合；逐日对 change_pct 降序排名（缺失涨跌幅的行业当日不参与排名）
        by_date: dict[str, list[tuple[str, float]]] = {}
        name_by_code: dict[str, str] = {}
        for code, name, d, pct in rows:
            ds = str(d)
            if pct is not None:
                by_date.setdefault(ds, []).append((code, float(pct)))
            name_by_code[code] = name

        dates = sorted(by_date)
        if not dates:
            return empty

        daily_by_code: dict[str, list[dict]] = {}
        rank_sum: dict[str, float] = {}
        rank_cnt: dict[str, int] = {}
        for ds in dates:
            items = sorted(by_date[ds], key=lambda x: x[1], reverse=True)
            for rank, (code, pct) in enumerate(items, start=1):
                daily_by_code.setdefault(code, []).append(
                    {"date": ds, "change_pct": round(pct, 2), "rank": rank}
                )
                rank_sum[code] = rank_sum.get(code, 0.0) + rank
                rank_cnt[code] = rank_cnt.get(code, 0) + 1

        sectors = []
        for code, daily in daily_by_code.items():
            avg = rank_sum[code] / rank_cnt[code] if rank_cnt[code] else None
            sectors.append({
                "code": code,
                "name": name_by_code.get(code, code),
                "avg_rank": round(avg, 1) if avg is not None else None,
                "daily": daily,
            })
        sectors.sort(key=lambda s: (s["avg_rank"] if s["avg_rank"] is not None else 9999.0, s["code"]))

        return {
            "dates": dates,
            "sectors": sectors,
            "meta": {"trade_days": len(dates), "latest_date": dates[-1]},
        }
    except Exception as e:
        # 不吞真实报错：打印后返回空结构（与相邻快照函数风格一致）
        print(f"[market_service] get_sw_sector_rank_trend error: {e}")
        return empty


# 申万一级行业估值历史缓存（避免频繁调用 AkShare）
# key: f"sw_val_{start_date}_{end_date}"，value: {data, fetched_at}
_valuation_history_cache: dict[str, Any] = {}
_VALUATION_CACHE_TTL = 3600  # 缓存有效期 1 小时
_VALUATION_CACHE_MAX_KEYS = 8  # 超过则清掉最旧的，避免跨天累积后内存只增不减
# 每个 key 一把锁：缓存未命中时只允许一个线程去拉，其余等待结果，
# 避免并发请求把 akshare 全量拉取（约 30s）重复触发 N 次。
_valuation_locks: dict[str, threading.Lock] = {}
_valuation_locks_guard = threading.Lock()


def _valuation_lock_for(key: str) -> threading.Lock:
    with _valuation_locks_guard:
        lock = _valuation_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _valuation_locks[key] = lock
        return lock


def _valuation_cache_put(key: str, data: list[dict]) -> None:
    with _valuation_locks_guard:
        _valuation_history_cache[key] = {"data": data, "fetched_at": time.time()}
        if len(_valuation_history_cache) > _VALUATION_CACHE_MAX_KEYS:
            for old_key in sorted(
                _valuation_history_cache,
                key=lambda k: _valuation_history_cache[k]["fetched_at"],
            )[: len(_valuation_history_cache) - _VALUATION_CACHE_MAX_KEYS]:
                _valuation_history_cache.pop(old_key, None)
                _valuation_locks.pop(old_key, None)


def ensure_sw_sector_valuation_snapshot(trade_date: str | None = None) -> int:
    """确保 base_sw_sector_daily 存在指定交易日的 PE/PB 估值快照。

    仅依赖网关 ``sw_index_first_info``（申万一级行业当日 PE/PB/股息率/成份数），
    不依赖实时行情接口，因此即使行情接口抖动也能累积估值历史。

    若当日已存在有效估值（任意行业 pe/pb 非空）则跳过，幂等；否则拉取并 upsert。
    代码统一截掉 ``.SI`` 后缀（如 ``801010``），与回填/历史接口保持一致。

    Returns:
        本次实际写入/覆盖的行数（0 表示已存在或无数据）。
    """
    try:
        from database.connection import get_db
        from datetime import date as _date

        day = trade_date or _date.today().isoformat()
        db = get_db()
        existing = db.fetchone(
            "SELECT COUNT(*) FROM base_sw_sector_daily "
            "WHERE trade_date = ? AND (pe IS NOT NULL OR pb IS NOT NULL)",
            [day],
        )
        if existing and existing[0] and existing[0] > 0:
            print(f"[SW Valuation] {day} 估值快照已存在({existing[0]}行)，跳过")
            return 0
    except Exception as e:
        print(f"[SW Valuation] 检查已有快照失败(继续尝试写入): {e}")

    try:
        first = _akshare_request("sw_index_first_info", timeout=20)
    except Exception as e:
        print(f"[SW Valuation] 网关 sw_index_first_info 调用失败: {e}")
        return 0
    if not first:
        return 0

    sectors: list[dict] = []
    for r in first:
        code = str(r.get("行业代码", "")).split(".")[0]
        if not code:
            continue
        sectors.append({
            "code": code,
            "name": str(r.get("行业名称", "")),
            "price": None,
            "prev_close": None,
            "change_pct": None,
            "pe": _safe_float(r.get("静态市盈率")),
            "ttm_pe": _safe_float(r.get("TTM(滚动)市盈率")),
            "pb": _safe_float(r.get("市净率")),
            "dividend_yield": _safe_float(r.get("静态股息率")),
            "count": _safe_int(r.get("成份个数")),
        })
    if not sectors:
        return 0
    return _save_sw_sector_snapshot(sectors, trade_date=day)


def get_all_sw_sector_valuation_rows(window_days: int = 250) -> list[dict]:
    """从 base_sw_sector_daily 读取所有行业的估值快照（用于估值分位/拥挤度计算）。

    只取有 pe 或 pb 的交易日（即真正累积到估值的快照行），按 (归一化代码, 交易日)
    去重，避免 get_sw_sectors 与 ensure 在不同代码格式下产生的同日重复行。

    Returns:
        [{"code","name","date","pe","ttm_pe","pb","dividend_yield"}, ...]（按代码、日期升序）
    """
    try:
        from database.connection import get_db
        from datetime import date as _date, timedelta as _td

        db = get_db()
        sd = (_date.today() - _td(days=window_days)).isoformat()
        raw = db.fetchall(
            """
            SELECT sector_code, sector_name, trade_date, pe, ttm_pe, pb, dividend_yield
            FROM base_sw_sector_daily
            WHERE trade_date >= ? AND (pe IS NOT NULL OR pb IS NOT NULL)
            ORDER BY sector_code, trade_date
            """,
            [sd],
        )
    except Exception as e:
        print(f"[SW Valuation] 读取本地估值快照失败: {e}")
        return []

    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for r in raw:
        code = str(r[0]).split(".")[0]
        day = str(r[2])
        key = (code, day)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "code": code,
            "name": str(r[1]),
            "date": day,
            "pe": float(r[3]) if r[3] is not None else None,
            "ttm_pe": float(r[4]) if r[4] is not None else None,
            "pb": float(r[5]) if r[5] is not None else None,
            "dividend_yield": float(r[6]) if r[6] is not None else None,
        })
    return out


def get_sw_sector_valuation_history(
    sector_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[list[dict], dict]:
    """获取申万一级行业的历史估值数据（PE / PB / 股息率）。

    数据源：本地 DuckDB ``base_sw_sector_daily``（由 ``ensure_sw_sector_valuation_snapshot``
    每日从网关 ``sw_index_first_info`` 累积 PE/PB/股息率快照）。该上游稳定可用，行业估值历史
    是**真实累积**的，不再依赖已挂掉的 ``index_analysis_daily_sw``。

    调用前会懒触发当日快照累积（幂等）：打开行业估值页即可自然累积历史；数据越多，
    分位/拥挤度越准。历史不足时在 meta 中给出 ``snapshotStats`` 供前端提示。

    Args:
        sector_code: 申万一级行业代码（如 '801010'），为 None 则返回所有行业
        start_date: 开始日期 'YYYYMMDD'（仅用于推算窗口天数，默认近 250 天）
        end_date: 结束日期 'YYYYMMDD'（默认今天）

    Returns:
        (list[dict], meta)  — meta 含数据来源/累积情况
    """
    if USE_MOCK_DATA:
        return [], _build_meta(True, "MOCK(模拟数据)")

    from datetime import date as _date, timedelta as _td

    today = _date.today()
    if not end_date:
        end_date = today.strftime("%Y%m%d")
    if not start_date:
        start_date = (today - _td(days=250)).strftime("%Y%m%d")

    # 懒触发当日估值快照累积（幂等：已存在则跳过）。即使行情接口抖动，
    # sw_index_first_info 仍可提供当日 PE/PB，从而让历史自然滚动增长。
    try:
        ensure_sw_sector_valuation_snapshot()
    except Exception as e:
        print(f"[SW Valuation] 当日快照累积失败(继续读已有历史): {e}")

    # 由起止日期推算窗口天数
    window_days = 250
    try:
        ed = _date.strptime(end_date, "%Y%m%d")
        sd = _date.strptime(start_date, "%Y%m%d")
        window_days = max(30, (ed - sd).days + 1)
    except Exception:
        pass

    rows = get_all_sw_sector_valuation_rows(window_days=window_days)

    # 按 sector_code 过滤
    if sector_code:
        rows = [r for r in rows if r["code"] == sector_code]

    if not rows:
        m = _build_meta(False, f"本地 base_sw_sector_daily 暂无估值快照(网关 {AKSHARE_HOST})")
        m["status"] = "unavailable"
        m["message"] = (
            "行业估值快照尚未累积到数据。请确认网关 sw_index_first_info 可访问，"
            "或稍后重试（打开行业估值页会自动累积当日快照）。"
        )
        m["snapshotStats"] = get_sw_sector_snapshot_stats()
        return [], m

    m = _build_meta(False, f"本地累积(网关 sw_index_first_info, 窗口{window_days}天)")
    m["snapshotStats"] = get_sw_sector_snapshot_stats()
    return rows, m


def get_board_sectors_with_meta() -> tuple[list, dict]:
    """板块涨幅排行"""
    if USE_MOCK_DATA:
        return mock_data.MOCK_MACRO_DATA["boardSectors"], _build_meta(True, "MOCK(模拟数据)")
    sectors = get_board_sectors_real()
    if sectors:
        return sectors, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")
    return [], gateway_no_data_meta()


def get_fund_flows_with_meta() -> tuple[dict, dict]:
    """资金流向"""
    if USE_MOCK_DATA:
        return mock_data.MOCK_MACRO_DATA["fundFlows"], _build_meta(True, "MOCK(模拟数据)")
    flows = get_fund_flows_real()
    if flows:
        if flows.get("source") == "board_proxy":
            note = "板块行业净流入代理(东财大盘主力净流入源不可用)"
        else:
            note = f"AkShare WebAPI ({AKSHARE_HOST})"
        return flows, _build_meta(False, note)
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "mainInflow": 0, "mainInflowPct": 0,
        "superLargeInflow": 0, "superLargeInflowPct": 0,
        "largeInflow": 0, "largeInflowPct": 0,
        "mediumInflow": 0, "mediumInflowPct": 0,
        "smallInflow": 0, "smallInflowPct": 0,
        "industryFlows": [],
    }, gateway_no_data_meta()


def get_zt_stats_with_meta() -> tuple[dict, dict]:
    """涨跌停统计"""
    if USE_MOCK_DATA:
        return mock_data.MOCK_MACRO_DATA["ztStats"], _build_meta(True, "MOCK(模拟数据)")
    stats = get_zt_stats_real()
    if stats:
        return stats, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "ztCount": 0, "dtCount": 0,
        "prevZTPerformance": {"avgChange": 0.0, "topPerformer": "", "topPerformerChange": 0.0},
        "ztList": [], "dtList": [],
    }, gateway_no_data_meta()


def get_fund_ranking_with_meta() -> tuple[list, dict]:
    """基金涨跌排行"""
    if USE_MOCK_DATA:
        return mock_data.MOCK_MACRO_DATA["fundRanking"], _build_meta(True, "MOCK(模拟数据)")
    ranking = get_fund_ranking_real()
    if ranking:
        return ranking, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")
    return [], gateway_no_data_meta()


def _is_a_share_index(item: dict) -> bool:
    """判断指数是否为 A 股指数（按代码或名称）"""
    code = item.get("code", "")
    name = item.get("name", "")
    if code in dict(_A_SHARE_OVERVIEW_INDICES).values():
        return True
    if name and _get_index_code(name) in dict(_A_SHARE_OVERVIEW_INDICES).values():
        return True
    return False


def _market_by_code_or_name(item: dict) -> str:
    """推断指数所属市场"""
    code = item.get("code", "")
    name = item.get("name", "")
    if code in dict(_A_SHARE_OVERVIEW_INDICES).values():
        return "a_share"
    if name and _get_index_code(name) in dict(_A_SHARE_OVERVIEW_INDICES).values():
        return "a_share"
    # 港股/美股常见名称兜底
    if any(k in name for k in ("恒生", "国企", "港股")):
        return "hk"
    if any(k in name for k in ("标普", "纳斯达克", "道琼斯", "罗素")):
        return "us"
    return "a_share"


# ============================================================
# index_valuation 上游调用：TTL 缓存 + singleflight（2026-10-16）
# ============================================================
# 背景：/market/indices 与 /market/overview 都打同一上游
# processed_data(index_valuation)，原先无缓存无去重 → 一次 Dashboard 加载
# 双打，且用户点「刷新」立即重打全套上游。此处在 _processed_data_request
# 之上包一层：
# - TTL 30s：日内行情 30s 新鲜度足够（sw-sectors 已 10min、macro 1h），
#   同页双打与 30s 内的重复刷新全部命中缓存；
# - singleflight：未命中时只放一个请求在途，其余并发请求等它落地后读缓存，
#   避免冷启动瞬间多线程同时打网关；
# - 失败不写缓存（无负缓存），下次请求立即重试，故障恢复无延迟。
_INDEX_VAL_TTL = 30
_INDEX_VAL_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_INDEX_VAL_LOCK = threading.Lock()
_INDEX_VAL_INFLIGHT: threading.Event | None = None


def _fetch_index_valuation_raw(force: bool = False) -> list | None:
    """index_valuation 原始上游数据（30s TTL + singleflight）。

    force=True 穿透缓存与在途等待，直接打上游（预留手动刷新用）。
    """
    global _INDEX_VAL_INFLIGHT
    now = time.time()
    with _INDEX_VAL_LOCK:
        c = _INDEX_VAL_CACHE
        if not force and c["data"] is not None and (now - c["ts"]) < _INDEX_VAL_TTL:
            return c["data"]
        ev = _INDEX_VAL_INFLIGHT
        if ev is None:
            ev = threading.Event()
            _INDEX_VAL_INFLIGHT = ev
            leader = True
        else:
            leader = False
    if not leader:
        # 在途请求最长约 timeout(15s)+retries，等 45s 足够；超时按未命中处理
        ev.wait(timeout=45)
        with _INDEX_VAL_LOCK:
            c = _INDEX_VAL_CACHE
            if c["data"] is not None:
                return c["data"]
        return None
    try:
        data = _processed_data_request(
            "index_valuation", {"subtype": "all", "period": 5}, retries=1, timeout=15
        )
        if data:
            with _INDEX_VAL_LOCK:
                _INDEX_VAL_CACHE["data"] = data
                _INDEX_VAL_CACHE["ts"] = time.time()
        return data
    finally:
        with _INDEX_VAL_LOCK:
            _INDEX_VAL_INFLIGHT = None
        ev.set()


def _fetch_index_valuation_data() -> tuple[list[dict], list[dict]]:
    """一次性获取指数估值数据，返回 (realtime_indices, indices_valuation) 两种格式

    realtime_indices: 用于 marketOverview.indices (MarketIndex 格式，仅 A 股核心指数)
    indices_valuation: 用于跨市场指数估值表 (IndexValuation 格式)
    """
    data = _fetch_index_valuation_raw()

    if not data or not isinstance(data, list):
        return [], []

    # 1. 统一先转成 MarketIndex 格式（pe/pb/百分位缺失时保留 None，绝不伪造为 0）
    raw_items: list[dict] = []
    for item in data:
        latest_price = _safe_float(item.get("latest_price"))
        chg_pct = _safe_float(item.get("chg_pct"))
        raw_items.append({
            "name": item.get("index_name", ""),
            "code": _get_index_code(item.get("index_name", "")),
            "price": latest_price,
            "change": _calc_change(latest_price, chg_pct),
            "changePct": chg_pct,
            "pe": _safe_float_or_none(item.get("pe")),
            "pb": _safe_float_or_none(item.get("pb")),
            "pePercentile": _safe_float_or_none(item.get("pe_percentile")),
            "pbPercentile": _safe_float_or_none(item.get("pb_percentile")),
            "category": item.get("category", ""),
            "change3mPct": _safe_float(item.get("3m_change_pct")),
            "winRate": _safe_float(item.get("win_rate")),
        })

    # 2. 分离 A 股与跨市场指数，补齐 A 股核心指数
    a_share_items = [it for it in raw_items if _is_a_share_index(it)]
    other_items = [it for it in raw_items if not _is_a_share_index(it)]

    realtime_indices = _ensure_overview_indices(a_share_items)
    all_items = realtime_indices + other_items

    # 3. 生成跨市场估值表数据（无百分位时 category=unknown，避免被误归入"极度低估"）
    indices_valuation = []
    for it in all_items:
        pe_pct = it.get("pePercentile")
        if pe_pct is None:
            cat = "unknown"
        elif pe_pct < 20:
            cat = "opportunity"
        elif pe_pct < 40:
            cat = "undervalued"
        elif pe_pct > 80:
            cat = "overvalued"
        else:
            cat = "normal"

        indices_valuation.append({
            "name": it.get("name", ""),
            "code": it.get("code", ""),
            "level": it.get("price") or 0,
            # 行情类字段 null 归 0（前端直接 toFixed）；估值类字段（pe/pb/百分位）保留 None
            "change_pct": it.get("changePct") or 0,
            "pe": it.get("pe"),
            "pe_percentile": it.get("pePercentile"),
            "pb": it.get("pb"),
            "pb_percentile": it.get("pbPercentile"),
            "category": cat,
            "change_3m_pct": it.get("change3mPct") or 0,
            "win_rate": it.get("winRate") or 0,
            "hasValuation": it.get("hasValuation", True),
            "market": _market_by_code_or_name(it),
        })

    return realtime_indices, indices_valuation





# ============================================================
# 指数估值：同口径 PE/PB 分位重算（2026-10-13，对齐指数分析页口径）
# ============================================================
# 背景：上游 processed_data index_valuation/all 的 pe 取腾讯实时口径，
# 而 pe_percentile 按中证官网(index-perf)序列末值计算——同一行两个口径
# （沪深300 曾显示 PE 13.1 + 分位 66%，但腾讯口径 12.5 的真实分位是 69.5%；
#   上证红利更曾被标 100% 分位，同口径实际仅 74.7%）。
# 指数分析页(/index-analysis)数据"全都是好的"原因：它走 valuation_service，
# PB/PE 取值与分位都取自网关 /api/index-valuation/{code}/history（腾讯口径
# 月度快照，197-237 个样本），分位由 doraemon 侧对**同一序列**计算，永远自洽。
# 此处让宏观看板复用同一口径：pe/pb 与分位全部来自该历史序列；
# 无历史序列的指数（如科创综指网关未覆盖）分位置空显示"—"，宁缺勿假。

_PB_PE_HIST_CACHE: dict[str, tuple[float, dict | None]] = {}
_PB_PE_HIST_TTL = 1800  # 30 分钟（上游序列每日更新，无需更频繁拉取）
_PB_PE_HIST_LOCK = threading.Lock()
_MIN_VALUATION_SAMPLES = 24  # 与 valuation_service.MIN_HISTORY_SAMPLES 对齐：不足 2 年不算分位
_COND_WIN_BAND = 0.10        # 条件胜率：±10% 相对 PE 区间视为「同一估值水平」
_COND_WIN_MIN_SAMPLES = 10   # 可比样本不足 10 个月则置 None（宁缺勿假）
_COND_WIN_FORWARD = 3        # 前向持有期：3 个月


def _percentile_rank(value: float, values: list[float]) -> float:
    """升序百分位（与 valuation_service._percentile 同口径）：≤value 的样本占比×100"""
    if not values:
        return 0.0
    below = sum(1 for v in values if v is not None and v <= value)
    return below / len(values) * 100.0


def _chg_from_month_buckets(rows: list[dict], months_back: int) -> float | None:
    """月度快照序列的 N 月涨跌幅（%）：末值 vs N 个桶前的值。

    桶值为当月最后收盘（当前月桶=最新收盘），与精确交易日复算有少量误差，
    仅作看板 glance 级展示；样本不足返回 None。
    """
    vals = [float(r["index_value"]) for r in rows if r.get("index_value") is not None]
    if len(vals) <= months_back:
        return None
    base = vals[-(months_back + 1)]
    if base <= 0:
        return None
    return round((vals[-1] - base) / base * 100, 2)


def _conditional_win_rate_3m(rows: list[dict]) -> float | None:
    """条件胜率（%）：历史上与当前 PE 水平相当（±10%）的月份，持有 3 个月正收益的占比

    替代原 win_rate（近 250 日上涨日占比，数学上恒≈50%、零区分度）。
    输入为腾讯口径月度快照（date/pe_ttm/index_value 升序）：
    以 pe_ttm 落在 [cur×(1±10%)] 的月份为可比样本，
    前向收益 = 3 个桶后的 index_value / 样本月 index_value - 1 > 0 记为正。
    样本不足 _COND_WIN_MIN_SAMPLES 返回 None（前端显示"—"），宁缺勿假。
    """
    pts = [
        (float(r["pe_ttm"]), float(r["index_value"]))
        for r in rows
        if r.get("pe_ttm") is not None and r.get("index_value") is not None
    ]
    if len(pts) <= _COND_WIN_FORWARD:
        return None
    cur_pe = pts[-1][0]
    if cur_pe <= 0:
        return None
    hits = total = 0
    for i in range(len(pts) - _COND_WIN_FORWARD):
        pe_i, iv_i = pts[i]
        if pe_i <= 0 or iv_i <= 0:
            continue
        if abs(pe_i - cur_pe) / cur_pe > _COND_WIN_BAND:
            continue
        fwd_iv = pts[i + _COND_WIN_FORWARD][1]
        if fwd_iv <= 0:
            continue
        total += 1
        if fwd_iv / iv_i - 1 > 0:
            hits += 1
    if total < _COND_WIN_MIN_SAMPLES:
        return None
    return round(hits / total * 100, 1)


def _chg_3m_from_sina(code: str) -> float | None:
    """新浪日线实算近 3 月涨跌幅（63 个交易日间隔）；样本不足返回 None"""
    bars = _fetch_real_kline("stock_zh_index_daily", {"symbol": _index_sina_symbol(code)}, count=70)
    closes = [b["close"] for b in bars if b.get("close")]
    if len(closes) < 64:
        return None
    base = closes[-64]
    if base <= 0:
        return None
    return round((closes[-1] - base) / base * 100, 2)


def _index_pb_pe_snapshot(code: str) -> dict | None:
    """单指数 PB/PE 历史快照：末值 + 全史升序分位（带 30 分钟进程内缓存）

    数据源与指数分析页 valuation_service 完全相同：网关
    /api/index-valuation/{code}/history（腾讯口径月度快照）。

    Returns:
        {"pe","pb","pe_percentile","pb_percentile","pe_samples","pb_samples",
         "as_of","chg_1y_pct","win_rate"}；无数据返回 None。
        pe/pb 为序列末值；分位=末值在全史中的升序百分位（样本不足 24 个月置 None）；
        win_rate=条件胜率（与当前 PE ±10% 区间持有 3 个月正收益占比，样本<10 置 None）。
    """
    code = (code or "").strip()
    if not code:
        return None
    now = time.time()
    with _PB_PE_HIST_LOCK:
        cached = _PB_PE_HIST_CACHE.get(code)
        if cached and (now - cached[0]) < _PB_PE_HIST_TTL:
            return cached[1]

    from services.index_pb_pe import get_index_pb_pe_meta

    data = get_index_pb_pe_meta(code, timeout=15)
    snap: dict | None = None
    if data:
        pb_rows = [r for r in (data.get("pb") or []) if isinstance(r, dict) and r.get("pb") is not None]
        pe_rows = [r for r in (data.get("pe") or []) if isinstance(r, dict) and r.get("pe_ttm") is not None]
        if pb_rows or pe_rows:
            pb_vals = [float(r["pb"]) for r in pb_rows]
            pe_vals = [float(r["pe_ttm"]) for r in pe_rows]
            last_pb = pb_vals[-1] if pb_vals else None
            last_pe = pe_vals[-1] if pe_vals else None
            updated = str(data.get("updated_at") or "")
            snap = {
                "pe": last_pe,
                "pb": last_pb,
                "pe_percentile": round(_percentile_rank(last_pe, pe_vals), 2)
                if (last_pe is not None and len(pe_vals) >= _MIN_VALUATION_SAMPLES) else None,
                "pb_percentile": round(_percentile_rank(last_pb, pb_vals), 2)
                if (last_pb is not None and len(pb_vals) >= _MIN_VALUATION_SAMPLES) else None,
                "pe_samples": len(pe_vals),
                "pb_samples": len(pb_vals),
                "as_of": updated[:10] or None,
                "chg_1y_pct": _chg_from_month_buckets(pb_rows or pe_rows, 12),
                "win_rate": _conditional_win_rate_3m(pe_rows),
            }
    with _PB_PE_HIST_LOCK:
        _PB_PE_HIST_CACHE[code] = (now, snap)
    return snap


def _valuation_category(pe_pct: float | None, pe: float | None) -> str:
    """按 PE 分位判定估值类别；高分红类指数（绝对 PE<10）分位>80 也不标「高估」"""
    if pe_pct is None:
        return "unknown"
    if pe_pct < 20:
        return "opportunity"   # 极度低估
    if pe_pct < 40:
        return "undervalued"   # 低估
    if pe_pct > 80:
        # 上证红利等同口径分位曾达 100% 系红利股大涨所致，绝对 PE 仍低——
        # 「比自己历史贵」≠「贵」，PE<10 降档为 normal，避免前端标红误导
        if pe is not None and pe < 10:
            return "normal"
        return "overvalued"    # 高估
    return "normal"            # 正常


def _enrich_valuation_with_history(indices: list[dict]) -> list[dict]:
    """用同口径历史序列重算估值行的 pe/pb/分位/类别（见上方模块头说明）。

    - 有历史序列：pe/pb 取序列末值，分位=末值全史升序百分位（≥24 个月守卫）
    - 无历史序列（如科创综指）：分位置空、category=unknown，不采用上游混合口径值

    2026-10-16：串行改并行。原实现按顺序对每个指数打网关
    index-valuation/{code}/history，~25 个指数冷缓存时单接口要 10-30s；
    改 8 路并发后约 2-5s。_index_pb_pe_snapshot 自带每码 30min 缓存，
    并发打不同 code 互不竞争；requests Session 连接池上限 32，远高于 8。
    """
    # 无历史序列 / 无代码的行：直接置 unknown，不必打网关
    pending: list[dict] = []
    for idx in indices:
        if idx.get("hasValuation") is False or not idx.get("code"):
            idx["pe_percentile"] = None
            idx["pb_percentile"] = None
            idx["category"] = "unknown"
            # 无历史序列不保留上游 win_rate（250 日上涨日占比恒≈50%，零信息）
            idx["win_rate"] = None
        else:
            pending.append(idx)

    if not pending:
        return indices

    def _work(idx: dict) -> tuple[dict, dict | None]:
        try:
            return idx, _index_pb_pe_snapshot(idx["code"])
        except Exception:
            return idx, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for idx, snap in pool.map(_work, pending):
            if not snap:
                idx["pe_percentile"] = None
                idx["pb_percentile"] = None
                idx["category"] = "unknown"
                idx["win_rate"] = None
                continue
            if snap["pe"] is not None:
                idx["pe"] = snap["pe"]
            if snap["pb"] is not None:
                idx["pb"] = snap["pb"]
            idx["pe_percentile"] = snap["pe_percentile"]
            idx["pb_percentile"] = snap["pb_percentile"]
            idx["category"] = _valuation_category(snap["pe_percentile"], snap["pe"])
            if snap.get("as_of"):
                idx["pe_as_of"] = snap["as_of"]
            if snap.get("chg_1y_pct") is not None:
                idx["change_1y_pct"] = snap["chg_1y_pct"]
            # 条件胜率覆盖上游 win_rate（可比样本<10 个月时为 None，前端显示"—"）
            idx["win_rate"] = snap.get("win_rate")
    return indices


def _map_index_valuation(data: list, category: str | None = None) -> list[dict]:
    """将 index_valuation 原始数据映射为前端 IndexValuation 格式，并按 category 过滤

    pe/pb/百分位上游缺失时保留 None（前端显示"—"），绝不伪造为 0。
    ⚠️ 此处的 pe_percentile 是上游混合口径值（腾讯 PE + 中证序列分位），
    category 亦由此推导——调用方必须随后执行 _enrich_valuation_with_history
    重算为同口径分位与类别，并在重算后再做 category 过滤。
    """
    indices = []
    for item in data:
        idx_name = item.get("index_name", "")
        # 上证380 无 PE 数据、已弃用，由科创综指替代（见 _swap_380_for_star_board）
        if idx_name == "上证380" or _get_index_code(idx_name) == "000009":
            continue
        # 根据PE百分位判断估值类别（初判；随后会被同口径重算覆盖）
        pe_pct = _safe_float_or_none(item.get("pe_percentile"))
        pe_val = _safe_float_or_none(item.get("pe"))

        indices.append({
            "name": idx_name,
            "code": _get_index_code(idx_name),
            # 上游行情缺失时置 None（前端显示"—"），与 docstring「绝不伪造为 0」一致
            "level": _safe_float_or_none(item.get("latest_price")),
            "change_pct": _safe_float_or_none(item.get("chg_pct")),
            "pe": pe_val,
            "pe_percentile": pe_pct,
            "pb": _safe_float_or_none(item.get("pb")),
            "pb_percentile": _safe_float_or_none(item.get("pb_percentile")),
            "category": _valuation_category(pe_pct, pe_val),
            "change_3m_pct": _safe_float_or_none(item.get("3m_change_pct")),
            # win_rate：此处透传上游混合口径值（250 日上涨日占比，恒≈50%），
            # 随后 _enrich_valuation_with_history 会用同口径序列实算的条件胜率覆盖；
            # 无历史序列时置 None（不保留零信息量的上游值）
            "win_rate": _safe_float_or_none(item.get("win_rate")),
            # 上游快照日期（行情口径），供前端展示「行情截至」
            "valuation_date": str(item.get("date") or "")[:10] or None,
        })

    if category:
        indices = [idx for idx in indices if idx.get("category") == category]
    return indices


def _swap_380_for_star_board(indices: list[dict], category: str | None = None) -> list[dict]:
    """上证380 已在 _map_index_valuation 剔除；此处补入科创综指(000680)。

    科创综指的 PE/PB 上游 index_valuation 与网关 index-valuation 历史均无源
    （000680 history 实测 months=None），故仅用实时行情补录点位/涨跌幅，
    估值字段置 None（category=unknown，前端显示"—"），绝不伪造估值。
    近3月涨跌幅用新浪日线实算（63 交易日间隔）；win_rate 不伪造 0，置 None。
    已含科创系列、或按非 unknown 分类过滤时不补录。
    """
    # 按分类过滤时，科创综指(unknown) 仅在未过滤或过滤 unknown 时加入
    if category and category != "unknown":
        return indices
    if any(idx.get("name") in ("科创板", "科创综指", "科创50") for idx in indices):
        return indices
    quote = _fetch_index_quote("000680")
    if not quote or not quote.get("price"):
        return indices
    indices.append({
        "name": "科创综指",
        "code": "000680",
        "level": quote.get("price") or 0,
        "change_pct": quote.get("changePct") or 0,
        "pe": None,
        "pe_percentile": None,
        "pb": None,
        "pb_percentile": None,
        "category": "unknown",
        "change_3m_pct": _chg_3m_from_sina("000680"),  # 新浪日线实算；取不到置 None（显示"—"）
        "win_rate": None,                              # 上游无此字段，不伪造 0
        "hasValuation": False,
    })
    return indices


def get_indices_with_meta(category: str | None = None, date: str | None = None) -> tuple[list[dict], dict]:
    """获取指数估值列表（分区接口），返回 (data, meta)
    
    Args:
        category: 可选过滤条件 (undervalued/opportunity/normal/overvalued)
        date: 保留参数，当前未使用
    """
    print(f"[Indices] 获取指数估值列表 (category={category})...")
    if USE_MOCK_DATA:
        indices = mock_data.MOCK_MACRO_DATA["indices"]
        if category:
            indices = [idx for idx in indices if idx.get("category") == category]
        return indices, _build_meta(True, "MOCK(模拟数据)")

    data = _fetch_index_valuation_raw()

    if data and isinstance(data, list):
        # 顺序很重要：先映射(不过滤) → 补录科创综指 → 同口径重算 pe/pb/分位/类别，
        # 最后才按 category 过滤——保证过滤作用于重算后的正确类别
        # （上游 pe_percentile 是腾讯 PE + 中证序列分位的混合口径，不可直接用于分类）
        indices = _map_index_valuation(data)
        # 上证380 换成科创综指（上游 index_valuation 无该指数，用实时行情补录，PE/PB 显示"—"）
        indices = _swap_380_for_star_board(indices)
        indices = _enrich_valuation_with_history(indices)
        if category:
            indices = [idx for idx in indices if idx.get("category") == category]
        print(f"[Indices] 成功获取 {len(indices)} 个指数估值")
        return indices, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")

    print("[Indices] 获取失败，返回空列表(不再使用 mock 数据)")
    return [], gateway_no_data_meta()


def _index_sina_symbol(code: str) -> str:
    """将指数数字代码转换为新浪日线接口所需的前缀代码(sh/sz/bj)"""
    code = (code or "").strip()
    if code[:2] in ("sh", "sz", "bj"):
        return code
    if code.startswith(("399", "39")):
        return "sz" + code
    if code.startswith("899"):
        return "bj" + code
    # 其余(000xxx、6xxxxx、88xxxx 等)按上证处理
    return "sh" + code


def get_index_history(
    code: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """指数 K 线(真实数据, 新浪日线)"""
    points = _fetch_real_kline(
        "stock_zh_index_daily",
        {"symbol": _index_sina_symbol(code)},
        count=300,
    )
    return _filter_by_date_range(points, start_date, end_date)


# ============================================================
# 指数估值历史（乐咕乐股 stock_index_pe_lg / stock_index_pb_lg 真实序列）
# 供指数估值分析页画真实 PE/PB 估值带，取代前端模拟曲线。
# ============================================================

_VALUATION_HIST_CACHE: dict[str, tuple[float, list[dict]]] = {}
_VALUATION_HIST_TTL = 1800  # 30分钟缓存（上游序列每日更新，无需更频繁拉取）


def get_index_valuation_history(name: str, indicator: str = "pe") -> tuple[list[dict], dict]:
    """指数估值历史序列（真实数据，乐咕乐股），返回 (data, meta)

    Args:
        name: 指数名称（上游 symbol，如"沪深300""中证1000"）
        indicator: pe → 滚动市盈率(PE TTM)；pb → 市净率(PB)

    Returns:
        ([{date, value, index_level}] 按日期升序, meta)；不支持的指数返回空列表，绝不伪造。
    """
    name = (name or "").strip()
    if not name:
        return [], _build_meta(False, "参数缺失")
    if USE_MOCK_DATA:
        return [], _build_meta(True, "MOCK(模拟数据)")

    method = "stock_index_pe_lg" if indicator == "pe" else "stock_index_pb_lg"
    cache_key = f"{method}:{name}"
    now = time.time()
    cached = _VALUATION_HIST_CACHE.get(cache_key)
    if cached and now - cached[0] < _VALUATION_HIST_TTL:
        return cached[1], _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST}) 缓存")

    rows = _akshare_request(method, {"symbol": name}, retries=1, timeout=20)
    if not rows or not isinstance(rows, list):
        return [], _build_meta(False, "无可用数据(该指数无估值历史源)")

    value_key = "滚动市盈率" if indicator == "pe" else "市净率"
    out: list[dict] = []
    for row in rows:
        date = str(row.get("日期", ""))[:10]
        value = _safe_float_or_none(row.get(value_key))
        if not date or value is None:
            continue
        out.append({
            "date": date,
            "value": value,
            "index_level": _safe_float_or_none(row.get("指数")),
        })
    out.sort(key=lambda x: x["date"])
    _VALUATION_HIST_CACHE[cache_key] = (now, out)
    print(f"[ValuationHist] {name} {indicator.upper()} 序列 {len(out)} 条 ({out[0]['date']} ~ {out[-1]['date']})" if out else f"[ValuationHist] {name} {indicator.upper()} 无有效数据")
    return out, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")


def get_kline(
    code: str,
    type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    count: int = 50,
) -> list[dict]:
    """个股/ETF/可转债 K 线(真实数据)

    股票/ETF: 东财 stock_zh_a_hist, adjust="qfq" 前复权——分红除息造成的价格跳空
    被平滑，技术指标(MA/RSI/布林)与历史胜率统计必须基于复权价，否则失真。
    前复权以最新价为锚，当前价格显示不受影响。

    可转债(代码 11/12 开头 6 位，或显式 type="cb")：东财股票接口不支持转债，
    走新浪 bond_zh_hs_daily 全量历史（转债不分红除息，价格序列天然连续无需复权），
    再按日期区间过滤。默认窗口与股票一致(近 365 天)。

    count: 保留最近 N 根 K 线；传 0 返回区间内全部。
    """
    today = datetime.now()
    start = start_date.replace("-", "") if start_date else (today - timedelta(days=365)).strftime("%Y%m%d")
    end = end_date.replace("-", "") if end_date else today.strftime("%Y%m%d")

    # 转债路由：SH 转债 110/111/113/118，SZ 转债 123/127/128 → 前缀 11=sh / 12=sz
    if type == "cb" or (len(code) == 6 and code[:2] in {"11", "12"}):
        prefix = "sh" if code.startswith("11") else "sz"
        points = _fetch_real_kline("bond_zh_hs_daily", {"symbol": f"{prefix}{code}"}, count=0)
        points = _filter_by_date_range(
            points,
            start_date or (today - timedelta(days=365)).strftime("%Y-%m-%d"),
            end_date or today.strftime("%Y-%m-%d"),
        )
        return points[-count:] if count else points

    params = {
        "symbol": code,
        "period": "daily",
        "start_date": start,
        "end_date": end,
        "adjust": "qfq",
    }
    points = _fetch_real_kline("stock_zh_a_hist", params, count=count)
    return _filter_by_date_range(points, start_date, end_date)


# ============================================================
# 贵金属: 黄金/白银现货价格 + 金银比
# ============================================================

# 贵金属缓存(5分钟): SGE 历史每次拉全量(~2500行), 加缓存避免频繁打 AkShare
_PRECIOUS_CACHE: dict = {"data": None, "ts": 0, "lock": threading.Lock()}
_PRECIOUS_TTL = 300


def get_precious_metals_with_meta() -> tuple[dict, dict]:
    """黄金/白银现货价格 + 金银比（上海黄金交易所 Au99.99 / Ag99.99）

    单位说明: SGE 黄金报价 元/克, 白银报价 元/千克。计算金银比前需统一单位,
    后端将白银折算为 元/克(÷1000)。金银比 = 黄金价(元/克) / 白银价(元/克), 无量纲。

    数据源: AkShare spot_hist_sge (经 AkShare WebAPI /api/ak 代理)。
    取数失败时返回 available=False, 绝不返回伪造数据。
    """
    if USE_MOCK_DATA:
        return {}, _build_meta(True, "MOCK(模拟数据)")

    with _PRECIOUS_CACHE["lock"]:
        if _PRECIOUS_CACHE["data"] is not None and (time.time() - _PRECIOUS_CACHE["ts"]) < _PRECIOUS_TTL:
            return _PRECIOUS_CACHE["data"], _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")

    gold_rows = _akshare_request("spot_hist_sge", {"symbol": "Au99.99"}, timeout=20)
    silver_rows = _akshare_request("spot_hist_sge", {"symbol": "Ag99.99"}, timeout=20)

    if not gold_rows or not silver_rows:
        # 抓取失败: 若有旧缓存则复用, 否则返回空(前端走错误/空态)
        with _PRECIOUS_CACHE["lock"]:
            if _PRECIOUS_CACHE["data"] is not None:
                return _PRECIOUS_CACHE["data"], _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST}) (旧缓存)")
        return {"available": False}, gateway_no_data_meta()

    # --- 黄金 (元/克) ---
    g_last = gold_rows[-1]
    g_prev = gold_rows[-2] if len(gold_rows) > 1 else None
    g_price = _safe_float(g_last.get("close"), None)
    g_change = None
    if g_prev:
        p = _safe_float(g_prev.get("close"), None)
        if p:
            g_change = round((g_price - p) / p * 100, 2)
    gold_hist = [
        {"date": r.get("date"), "price": _safe_float(r.get("close"), None)}
        for r in gold_rows
    ]

    # --- 白银 (元/千克 → 折算 元/克) ---
    s_last = silver_rows[-1]
    s_prev = silver_rows[-2] if len(silver_rows) > 1 else None
    s_price_raw = _safe_float(s_last.get("close"), None)       # 元/千克
    s_price = round(s_price_raw / 1000, 2) if s_price_raw else None  # 元/克
    s_change = None
    if s_prev:
        pp = _safe_float(s_prev.get("close"), None)
        if pp:
            s_change = round((s_price_raw - pp) / pp * 100, 2)
    silver_hist = [
        {"date": r.get("date"), "price": round(v / 1000, 2)}
        for r in silver_rows
        if (v := _safe_float(r.get("close"), None)) is not None
    ]

    # --- 金银比: 基于完整对齐窗口(不截断), 以白银(数据更稀缺)为锚匹配黄金 ---
    # 白银全量通常远短于黄金, 用其完整区间可覆盖 SGE 上市以来(约十年)的金银比历史。
    ag_map = {r.get("date"): _safe_float(r.get("close"), None) for r in silver_rows}
    ratio_hist: list[dict] = []
    for r in gold_rows:
        d = r.get("date")
        ag_raw = ag_map.get(d)
        if ag_raw and ag_raw > 0:
            g_close = _safe_float(r.get("close"), None)
            if g_close is None:
                continue
            ratio = g_close / (ag_raw / 1000)
            ratio_hist.append({"date": d, "ratio": round(ratio, 2)})

    current_ratio = ratio_hist[-1]["ratio"] if ratio_hist else None

    data = {
        "available": True,
        "updated_at": g_last.get("date"),
        "note": "黄金 SGE Au99.99 (元/克); 白银 SGE Ag99.99 已折算为元/克(原始报价元/千克); 金银比 = 金价÷银价(同单位)",
        "gold": {
            "name": "黄金现货 Au99.99",
            "symbol": "Au99.99",
            "price": g_price,
            "unit": "元/克",
            "date": g_last.get("date"),
            "change_pct": g_change,
            "history": gold_hist,
        },
        "silver": {
            "name": "白银现货 Ag99.99",
            "symbol": "Ag99.99",
            "price": s_price,
            "unit": "元/克",
            "raw_price": s_price_raw,
            "raw_unit": "元/千克",
            "date": s_last.get("date"),
            "change_pct": s_change,
            "history": silver_hist,
        },
        "ratio": {
            "current": current_ratio,
            "unit": "倍",
            "history": ratio_hist,
        },
    }

    with _PRECIOUS_CACHE["lock"]:
        _PRECIOUS_CACHE["data"] = data
        _PRECIOUS_CACHE["ts"] = time.time()
    return data, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")
