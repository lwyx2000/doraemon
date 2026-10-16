"""Shared AkShare WebAPI client.

统一封装对 AkShare WebAPI 的调用，供各业务服务复用。
遵循“真实优先、失败返回 None”的原则：取数失败时上层应返回空/缺省真实结构，
绝不使用 mock 数据填充。

提供两个入口：
- ``akshare_request``  → 通用方法接口 ``/api/ak?method=...``（AkShare 方法透传）
- ``akshare_api_get``  → 业务接口（如 ``/api/index-valuation/...``），按同一信封解包
"""

from __future__ import annotations

import threading
import time

import requests
from requests.adapters import HTTPAdapter

from core.config import AKSHARE_API_BASE


# ============================================================
# 共享 HTTP Session（连接池 + keep-alive）
# ============================================================
# 背景：原先各处裸 `requests.get()`，每次上游调用都新建 TCP 连接
# （三次握手 + 网关侧 accept），一页 10+ 接口 × 每接口多次上游调用时，
# 短连接开销与 TIME_WAIT 积压明显。改为模块级共享 Session 后：
# - 同一 host 的连接自动复用（keep-alive），省握手；
# - HTTPAdapter 连接池上限 32，覆盖并发扇出（估值补全并行化后峰值更高）。
# requests.Session 的 get/post 在官方文档约定下线程安全（连接池内部加锁），
# 本项目端点均为 sync def（跑在 anyio 线程池），可安全共享。
_session: requests.Session | None = None
_session_lock = threading.Lock()


def get_session() -> requests.Session:
    """返回模块级共享 Session（懒初始化，双检锁）。"""
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is None:
            s = requests.Session()
            adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32)
            s.mount("http://", adapter)
            s.mount("https://", adapter)
            _session = s
    return _session


def akshare_request(
    method: str,
    params: dict | None = None,
    retries: int = 1,
    timeout: int = 8,
) -> list[dict] | dict | None:
    """调用 AkShare WebAPI (/api/ak 通用接口)。

    注意：此接口容易反爬，超时时间不宜过长。

    Args:
        method: AkShare 方法名
        params: 方法参数
        retries: 重试次数
        timeout: 单次超时时间（秒）

    Returns:
        API 返回的数据（通常是 list[dict]），失败返回 None
    """
    url = f"{AKSHARE_API_BASE}/api/ak"
    request_params: dict = {"method": method}
    if params:
        request_params.update(params)

    for attempt in range(retries):
        try:
            print(f"[AkShare Client] 调用 {method} (尝试 {attempt + 1}/{retries}, 超时{timeout}s)...")
            response = get_session().get(url, params=request_params, timeout=timeout)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 200:
                print(f"[AkShare Client] {method} 返回错误: {result.get('message')}")
                return None

            data = result.get("data")
            print(f"[AkShare Client] {method} 成功，返回 {len(data) if isinstance(data, list) else '对象'} 数据")
            return data

        except requests.exceptions.Timeout:
            print(f"[AkShare Client] {method} 超时 (attempt {attempt + 1}/{retries})")
        except requests.exceptions.ConnectionError as e:
            print(f"[AkShare Client] {method} 连接错误: {e} (attempt {attempt + 1}/{retries})")
        except Exception as e:
            print(f"[AkShare Client] {method} 错误: {e} (attempt {attempt + 1}/{retries})")

        if attempt < retries - 1:
            time.sleep(1)

    print(f"[AkShare Client] {method} 所有重试失败")
    return None


def akshare_api_get(
    path: str,
    params: dict | None = None,
    retries: int = 2,
    timeout: int = 15,
) -> list[dict] | dict | None:
    """调用 AkShare WebAPI 的**业务接口**（非 /api/ak 通用方法接口）。

    与 ``akshare_request`` 的差别：直接拼业务路径（如
    ``/api/index-valuation/000300/history``），仍按
    ``{"code":200,"message":"success","data":...}`` 信封解包。

    Args:
        path: 业务路径，可带或不带前导斜杠
        params: 查询参数
        retries: 重试次数
        timeout: 单次超时时间（秒）

    Returns:
        API 返回的 data（dict 或 list），失败返回 None
    """
    if not path.startswith("/"):
        path = "/" + path
    url = f"{AKSHARE_API_BASE}{path}"

    for attempt in range(retries):
        try:
            response = get_session().get(url, params=params, timeout=timeout)
            response.raise_for_status()
            result = response.json()

            if not isinstance(result, dict):
                print(f"[AkShare Client] {path} 响应格式异常")
                return None
            if result.get("code") != 200:
                print(f"[AkShare Client] {path} 返回错误: {result.get('message')}")
                return None

            data = result.get("data")
            if isinstance(data, list):
                print(f"[AkShare Client] {path} 成功，返回 {len(data)} 条")
            elif isinstance(data, dict):
                print(f"[AkShare Client] {path} 成功，返回对象 keys={list(data.keys())[:6]}")
            else:
                print(f"[AkShare Client] {path} 成功")
            return data

        except requests.exceptions.Timeout:
            print(f"[AkShare Client] {path} 超时 (attempt {attempt + 1}/{retries})")
        except requests.exceptions.ConnectionError as e:
            print(f"[AkShare Client] {path} 连接错误: {e} (attempt {attempt + 1}/{retries})")
        except Exception as e:
            print(f"[AkShare Client] {path} 错误: {e} (attempt {attempt + 1}/{retries})")

        if attempt < retries - 1:
            time.sleep(1)

    print(f"[AkShare Client] {path} 所有重试失败")
    return None
