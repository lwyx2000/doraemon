"""按资金账号的外部上传契约集成测试（独立临时 SQLite，不碰线上数据）。

运行：python backend/scripts/test_external_upload.py
覆盖：持仓多账号隔离 / type 放开 / mode=replace / 成交按账号覆盖互不相删 /
负数量与回购购回 / 统一批量端点 / 账号总览 / dry_run 不写库。
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

# 本机轻量测试环境可能没装 python-jose；上传链路不走 JWT 解码，注入最小 stub
try:
    import jose  # noqa: F401
except ImportError:
    _jose = types.ModuleType("jose")
    _jose.JWTError = Exception
    _jose.jwt = types.SimpleNamespace(encode=lambda *a, **k: "", decode=lambda *a, **k: {})
    sys.modules["jose"] = _jose

# 上传链路不访问行情网关，测试里 _fetch_quotes 被替换；仅需让 import 成功
try:
    import requests  # noqa: F401
except ImportError:
    _req = types.ModuleType("requests")
    _req.Session = object
    _req.exceptions = types.SimpleNamespace(HTTPError=Exception, RequestException=Exception,
                                            Timeout=Exception, ConnectionError=Exception)
    _adapters = types.ModuleType("requests.adapters")
    _adapters.HTTPAdapter = object
    _req.adapters = _adapters
    sys.modules["requests"] = _req
    sys.modules["requests.adapters"] = _adapters

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ["BIZ_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="doraemon_ext_")) / "biz.sqlite")
os.environ["USE_MOCK_DATA"] = "false"

from database.sqlite_connection import get_biz_db  # noqa: E402
from database.init_sqlite import BIZ_TABLES, BIZ_INDEXES  # noqa: E402
from models import HoldingUploadRequest, TradeUploadRequest  # noqa: E402

db = get_biz_db()
for sql in BIZ_TABLES:
    db.execute(sql)
for sql in BIZ_INDEXES:
    try:
        db.execute(sql)
    except Exception:
        pass
db.execute("INSERT INTO biz_users (pk_user, username, password_hash) VALUES (1, 'trader', 'x')")
db.execute("INSERT INTO biz_users (pk_user, username, password_hash) VALUES (2, 'legacy', 'x')")

from routers.holdings_router import import_holdings_api  # noqa: E402
from routers.trades_router import import_trades_endpoint  # noqa: E402
from routers.external_router import external_batch  # noqa: E402
from services.holdings_service import build_holdings_view, _fetch_quotes  # noqa: E402
from services.trades_service import get_trades  # noqa: E402
from services.external_data_service import (  # noqa: E402
    account_overview, list_orders, list_balances, purge_accounts,
)
import services.holdings_service as holdings_service  # noqa: E402

# 行情是外部网络，单测里固定为空（用客户端上报市值兜底）
holdings_service._fetch_quotes = lambda holdings: {}

DATE = "2026-11-14"
A1, A2 = "666622117166", "262700008483"


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("  OK", msg)


def holding(code, typ, qty, cost, **kw):
    return {"code": code, "name": kw.pop("name", code), "type": typ,
            "quantity": qty, "cost_price": cost, **kw}


def trade(code, direction, price, qty, **kw):
    return {"code": code, "name": kw.pop("name", code), "direction": direction,
            "price": price, "quantity": qty, **kw}


print("[1] 持仓：多账号隔离 + 逆回购/可转债 type 放开")
res = import_holdings_api(HoldingUploadRequest(
    username="trader", source="test", account=A1, broker_name="华泰证券",
    items=[
        holding("204001", "repo", 1000, 1.2, broker_account=A1,
                avail_qty=1000, client_market_value=85000, last_price=1.2),
        holding("204001", "repo", 500, 1.3, broker_account=A2,
                client_market_value=42000),
        holding("127119", "bond_cb", 10, 140.0, name="中鼎转03"),
    ],
)).data
check(res["added"] == 3 and not res["failed"], "3 条全部入库，无 failed: %r" % res)
check(len(res["by_account"]) == 2, "按账号返回 2 组明细")

# A2 再次上传同标的 → 更新而不是新增；A1 不动
res2 = import_holdings_api(HoldingUploadRequest(
    username="trader", source="test", account=A2, broker_name="银河证券",
    items=[holding("204001", "repo", 600, 1.31, broker_account=A2)],
)).data
check(res2["updated"] == 1 and res2["added"] == 0, "同账号同标的覆盖更新，不串到 A1")
rows = db.fetchall("SELECT broker_account, quantity FROM biz_holdings WHERE code='204001' ORDER BY broker_account")
check(dict((r[0], r[1]) for r in rows) == {A1: 1000.0, A2: 600.0}, "两个资金账号各存各的数量")

print("[2] 成交：同日多账号分次上传互不删除")
r1 = import_trades_endpoint(TradeUploadRequest(
    username="trader", source="test", account=A1, broker_name="华泰证券", trade_date=DATE,
    items=[trade("204001", "sell", 1.2, 850, type="repo", amount=85000,
                 trade_id="T-A1-1", biz="通用回购逆回购", broker_account=A1)],
)).data
check(r1["inserted"] == 1 and not r1["failed"], "A1 逆回购成交入库，amount 显式保留")
r2 = import_trades_endpoint(TradeUploadRequest(
    username="trader", source="test", account=A2, broker_name="银河证券", trade_date=DATE,
    items=[trade("127119", "sell", 140.15, 10, type="bond_cb", amount=1401.5,
                 trade_id="T-A2-1", broker_account=A2)],
)).data
check(r2["inserted"] == 1 and r2["deleted"] == 0, "A2 上传不删 A1 的当日成交")
all_trades = get_trades("1", trade_date=DATE)
check(len(all_trades) == 2, "当日共 2 条成交（两账号各 1）")
check(next(t for t in all_trades if t["broker_account"] == A1)["amount"] == 85000.0,
      "逆回购 amount 未被 price*quantity 覆盖")

print("[3] 成交：购回负数量 / 中文业务方向")
r3 = import_trades_endpoint(TradeUploadRequest(
    username="trader", source="test", account=A1, broker_name="华泰证券", trade_date=DATE,
    items=[trade("204001", "通用回购逆回购购回", 1.2, -790, type="repo",
                 amount=79000, trade_id="T-A1-2", biz="通用回购逆回购购回",
                 broker_account=A1)],
)).data
check(r3["inserted"] == 1 and not r3["failed"], "购回负数量被接受")
back = [t for t in get_trades("1", trade_date=DATE) if t["trade_id"] == "T-A1-2"]
check(back[0]["direction"] == "repo_buy" and back[0]["quantity"] == -790,
      "中文业务名归一化为 repo_buy，负数量原样保留")

print("[4] 统一批量：一次 POST 传两个账号的全部数据")
batch = external_batch({
    "username": "trader", "source": "test", "trade_date": DATE,
    "accounts": [
        {"account": A1, "broker_name": "华泰证券",
         "holdings": [
             holding("600519", "stock", 100, 1680.0, name="贵州茅台",
                     client_market_value=170000),
             holding("204001", "repo", 1000, 1.2, name="GC001",
                     client_market_value=85000),
             holding("127119", "bond_cb", 10, 140.0, name="中鼎转03",
                     client_market_value=1400),
         ],
         "trades": [trade("600519", "buy", 1680.0, 100, trade_id="B-A1-1")],
         "orders": [{"order_no": "O-A1-1", "code": "600519", "name": "贵州茅台",
                     "side": "买入", "price": 1680.0, "quantity": 100, "filled_qty": 100}],
         "balance": {"total_asset": 256504.88, "available": 78967.99,
                     "market_value": 177287.30, "today_profit": 737.70},
         "settlements": [{"trade_id": "S-A1-1", "code": "600519", "name": "贵州茅台",
                          "direction": "买入", "price": 1680.0, "quantity": 100,
                          "commission": 25, "stamp_tax": 0, "transfer_fee": 1}]},
        {"account": A2, "broker_name": "银河证券",
         "holdings": [holding("510300", "etf", 10000, 3.85, name="沪深300ETF",
                              client_market_value=39200)],
         "trades": [trade("510300", "buy", 3.92, 10000, trade_id="B-A2-1")],
         "balance": {"total_asset": 50000, "available": 10800, "today_profit": 120}},
    ],
}).data
check(batch["ok"] and batch["account_count"] == 2, "两个账号全部处理")
check(all(not r.get("failed") for r in batch["results"]), "批量端点无失败条目: %r" % batch["totals"])
check(batch["totals"]["failed"] == 0, "汇总 failed=0")
parts = batch["results"][0]["parts"]
check(set(parts) == {"holdings", "trades", "orders", "balance", "settlements"},
      "5 类数据全部落库")

print("[5] 按账号查询 + 账号总览")
orders = list_orders("1", broker_account=A1)
check(len(orders) == 1 and orders[0]["direction"] == "buy", "委托按账号查回且方向归一化")
bals = list_balances("1", broker_account=A1)
check(len(bals) == 1 and bals[0]["total_asset"] == 256504.88, "资金面板按账号查回")
ov = account_overview("1")
check(ov["account_count"] >= 2, "总览列出全部资金账号")
a1 = next(a for a in ov["accounts"] if a["account"] == A1)
check(a1["order_count"] >= 1 and a1["settlement_count"] >= 1 and a1["balance"] is not None,
      "总览含委托数 / 交割单数 / 最新资金面板")

print("[6] 持仓分析汇总：品种、账号、客户端市值")
view = build_holdings_view("1", save_snapshot=False)
labels = {i["type_label"] for i in view["items"]}
check("国债逆回购" in labels and "可转债" in labels, "逆回购 / 可转债进入持仓分析")
check(len(view["summary"]["allocation_by_broker_account"]) >= 2, "按资金账号的资产配置")
check(any(a["account"] == A1 for a in view["summary"]["accounts"]), "summary.accounts 含资金账号")
check(view["summary"]["total_market_value"] > 0, "客户端上报市值进入总市值")

print("[7] dry_run 不写库")
before = db.fetchone("SELECT count(*) FROM biz_trades WHERE fk_user=1")[0]
dry = external_batch({
    "username": "trader", "source": "test", "trade_date": DATE, "dry_run": 1,
    "accounts": [{"account": A1, "trades": [trade("000001", "buy", 10, 100, trade_id="DRY-1")]}],
}).data
after = db.fetchone("SELECT count(*) FROM biz_trades WHERE fk_user=1")[0]
check(dry["dry_run"] and before == after, "dry_run 只预演，不写库")

print("[8] 同日重复上传幂等（收盘后手工重跑 / 断点重传不能 500）")
same_body = {
    "username": "trader", "source": "test", "trade_date": DATE,
    "accounts": [{
        "account": A1, "broker_name": "华泰证券",
        "holdings": [holding("600519", "stock", 100, 1680.0, name="贵州茅台",
                            client_market_value=170000)],
        "trades": [trade("600519", "buy", 1680.0, 100, trade_id="REP-1")],
        "orders": [{"order_no": "REP-O1", "code": "600519", "name": "贵州茅台",
                    "side": "买入", "price": 1680.0, "quantity": 100}],
        "balance": {"total_asset": 256504.88, "available": 78967.99},
        "settlements": [{"trade_id": "REP-S1", "code": "600519", "name": "贵州茅台",
                         "direction": "买入", "price": 1680.0, "quantity": 100}],
    }],
}
r1 = external_batch(same_body).data
r2 = external_batch(same_body).data
check(r1["ok"] and r2["ok"], "两次上传都成功: %r / %r" % (r1["totals"], r2["totals"]))
check(r2["totals"]["failed"] == 0, "第二次上传无失败条目")

print("[9] 交割单行内 trade_date 与请求级不同时，重复上传不 500 不重复")
hist_body = {
    "username": "trader", "source": "test", "trade_date": DATE,
    "accounts": [{
        "account": A1, "broker_name": "华泰证券",
        "settlements": [{"trade_id": "HIST-1", "trade_date": "2026-11-03",
                         "code": "600519", "name": "贵州茅台", "direction": "买入",
                         "price": 1680.0, "quantity": 100}],
    }],
}
h1 = external_batch(hist_body).data
n1 = db.fetchone("SELECT count(*) FROM biz_settlements WHERE fk_user=1 AND trade_id=?",
                 [f"{A1}:HIST-1"])[0]
h2 = external_batch(hist_body).data
n2 = db.fetchone("SELECT count(*) FROM biz_settlements WHERE fk_user=1 AND trade_id=?",
                 [f"{A1}:HIST-1"])[0]
check(h1["ok"] and h2["ok"] and n1 == n2 == 1,
      "历史日期交割单重复上传不 500、不重复: %d/%d" % (n1, n2))

print("[10] 一次性清理：只保留 trader + 白名单资金账号")
# 造脏数据：另一个登录用户的数据 + trader 名下的探测账号
external_batch({
    "username": "legacy", "source": "test", "trade_date": DATE,
    "accounts": [{"account": "LEGACY-ACC",
                  "holdings": [holding("600000", "stock", 100, 10.0)]}],
})
external_batch({
    "username": "trader", "source": "test", "trade_date": DATE,
    "accounts": [{"account": "TESTACC",
                  "holdings": [holding("600001", "stock", 100, 10.0)]}],
})
_junk_where = ("fk_user=2 OR (fk_user=1 AND COALESCE(broker_account,'') NOT IN (?,?))")
_keep_where = "fk_user=1 AND COALESCE(broker_account,'') IN (?,?)"
before_keep = db.fetchone("SELECT count(*) FROM biz_holdings WHERE " + _keep_where,
                          [A1, A2])[0]
before_junk = db.fetchone("SELECT count(*) FROM biz_holdings WHERE " + _junk_where,
                          [A1, A2])[0]
check(before_keep > 0 and before_junk > 0, "清理前：白名单账号有数据、脏数据也在")

try:
    purge_accounts("1", [A1, A2], dry_run=True, confirm="")
    raise AssertionError("缺 confirm 应拒绝")
except ValueError:
    print("  OK 缺 confirm 应拒绝")
try:
    purge_accounts("1", [], dry_run=True, confirm="PURGE")
    raise AssertionError("空 keep_accounts 应拒绝")
except ValueError:
    print("  OK 空 keep_accounts 应拒绝")

pre = purge_accounts("1", [A1, A2], dry_run=True, confirm="PURGE")
check(pre["would_delete"] >= before_junk and pre["deleted"] == 0,
      "dry_run 只统计不写库: would=%d" % pre["would_delete"])
check(db.fetchone("SELECT count(*) FROM biz_holdings WHERE " + _junk_where,
                  [A1, A2])[0] == before_junk, "dry_run 后脏数据仍在")

res = purge_accounts("1", [A1, A2], dry_run=False, confirm="PURGE")
check(res["deleted"] == pre["would_delete"],
      "真实清理删除数等于预演数: %d/%d" % (res["deleted"], pre["would_delete"]))
check(db.fetchone("SELECT count(*) FROM biz_holdings WHERE " + _keep_where,
                  [A1, A2])[0] == before_keep, "白名单资金账号数据完好")
check(db.fetchone("SELECT count(*) FROM biz_holdings WHERE " + _junk_where,
                  [A1, A2])[0] == 0, "其它用户 / 探测账号数据已清空")
check(db.fetchone("SELECT count(*) FROM biz_brokers WHERE account IN ('TESTACC','LEGACY-ACC')")[0] == 0,
      "对应的券商注册行已清理")
check(db.fetchone("SELECT count(*) FROM biz_users")[0] == 2, "登录账号行不动")

print("\nALL EXTERNAL UPLOAD TESTS PASSED")
