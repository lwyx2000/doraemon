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
    get_board_sectors_with_meta,
    get_data_source_status,
    get_fund_flows_with_meta,
    get_fund_ranking_with_meta,
    get_index_history,
    get_indices_with_meta,
    get_kline,
    get_macro_indicators_with_meta,
    get_market_overview_with_meta,
    get_precious_metals_with_meta,
    get_sw_sector_history,
    get_sw_sector_relative_strength,
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


@router.get("/sw-sectors/relative-strength", response_model=ApiResponse[list[dict]])
def sw_sector_strength(
    days: int = Query(default=5, ge=1, le=30),
) -> ApiResponse[list[dict]]:
    """各申万一级行业的相对强度：近 N 日累计涨跌幅 vs 当日涨跌幅。"""
    data = get_sw_sector_relative_strength(days=days)
    return ApiResponse(data=data)


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
