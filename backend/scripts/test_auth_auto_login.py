"""自动登录（refresh token）回归测试（独立临时 SQLite，不碰线上数据）。

运行：python backend/scripts/test_auth_auto_login.py

覆盖：
- 不勾选自动登录 → 不下发 refresh_token
- 勾选自动登录 → 下发长效 refresh_token，且能换发新的 access token
- refresh token 不能当 access token 调用业务接口（typ 校验）
- 伪造 / 过期 / 类型错误的 refresh 一律 401
- 管理员重置密码（token_version +1）后长效凭证立即失效
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ["BIZ_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="doraemon_auth_")) / "biz.sqlite")
os.environ["USE_MOCK_DATA"] = "false"
os.environ["AUTO_LOGIN_DAYS"] = "30"

from fastapi import HTTPException  # noqa: E402
from jose import jwt  # noqa: E402

from core.config import JWT_ALGORITHM, JWT_SECRET  # noqa: E402
from core.deps import _resolve_user, create_access_token  # noqa: E402
from database.sqlite_connection import get_biz_db  # noqa: E402
from database.init_sqlite import BIZ_INDEXES, BIZ_TABLES  # noqa: E402
from services import auth_service  # noqa: E402

db = get_biz_db()
for sql in BIZ_TABLES:
    db.execute(sql)
for sql in BIZ_INDEXES:
    try:
        db.execute(sql)
    except Exception:
        pass
db.execute(
    "INSERT INTO biz_users (pk_user, username, password_hash) VALUES (1, 'trader', 'stub-hash')",
)
# 本机 passlib/bcrypt 版本组合在 hash() 时会抛 "password cannot be longer than 72 bytes"，
# 与本次要测的 JWT 逻辑无关；这里只替换口令校验，保留完整签发/续期链路。
auth_service._verify = lambda password, _h: password == "trader123"


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError("FAIL: " + msg)
    print("  OK", msg)


def expect_401(fn, msg: str) -> None:
    try:
        fn()
    except HTTPException as e:
        check(e.status_code == 401, msg)
        return
    raise AssertionError("FAIL: 期望 401，实际没有抛错 -> " + msg)


print("[1] 登录：是否下发 refresh_token 由 auto_login 决定")
plain = auth_service.authenticate("trader", "trader123")
check(plain["refresh_token"] is None, "默认不勾选自动登录，不下发长效凭证")
check(plain["username"] == "trader" and plain["token"], "普通登录仍返回 access token")

auto = auth_service.authenticate("trader", "trader123", auto_login=True)
rt = auto["refresh_token"]
check(bool(rt), "勾选自动登录，下发 refresh_token")
payload = jwt.decode(rt, JWT_SECRET, algorithms=[JWT_ALGORITHM])
check(payload.get("typ") == "refresh" and payload.get("sub") == "1",
      "refresh_token 带 typ=refresh 与 sub=pk_user")
check(payload.get("token_version") == 0, "refresh_token 带 token_version")
exp_days = (jwt.decode(rt, JWT_SECRET, algorithms=[JWT_ALGORITHM])["exp"]
            - jwt.decode(auto["token"], JWT_SECRET, algorithms=[JWT_ALGORITHM])["exp"]) / 86400.0
check(29 <= exp_days <= 31, "refresh_token 有效期 30 天，明显长于 24h access token: %.1f 天" % exp_days)

print("[2] 续期：refresh 换发新 access token")
new = auth_service.refresh_access_token(rt)
check(bool(new["token"]) and new["username"] == "trader", "refresh 返回新的 access token")
check(new["refresh_token"] == rt, "refresh_token 原值回填，前端可继续沿用")
check(_resolve_user(new["token"]) == "1", "新 access token 可通过业务鉴权")

print("[3] 安全边界：refresh token 不能当 access token 用")
expect_401(lambda: _resolve_user(rt), "refresh token 直接调业务接口被拒（typ 校验）")
expect_401(lambda: auth_service.refresh_access_token(auto["token"]),
           "拿 access token 冒充 refresh 被拒")
expect_401(lambda: auth_service.refresh_access_token("not-a-jwt"),
           "乱码 refresh token 被拒")
fake = create_access_token({"typ": "refresh", "sub": "1", "token_version": 0},
                           expires_delta=timedelta(seconds=-1))
expect_401(lambda: auth_service.refresh_access_token(fake), "已过期的 refresh token 被拒")

print("[4] 管理员重置密码后长效凭证立即失效")
db.execute("UPDATE biz_users SET token_version = token_version + 1 WHERE pk_user = 1")
expect_401(lambda: auth_service.refresh_access_token(rt),
           "token_version 变化后旧 refresh_token 失效")
expect_401(lambda: _resolve_user(new["token"]), "旧 access token 同样失效")

print("\nALL AUTH AUTO-LOGIN TESTS PASSED")
