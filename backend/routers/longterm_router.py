"""LongTerm router — 长期视角数据（老钱日日谈 A股看板，爬取落库）。

数据来源：https://ashare.laoqianriritan.com（第三方静态站，页面已注明）。
每周六 17:30 定时采集（jobs/longterm_job.py），首次部署后需手动
POST /collect 触发一次全量采集。GET 端点全部免鉴权；POST /collect 需登录。
"""

from fastapi import APIRouter, Depends, Query

from core.deps import get_current_user
from models import ApiResponse

router = APIRouter(tags=["longterm"])


@router.get("/sw-returns", response_model=ApiResponse[dict])
def longterm_sw_returns() -> ApiResponse[dict]:
    """申万行业年度涨跌幅热力图（2005 起 + YTD + CAGR 指标）。"""
    from services import longterm_service

    data = longterm_service.get_sw_returns()
    return ApiResponse(data=data)


@router.get("/return-decomp", response_model=ApiResponse[dict])
def longterm_return_decomp() -> ApiResponse[dict]:
    """指数收益三因子拆解（全收益 = 股息 + 盈利 + 估值）。"""
    from services import longterm_service

    data = longterm_service.get_return_decomp()
    return ApiResponse(data=data)


@router.get("/trend-temperature", response_model=ApiResponse[dict])
def longterm_trend_temperature() -> ApiResponse[dict]:
    """市场趋势温度：个股 MA250 上方占比（日频）+ 行业 MACD>0 占比（月频）。"""
    from services import longterm_service

    data = longterm_service.get_trend_temperature()
    return ApiResponse(data=data)


@router.get("/wide-base", response_model=ApiResponse[dict])
def longterm_wide_base(
    days: int = Query(default=0, ge=0, le=6000, description="每指数截取最近 N 个交易日，0=全量"),
) -> ApiResponse[dict]:
    """宽基指数全收益净值序列（2005-01-04 起，9 指数）。"""
    from services import longterm_service

    data = longterm_service.get_wide_base(days=days)
    return ApiResponse(data=data)


@router.get("/huazheng", response_model=ApiResponse[dict])
def longterm_huazheng(
    days: int = Query(default=0, ge=0, le=6000, description="每因子截取最近 N 个交易日，0=全量"),
) -> ApiResponse[dict]:
    """华证六因子净值序列（成长/价值/低波/动量/质量/红利）。"""
    from services import longterm_service

    data = longterm_service.get_huazheng(days=days)
    return ApiResponse(data=data)


@router.get("/status", response_model=ApiResponse[dict])
def longterm_status() -> ApiResponse[dict]:
    """各源抓取状态（行数/上游更新时间/我方抓取时间/最近错误）+ 定时任务状态。"""
    from services import longterm_service
    from jobs.longterm_job import scheduler_status

    data = longterm_service.snapshot_stats()
    data["scheduler"] = scheduler_status()
    return ApiResponse(data=data)


@router.post("/collect", response_model=ApiResponse[dict])
def longterm_collect(
    user_id: str = Depends(get_current_user),
    async_mode: bool = Query(default=True, description="True=后台线程执行并立即返回；False=同步执行并等待结果"),
) -> ApiResponse[dict]:
    """手动触发一次采集（等价于定时任务主体，幂等）。

    首次部署后调用一次即完成全量落库（wide_base/huazheng 约 8 万行，
    同步执行约 10-30 秒；async_mode=True 时立即返回，用 GET /status 查看进度）。
    """
    from services import longterm_service

    if async_mode:
        from jobs.longterm_job import run_collect_async

        started = run_collect_async()
        return ApiResponse(data={
            "started": started,
            "mode": "async",
            "message": "已在后台开始采集，用 GET /longterm/status 查看进度"
                      if started else "已有采集任务正在运行",
        })

    result = longterm_service.collect_all()
    return ApiResponse(data={"started": result.get("ok", False), "mode": "sync", **result})
