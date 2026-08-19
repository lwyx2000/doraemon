"""Market data service — macro indicators, index valuations, K-line history.

从 AkShare WebAPI (core.config.AKSHARE_API_BASE) 获取真实数据，无法获取的字段使用 mock 数据填充。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any
import requests
import time

from core.config import AKSHARE_API_BASE, USE_MOCK_DATA
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
            response = requests.get(url, params=request_params, timeout=timeout)
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
        r = requests.get(
            f"{AKSHARE_API_BASE}/api/processed_data",
            params={"category": "market_stats"},
            timeout=timeout,
        )
        return r.status_code == 200
    except Exception:
        return False


def _fetch_jisilu_login_status(timeout: int = _STATUS_CHECK_TIMEOUT) -> bool | None:
    """读取 53 侧 /api/jisilu/auth-status 的严格登录标志；不可用返回 None。"""
    try:
        r = requests.get(
            f"{AKSHARE_API_BASE}/api/jisilu/auth-status",
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("data") or {}
        # 显式 true/false 才采信，字段缺失视为不可用
        if "logged_in" not in data:
            return None
        return bool(data.get("logged_in"))
    except Exception:
        return None


def get_data_source_status() -> dict:
    """数据源连接状态：AkShare WebAPI 可达性 + 集思录登录态(严格)。

    - akshareConnected: 53 服务是否可达。
    - jisiluLoggedIn: 是否真正登录集思录(严格)。
      优先读取 53 侧新增的 /api/jisilu/auth-status（直接依据 Cookie 配置/动态登录
      能力判定，而非"能否取到数据"——游客态也能取到部分数据，故旧推断不可靠）；
      若该接口不可用则回退到旧推断(能否取到 jisilu 数据)。

    两项探测并行执行，超时均缩短为 5s，避免数据源不可达时长时间阻塞设置页。
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        akshare_future = pool.submit(_check_akshare_reachable)
        jisilu_future = pool.submit(_fetch_jisilu_login_status)
        akshare_connected = akshare_future.result()
        jisilu_logged_in = jisilu_future.result()

    if jisilu_logged_in is None:
        # 兜底：旧推断（能否取到 jisilu 数据）
        try:
            r = requests.get(
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
            response = requests.get(url, params=request_params, timeout=timeout)
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
            response = requests.get(url, params=request_params, timeout=30)
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


def _market_status(now: datetime | None = None) -> str:
    """根据当前时间返回 A 股市场交易状态（不再硬编码"开盘中"）"""
    now = now or datetime.now()
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
        "科创综指": "000699",
        "科创板": "000699",
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
    ("科创板", "000699"),
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
    """补齐/替换大盘看板指数：剔除无数据的上证380，确保科创板/科创50/中证A500等存在"""
    by_code: dict[str, dict] = {}
    for idx in indices:
        c = idx.get("code", "")
        if c and c not in by_code:
            by_code[c] = idx

    result = []
    for name, code in _A_SHARE_OVERVIEW_INDICES:
        if code in by_code:
            item = by_code[code]
            # 使用期望展示名称（如上游叫"科创综指"，展示为"科创板"）
            item["name"] = name
            result.append(item)
        else:
            # 缺失时尝试实时行情补录
            quote = _fetch_index_quote(code)
            # 跳过无实时行情的指数（如北证50 上游未返回名称/价格）
            if not quote or not quote.get("name") or quote.get("price") in (None, 0):
                continue
            # 使用期望展示名称（如上游叫"科创200"，展示为"科创板"）
            quote["name"] = name
            # 实时行情补录的指数无估值数据，置 None 让前端显示 '—'
            quote["pe"] = None
            quote["pb"] = None
            quote["pePercentile"] = None
            quote["pbPercentile"] = None
            quote.setdefault("category", "")
            quote.setdefault("change3mPct", 0.0)
            quote.setdefault("winRate", 0.0)
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
    yest_yuan = _safe_float(data.get("yesterday_same_time_turnover")) if data.get("yesterday_same_time_turnover") is not None else None
    total_e = round(total_yuan / 1e8, 2) if total_yuan else 0.0
    sh_e = round(_safe_float(data.get("sh_turnover")) / 1e8, 2) if data.get("sh_turnover") is not None else 0.0
    sz_e = round(_safe_float(data.get("sz_turnover")) / 1e8, 2) if data.get("sz_turnover") is not None else 0.0
    turnover_change_abs = None
    if yest_yuan is not None and yest_yuan > 0:
        turnover_change_abs = round((total_yuan - yest_yuan) / 1e8, 2)
    return {
        "date": data.get("date", datetime.now().strftime("%Y-%m-%d")),
        "totalTurnover": total_e,
        "shTurnover": sh_e,
        "szTurnover": sz_e,
        "turnoverChangePct": _safe_float(data.get("turnover_change_pct")),
        "turnoverChangeAbs": turnover_change_abs,
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
_MACRO_CACHE: dict = {"data": None, "ts": 0, "lock": threading.Lock()}
_MACRO_TTL = 3600


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


def _fetch_10y_history() -> dict[str, float]:
    """分段(<1年/次, akshare bond_china_yield 限制)拉取中债10Y国债收益率历史

    Returns: {date: rate}，取数全失败返回空 dict
    """
    end = datetime.now()
    start = end.replace(year=end.year - 10)
    result: dict[str, float] = {}
    cur = start
    attempts = 0
    while cur < end and attempts < 3:
        attempts += 1
        nxt = min(cur.replace(year=cur.year + 1), end)
        sd = cur.strftime("%Y%m%d")
        ed = nxt.strftime("%Y%m%d")
        df = _akshare_request("bond_china_yield", {"start_date": sd, "end_date": ed}, retries=1, timeout=6)
        if df and isinstance(df, list):
            for row in df:
                d = str(row.get("日期", ""))[:10]
                v = _safe_float(row.get("10年"), None)
                if d and v is not None:
                    result[d] = v
        cur = nxt
    return result


def get_macro_indicators_with_meta() -> tuple[dict, dict]:
    """宏观指标（DR007 / GC001 / ERP）— 全部来自 AkShare 真实数据，取数失败返回空(不再伪造)"""
    if USE_MOCK_DATA:
        return {k: v for k, v in mock_data.MOCK_MACRO_DATA.items() if k in ("erp", "erp_percentile_3y", "erp_percentile_5y", "erp_percentile_10y", "dr007", "gc001")}, _build_meta(True, "MOCK(模拟数据)")
    with _MACRO_CACHE["lock"]:
        if _MACRO_CACHE["data"] is not None and (time.time() - _MACRO_CACHE["ts"]) < _MACRO_TTL:
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
        return {}, _build_meta(False, "无可用数据(取数失败)")

    with _MACRO_CACHE["lock"]:
        _MACRO_CACHE["data"] = result
        _MACRO_CACHE["ts"] = time.time()
    return result, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")


def get_market_overview_with_meta() -> tuple[dict, dict]:
    """市场概况：指数行情 + 涨跌家数 + 成交额"""
    if USE_MOCK_DATA:
        return mock_data.MOCK_MACRO_DATA["marketOverview"], _build_meta(True, "MOCK(模拟数据)")
    realtime_indices, _ = _fetch_index_valuation_data()
    market_stats = get_market_stats_real()

    if market_stats:
        # 成交额变化统一使用绝对值(亿元)：上游提供昨日成交额则直接相减；
        # 只有百分比时，按当前成交额反推近似绝对变化；都没有则置 0。
        total_e = market_stats.get("totalTurnover", 0) or 0
        vol_change = market_stats.get("turnoverChangeAbs")
        if vol_change is None:
            pct = market_stats.get("turnoverChangePct")
            if pct is not None and total_e:
                vol_change = round(total_e * pct / 100, 2)
            else:
                vol_change = 0
        data = {
            "date": market_stats["date"],
            "status": _market_status(),
            "indices": realtime_indices,
            "upCount": market_stats["upCount"],
            "downCount": market_stats["downCount"],
            "flatCount": market_stats["flatCount"],
            "totalVolume": market_stats["totalTurnover"],
            "volumeChange": vol_change,
        }
        return data, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")
    if realtime_indices:
        data = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status": _market_status(),
            "indices": realtime_indices,
            "upCount": 0,
            "downCount": 0,
            "flatCount": 0,
            "totalVolume": 0,
            "volumeChange": 0,
        }
        return data, _build_meta(False, "AkShare WebAPI (部分数据)")
    # 取数失败：返回空数据(绝不返回伪造数据)，前端走错误/空态
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "status": "数据获取中",
        "indices": [],
        "upCount": 0,
        "downCount": 0,
        "flatCount": 0,
        "totalVolume": 0,
        "volumeChange": 0,
    }, _build_meta(False, "无可用数据(取数失败)")


