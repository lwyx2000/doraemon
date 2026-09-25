"""Monitor service — system dashboard and cache configuration.

缓存配置持久化到 DuckDB 的 biz_config 表（key=monitor_cache_config），重启保留；
内存字典 _cache_config 为运行态，启动时由 load_cache_config() 从库加载，更新时同步落库。
"""

from __future__ import annotations

import json
from typing import Any

from database.connection import get_db

# 缓存配置在 biz_config 表中的键
_CACHE_CONFIG_KEY = "monitor_cache_config"

# 默认缓存配置（库中没有时回退，并作为首次落库的初始值）
_DEFAULT_CACHE_CONFIG: dict = {
    "enabled": True,
    "ttl_seconds": 300,
    "max_size": 1000,
    "method": None,
}

# ============================================================
# In-memory state（运行态，启动时由 load_cache_config 填充）
# ============================================================

_cache_config: dict = dict(_DEFAULT_CACHE_CONFIG)
_loaded: bool = False


def load_cache_config() -> None:
    """从 biz_config 表加载缓存配置到内存（幂等，进程内只真正读库一次）。

    库中存在则覆盖内存默认值；不存在则保持默认并写入库（保证后续可见）。
    """
    global _cache_config, _loaded
    if _loaded:
        return
    try:
        db = get_db()
        row = db.fetchone(
            "SELECT value_json FROM biz_config WHERE key = ?", [_CACHE_CONFIG_KEY]
        )
        if row and row[0] is not None:
            stored = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            if isinstance(stored, dict):
                merged = dict(_DEFAULT_CACHE_CONFIG)
                merged.update(stored)
                _cache_config = merged
        else:
            # 库中没有 → 用当前默认落库，确保下次启动能读到
            _persist_cache_config()
    except Exception as e:
        # 读库失败不应阻断启动：保留内存默认
        print(f"[WARN] load_cache_config failed, keep defaults: {e}")
    _loaded = True


def _persist_cache_config() -> None:
    """将内存 _cache_config 原子 upsert 到 biz_config（ON CONFLICT 指定 PK，安全）。"""
    db = get_db()
    payload = json.dumps(_cache_config, ensure_ascii=False)
    db.execute(
        "INSERT INTO biz_config (key, value_json, updated_at) VALUES (?, ?, now()) "
        "ON CONFLICT (key) DO UPDATE SET value_json = excluded.value_json, "
        "updated_at = excluded.updated_at",
        [_CACHE_CONFIG_KEY, payload],
    )


# ============================================================
# Dashboard
# ============================================================

def get_monitor_dashboard() -> dict:
    """Return mock dashboard data with system metrics and service statuses."""
    return {
        "system_uptime": "7d 12h 34m",
        "api_calls_today": 15234,
        "cache_hit_rate": 87.5,
        "active_connections": 12,
        "last_error": None,
        "services": [
            {"name": "API Server", "status": "healthy", "latency_ms": 12},
            {"name": "Database", "status": "healthy", "latency_ms": 8},
            {"name": "Cache (Redis)", "status": "healthy", "latency_ms": 3},
            {"name": "Data Feed", "status": "degraded", "latency_ms": 245},
        ],
    }


# ============================================================
# Cache config
# ============================================================

def get_all_cache_config() -> dict:
    """Return the global cache configuration (not tied to a specific method)."""
    load_cache_config()  # 幂等，确保内存态已从库加载
    return dict(_cache_config)


def get_cache_config(method: str) -> dict:
    """Return the cache configuration for a given method."""
    load_cache_config()
    return {**_cache_config, "method": method}


def update_cache_config(
    enabled: bool,
    ttl_seconds: int,
    max_size: int,
    method: str | None,
) -> dict:
    """Update and persist the cache configuration."""
    _cache_config["enabled"] = enabled
    _cache_config["ttl_seconds"] = ttl_seconds
    _cache_config["max_size"] = max_size
    _cache_config["method"] = method
    try:
        _persist_cache_config()
    except Exception as e:
        print(f"[WARN] update_cache_config persist failed: {e}")
    return dict(_cache_config)
