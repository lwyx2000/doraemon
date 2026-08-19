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

# 默认关闭 mock：直接连接 53 上的 AkShare WebAPI 获取真实行情数据。
# 仅在确实需要纯演示/离线时才显式设置 USE_MOCK_DATA=true。
USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "false").lower() == "true"

# AkShare WebAPI 数据源地址（供 market/fund 等服务调用上游取数，支持环境变量覆盖）
# 默认指向 192.168.3.53:8000（akshare 数据服务所在机器）；
# 若网关与 akshare 同机运行，可设 AKSHARE_API_BASE=http://127.0.0.1:8000
#AKSHARE_API_BASE = os.getenv("AKSHARE_API_BASE", "http://192.168.3.53:8000")

# 企业微信群机器人 Webhook URL（用于预警通知推送）
# 环境变量覆盖：WECOM_WEBHOOK_URL
WECOM_WEBHOOK_URL = os.getenv("WECOM_WEBHOOK_URL", "")

# 钉钉机器人 Webhook URL
DINGTALK_WEBHOOK_URL = os.getenv("DINGTALK_WEBHOOK_URL", "")
#AKSHARE_API_BASE = os.getenv("AKSHARE_API_BASE", "http://10.100.213.248:8000")
AKSHARE_API_BASE = os.getenv("AKSHARE_API_BASE", "http://192.168.3.53:8000")
