"""Holdings router — 多券商统一持仓：查询/导入/变更/删除/快照。"""

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from models import ApiResponse, HoldingImportRequest, HoldingUpdate
from services.holdings_service import (
    HOLDING_TYPES,
    build_holdings_view,
    delete_holding,
    get_snapshots,
    import_holdings,
    take_snapshot,
    update_holding,
)
from core.deps import get_current_user

router = APIRouter(prefix="/holdings", tags=["holdings"])


@router.get("", response_model=ApiResponse[dict])
async def list_holdings(
    type: str | None = None,
    broker: str | None = None,
    account: str | None = None,
    user_id: str = Depends(get_current_user),
):
    """持仓明细 + 行情盈亏 + 汇总统计（资产配置/预警），支持按类型/券商/账户过滤。"""
    if type and type not in HOLDING_TYPES:
        raise HTTPException(status_code=400, detail=f"未知持仓类型: {type}")
    data = build_holdings_view(user_id, type_filter=type, broker_filter=broker, account_filter=account)
    return ApiResponse(data=data)


@router.post("/import", response_model=ApiResponse[dict])
async def import_holdings_endpoint(
    body: HoldingImportRequest,
    user_id: str = Depends(get_current_user),
):
    """JSON 文档批量导入：按 code+type+account 去重，重复导入为覆盖更新。"""
    result = import_holdings(user_id, [item.model_dump() for item in body.items])
    return ApiResponse(data=result)


# CSV 列名映射（兼容华泰 PC 客户端等常见导出表头）
_CSV_HEADER_ALIASES: dict[str, list[str]] = {
    "code": ["code", "证券代码", "代码", " stock code", "基金代码"],
    "name": ["name", "证券名称", "名称", "stock name", "基金名称"],
    "type": ["type", "类型", "品种", "持仓类型"],
    "quantity": ["quantity", "持仓数量", "数量", "持仓/可用", "可用数量", "证券数量"],
    "cost_price": ["cost_price", "成本价", "成本", "买入均价", "持仓成本", "现价/成本"],
    "broker": ["broker", "券商", "券商名称", "渠道"],
    "account": ["account", "账户", "子账户", "资金账户", "账号类型"],
    "open_date": ["open_date", "建仓日期", "开仓日期", "买入日期"],
    "currency": ["currency", "币种", "货币"],
}


def _normalize_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    """把各种中文/英文表头统一成 schema 字段。"""
    out: dict[str, Any] = {}
    lowered = {k.strip().lower(): v for k, v in row.items() if k is not None}
    for field, aliases in _CSV_HEADER_ALIASES.items():
        for alias in aliases:
            if alias in lowered and lowered[alias] not in (None, ""):
                out[field] = lowered[alias]
                break
    return out


@router.post("/import/csv", response_model=ApiResponse[dict])
async def import_holdings_csv(
    file: UploadFile = File(...),
    broker: str = Form(""),
    account: str = Form(""),
    user_id: str = Depends(get_current_user),
):
    """CSV 文件批量导入：从 Excel 另存为的 CSV 或券商客户端导出文件直接上传。
    表单字段 broker / account 可为所有行提供默认值；CSV 行内同名字段优先级更高。
    """
    if not file.filename or not file.filename.lower().endswith((".csv", ".txt")):
        raise HTTPException(status_code=400, detail="仅支持 .csv / .txt 文件")
    content = await file.read()
    # 尝试常见中文编码
    text = None
    for enc in ("utf-8-sig", "gbk", "gb2312", "utf-8"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(status_code=400, detail="无法识别文件编码")

    reader = csv.DictReader(io.StringIO(text))
    items: list[dict[str, Any]] = []
    for idx, raw in enumerate(reader):
        if not any(v not in (None, "") for v in raw.values()):
            continue
        row = _normalize_csv_row(raw)
        if not row.get("code") or not row.get("name"):
            continue
        # 默认值
        if broker and not row.get("broker"):
            row["broker"] = broker
        if account and not row.get("account"):
            row["account"] = account
        # 未指定类型时根据代码推断
        if not row.get("type"):
            code = str(row.get("code") or "")
            if code.startswith(("1", "5", "0", "2", "3")) and len(code) == 6:
                row["type"] = "etf"  # 场内基金统称 etf（含 ETF/LOF）
            elif code.startswith(("6", "0", "3")) and len(code) == 6:
                row["type"] = "stock"
            else:
                row["type"] = "stock"
        items.append(row)

    if not items:
        raise HTTPException(status_code=400, detail="未解析到有效持仓行")

    result = import_holdings(user_id, items)
    return ApiResponse(data=result)


@router.put("/{holding_id}", response_model=ApiResponse[dict])
async def update_holding_endpoint(
    holding_id: str,
    body: HoldingUpdate,
    user_id: str = Depends(get_current_user),
):
    """手动变更持仓（数量/成本/手动现价/券商等）。"""
    fields = body.model_dump(exclude_unset=True)
    item = update_holding(user_id, holding_id, fields)
    if item is None:
        raise HTTPException(status_code=404, detail="持仓不存在")
    return ApiResponse(data=item)


@router.delete("/{holding_id}", response_model=ApiResponse[dict])
async def delete_holding_endpoint(
    holding_id: str,
    user_id: str = Depends(get_current_user),
):
    deleted = delete_holding(user_id, holding_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="持仓不存在")
    return ApiResponse(data={"deleted": True})


@router.get("/snapshots", response_model=ApiResponse[list[dict]])
async def list_snapshots(user_id: str = Depends(get_current_user)):
    """历史每日快照（总市值/总盈亏），用于历史盈亏曲线。"""
    return ApiResponse(data=get_snapshots(user_id))


@router.post("/snapshot", response_model=ApiResponse[dict])
async def take_snapshot_endpoint(user_id: str = Depends(get_current_user)):
    """手动触发当日快照（重新抓取行情计算后落库）。"""
    snap = take_snapshot(user_id)
    if snap is None:
        raise HTTPException(status_code=400, detail="无持仓或无可定价标的，无法生成快照")
    return ApiResponse(data=snap)
