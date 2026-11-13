"""get_kline 行情链路回归测试（标准库 unittest，stub 掉数据库与网关，不触网）。

覆盖：
1. 资产类型路由：ETF/个股/显式 type 覆盖/指数必须显式（不与代码段猜）
2. 字段映射：中英文列名兼容、amount 刻意不映射、count 截断
3. 容灾链 fail-fast 契约：显式 type + 日期窗口、5xx 不重试、
   仅 no_data 重试一次、失败绝不伪装成「标的无行情」
4. get_kline 集成：转债仍走 bond_zh_hs_daily、日期规范化、count 语义

运行：python -m unittest backend/test_kline_quote_route.py -v
"""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _load_market_service():
    path = Path(__file__).with_name("services") / "market_service.py"
    stubs = {
        # 本地托管 Python 可能没有 requests；get_session 已被 stub，
        # 模块级只需要 requests.exceptions 这两个符号存在即可。
        "requests": _mod(
            "requests",
            exceptions=_mod("requests.exceptions",
                            Timeout=type("Timeout", (Exception,), {}),
                            ConnectionError=type("ConnectionError", (Exception,), {})),
        ),
        "core": _mod("core"),
        "core.config": _mod("core.config", AKSHARE_API_BASE="http://gateway.test",
                            USE_MOCK_DATA=False),
        "database": _mod("database"),
        "database.bulk": _mod("database.bulk", bulk_insert=lambda *a, **k: None),
        "services": _mod("services"),
        "services.akshare_client": _mod("services.akshare_client",
                                        get_session=lambda: None),
        "services.meta_utils": _mod("services.meta_utils",
                                    gateway_no_data_meta=lambda: {}),
        "mock_data": _mod("mock_data"),
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("_ms_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


MS = _load_market_service()


class _Resp:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    """按顺序返回预设响应，并记录每次请求参数。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok(rows):
    return _Resp({"code": 200, "message": "success", "data": rows,
                  "meta": {"status": "ok", "adjust": "qfq", "source": "qq"}})


def _no_data():
    return _Resp({"code": 200, "message": "success", "data": [],
                  "meta": {"status": "no_data", "reason": "upstream_empty"}})


ROWS = [
    {"date": "2026-11-10", "open": 4.1, "close": 4.2, "high": 4.3,
     "low": 4.0, "volume": 100.0, "amount": None},
    {"日期": "2026-11-11", "开盘": 4.2, "收盘": 4.3, "最高": 4.4,
     "最低": 4.1, "成交量": 120, "成交额": 500.0},
    {"date": "2026-11-12", "open": 4.3, "close": 4.4, "high": 4.5,
     "low": 4.2, "volume": 130.0, "amount": None},
]

MAPPED_ROWS = MS._map_kline_rows(ROWS)


class TestAssetType(unittest.TestCase):
    def test_fund_code_segments_route_to_etf(self):
        for c in ("510300", "159915", "588000", "560050", "511010",
                  "161725", "501300", "518880", "513100"):
            self.assertEqual(MS._kline_asset_type(c), "ETF", c)

    def test_stock_codes_route_to_stock(self):
        for c in ("600519", "000001", "300750", "688981", "000858"):
            self.assertEqual(MS._kline_asset_type(c), "STOCK", c)

    def test_explicit_type_overrides(self):
        self.assertEqual(MS._kline_asset_type("510300", "STOCK"), "STOCK")
        self.assertEqual(MS._kline_asset_type("600519", "etf"), "ETF")
        self.assertEqual(MS._kline_asset_type("000300", "INDEX"), "INDEX")
        # 000001 既是个股又是上证指数：自动判定必须保守为 STOCK，不猜
        self.assertEqual(MS._kline_asset_type("000001"), "STOCK")
        self.assertEqual(MS._kline_asset_type("000001", "index"), "INDEX")

    def test_unknown_hint_falls_back_to_code_segment(self):
        self.assertEqual(MS._kline_asset_type("510300", "cb"), "ETF")
        self.assertEqual(MS._kline_asset_type("600519", None), "STOCK")


class TestMapKlineRows(unittest.TestCase):
    def test_chinese_and_english_columns(self):
        out = MS._map_kline_rows(ROWS)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["date"], "2026-11-10")
        self.assertEqual(out[1]["close"], 4.3)
        self.assertEqual(out[1]["volume"], 120)
        self.assertEqual(set(out[0]), {"date", "open", "close", "high", "low", "volume"})

    def test_amount_is_never_mapped(self):
        # 上游 amount 部分源为 null，策略层不得依赖；映射层直接丢弃
        self.assertNotIn("amount", MS._map_kline_rows(ROWS)[0])
        self.assertNotIn("成交额", MS._map_kline_rows(ROWS)[1])

    def test_count_and_invalid_rows(self):
        self.assertEqual(len(MS._map_kline_rows(ROWS, count=2)), 2)
        self.assertEqual(MS._map_kline_rows(ROWS, count=2)[0]["date"], "2026-11-11")
        self.assertEqual(MS._map_kline_rows([{"date": "2026-11-12"}]), [])
        self.assertEqual(MS._map_kline_rows(None), [])


class TestQuoteChainContract(unittest.TestCase):
    def _run(self, *responses):
        session = _Session(*responses)
        with patch.object(MS, "get_session", lambda: session):
            out = MS._fetch_kline_via_quote("510300", "ETF", "2021-11-13", "2026-11-12")
        return out, session.calls

    def test_success_sends_explicit_type_and_window(self):
        out, calls = self._run(_ok(ROWS))
        self.assertEqual(len(out), 3)
        self.assertEqual(len(calls), 1)
        p = calls[0]["params"]
        self.assertEqual(p["type"], "ETF")
        self.assertEqual(p["code"], "510300")
        self.assertEqual(p["start_date"], "2021-11-13")
        self.assertEqual(p["end_date"], "2026-11-12")
        self.assertEqual(p["adjust"], "qfq")
        self.assertIn("/api/quote/kline", calls[0]["url"])

    def test_no_data_retried_exactly_once(self):
        out, calls = self._run(_no_data(), _ok(ROWS))
        self.assertEqual(len(out), 3)
        self.assertEqual(len(calls), 2)

    def test_persistent_no_data_returns_empty_after_two_calls(self):
        out, calls = self._run(_no_data(), _no_data())
        self.assertEqual(out, [])
        self.assertEqual(len(calls), 2)

    def test_http_error_is_never_retried(self):
        for resp in (_Resp({}, status_code=500), _Resp({}, status_code=503),
                     _Resp({}, status_code=504)):
            out, calls = self._run(resp, _ok(ROWS))
            self.assertEqual(out, [])
            self.assertEqual(len(calls), 1, "5xx 不能被重试放大")

    def test_business_error_is_never_retried(self):
        err = _Resp({"code": 422, "message": "bad type", "data": None})
        out, calls = self._run(err, _ok(ROWS))
        self.assertEqual(out, [])
        self.assertEqual(len(calls), 1)

    def test_ok_but_empty_is_not_retried(self):
        empty = _Resp({"code": 200, "data": [], "meta": {"status": "ok"}})
        out, calls = self._run(empty, _ok(ROWS))
        self.assertEqual(out, [])
        self.assertEqual(len(calls), 1)

    def test_exception_returns_empty_without_retry(self):
        out, calls = self._run(TimeoutError("upstream"), _ok(ROWS))
        self.assertEqual(out, [])
        self.assertEqual(len(calls), 1)


class TestGetKlineIntegration(unittest.TestCase):
    def test_etf_uses_quote_chain_with_normalized_dates(self):
        with patch.object(MS, "_fetch_kline_via_quote", return_value=MAPPED_ROWS) as q:
            out = MS.get_kline("510300", start_date="20211113",
                               end_date="20261112", count=0)
        self.assertEqual(len(out), 3)
        args = q.call_args.args
        self.assertEqual(args[1], "ETF")
        self.assertEqual(args[2], "2021-11-13")
        self.assertEqual(args[3], "2026-11-12")

    def test_stock_uses_stock_type(self):
        with patch.object(MS, "_fetch_kline_via_quote", return_value=[]) as q:
            MS.get_kline("600519")
        self.assertEqual(q.call_args.args[1], "STOCK")

    def test_explicit_index_type_passed_through(self):
        with patch.object(MS, "_fetch_kline_via_quote", return_value=[]) as q:
            MS.get_kline("000300", type="INDEX")
        self.assertEqual(q.call_args.args[1], "INDEX")

    def test_count_keeps_last_n_after_date_filter(self):
        with patch.object(MS, "_fetch_kline_via_quote", return_value=MAPPED_ROWS):
            out = MS.get_kline("510300", start_date="2026-11-11",
                               end_date="2026-11-12", count=1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["date"], "2026-11-12")

    def test_cb_keeps_bond_path_and_never_hits_quote_chain(self):
        with patch.object(MS, "_fetch_real_kline", return_value=[]) as bond, \
             patch.object(MS, "_fetch_kline_via_quote", return_value=ROWS) as q:
            MS.get_kline("113050", count=0)
            MS.get_kline("600519", type="cb", count=0)
        self.assertEqual(bond.call_count, 2)
        self.assertEqual(bond.call_args_list[0].args[0], "bond_zh_hs_daily")
        self.assertEqual(bond.call_args_list[0].args[1]["symbol"], "sh113050")
        q.assert_not_called()


if __name__ == "__main__":
    unittest.main()
