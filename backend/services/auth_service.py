"""Authentication service — login, register, password change, JWT.

用户持久化到 DuckDB 的 biz_users 表，跨重启 / 容器重建保留。
登录 / 注册 / 改密均读写 biz_users，密码以 bcrypt 哈希存储（passlib[bcrypt]）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from passlib.context import CryptContext

from core.deps import create_access_token
from database.connection import get_db

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 首次启动种子账号：仅当库中不存在同名用户时插入（幂等，不会覆盖已有账号）。
# 修改默认密码后重建即可；已存在的账号不受影响。
# 注：sos 为历史注册账号，原内存态已随重建丢失，此处以 sos123 重建，登录后可自行改密。
SEED_USERS: list[tuple[str, str]] = [
    ("trader", "trader123"),
    ("sos", "sos123"),
]


def _hash(password: str) -> str:
    return _pwd_context.hash(password)


def _verify(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except Exception:
        return False


def _build_token(username: str) -> dict:
    token = create_access_token({"sub": username})
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    return {"token": token, "expires_at": expires_at, "username": username}


def _fetch_hash(username: str) -> str | None:
    db = get_db()
    row = db.fetchone("SELECT password_hash FROM biz_users WHERE username = ?", [username])
    return row[0] if row else None


def _username_exists(username: str) -> bool:
    db = get_db()
    row = db.fetchone("SELECT 1 FROM biz_users WHERE username = ?", [username])
    return row is not None


def authenticate(username: str, password: str) -> dict:
    """校验凭据并返回 JWT。

    Raises:
        HTTPException: 401 凭据无效 / 用户不存在。
    """
    h = _fetch_hash(username)
    if h is None or not _verify(password, h):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="",
        )
    return _build_token(username)


def register(username: str, password: str) -> dict:
    """注册新用户（写入 biz_users）并返回 JWT。

    Raises:
        HTTPException: 400 输入非法或用户名已存在。
    """
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名和密码不能为空",
        )
    if len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码至少 6 位",
        )
    if not re.fullmatch(r"[A-Za-z0-9_]{2,50}", username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名仅限字母/数字/下划线，2-50 位",
        )
    if _username_exists(username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在",
        )
    db = get_db()
    db.execute(
        "INSERT INTO biz_users (username, password_hash) VALUES (?, ?)",
        [username, _hash(password)],
    )
    return _build_token(username)


def change_password(username: str, old_password: str, new_password: str) -> dict:
    """修改密码：校验旧密码后更新 biz_users 中的哈希。

    Raises:
        HTTPException: 400 新密码不合法；401 用户不存在或旧密码不正确。
    """
    if not new_password or len(new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码至少 6 位",
        )
    db = get_db()
    row = db.fetchone("SELECT password_hash FROM biz_users WHERE username = ?", [username])
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    if not _verify(old_password, row[0]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="旧密码不正确",
        )
    db.execute(
        "UPDATE biz_users SET password_hash = ? WHERE username = ?",
        [_hash(new_password), username],
    )
    return {"changed": True, "username": username}


def ensure_seed_users(db) -> None:
    """启动期幂等种子默认账号（trader / sos）。

    使用 INSERT ... WHERE NOT EXISTS，即使并发启动也保证不重复、不覆盖。
    """
    for username, password in SEED_USERS:
        db.execute(
            "INSERT INTO biz_users (username, password_hash) "
            "SELECT ?, ? WHERE NOT EXISTS ("
            "SELECT 1 FROM biz_users WHERE username = ?)",
            [username, _hash(password), username],
        )
