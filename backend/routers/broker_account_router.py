"""Broker account router — 用户自定义券商账号（持仓页筛选/导入选用）。"""

from fastapi import APIRouter, Depends, HTTPException

from models import ApiResponse, BrokerAccountRequest
from services.broker_account_service import (
    create_broker_account,
    delete_broker_account,
    list_broker_accounts,
    update_broker_account,
)
from core.deps import get_current_user

router = APIRouter(prefix="/broker-accounts", tags=["broker-accounts"])


@router.get("", response_model=ApiResponse[list[dict]])
async def get_broker_accounts(user_id: str = Depends(get_current_user)):
    return ApiResponse(data=list_broker_accounts(user_id))


@router.post("", response_model=ApiResponse[dict])
async def add_broker_account(
    body: BrokerAccountRequest,
    user_id: str = Depends(get_current_user),
):
    item = create_broker_account(user_id, body.broker, body.account)
    if item is None:
        raise HTTPException(status_code=409, detail="该券商账号已存在")
    return ApiResponse(data=item)


@router.put("/{account_id}", response_model=ApiResponse[dict])
async def edit_broker_account(
    account_id: str,
    body: BrokerAccountRequest,
    user_id: str = Depends(get_current_user),
):
    item = update_broker_account(user_id, account_id, body.broker, body.account)
    if item is None:
        raise HTTPException(status_code=404, detail="券商账号不存在")
    return ApiResponse(data=item)


@router.delete("/{account_id}", response_model=ApiResponse[dict])
async def remove_broker_account(
    account_id: str,
    user_id: str = Depends(get_current_user),
):
    if not delete_broker_account(user_id, account_id):
        raise HTTPException(status_code=404, detail="券商账号不存在")
    return ApiResponse(data={"deleted": True})
