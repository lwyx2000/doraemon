"""Auth router — login endpoint."""

from fastapi import APIRouter

from models import ApiResponse, LoginRequest, LoginResponse
from services.auth_service import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(request: LoginRequest) -> ApiResponse[LoginResponse]:
    """Authenticate user and return JWT token."""
    data = authenticate(request.username, request.password)
    return ApiResponse(data=LoginResponse(**data))
