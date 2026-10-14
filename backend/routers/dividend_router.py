"""Dividend router — 红利策略研究（红利指数估值 + 红利基金名录）。"""

from fastapi import APIRouter, Depends, Query

from core.deps import get_current_user

from models import ApiResponse
from services import fund_fee_service, fund_holdings_service, fund_index_map_service
from services import fund_extra_metrics_service
from services.dividend_service import (
    get_cashflow_overview,
    get_dividend_fund_codes,
    get_dividend_overview,
    get_index_funds,
    pe_backfill_start,
    pe_backfill_status,
    refresh_dividend_cache,
)

router = APIRouter(tags=["dividend"])


@router.post("/fill-index-pe", response_model=ApiResponse[dict])
def dividend_fill_index_pe(
    user_id: str = Depends(get_current_user),
    codes: str | None = Query(None, description="逗号分隔的指数代码；缺省自动挑未回填的"),
    limit: int = Query(8, ge=1, le=44),
) -> ApiResponse[dict]:
    """启动一轮「指数 PE 历史序列」回填（后台线程，默认 8 个指数，并发 2）。

    ⚠️ **会反复请求中证官网**，而中证长期限流（封禁约 3 小时）。故：
      - 并发固定为 2，不要提高
      - 分批推进，每批之间可在页面间隔操作
      - 中断后重跑会**自动跳过已回填的指数**（断点续传）

    已在运行时直接返回当前进度，不会重复启动。
    """
    want = [c.strip() for c in codes.split(",") if c.strip()] if codes else None
    return ApiResponse(
        data=pe_backfill_start(want, limit=limit),
        meta={"isMock": False, "dataSource": "aksharewebapi /api/ak (stock_zh_index_hist_csindex)"},
    )


@router.get("/index-pe-progress", response_model=ApiResponse[dict])
def dividend_index_pe_progress() -> ApiResponse[dict]:
    """查询「PE 历史序列回填」进度（供前端轮询）。"""
    return ApiResponse(data=pe_backfill_status())


@router.get("/overview", response_model=ApiResponse[dict])
def dividend_overview(force: bool = Query(False)) -> ApiResponse[dict]:
    """红利研究总览。

    ``?force=1`` 时会真正去打上游刷新（较慢）；**默认走本地基线 + 6h 缓存**，
    微秒级返回——上游刷新交由「点刷新」按钮和每日回填 job 负责。

    返回：
    - ``indices``：各红利指数的 PE / PE 分位 / 股息率 / 股债收益比，以及
      **三套独立仓位信号**（股债收益比 / PE 分位 / 股息率），不做综合裁决。
    - ``funds``：全市场红利基金名录，分 ``etf``（场内）/ ``passive``（被动场外）/
      ``active``（主动）三组。
    """
    data = get_dividend_overview(force=force)
    meta = {
        "isMock": False,
        "dataSource": "aksharewebapi /api/ak (csindex + 东财基金名录)",
        "updatedAt": data.get("updated_at"),
    }
    return ApiResponse(data=data, meta=meta)


@router.post("/refresh", response_model=ApiResponse[dict])
def dividend_refresh(user_id: str = Depends(get_current_user)) -> ApiResponse[dict]:
    """强制刷新指数估值与基金名录缓存（取数较慢，勿高频调用）。"""
    data = refresh_dividend_cache()
    return ApiResponse(data=data)


@router.post("/fill-fees", response_model=ApiResponse[dict])
def dividend_fill_fees(user_id: str = Depends(get_current_user), limit: int = Query(80, ge=1, le=600)) -> ApiResponse[dict]:
    """手动触发一轮「规模 / 管理费 / 托管费 / 申购费」后台补全。

    数据源为同花顺 ``fund_info_ths``（**逐只查询**），一次补 ``limit`` 只（默认 80），
    结果落 DuckDB，页面刷新即可看到。已在跑时直接返回当前进度。
    """
    codes = fund_fee_service.all_known_codes()
    prog = fund_fee_service.start_fill(codes, limit=limit)
    snap = fund_fee_service.snapshot(codes)
    snap["round_running"] = prog["running"]
    return ApiResponse(
        data=snap,
        meta={"isMock": False, "dataSource": "aksharewebapi /api/ak (fund_info_ths)"},
    )


@router.get("/fee-progress", response_model=ApiResponse[dict])
def dividend_fee_progress() -> ApiResponse[dict]:
    """查询费率补全进度（供前端轮询）。"""
    return ApiResponse(data=fund_fee_service.snapshot())


@router.post("/fill-extra-metrics", response_model=ApiResponse[dict])
def dividend_fill_extra_metrics(
    user_id: str = Depends(get_current_user),
    limit: int = Query(80, ge=1, le=600),
    force: bool = Query(False, description="强制重算全部已知基金（忽略缺口判断），数据源更换后全量刷新用"),
) -> ApiResponse[dict]:
    """手动触发一轮「跟踪误差 / 分红频率 / 行业集中度」后台补全（默认 80 只）。

    三项指标分别走不同数据源（天天基金 lsjz 直连 / 天天基金 F10 fhsp /
    东财季报持仓 + 申万行业），一次补 ``limit`` 只，结果落 DuckDB，页面刷新即可见。
    ``force=true`` 忽略缺口判断、重算全部已知基金（如 tracking_error 数据源由
    fund_open_fund_info_em 代理换成 lsjz 直连后，需全量刷新旧 None）。
    已在跑时直接返回当前进度。
    """
    codes = fund_extra_metrics_service.all_known_codes()
    prog = fund_extra_metrics_service.start_fill(codes, limit=limit, force=force)
    snap = fund_extra_metrics_service.snapshot(codes)
    snap["round_running"] = prog["running"]
    return ApiResponse(
        data=snap,
        meta={"isMock": False, "dataSource": "天天基金 lsjz / fhsp / 申万行业映射"},
    )


