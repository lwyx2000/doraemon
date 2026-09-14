"""Market router — macro, indices, and K-line endpoints."""

from fastapi import APIRouter, Query

from models import (
    ApiResponse,
    BoardSector,
    FundFlows,
    FundRankingItem,
    IndexValuation,
    KlineItem,
    MacroIndicators,
    MarketOverview,
    ZTStats,
)
from services.market_service import (
    backfill_sw_sector_history,
    get_board_sectors_with_meta,
    get_data_source_status,
    get_fund_flows_with_meta,
    get_fund_ranking_with_meta,
    get_index_history,
    get_index_valuation_history,
    get_indices_with_meta,
    get_kline,
    get_macro_indicators_with_meta,
    get_market_overview_with_meta,
    get_precious_metals_with_meta,
    get_sw_sector_history,
    get_sw_sector_relative_strength,
    get_sw_sector_snapshot_stats,
    get_sw_sector_valuation_history,
    get_sw_sectors,
    get_zt_stats_with_meta,
)

router = APIRouter(tags=["market"])


@router.get("/macro/indicators", response_model=ApiResponse[MacroIndicators])
def macro_indicators() -> ApiResponse[MacroIndicators]:
    """宏观指标（ERP / DR007 / GC001 等）"""
    data, meta = get_macro_indicators_with_meta()
    return ApiResponse(data=data, meta=meta)


@router.get("/overview", response_model=ApiResponse[MarketOverview])
def overview() -> ApiResponse[MarketOverview]:
    """市场概况：指数行情、涨跌家数、成交额"""
    data, meta = get_market_overview_with_meta()
    return ApiResponse(data=data, meta=meta)


@router.get("/board-sectors", response_model=ApiResponse[list[BoardSector]])
def board_sectors() -> ApiResponse[list[BoardSector]]:
    """板块涨幅排行"""
    data, meta = get_board_sectors_with_meta()
    return ApiResponse(data=data, meta=meta)


@router.get("/fund-flows", response_model=ApiResponse[FundFlows])
def fund_flows() -> ApiResponse[FundFlows]:
    """资金流向"""
    data, meta = get_fund_flows_with_meta()
    return ApiResponse(data=data, meta=meta)


@router.get("/zt-stats", response_model=ApiResponse[ZTStats])
def zt_stats() -> ApiResponse[ZTStats]:
    """涨跌停统计"""
    data, meta = get_zt_stats_with_meta()
    return ApiResponse(data=data, meta=meta)


@router.get("/fund-ranking", response_model=ApiResponse[list[FundRankingItem]])
def fund_ranking() -> ApiResponse[list[FundRankingItem]]:
    """基金涨跌排行"""
    data, meta = get_fund_ranking_with_meta()
    return ApiResponse(data=data, meta=meta)


@router.get("/indices", response_model=ApiResponse[list[IndexValuation]])
def indices(
    category: str | None = Query(default=None),
    date: str | None = Query(default=None),
) -> ApiResponse[list[IndexValuation]]:
    """Return index valuations, optionally filtered by category."""
    data, meta = get_indices_with_meta(category=category, date=date)
    return ApiResponse(data=data, meta=meta)


@router.get("/indices/valuation-history", response_model=ApiResponse[list[dict]])
def index_valuation_history(
    name: str = Query(..., description="指数名称，如 沪深300"),
    indicator: str = Query(default="pe", pattern="^(pe|pb)$", description="pe=滚动市盈率(TTM)，pb=市净率"),
) -> ApiResponse[list[dict]]:
    """指数估值历史序列（乐咕乐股真实数据），供估值分析页画真实 PE/PB 估值带。"""
    data, meta = get_index_valuation_history(name=name, indicator=indicator)
    return ApiResponse(data=data, meta=meta)


@router.get("/indices/{code}/history", response_model=ApiResponse[list[dict]])
def index_history(
    code: str,
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
) -> ApiResponse[list[dict]]:
    """Return mock K-line history for an index."""
    data = get_index_history(code=code, start_date=start_date, end_date=end_date)
    return ApiResponse(data=data)


@router.get("/status", response_model=ApiResponse[dict])
def data_source_status() -> ApiResponse[dict]:
    """数据源连接状态：AkShare 可达性 + 集思录登录/可用态。"""
    data = get_data_source_status()
    return ApiResponse(data=data)


