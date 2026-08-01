"""QuantTerminal Pro — FastAPI application entry point.

Run:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
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

    yield

    # Shutdown
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
    allow_origins=["*"],
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
from routers.strategy_router import router as strategy_router
from routers.alert_router import router as alert_router
from routers.ai_router import router as ai_router
from routers.monitor_router import router as monitor_router

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(market_router, prefix=API_PREFIX)
app.include_router(fund_router, prefix=API_PREFIX)
app.include_router(etf_router, prefix=API_PREFIX)
app.include_router(cb_router, prefix=API_PREFIX)
app.include_router(reits_router, prefix=API_PREFIX)
app.include_router(favorite_router, prefix=API_PREFIX)
app.include_router(portfolio_router, prefix=API_PREFIX)
app.include_router(strategy_router, prefix=API_PREFIX)
app.include_router(alert_router, prefix=API_PREFIX)
app.include_router(ai_router, prefix=API_PREFIX)
app.include_router(monitor_router, prefix=API_PREFIX)


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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
