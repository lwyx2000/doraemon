"""统一的 meta 构造工具。

后端各 service 在「取数成功 / mock / 网关无数据」三种状态下，应返回一致的 meta 结构，
供前端区分展示：
- 真实数据：  {"isMock": False, "dataSource": "AkShare WebAPI (host)", "gatewayEmpty": False, ...}
- mock 数据： {"isMock": True,  "dataSource": "MOCK(模拟数据)",            "gatewayEmpty": False, ...}
- 网关无数据：{"isMock": False, "dataSource": "网关无数据",                "gatewayEmpty": True,  ...}

前端据此判断：gatewayEmpty=True 且非 mock → 显示「网关无数据」；
gatewayEmpty=False 且数据为空 → 可能是正常空（如用户无持仓），显示「暂无数据」。
"""

from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def gateway_no_data_meta(note: str = "网关无数据") -> dict[str, Any]:
    """网关取数失败 / 返回空时使用的标准 meta。

    gatewayEmpty=True 让前端明确区分「网关没给数据」与「本就该为空」。
    """
    return {
        "isMock": False,
        "dataSource": "网关无数据",
        "gatewayEmpty": True,
        "updateTime": None,
        "mockTime": None,
        "note": note,
    }


def real_meta(host: str, note: str = "") -> dict[str, Any]:
    """真实取数成功时的标准 meta。"""
    return {
        "isMock": False,
        "dataSource": f"AkShare WebAPI ({host})",
        "gatewayEmpty": False,
        "updateTime": _now(),
        "mockTime": None,
        "note": note,
    }


def real_meta_base(base: str, note: str = "") -> dict[str, Any]:
    """真实取数成功时的标准 meta，host 由 AKSHARE_API_BASE 派生。"""
    host = base.rstrip("/").split("://")[-1]
    return real_meta(host, note)


def mock_meta(note: str = "MOCK(模拟数据)") -> dict[str, Any]:
    """mock/离线模式下的标准 meta。"""
    return {
        "isMock": True,
        "dataSource": note,
        "gatewayEmpty": False,
        "updateTime": None,
        "mockTime": _now(),
        "note": note,
    }
