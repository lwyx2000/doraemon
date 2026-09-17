"""Auth router — login, register, password change & admin account-management endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from models import ApiResponse, LoginRequest, LoginResponse, RegisterRequest, ChangePasswordRequest
from services.auth_service import (
    authenticate,
    register,
    change_password,
    admin_list_users,
    admin_reset_password,
)
from core.deps import get_current_user, require_admin

router = APIRouter(tags=["auth"])


class AdminUserItem(BaseModel):
    pk_user: int
    username: str
    is_admin: bool
    must_change_password: bool


class AdminListUsersResponse(BaseModel):
    users: list[AdminUserItem]


class AdminResetPasswordRequest(BaseModel):
    username: str
    # 省略则自动生成高强度临时密码（由响应返回给管理员转交用户）
    new_password: Optional[str] = None


@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(request: LoginRequest) -> ApiResponse[LoginResponse]:
    """Authenticate user and return JWT token."""
    data = authenticate(request.username, request.password)
    return ApiResponse(data=LoginResponse(**data))


@router.post("/register", response_model=ApiResponse[LoginResponse])
async def register_endpoint(request: RegisterRequest) -> ApiResponse[LoginResponse]:
    """Register a new user and return JWT token."""
    data = register(request.username, request.password)
    return ApiResponse(data=LoginResponse(**data))


@router.put("/password", response_model=ApiResponse[dict])
async def change_password_endpoint(
    body: ChangePasswordRequest,
    user_id: str = Depends(get_current_user),
) -> ApiResponse[dict]:
    """修改当前登录用户的密码（user_id 即 JWT sub 用户名）。

    常规改密需提供 old_password；被管理员强制改密的用户可只传 new_password。
    """
    data = change_password(user_id, body.new_password, body.old_password)
    return ApiResponse(data=data)


@router.post("/admin/list-users", response_model=ApiResponse[AdminListUsersResponse])
async def admin_list_users_endpoint(
    _: str = Depends(require_admin),
) -> ApiResponse[AdminListUsersResponse]:
    """管理员：列出全部用户（不含密码哈希）。仅管理员可调用。"""
    users = [AdminUserItem(**u) for u in admin_list_users()]
    return ApiResponse(data=AdminListUsersResponse(users=users))


@router.post("/admin/reset-password", response_model=ApiResponse[dict])
async def admin_reset_password_endpoint(
    body: AdminResetPasswordRequest,
    _: str = Depends(require_admin),
) -> ApiResponse[dict]:
    """管理员：重置指定用户密码（强制其下次登录改密，并使旧 token 失效）。仅管理员可调用。"""
    data = admin_reset_password(body.username, body.new_password)
    return ApiResponse(data=data)
