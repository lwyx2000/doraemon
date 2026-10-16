"""QuantTerminal Pro — FastAPI application entry point.

Run:
    uvicorn main:app --reload --host 0.0.0.0 --port 8001

注意：端口 8000 已被 AkShare WebAPI (金融数据聚合服务) 占用，
Doraemon 后端使用 8001 端口，通过 AKSHARE_API_BASE (默认 http://192.168.3.53:8000) 获取数据。
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import APP_NAME, APP_VERSION, API_PREFIX, USE_MOCK_DATA
from database.connection import close_db, get_db
from database.sqlite_connection import get_biz_db, close_biz_db


# ============================================================
# Lifespan: startup / shutdown
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if USE_MOCK_DATA:
        print("[Startup] Running in MOCK DATA mode — no live database queries")
    else:
        db = get_db()
        print(f"[Startup] Database connected: {db.db_path}")
        # 幂等确保全部表存在（含 base_sw_sector_daily）：新库/旧库缺表自动补建，
        # 否则 SW 快照统计在启动时就会因表不存在而报错，自动回填也永远不会触发。
        from database.init_db import ensure_schema

        ensure_schema(db)
        # 一次性修复：base_sw_sector_daily 表存储损坏（2026-10-15 事故，见
        # database.init_db.repair_sw_sector_docstring）。修复成功后移除该 env。
        if os.getenv("REPAIR_SW_SECTOR_TABLE") == "1":
            from database.init_db import repair_sw_sector_table

            repair_sw_sector_table(db)
        # 用户绑定迁移：pk_users(UUID) -> pk_user(BIGINT 自增)；fk_users(UUID) -> fk_user(BIGINT)，幂等
        from database.init_db import migrate_pk_user_schema
        migrate_pk_user_schema(db)
        # 用户安全列迁移：增加 must_change_password / token_version（强制改密 + 令牌失效），幂等
        from database.init_db import migrate_user_security_columns
        migrate_user_security_columns(db)
        # 业务（biz_*）数据迁至独立 SQLite 库：建表 + 从 DuckDB 拷贝现有业务数据（幂等，重启保留）。
        # 必须在上面的 DuckDB 用户迁移之后执行，确保拷入 SQLite 的 biz_users 已是正确 pk_user 结构。
        from database.init_sqlite import init_biz_database
        init_biz_database()
        # 启动期幂等种子默认账号（trader / sos）到 biz_users（SQLite），仅当不存在时插入
        from services.auth_service import ensure_seed_users
        ensure_seed_users(get_biz_db())
        # 申万行业快照：定时收盘落库 + 首次启动自动回填历史
        from jobs.sw_snapshot_job import start_sw_snapshot_scheduler

        start_sw_snapshot_scheduler()
        # 全市场成交额：每交易日收盘后固定落一次全天值（供看板「上一日成交额」读取）
        from jobs.turnover_snapshot_job import start_turnover_snapshot_scheduler

        start_turnover_snapshot_scheduler()
        # 贪婪恐惧指数：每交易日收盘后采集 6 指标情绪温度计（历史需首次回填，见 /fear-greed/backfill）
        from jobs.fear_greed_job import start_fear_greed_scheduler

        start_fear_greed_scheduler()
        # 长期视角数据（老钱日日谈 A股看板）：每周六采集 5 源（首次部署后需手动 POST /longterm/collect 全量落库）
        from jobs.longterm_job import start_longterm_scheduler

        start_longterm_scheduler()
        # 红利基金规模/费率：每日凌晨后台渐进补全（同花顺只能逐只查询）
        from jobs.dividend_fee_job import start_dividend_fee_scheduler

        start_dividend_fee_scheduler()
        # 红利基金跟踪指数识别：每日凌晨后台渐进补全（天天基金 F10 逐只取「跟踪标的」）
        from jobs.dividend_index_map_job import start_dividend_index_map_scheduler

        start_dividend_index_map_scheduler()
        # 红利基金季报持仓：每日凌晨后台渐进补全（东财 fund_portfolio_hold_em 逐只取）
        from jobs.dividend_holdings_job import start_dividend_holdings_scheduler

        start_dividend_holdings_scheduler()
        # 红利/现金流三类补充指标（跟踪误差 / 分红频率 / 行业集中度）：每日凌晨后台渐进补全
        from jobs.dividend_extra_metrics_job import start_dividend_extra_metrics_scheduler

        start_dividend_extra_metrics_scheduler()
        # 红利指数 PE 历史序列回填：每日 07:20 小批量推进（中证官网长期限流，不能一次拉完）
        from jobs.dividend_pe_backfill_job import start_dividend_pe_backfill_scheduler

        start_dividend_pe_backfill_scheduler()
        # ETF 每日申赎快照：每天 19:00 快照份额/规模/净值（麦蕊 fund_rank etf）
        from jobs.etf_subscription_job import start_etf_subscription_scheduler

        start_etf_subscription_scheduler()
        # ETF 费率后台渐进补全：每天 05:00 补一批（复用 fund_fee_service 三源互备）
        from jobs.etf_fee_job import start_etf_fee_scheduler

        start_etf_fee_scheduler()
        # 监控缓存配置：从 biz_config 恢复（重启保留用户改过的配置）
        from services.monitor_service import load_cache_config

        load_cache_config()

        # 市场概况上游预热（2026-10-16）：网关对 index_valuation / market_stats 的
        # 冷首算分别可到 ~120s / ~35s（12 指数估值遍历 + 新浪全A股 5500+ 只），
        # 不预热则部署/重启后第一个打开首页的用户干等甚至拿到「网关无数据」。
        # 后台线程启动即打，与 singleflight/TTL 缓存天然衔接（预热就是普通缓存填充），
        # 失败仅打印不阻断启动。
        import threading as _threading

        def _warm_market_upstreams():
            try:
                from services.market_service import (
                    _fetch_index_valuation_raw,
                    get_market_stats_real,
                )

                print("[Startup] 预热市场概况上游(index_valuation / market_stats)...")
                _fetch_index_valuation_raw(force=True)
                get_market_stats_real()
                print("[Startup] 市场概况上游预热完成")
            except Exception as e:
                print(f"[Startup] 市场概况上游预热失败(忽略, 不影响启动): {e!r}")

        _threading.Thread(
            target=_warm_market_upstreams, daemon=True, name="warm-market"
        ).start()

    yield

    # Shutdown
    if not USE_MOCK_DATA:
        from jobs.sw_snapshot_job import stop_sw_snapshot_scheduler

        stop_sw_snapshot_scheduler()
        from jobs.turnover_snapshot_job import stop_turnover_snapshot_scheduler

        stop_turnover_snapshot_scheduler()
        from jobs.fear_greed_job import stop_fear_greed_scheduler

        stop_fear_greed_scheduler()
        from jobs.longterm_job import stop_longterm_scheduler

        stop_longterm_scheduler()
        from jobs.dividend_fee_job import stop_dividend_fee_scheduler

        stop_dividend_fee_scheduler()
        from jobs.dividend_index_map_job import stop_dividend_index_map_scheduler

        stop_dividend_index_map_scheduler()
        from jobs.dividend_holdings_job import stop_dividend_holdings_scheduler

        stop_dividend_holdings_scheduler()
        from jobs.dividend_extra_metrics_job import stop_dividend_extra_metrics_scheduler

        stop_dividend_extra_metrics_scheduler()
        from jobs.dividend_pe_backfill_job import stop_dividend_pe_backfill_scheduler

        stop_dividend_pe_backfill_scheduler()
        from jobs.etf_subscription_job import stop_etf_subscription_scheduler

        stop_etf_subscription_scheduler()
        from jobs.etf_fee_job import stop_etf_fee_scheduler

        stop_etf_fee_scheduler()
    close_db()
    close_biz_db()
    print("[Shutdown] Database connection closed")


# ============================================================
# App
# ============================================================

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="量化终端 Pro — 套利交易分析平台后端 API",
    lifespan=lifespan,
)

# CORS — 仅放行显式来源，禁止 `*` + allow_credentials 的危险组合。
# 生产环境前端经 nginx 同源反代 /api，不触发跨域；
# 开发态 Vite 跑在 localhost:5173/5174；如需额外来源用环境变量 CORS_ALLOW_ORIGINS 注入（逗号分隔）。
def _cors_allow_origins() -> list[str]:
    env = os.getenv("CORS_ALLOW_ORIGINS")
    if env:
        return [o.strip() for o in env.split(",") if o.strip()]
    return [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://192.168.3.53:9080",  # 生产环境前端同源 nginx 反代 /api，此处仅作兜底白名单
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Register routers
# ============================================================

from routers.auth_router import router as auth_router
from routers.market_router import router as market_router
from routers.fund_router import router as fund_router
from routers.etf_router import router as etf_router
from routers.convertible_bond_router import router as cb_router
from routers.reits_router import router as reits_router
from routers.favorite_router import router as favorite_router
from routers.portfolio_router import router as portfolio_router
from routers.holdings_router import router as holdings_router
from routers.strategy_router import router as strategy_router
from routers.alert_router import router as alert_router
from routers.ai_router import router as ai_router
from routers.monitor_router import router as monitor_router
from routers.notification_router import router as notification_router
from routers.broker_account_router import router as broker_account_router
from routers.account_name_router import router as account_name_router
from routers.signal_router import router as signal_router
from routers.strategy_library_router import router as strategy_library_router
from routers.valuation_router import router as valuation_router
from routers.charts_router import router as charts_router
from routers.datasource_router import router as datasource_router
from routers.jobs_router import router as jobs_router
from routers.dividend_router import router as dividend_router
from routers.longterm_router import router as longterm_router

app.include_router(auth_router, prefix=f"{API_PREFIX}/auth")
app.include_router(broker_account_router, prefix=API_PREFIX)
app.include_router(account_name_router, prefix=API_PREFIX)
app.include_router(market_router, prefix=f"{API_PREFIX}/market")
app.include_router(fund_router, prefix=API_PREFIX)
app.include_router(etf_router, prefix=f"{API_PREFIX}/etf")
app.include_router(cb_router, prefix=f"{API_PREFIX}/cb")
app.include_router(reits_router, prefix=f"{API_PREFIX}/reits")
app.include_router(favorite_router, prefix=API_PREFIX)
app.include_router(portfolio_router, prefix=API_PREFIX)
app.include_router(holdings_router, prefix=API_PREFIX)
app.include_router(strategy_router, prefix=API_PREFIX)
app.include_router(alert_router, prefix=API_PREFIX)
app.include_router(ai_router, prefix=API_PREFIX)
app.include_router(monitor_router, prefix=f"{API_PREFIX}/monitor")
app.include_router(notification_router, prefix=API_PREFIX)
app.include_router(signal_router, prefix=f"{API_PREFIX}/signals")
app.include_router(strategy_library_router, prefix=f"{API_PREFIX}/strategy-library")
app.include_router(valuation_router, prefix=f"{API_PREFIX}/valuation")
app.include_router(charts_router, prefix=f"{API_PREFIX}/charts")
app.include_router(datasource_router, prefix=f"{API_PREFIX}/datasources")
app.include_router(jobs_router, prefix=f"{API_PREFIX}/jobs")
app.include_router(dividend_router, prefix=f"{API_PREFIX}/dividend")
app.include_router(longterm_router, prefix=f"{API_PREFIX}/longterm")


# ============================================================
# Health check
# ============================================================

@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


@app.get("/", tags=["system"])
async def root():
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "docs": "/docs",
        "api_prefix": API_PREFIX,
        "mock_mode": USE_MOCK_DATA,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
