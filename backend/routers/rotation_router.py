"""Rotation router — 组合层相对动量轮动实验室（档 C）。

端点：
- GET  /presets    预设资产池（四资产 / 二八 / 创业红利）
- POST /backtest   组合层轮动回测：ROC 横截面排名 → top-K 等权 → 周度再平衡

与 /api/v1/signals/winrate/scan 的分工：
- winrate/scan 是**单标的**入场点胜率统计（全仓 0/1、固定持有 N 日）。
- rotation/backtest 是**组合层**逐日账本（横截面排序、权重、再平衡、资金曲线）。
两者共用行情通道，但引擎、口径、输出结构完全独立，互不改动。

``execution_lag`` 刻意不作为请求字段：0 是含已知前视偏差的对拍口径，
只由回归测试在进程内调用，生产路径固定 1（T+1 生效、无前视）。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.deps import get_current_user
from models import ApiResponse
from services import rotation_service

router = APIRouter(tags=["rotation"])


class RotationRequest(BaseModel):
    """组合轮动回测参数。所有数值型参数都有护栏，非法值在 service 层再校验一次。"""

    symbols: list[str] = Field(
        ..., min_length=2, max_length=rotation_service.MAX_SYMBOLS,
        description="资产池代码（场内 ETF/LOF），2~20 只，按 ROC 横截面排名",
    )
    lookback: int = Field(default=rotation_service.DEFAULT_LOOKBACK, ge=2, le=250,
                          description="ROC 回看交易日数，默认 20")
    rebalance: int = Field(default=rotation_service.DEFAULT_REBALANCE, ge=1, le=60,
                           description="再平衡间隔（交易日），默认 5 = 周度")
    top: int = Field(default=rotation_service.DEFAULT_TOP, ge=1, le=20,
                     description="持有 ROC 排名前 K 名，等权")
    years: int = Field(default=5, ge=1, le=10,
                       description="回看年数，默认 5 年（约 1211 根）")
    min_return: Optional[float] = Field(
        default=None, ge=-1.0, le=1.0,
        description="空仓阈值（小数，如 0 表示冠军 ROC<=0 时持现金）；"
                    "None = 永不空仓，永远持最强（技能默认口径）",
    )
    cost_bps: float = Field(default=0.0, ge=0, le=100,
                            description="单边换手成本（基点），如 5 = 0.05%；"
                                        "默认 0 与技能脚本口径一致，实盘须显式设置")
    bias_overlay: bool = Field(
        default=False,
        description="是否对持仓叠加 BIAS20/BIAS60 三档过热降权（1→0.5→0.25→0.125）",
    )


@router.get("/presets", response_model=ApiResponse[list[dict]])
def presets(user_id: str = Depends(get_current_user)) -> ApiResponse[list[dict]]:
    """预设资产池清单，前端下拉直接用。"""
    return ApiResponse(data=rotation_service.get_presets())


@router.post("/backtest", response_model=ApiResponse[dict])
def backtest(
    body: RotationRequest, user_id: str = Depends(get_current_user),
) -> ApiResponse[dict]:
    """跑一次组合层动量轮动回测。

    返回 config / window / coverage / metrics / equity_curve / signals /
    correlation / latest / caveats。任一标的取数失败或公共交易日不足一律 400，
    绝不静默剔除标的后返回一份看似正常的结果。
    """
    try:
        data = rotation_service.run_rotation(
            symbols=body.symbols,
            lookback=body.lookback,
            rebalance=body.rebalance,
            top=body.top,
            years=body.years,
            min_return=body.min_return,
            cost_bps=body.cost_bps,
            bias_overlay=body.bias_overlay,
        )
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)
    return ApiResponse(data=data)
