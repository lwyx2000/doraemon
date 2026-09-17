"""FastAPI dependencies: authentication, database access."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from core.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS, USE_MOCK_DATA, ADMIN_USERS

# mock 数据模式下前端不携带 token，使用固定 demo 用户，
# 使受保护的接口（favorites / portfolios / alerts / strategies / ai）也能正常返回数据。
# 注意：业务表 fk_user 为 BIGINT 类型，因此 demo 用户也必须是合法整数，否则写入/查询会因
# 类型转换失败而 500。
DEMO_USER_ID = "1"
from database.connection import get_db, Database

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"/api/v1/auth/login", auto_error=False)



def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=JWT_EXPIRE_HOURS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _unauthorized(detail: str = "未登录或登录已过期") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _resolve_user(token: Optional[str], require_admin: bool = False) -> str:
    """解码并校验 JWT，返回 user_id（str）。

    - token 缺失/非法 → 401
    - require_admin 且非管理员 → 403
    - token 中的 token_version 与数据库不一致（被重置/改密）→ 401（旧 token 立即失效）
    """
    if token is None:
        raise _unauthorized()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise _unauthorized("无效或过期的登录凭证")
    user_id = payload.get("sub")
    if not user_id:
        raise _unauthorized("无效的登录凭证")
    if require_admin:
        username = payload.get("username")
        if username not in ADMIN_USERS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="仅管理员可执行此操作",
            )
    # token_version 校验：管理员重置/用户改密后，让已签发 token 立即失效
    token_version = payload.get("token_version")
    db = get_db()
    row = db.fetchone("SELECT token_version FROM biz_users WHERE pk_user = ?", [user_id])
    if row is None:
        raise _unauthorized("用户不存在")
    db_version = int(row[0] or 0)
    if token_version != db_version:
        raise _unauthorized("登录状态已失效，请重新登录")
    return user_id


def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> str:
    """Validate JWT token and return the user identifier.

    默认（真实数据模式）强制鉴权：未携带或无效 token 直接返回 401，
    保护持仓/预警/策略/AI 配置等用户私有数据。
    仅 USE_MOCK_DATA=true（纯演示/离线模式）时，无 token 回退到 demo 用户，
    保证演示环境无需登录也能浏览全部功能。
    """
    if USE_MOCK_DATA:
        if token:
            try:
                payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
                user_id = payload.get("sub")
                if user_id:
                    return user_id
            except JWTError:
                pass
        return DEMO_USER_ID

    return _resolve_user(token, require_admin=False)


def require_admin(token: Optional[str] = Depends(oauth2_scheme)) -> str:
    """管理员依赖：非管理员 → 403；同时通过 token_version 校验防旧 token 复用。

    仅管理员账号可访问账号管理接口（列出用户 / 重置密码）。
    """
    if USE_MOCK_DATA:
        return DEMO_USER_ID
    return _resolve_user(token, require_admin=True)


def get_optional_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    """Return user ID if token is valid, otherwise None (for optional auth)."""
    if token is None:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
