"""Application configuration."""

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "database" / "quantterminal.duckdb"))

JWT_SECRET = os.getenv("JWT_SECRET", "quantterminal-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# 管理员账号（仅用于「账号管理」功能：列出用户 / 重置密码）。
# 以逗号分隔；命中即视为管理员。管理员登录后仅暴露账号管理功能，不暴露交易功能。
# 默认包含 sos —— 内部系统小而固定，用环境变量集中管理，无需在数据库额外加 is_admin 列。
ADMIN_USERS = {u.strip() for u in os.getenv("ADMIN_USERS", "sos").split(",") if u.strip()}

API_PREFIX = "/api/v1"
APP_NAME = "QuantTerminal Pro"
APP_VERSION = "1.0.0"

# 默认关闭 mock：直接连接 53 上的 AkShare WebAPI 获取真实行情数据。
# 仅在确实需要纯演示/离线时才显式设置 USE_MOCK_DATA=true。
USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "false").lower() == "true"

# AkShare WebAPI 数据源地址（供 market/fund/valuation 等服务调用上游取数，支持环境变量覆盖）
# 默认指向外网可达的网关（项目核心规则：所有数据经此网关获取）。
# 当前外网网关 http://10.100.213.248:8000 实测可用（指数估值/宏观/CPI/10Y国债 等均返回真实数据）。
# 在 53 内网机上运行时，用环境变量覆盖：AKSHARE_API_BASE=http://192.168.3.53:8000
AKSHARE_API_BASE = os.getenv("AKSHARE_API_BASE", "http://10.100.213.248:8000")

# 企业微信群机器人 Webhook URL（用于预警通知推送）
# 环境变量覆盖：WECOM_WEBHOOK_URL
WECOM_WEBHOOK_URL = os.getenv("WECOM_WEBHOOK_URL", "")

# 钉钉机器人 Webhook URL
DINGTALK_WEBHOOK_URL = os.getenv("DINGTALK_WEBHOOK_URL", "")