def get_sw_sectors() -> tuple[list[dict], dict]:
    """申万一级行业基础数据（实时涨跌幅 + PE / PB / 股息率），用于行业热力图。

    数据源：本地 akshare（免费、无需 token），不走 AkShare WebAPI 网关。
      - ``index_realtime_sw(symbol='一级行业')`` 取 31 个申万一级行业实时价 → 计算涨跌幅；
      - ``sw_index_first_info()`` 取各行业的 PE / PB / 股息率 / 成份数。
    网关（192.168.3.53:8000）未映射任何申万行业方法（sw_index_spot / index_hist_sw 等
    均返回 500），故这里直接调用本地 akshare。
    """
    if USE_MOCK_DATA:
        return [], _build_meta(True, "MOCK(模拟数据)")

    try:
        import akshare as ak
    except Exception as e:  # pragma: no cover
        return [], _build_meta(False, f"本地 akshare 不可用: {e}")

    # 1) 实时一级行业（最新价 / 昨收盘）
    try:
        rt = ak.index_realtime_sw(symbol="一级行业")
    except Exception as e:
        return [], _build_meta(False, f"AkShare index_realtime_sw 失败: {e}")
    if rt is None or len(rt) == 0:
        return [], _build_meta(False, "AkShare 无申万实时返回")

    rt_map: dict[str, dict] = {}
    for _, row in rt.iterrows():
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

    # 2) 一级行业估值（PE / PB / 股息率 / 成份数）
    val_map: dict[str, dict] = {}
    try:
        first = ak.sw_index_first_info()
        if first is not None and len(first) > 0:
            for _, row in first.iterrows():
                val_map[row.get("行业名称")] = {
                    "count": _safe_int(row.get("成份个数")),
                    "pe": _safe_float(row.get("静态市盈率")),
                    "ttm_pe": _safe_float(row.get("TTM(滚动)市盈率")),
                    "pb": _safe_float(row.get("市净率")),
                    "dividend_yield": _safe_float(row.get("静态股息率")),
                }
    except Exception:
        val_map = {}  # 估值取不到不影响涨跌幅热力图

    # 3) 合并（以实时行情为主，估值缺失则补 None）
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

    return sectors, _build_meta(False, "AkShare 本地 (index_realtime_sw)")


