"""Authentication service — login, register, password change, JWT.

用户持久化到 DuckDB 的 biz_users 表，跨重启 / 容器重建保留。
登录 / 注册 / 改密均读写 biz_users，密码以 bcrypt 哈希存储（passlib[bcrypt]）。

关键约定（2026-09-17 改造）：
- JWT 的 sub 一律为 biz_users.pk_user（自增 BIGINT），而非 username。
  这样即便 username 后续变更，所有以 fk_user 绑定的业务数据（持仓 / 设置 / 自选等）都不会失联。
- 业务表统一以 fk_user（BIGINT）引用 biz_users.pk_user；username 仅用于登录入参与人机显示。
"""

from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from passlib.context import CryptContext

from core.config import ADMIN_USERS
from core.deps import create_access_token
from database.connection import get_db

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 首次启动种子账号：仅当库中不存在同名用户时插入（幂等，不会覆盖已有账号）。
# 修改默认密码后重建即可；已存在的账号不受影响。
# 注：sos 为历史注册账号，原内存态已随重建丢失，此处以 sos123 重建，登录后可自行改密。
SEED_USERS: list[tuple[str, str]] = [
    ("trader", "trader123"),
    ("sos", "qwe123"),
]


def _hash(password: str) -> str:
    return _pwd_context.hash(password)