@router.get("/extra-metrics-progress", response_model=ApiResponse[dict])
def dividend_extra_metrics_progress() -> ApiResponse[dict]:
    """查询三类指标补全进度（供前端轮询）。"""
    return ApiResponse(data=fund_extra_metrics_service.snapshot())


@router.get("/index-funds", response_model=ApiResponse[dict])
def dividend_index_funds(code: str = Query(..., description="红利指数代码，如 000922")) -> ApiResponse[dict]:
    """单只红利指数 → 跟踪它的场内 / 场外基金 + 中证官方编制说明。

    前端点击指数行弹窗即用：
    - ``funds.onshore`` / ``funds.offshore``：该指数对应的场内 / 场外基金；
    - ``compilation``：中证 ``index-basic-info`` 的官方编制说明；
      中证取数失败时为 ``None``（前端显示「暂不可得」，**不 mock**）。
    """
    data = get_index_funds(code)
    comp = data.get("compilation") or {}
    return ApiResponse(
        data=data,
        meta={
            "isMock": False,
            "dataSource": "csindex index-basic-info + 东财基金名录",
            "updatedAt": comp.get("fetched_at"),
        },
    )


@router.post("/fill-index-map", response_model=ApiResponse[dict])
def dividend_fill_index_map(user_id: str = Depends(get_current_user), limit: int = Query(20, ge=1, le=200)) -> ApiResponse[dict]:
    """手动触发一轮「业绩比较基准 → 跟踪指数」识别（默认 20 只）。

    仅在库里既无映射、也无基准文本的基金上工作；已抓过基准的可离线识别。
    """
    codes = get_dividend_fund_codes()
    prog = fund_index_map_service.map_batch(codes, limit=limit)
    return ApiResponse(
        data=prog,
        meta={"isMock": False, "dataSource": "aksharewebapi /api/ak (fund_info_ths)"},
    )


@router.get("/index-map-progress", response_model=ApiResponse[dict])
def dividend_index_map_progress() -> ApiResponse[dict]:
    """查询「跟踪指数识别」进度（供前端轮询）。"""
    return ApiResponse(data=fund_index_map_service.progress())


@router.post("/fill-holdings", response_model=ApiResponse[dict])
def dividend_fill_holdings(user_id: str = Depends(get_current_user), limit: int = Query(120, ge=1, le=600)) -> ApiResponse[dict]:
    """手动触发一轮「红利基金持仓股」后台补全（默认 120 只，并发 5 路）。

    数据源为东财 ``fund_portfolio_hold_em``（**逐只季报查询**）。一次补 ``limit`` 只，
    结果落 DuckDB，30 天后才重新拉取。已在跑时直接返回当前进度。
    """
    codes = fund_holdings_service.all_fund_codes()
    prog = fund_holdings_service.start_fill(codes, limit=limit)
    snap = fund_holdings_service.snapshot(codes)
    snap["round_running"] = prog["running"]
    return ApiResponse(
        data=snap,
        meta={"isMock": False, "dataSource": "aksharewebapi /api/ak (fund_portfolio_hold_em)"},
    )


@router.get("/holdings-progress", response_model=ApiResponse[dict])
def dividend_holdings_progress() -> ApiResponse[dict]:
    """查询「持仓股补全」进度（供前端轮询）。"""
    return ApiResponse(data=fund_holdings_service.snapshot())


@router.get("/cashflow-funds", response_model=ApiResponse[dict])
def dividend_cashflow_funds(force: bool = Query(False)) -> ApiResponse[dict]:
    """现金流基金名录（**独立一条线**，2026-10-07 用户拍板「单开 Tab」）。

    与 ``/overview`` 的红利名录互不相干：这里按「名称含『现金流』+ 被动指数型」重建，
    纯债 / 货币 / 主动同样不入。红利名录的 ``FUND_NAME_KEYS`` **一个字都没动**——
    159399「现金流ETF国泰」不在红利名录（名字没「红利」二字），但**会出现在这条线上**
    （名字含「现金流」、类型是指数型）。两条线各自解释自己的口径，不互相污染。

    ⚠️ 取数只碰 ``fund_name_em``（全市场约 2.8 万条，冷启动约 9s），**不碰中证接口**，
    不会触发 csindex 403 封禁。
    """
    return ApiResponse(data=get_cashflow_overview(force=force))


@router.get("/fund-holdings", response_model=ApiResponse[dict])
def dividend_fund_holdings(
    code: str = Query(..., description="基金代码，如 510880"),
    limit: int = Query(200, ge=1, le=500),
) -> ApiResponse[dict]:
    """单只红利基金的**季报持仓明细**（代码行点开弹窗即用）。

    ⚠️ 口径说明（前端必须一起展示，避免被当成实时持仓）：
    - 数据来自基金季报，是 **T-1 季度**的快照，不是实时持仓；
    - ``quarter``：所属报告期（如「2026年3季度股票投资明细」）；
    - ``stale``：超过 30 天未更新时为 true；无季报的基金返回空 ``rows``（**不 mock**）。
    """
    data = fund_holdings_service.get_holdings(code, limit=limit)
    return ApiResponse(
        data=data,
        meta={
            "isMock": False,
            "dataSource": "aksharewebapi /api/ak (fund_portfolio_hold_em 季报)",
            "updatedAt": data.get("fetched_at"),
            "note": "季报口径，非实时持仓",
        },
    )