def _save_sw_sector_snapshot(sectors: list[dict]) -> None:
    """将申万一级行业快照写入 DuckDB base_sw_sector_daily 表。

    同一行业同一交易日仅保留一条记录（UNIQUE 约束去重）。
    写入失败不影响主流程（热力图照常返回）。
    """
    if not sectors:
        return
    try:
        from database.connection import get_db
        from datetime import date as _date

        db = get_db()
        today_str = _date.today().isoformat()
        for s in sectors:
            db.execute(
                """
                INSERT OR REPLACE INTO base_sw_sector_daily
                    (sector_code, sector_name, trade_date, price, prev_close, change_pct, pe, ttm_pe, pb, dividend_yield, count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    s.get("code", ""),
                    s.get("name", ""),
                    today_str,
                    s.get("price"),
                    s.get("prev_close"),
                    s.get("change_pct"),
                    s.get("pe"),
                    s.get("ttm_pe"),
                    s.get("pb"),
                    s.get("dividend_yield"),
                    s.get("count"),
                ],
            )
    except Exception:
        pass  # 写入失败不影响热力图展示


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
        rows = db.fetchall(
            """
            SELECT sector_code, sector_name, trade_date, change_pct, price, pe, pb, dividend_yield
            FROM base_sw_sector_daily
            WHERE trade_date >= (
                SELECT MIN(trade_date) FROM (
                    SELECT DISTINCT trade_date FROM base_sw_sector_daily
                    ORDER BY trade_date DESC LIMIT ?
                ) t
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


def get_board_sectors_with_meta() -> tuple[list, dict]:
    """板块涨幅排行"""
    if USE_MOCK_DATA:
        return mock_data.MOCK_MACRO_DATA["boardSectors"], _build_meta(True, "MOCK(模拟数据)")
    sectors = get_board_sectors_real()
    if sectors:
        return sectors, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")
    return [], _build_meta(False, "无可用数据(取数失败)")


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
    }, _build_meta(False, "无可用数据(取数失败)")


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
    }, _build_meta(False, "无可用数据(取数失败)")


