"""FastAPI dependencies: authentication, database access."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from core.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS, USE_MOCK_DATA

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

    if token is None:
        raise _unauthorized()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise _unauthorized("无效的登录凭证")
        return user_id
    except JWTError:
        raise _unauthorized("无效或过期的登录凭证")


def get_optional_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    """Return user ID if token is valid, otherwise None (for optional auth)."""
    if token is None:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
