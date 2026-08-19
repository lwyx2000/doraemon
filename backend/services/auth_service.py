"""Authentication service — login and JWT token generation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from core.deps import create_access_token

# Demo users (hardcoded for development)
DEMO_USERS: dict[str, str] = {
    "trader": "trader123",
}

# 注册用户（进程级内存存储，重启清空；demo 阶段使用）
REGISTERED_USERS: dict[str, str] = {}


def _build_token(username: str) -> dict:
    token = create_access_token({"sub": username})
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    return {"token": token, "expires_at": expires_at, "username": username}


def authenticate(username: str, password: str) -> dict:
    """Validate credentials and return a JWT token.

    Args:
        username: Demo username.
        password: Demo password.

    Returns:
        Dict with ``token``, ``expires_at`` (ISO format, 24h from now) and ``username``.

    Raises:
        HTTPException: 401 if credentials are invalid.
    """
    if DEMO_USERS.get(username) != password and REGISTERED_USERS.get(username) != password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="",
        )

    return _build_token(username)


def register(username: str, password: str) -> dict:
    """Register a new user (in-memory) and return a JWT token.

    Raises:
        HTTPException: 400 if input invalid or username already exists.
    """
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名和密码不能为空",
        )
    if username in DEMO_USERS or username in REGISTERED_USERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在",
        )

    REGISTERED_USERS[username] = password
    return _build_token(username)


def change_password(username: str, old_password: str, new_password: str) -> dict:
    """修改密码：校验旧密码后更新存储（内存存储，重启清空）。

    Raises:
        HTTPException: 400 新密码不合法；401 旧密码不正确。
    """
    if not new_password or len(new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码至少 6 位",
        )
    if DEMO_USERS.get(username) == old_password:
        DEMO_USERS[username] = new_password
        return {"changed": True, "username": username}
    if REGISTERED_USERS.get(username) == old_password:
        REGISTERED_USERS[username] = new_password
        return {"changed": True, "username": username}
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="旧密码不正确",
    )
