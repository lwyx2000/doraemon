"""QuantTerminal Pro — FastAPI application entry point.

Run:
    uvicorn main:app --reload --host 0.0.0.0 --port 8001

注意：端口 8000 已被 AkShare WebAPI (金融数据聚合服务) 占用，
Doraemon 后端使用 8001 端口，通过 AKSHARE_API_BASE (默认 http://192.168.3.53:8000) 获取数据。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import APP_NAME, APP_VERSION, API_PREFIX, USE_MOCK_DATA
from database.connection import close_db, get_db


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
        # 启动期幂等种子默认账号（trader / sos）到 biz_users，仅当不存在时插入
        from services.auth_service import ensure_seed_users
        ensure_seed_users(db)
        # 用户绑定迁移：pk_users(UUID) -> pk_user(BIGINT 自增)；fk_users(UUID) -> fk_user(BIGINT)，幂等
        from database.init_db import migrate_pk_user_schema
        migrate_pk_user_schema(db)
        # 用户安全列迁移：增加 must_change_password / token_version（强制改密 + 令牌失效），幂等
        from database.init_db import migrate_user_security_columns
        migrate_user_security_columns(db)
        # 申万行业快照：定时收盘落库 + 首次启动自动回填历史
        from jobs.sw_snapshot_job import start_sw_snapshot_scheduler

        start_sw_snapshot_scheduler()

    yield

    # Shutdown
    if not USE_MOCK_DATA:
        from jobs.sw_snapshot_job import stop_sw_snapshot_scheduler

        stop_sw_snapshot_scheduler()
    close_db()
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

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "*",  # 开发环境允许所有来源
    ],
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
