"""Favorite router — user watchlist CRUD endpoints."""

from fastapi import APIRouter, Depends

from models import ApiResponse, FavoriteItem, FavoriteCreate
from services.favorite_service import (
    get_favorites,
    add_favorite,
    delete_favorite,
)
from core.deps import get_current_user

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get("", response_model=ApiResponse[list[FavoriteItem]])
async def list_favorites(user_id: str = Depends(get_current_user)):
    data = get_favorites(user_id)
    return ApiResponse(data=data)


@router.post("", response_model=ApiResponse[FavoriteItem])
async def create_favorite(
    item: FavoriteCreate,
    user_id: str = Depends(get_current_user),
):
    data = add_favorite(user_id, item.code, item.name, item.type, item.note)
    return ApiResponse(data=data)


@router.delete("/{favorite_id}", response_model=ApiResponse[dict])
async def remove_favorite(
    favorite_id: str,
    user_id: str = Depends(get_current_user),
):
    deleted = delete_favorite(user_id, favorite_id)
    if not deleted:
        return ApiResponse(code=404, message="Not found", data=None)
    return ApiResponse(data={"deleted": True})
