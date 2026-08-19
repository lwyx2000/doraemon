"""Monitor service — system dashboard and cache configuration.

All data is mock/in-memory; no database required.
"""

from __future__ import annotations

from typing import Any

# ============================================================
# In-memory state
# ============================================================

_cache_config: dict = {
    "enabled": True,
    "ttl_seconds": 300,
    "max_size": 1000,
    "method": None,
}


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
    return dict(_cache_config)


def get_cache_config(method: str) -> dict:
    """Return the cache configuration for a given method."""
    return {**_cache_config, "method": method}


def update_cache_config(
    enabled: bool,
    ttl_seconds: int,
    max_size: int,
    method: str | None,
) -> dict:
    """Update and return the cache configuration."""
    _cache_config["enabled"] = enabled
    _cache_config["ttl_seconds"] = ttl_seconds
    _cache_config["max_size"] = max_size
    _cache_config["method"] = method
    return dict(_cache_config)
