"""终端 / 券商管理路由（2026-11 重构）。

一个终端（设备/渠道）可挂多个券商；券商的 account 由客户端自传作为主标识，
并补充 name（券商名）/ remark（备注）。

全部接口受 JWT 保护（get_current_user）。

端点：
- GET    /terminals                              列出所有终端（内嵌券商）
- POST   /terminals                              新增终端
- PUT    /terminals/{terminal_id}                更新终端
- DELETE /terminals/{terminal_id}                删除终端（级联删除其券商）
- GET    /terminals/{terminal_id}/brokers        列出该终端下券商
- POST   /terminals/{terminal_id}/brokers        在终端下新增券商
- PUT    /terminals/{terminal_id}/brokers/{id}   更新券商
- DELETE /terminals/{terminal_id}/brokers/{id}   删除券商
- GET    /brokers                                列出用户全部券商（导入下拉用）
"""

from fastapi import APIRouter, Depends, HTTPException

from models import ApiResponse, BrokerRequest, TerminalRequest
from services.terminal_broker_service import (
    create_broker,
    create_terminal,
    delete_broker,
    delete_terminal,
    list_brokers,
    list_terminals,
    update_broker,
    update_terminal,
)
from core.deps import get_current_user

router = APIRouter(prefix="/terminals", tags=["terminals"])


# ---------------- 终端 ----------------

@router.get("", response_model=ApiResponse[list[dict]])
def get_terminals(user_id: str = Depends(get_current_user)):
    """列出当前用户所有终端，每个终端内嵌其券商列表。"""
    return ApiResponse(data=list_terminals(user_id))


@router.post("", response_model=ApiResponse[dict])
def add_terminal(body: TerminalRequest, user_id: str = Depends(get_current_user)):
    """新增终端；同名已存在返回 409。"""
    item = create_terminal(user_id, body.name, body.remark)
    if item is None:
        raise HTTPException(status_code=409, detail="该终端名称已存在或名称不能为空")
    return ApiResponse(data=item)


@router.put("/{terminal_id}", response_model=ApiResponse[dict])
def edit_terminal(terminal_id: str, body: TerminalRequest, user_id: str = Depends(get_current_user)):
    """更新终端；不存在返回 404。"""
    item = update_terminal(user_id, terminal_id, body.name, body.remark)
    if item is None:
        raise HTTPException(status_code=404, detail="终端不存在或名称不能为空")
    return ApiResponse(data=item)


@router.delete("/{terminal_id}", response_model=ApiResponse[dict])
def remove_terminal(terminal_id: str, user_id: str = Depends(get_current_user)):
    """删除终端及其下全部券商；不存在返回 404。"""
    if not delete_terminal(user_id, terminal_id):
        raise HTTPException(status_code=404, detail="终端不存在")
    return ApiResponse(data={"deleted": True})


# ---------------- 券商（嵌套在终端下） ----------------

@router.get("/{terminal_id}/brokers", response_model=ApiResponse[list[dict]])
def get_brokers_in_terminal(terminal_id: str, user_id: str = Depends(get_current_user)):
    """列出某终端下的券商。"""
    return ApiResponse(data=list_brokers(user_id, terminal_id=terminal_id))


@router.post("/{terminal_id}/brokers", response_model=ApiResponse[dict])
def add_broker(terminal_id: str, body: BrokerRequest, user_id: str = Depends(get_current_user)):
    """在终端下新增券商；account（客户端自传）同用户已存在返回 409；终端不存在返回 404。"""
    item = create_broker(user_id, terminal_id, body.name, body.account, body.remark)
    if item is None:
        # 区分终端不存在 / account 重复 / 必填缺失
        if not (body.name and body.account):
            raise HTTPException(status_code=400, detail="券商名与 account 均不能为空")
        # account 重复最可能
        raise HTTPException(status_code=409, detail="该 account（券商账号）已存在或终端不存在")
    return ApiResponse(data=item)


@router.put("/{terminal_id}/brokers/{broker_id}", response_model=ApiResponse[dict])
def edit_broker(terminal_id: str, broker_id: str, body: BrokerRequest, user_id: str = Depends(get_current_user)):
    """更新券商；不存在返回 404；account 与其他券商冲突返回 409。"""
    item = update_broker(
        user_id, broker_id,
        terminal_id=terminal_id, name=body.name, account=body.account, remark=body.remark,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="券商不存在或 account 冲突/无效")
    return ApiResponse(data=item)


@router.delete("/{terminal_id}/brokers/{broker_id}", response_model=ApiResponse[dict])
def remove_broker(terminal_id: str, broker_id: str, user_id: str = Depends(get_current_user)):
    """删除券商；不存在返回 404。"""
    if not delete_broker(user_id, broker_id):
        raise HTTPException(status_code=404, detail="券商不存在")
    return ApiResponse(data={"deleted": True})


# ---------------- 全部券商（导入下拉） ----------------

@router.get("/brokers", response_model=ApiResponse[list[dict]])
def get_all_brokers(user_id: str = Depends(get_current_user)):
    """列出用户全部券商（导入页面下拉选用）。"""
    return ApiResponse(data=list_brokers(user_id))
