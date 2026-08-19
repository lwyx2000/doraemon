"""Account name router — 账户名独立管理（普通/两融/信用等）。"""

from fastapi import APIRouter, Depends, HTTPException

from models import AccountNameRequest
from services.account_name_service import (
    create_account_name,
    delete_account_name,
    list_account_names,
    update_account_name,
)
from core.deps import get_current_user

router = APIRouter(prefix="/account-names", tags=["account-names"])


@router.get("")
async def get_account_names(user_id: str = Depends(get_current_user)):
    """列出当前用户所有账户名。"""
    return {"data": list_account_names(user_id)}


@router.post("")
async def add_account_name(
    body: AccountNameRequest,
    user_id: str = Depends(get_current_user),
):
    """新增账户名；同名已存在返回 409。"""
    item = create_account_name(user_id, body.name)
    if item is None:
        raise HTTPException(status_code=409, detail="该账户名已存在")
    return {"data": item}


@router.put("/{name_id}")
async def edit_account_name(
    name_id: str,
    body: AccountNameRequest,
    user_id: str = Depends(get_current_user),
):
    """更新账户名。"""
    item = update_account_name(user_id, name_id, body.name)
    if item is None:
        raise HTTPException(status_code=404, detail="账户名不存在")
    return {"data": item}


@router.delete("/{name_id}")
async def remove_account_name(
    name_id: str,
    user_id: str = Depends(get_current_user),
):
    """删除账户名。"""
    if not delete_account_name(user_id, name_id):
        raise HTTPException(status_code=404, detail="账户名不存在")
    return {"data": {"deleted": True}}