def get_fund_ranking_with_meta() -> tuple[list, dict]:
    """基金涨跌排行"""
    if USE_MOCK_DATA:
        return mock_data.MOCK_MACRO_DATA["fundRanking"], _build_meta(True, "MOCK(模拟数据)")
    ranking = get_fund_ranking_real()
    if ranking:
        return ranking, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")
    return [], _build_meta(False, "无可用数据(取数失败)")


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


def _fetch_index_valuation_data() -> tuple[list[dict], list[dict]]:
    """一次性获取指数估值数据，返回 (realtime_indices, indices_valuation) 两种格式

    realtime_indices: 用于 marketOverview.indices (MarketIndex 格式，仅 A 股核心指数)
    indices_valuation: 用于跨市场指数估值表 (IndexValuation 格式)
    """
    data = _processed_data_request("index_valuation", {"subtype": "all", "period": 5}, retries=1, timeout=15)

    if not data or not isinstance(data, list):
        return [], []

    # 1. 统一先转成 MarketIndex 格式
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
            "pe": _safe_float(item.get("pe")),
            "pb": _safe_float(item.get("pb")),
            "pePercentile": _safe_float(item.get("pe_percentile")),
            "pbPercentile": _safe_float(item.get("pb_percentile")),
            "category": item.get("category", ""),
            "change3mPct": _safe_float(item.get("3m_change_pct")),
            "winRate": _safe_float(item.get("win_rate")),
        })

    # 2. 分离 A 股与跨市场指数，补齐 A 股核心指数
    a_share_items = [it for it in raw_items if _is_a_share_index(it)]
    other_items = [it for it in raw_items if not _is_a_share_index(it)]

    realtime_indices = _ensure_overview_indices(a_share_items)
    all_items = realtime_indices + other_items

    # 3. 生成跨市场估值表数据
    indices_valuation = []
    for it in all_items:
        pe_pct = _safe_float(it.get("pePercentile"))
        if pe_pct < 20:
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
            "level": it.get("price", 0),
            "change_pct": it.get("changePct", 0),
            "pe": it.get("pe"),
            "pe_percentile": it.get("pePercentile"),
            "pb": it.get("pb"),
            "pb_percentile": it.get("pbPercentile"),
            "category": cat,
            "change_3m_pct": it.get("change3mPct", 0),
            "win_rate": it.get("winRate", 0),
            "hasValuation": it.get("hasValuation", True),
            "market": _market_by_code_or_name(it),
        })

    return realtime_indices, indices_valuation