def _verify(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except Exception:
        return False


def _is_admin(username: str) -> bool:
    """用户名是否在管理员清单（环境变量 ADMIN_USERS）中。"""
    return username in ADMIN_USERS


def _fetch_user_fields(pk: str) -> Optional[dict]:
    """按 pk_user 取 (username, must_change_password, token_version)，不存在返回 None。"""
    db = get_db()
    row = db.fetchone(
        "SELECT username, must_change_password, token_version "
        "FROM biz_users WHERE pk_user = ?",
        [pk],
    )
    if not row:
        return None
    return {
        "username": row[0],
        "must_change_password": bool(row[1]),
        "token_version": int(row[2] or 0),
    }


def _generate_temp_password(length: int = 10) -> str:
    """生成高强度临时密码（字母 + 数字）。"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _fetch_hash_by_username(username: str) -> str | None:
    db = get_db()
    row = db.fetchone("SELECT password_hash FROM biz_users WHERE username = ?", [username])
    return row[0] if row else None


def _fetch_pk(username: str) -> str | None:
    """username -> pk_user（UUID 字符串）。不存在返回 None。"""
    db = get_db()
    row = db.fetchone("SELECT pk_user FROM biz_users WHERE username = ?", [username])
    return str(row[0]) if row and row[0] is not None else None


def _fetch_hash_by_pk(pk: str) -> str | None:
    db = get_db()
    row = db.fetchone("SELECT password_hash FROM biz_users WHERE pk_user = ?", [pk])
    return row[0] if row else None


def _fetch_username_by_pk(pk: str) -> str | None:
    db = get_db()
    row = db.fetchone("SELECT username FROM biz_users WHERE pk_user = ?", [pk])
    return row[0] if row else None


def _build_token(
    pk: str,
    username: str,
    must_change_password: bool = False,
    token_version: int = 0,
) -> dict:
    # sub = pk_user（整数）；username / is_admin / token_version 随包下发供前端展示与令牌失效校验。
    token = create_access_token({
        "sub": str(pk),
        "username": username,
        "is_admin": _is_admin(username),
        "token_version": int(token_version),
    })
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    return {
        "token": token,
        "expires_at": expires_at,
        "username": username,
        "is_admin": _is_admin(username),
        "force_change": bool(must_change_password),
    }


def authenticate(username: str, password: str) -> dict:
    """校验凭据并返回 JWT（sub = pk_user）。

    Raises:
        HTTPException: 401 凭据无效 / 用户不存在。
    """
    pk = _fetch_pk(username)
    if pk is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="")
    h = _fetch_hash_by_username(username)
    if h is None or not _verify(password, h):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="")
    fields = _fetch_user_fields(pk)
    must = fields["must_change_password"] if fields else False
    tv = fields["token_version"] if fields else 0
    return _build_token(pk, username, must, tv)


def register(username: str, password: str) -> dict:
    """注册新用户（写入 biz_users）并返回 JWT。

    新注册用户非管理员（管理员仅由环境变量 ADMIN_USERS 决定），
    must_change_password / token_version 取表默认值 FALSE / 0。

    Raises:
        HTTPException: 400 输入非法或用户名已存在。
    """
    if not username or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名和密码不能为空")
    if len(password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="密码至少 6 位")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,50}", username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名仅限字母/数字/下划线，2-50 位")
    if _fetch_pk(username) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在")
    db = get_db()
    db.execute(
        "INSERT INTO biz_users (username, password_hash) VALUES (?, ?)",
        [username, _hash(password)],
    )
    pk = _fetch_pk(username)
    return _build_token(pk, username)


def change_password(
    user_pk: str,
    new_password: str,
    old_password: Optional[str] = None,
) -> dict:
    """修改密码：按 pk_user 校验旧密码后更新哈希。

    支持两种场景：
    - 常规改密：必须提供正确的 old_password。
    - 强制改密（管理员重置后）：用户无旧密码，old_password 可省略；
      且仅当该账号当前 must_change_password = TRUE 时才允许免旧密码改密。

    成功后清除 must_change_password 标记，使下次登录不再强制改密。

    Raises:
        HTTPException: 400 新密码不合法；401 用户不存在 / 旧密码不正确 / 非强制改密却未提供旧密码。
    """
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少 6 位")
    db = get_db()
    h = _fetch_hash_by_pk(user_pk)
    if h is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    fields = _fetch_user_fields(user_pk)
    is_forced = bool(fields["must_change_password"]) if fields else False
    if old_password:
        if not _verify(old_password, h):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="旧密码不正确")
    else:
        # 未提供旧密码：仅允许「被管理员强制改密」的用户免旧密码改密
        if not is_forced:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="请提供旧密码以修改密码",
            )
    db.execute(
        "UPDATE biz_users SET password_hash = ?, must_change_password = FALSE "
        "WHERE pk_user = ?",
        [_hash(new_password), user_pk],
    )
    return {"changed": True, "username": _fetch_username_by_pk(user_pk)}


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


# ============================================================
# 管理员账号管理（仅管理员可调用，由路由层 require_admin 把关）
# ============================================================

def admin_list_users() -> list[dict]:
    """列出全部用户（不含密码哈希）。is_admin 由环境变量 ADMIN_USERS 决定。"""
    db = get_db()
    rows = db.fetchall(
        "SELECT pk_user, username, must_change_password "
        "FROM biz_users ORDER BY pk_user"
    )
    return [
        {
            "pk_user": r[0],
            "username": r[1],
            "is_admin": r[1] in ADMIN_USERS,
            "must_change_password": bool(r[2]),
        }
        for r in rows
    ]


def admin_reset_password(target_username: str, new_password: Optional[str] = None) -> dict:
    """管理员重置指定用户密码。

    - new_password 省略时自动生成高强度临时密码（返回给管理员转交用户）。
    - 重置后强制用户下次登录改密（must_change_password = TRUE）。
    - token_version + 1，使该用户所有已签发 token 立即失效（防旧 token 续用）。
    """
    db = get_db()
    row = db.fetchone(
        "SELECT pk_user, token_version FROM biz_users WHERE username = ?",
        [target_username],
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    pk, tv = row
    if new_password is None:
        new_password = _generate_temp_password()
    if len(new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="密码至少 6 位")
    db.execute(
        "UPDATE biz_users SET password_hash = ?, must_change_password = TRUE, "
        "token_version = ? WHERE pk_user = ?",
        [_hash(new_password), int(tv or 0) + 1, pk],
    )
    return {
        "username": target_username,
        "new_password": new_password,
        "must_change_password": True,
    }
