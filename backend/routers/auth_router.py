"""Auth router — login, register & password change endpoints."""

from fastapi import APIRouter, Depends

from models import ApiResponse, LoginRequest, LoginResponse, RegisterRequest, ChangePasswordRequest
from services.auth_service import authenticate, register, change_password
from core.deps import get_current_user

router = APIRouter(tags=["auth"])


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
    """修改当前登录用户的密码（user_id 即 JWT sub 用户名）。"""
    data = change_password(user_id, body.old_password, body.new_password)
    return ApiResponse(data=data)