def _map_index_valuation(data: list, category: str | None = None) -> list[dict]:
    """将 index_valuation 原始数据映射为前端 IndexValuation 格式，并按 category 过滤"""
    indices = []
    for item in data:
        # 根据PE百分位判断估值类别
        pe_pct = _safe_float(item.get("pe_percentile"))
        if pe_pct < 20:
            cat = "opportunity"  # 极度低估
        elif pe_pct < 40:
            cat = "undervalued"  # 低估
        elif pe_pct > 80:
            cat = "overvalued"   # 高估
        else:
            cat = "normal"       # 正常

        indices.append({
            "name": item.get("index_name", ""),
            "code": _get_index_code(item.get("index_name", "")),
            "level": _safe_float(item.get("latest_price")),  # 当前点位(上游 latest_price)
            "change_pct": _safe_float(item.get("chg_pct")),
            "pe": _safe_float(item.get("pe")),
            "pe_percentile": pe_pct,
            "pb": _safe_float(item.get("pb")),
            "pb_percentile": _safe_float(item.get("pb_percentile")),
            "category": cat,
            "change_3m_pct": _safe_float(item.get("3m_change_pct")),
            "win_rate": _safe_float(item.get("win_rate")),
        })

    if category:
        indices = [idx for idx in indices if idx.get("category") == category]
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

    data = _processed_data_request("index_valuation", {"subtype": "all", "period": 5}, retries=1, timeout=15)

    if data and isinstance(data, list):
        indices = _map_index_valuation(data, category)
        print(f"[Indices] 成功获取 {len(indices)} 个指数估值")
        return indices, _build_meta(False, f"AkShare WebAPI ({AKSHARE_HOST})")

    print("[Indices] 获取失败，返回空列表(不再使用 mock 数据)")
    return [], _build_meta(False, "无可用数据(取数失败)")


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


def get_kline(
    code: str,
    type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """个股/ETF K 线(真实数据, 东财 stock_zh_a_hist)"""
    today = datetime.now()
    start = start_date.replace("-", "") if start_date else (today - timedelta(days=365)).strftime("%Y%m%d")
    end = end_date.replace("-", "") if end_date else today.strftime("%Y%m%d")
    params = {
        "symbol": code,
        "period": "daily",
        "start_date": start,
        "end_date": end,
        "adjust": "",
    }
    points = _fetch_real_kline("stock_zh_a_hist", params)
    return _filter_by_date_range(points, start_date, end_date)


# ============================================================
# 贵金属: 黄金/白银现货价格 + 金银比
# ============================================================

# 贵金属缓存(5分钟): SGE 历史每次拉全量(~2500行), 加缓存避免频繁打 AkShare
_PRECIOUS_CACHE: dict = {"data": None, "ts": 0, "lock": threading.Lock()}
_PRECIOUS_TTL = 300
# 走势图展示用的历史长度(近 1 年交易日)
_PRECIOUS_HISTORY_N = 250


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
        return {"available": False}, _build_meta(False, "无可用数据(取数失败)")

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
        {"date": r.get("date"), "price": round(_safe_float(r.get("close"), None) / 1000, 2)}
        for r in silver_rows
    ]

    # --- 金银比: 基于完整对齐窗口(不截断), 以白银(数据更稀缺)为锚匹配黄金 ---
    # 白银全量通常远短于黄金, 用其完整区间可覆盖 SGE 上市以来(约十年)的金银比历史。
    ag_map = {r.get("date"): _safe_float(r.get("close"), None) for r in silver_rows}
    ratio_hist: list[dict] = []
    for r in gold_rows:
        d = r.get("date")
        ag_raw = ag_map.get(d)
        if ag_raw and ag_raw > 0:
            ratio = _safe_float(r.get("close"), None) / (ag_raw / 1000)
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
