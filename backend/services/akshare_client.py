"""Shared AkShare WebAPI client.

统一封装对 AkShare WebAPI (/api/ak 通用接口) 的调用，供各业务服务复用。
遵循“真实优先、失败返回 None”的原则：取数失败时上层应返回空/缺省真实结构，
绝不使用 mock 数据填充。
"""

from __future__ import annotations

import time

import requests

from core.config import AKSHARE_API_BASE


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
            response = requests.get(url, params=request_params, timeout=timeout)
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
