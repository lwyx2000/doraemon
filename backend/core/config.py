"""Application configuration."""

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "database" / "quantterminal.duckdb"))

JWT_SECRET = os.getenv("JWT_SECRET", "quantterminal-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

API_PREFIX = "/api/v1"
APP_NAME = "QuantTerminal Pro"
APP_VERSION = "1.0.0"

USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "true").lower() == "true"