@router.get("/sw-sectors", response_model=ApiResponse[list[dict]])
def sw_sectors() -> ApiResponse[list[dict]]:
    """申万一级行业基础数据（PE / PB / 股息率）——估值热力图数据源。"""
    data, meta = get_sw_sectors()
    return ApiResponse(data=data, meta=meta)


@router.get("/sw-sectors/{sector_code}/history", response_model=ApiResponse[list[dict]])
def sw_sector_history(
    sector_code: str,
    days: int = Query(default=120, ge=1, le=500),
) -> ApiResponse[list[dict]]:
    """单个申万一级行业的历史快照（涨跌幅/PE/PB/股息率），用于查看历史走势。"""
    data = get_sw_sector_history(sector_code=sector_code, days=days)
    return ApiResponse(data=data)


@router.get("/sw-sectors/valuation-history", response_model=ApiResponse[list[dict]])
def sw_sector_valuation_history(
    sector_code: str | None = Query(default=None, description="申万一级行业代码，如 801010。不传则返回所有行业"),
    start_date: str | None = Query(default=None, description="开始日期 YYYYMMDD，默认近半年"),
    end_date: str | None = Query(default=None, description="结束日期 YYYYMMDD，默认今天"),
) -> ApiResponse[list[dict]]:
    """申万一级行业历史估值数据（PE / PB / 股息率），来自 AkShare index_analysis_daily_sw。

    可传入 sector_code 过滤单个行业，不传则返回所有行业的历史数据。
    由于 AkShare 接口较慢，后端对全量结果做 1 小时缓存。
    """
    data, meta = get_sw_sector_valuation_history(
        sector_code=sector_code, start_date=start_date, end_date=end_date
    )
    return ApiResponse(data=data, meta=meta)


@router.get("/sw-sectors/relative-strength", response_model=ApiResponse[list[dict]])
def sw_sector_strength(
    days: int = Query(default=5, ge=1, le=30),
) -> ApiResponse[list[dict]]:
    """各申万一级行业的相对强度：近 N 日累计涨跌幅 vs 当日涨跌幅。"""
    data = get_sw_sector_relative_strength(days=days)
    return ApiResponse(data=data)


@router.get("/sw-sectors/snapshot-stats", response_model=ApiResponse[dict])
def sw_sector_snapshot_stats() -> ApiResponse[dict]:
    """base_sw_sector_daily 落库情况：已有交易日数 / 行业数 / 最新日期 + 定时任务状态。"""
    stats = get_sw_sector_snapshot_stats()
    from jobs.sw_snapshot_job import scheduler_status

    stats["scheduler"] = scheduler_status()
    return ApiResponse(data=stats)


@router.post("/sw-sectors/backfill", response_model=ApiResponse[dict])
def sw_sector_backfill(
    days: int = Query(default=250, ge=5, le=2000, description="每个行业回填最近多少个交易日"),
    async_mode: bool = Query(default=True, description="True=后台线程执行并立即返回；False=同步执行并等待结果"),
) -> ApiResponse[dict]:
    """手动回填申万一级行业历史日线到 base_sw_sector_daily。

    可重复执行（同 (sector_code, trade_date) 冲突即覆盖）。PE/PB/股息率无免费历史源，留 NULL。
    """
    if async_mode:
        from jobs.sw_snapshot_job import run_backfill_async

        started = run_backfill_async(days=days)
        return ApiResponse(data={
            "started": started,
            "mode": "async",
            "days": days,
            "message": "已在后台开始回填，用 GET /sw-sectors/snapshot-stats 查看进度"
                      if started else "已有回填任务正在运行",
        })

    result = backfill_sw_sector_history(days=days)
    return ApiResponse(data={"started": result["ok"], "mode": "sync", **result})


@router.get("/precious-metals", response_model=ApiResponse[dict])
def precious_metals() -> ApiResponse[dict]:
    """贵金属：黄金/白银现货价格 + 金银比（上海黄金交易所 Au99.99 / Ag99.99）。"""
    data, meta = get_precious_metals_with_meta()
    return ApiResponse(data=data, meta=meta)


@router.get("/quote/kline", response_model=ApiResponse[list[KlineItem]])
def kline(
    code: str = Query(...),
    type: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
) -> ApiResponse[list[KlineItem]]:
    """Return mock K-line data for a quote code."""
    data = get_kline(
        code=code, type=type, start_date=start_date, end_date=end_date
    )
    return ApiResponse(data=data)
