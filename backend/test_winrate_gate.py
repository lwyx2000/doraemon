"""大盘门禁 v4 回归测试（标准库 unittest，stub 数据库与行情网关，不触网）。

覆盖：
1. gate 配置校验：默认口径、自定义、非法值一律 fail-fast 且不触达行情层
2. SMA 放行日：严格 >、前 slow-1 根不放行、返回日期集合而非位置索引
3. _build_gate：指数显式 type="INDEX"、显式日期窗口、any/all 集合语义、
   指数取数失败 / 根数不足抛错（绝不静默退化成无门禁）
4. 端到端：门禁关闭与 v3 完全一致；开启后触发数严格 ≤ 全量；
   **按日期对齐而非位置索引**；基线不受门禁影响；signal_days 反映过滤
5. 缓存：gate 配置进 key、开/关不串味、首次与命中都返回 gate、旧缓存降级
6. results 单标的数组结构相对 v2/v3 完全不变（前端表格与 CSV 零改动）

运行：python -m unittest backend/test_winrate_gate.py -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

V2_KEYS = {"symbol", "error", "triggers", "stats_5d", "stats_10d", "stats_20d", "yearly_10d"}


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _load_winrate_service():
    """按文件路径加载，stub 掉数据库与行情网关，纯逻辑测试不触网。"""
    path = Path(__file__).with_name("services") / "winrate_service.py"
    stubs = {
        "database": _mod("database"),
        "database.sqlite_connection": _mod(
            "database.sqlite_connection", get_biz_db=lambda: None
        ),
        "services": _mod("services"),
        "services.market_service": _mod(
            "services.market_service", get_kline=lambda *a, **k: []
        ),
        "services.signal_service": _mod("services.signal_service", EVALUATORS={}),
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("_winrate_gate_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


WIN = _load_winrate_service()


class _DB:
    """最小 SQLite 连接替身：记录所有 INSERT，可预置缓存命中行。"""

    def __init__(self, row=None):
        self.row = row
        self.executed: list[tuple] = []
        self.inserts: list[list] = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if params and "INSERT INTO biz_winrate_scan" in sql:
            self.inserts.append(list(params))

    def fetchone(self, sql, params=None):
        return self.row

    @property
    def insert_params(self):
        return self.inserts[-1] if self.inserts else None


def _dates(n: int, start: date | None = None, step: int = 1) -> list[str]:
    d0 = start or date(2024, 1, 1)
    return [(d0 + timedelta(days=i * step)).isoformat() for i in range(n)]


def _klines(dates: list[str], closes: list[float]) -> list[dict]:
    return [
        {"date": d, "open": c, "close": c, "high": c, "low": c, "volume": 1000}
        for d, c in zip(dates, closes)
    ]


def _rising(n: int = 120, start: date | None = None) -> list[dict]:
    """全程线性上升：10SMA > 20SMA，前 slow-1 根因窗口不足不放行。"""
    return _klines(_dates(n, start), [10.0 + i * 0.5 for i in range(n)])


def _flat(n: int = 120, start: date | None = None) -> list[dict]:
    """全程横盘：10SMA == 20SMA，严格 > 下一律不放行。"""
    return _klines(_dates(n, start), [10.0] * n)


def _falling(n: int = 120, start: date | None = None) -> list[dict]:
    """全程下降：10SMA < 20SMA，一律不放行。"""
    return _klines(_dates(n, start), [100.0 - i * 0.5 for i in range(n)])


def _mk(n: int = 120, drift: float = 0.001, start: date | None = None) -> list[dict]:
    """标的（ETF）日线：单调递增，保证触发样本可成交。"""
    out, price = [], 10.0
    for d in _dates(n, start):
        price *= 1.0 + drift
        out.append({"date": d, "open": round(price, 6), "close": round(price, 6),
                    "high": round(price, 6), "low": round(price, 6), "volume": 1000})
    return out


def _eval_at(*triggers):
    """构造在指定索引 flat→long 的评估器（每次触发持仓 3 天）。"""
    def f(klines, closes, params):
        pos = ["flat"] * len(klines)
        for t in triggers:
            for j in range(t, min(t + 3, len(pos))):
                pos[j] = "long"
        return pos, []
    return f


class _Base(unittest.TestCase):
    def setUp(self):
        self.db = _DB()
        p = patch("builtins.print")
        self.printed = p.start()
        self.addCleanup(p.stop)
        p2 = patch.object(WIN, "get_biz_db", return_value=self.db)
        p2.start()
        self.addCleanup(p2.stop)
        WIN.EVALUATORS.clear()
        WIN.get_kline = lambda *a, **k: []

    def _gate_kline(self, mapping: dict, fallback=None):
        """get_kline stub：type=INDEX 走门禁指数映射，其余走标的日线。"""
        def f(code, **kw):
            if kw.get("type") == "INDEX":
                return mapping.get(code, [])
            return fallback(code, **kw) if fallback else _mk()
        return f


# ---------------------------------------------------------------- 配置校验
class TestNormalizeGate(_Base):
    def test_none_or_disabled_returns_none(self):
        self.assertIsNone(WIN._normalize_gate(None))
        self.assertIsNone(WIN._normalize_gate({}))
        self.assertIsNone(WIN._normalize_gate({"enabled": False}))
        self.assertIsNone(WIN._normalize_gate({"enabled": False, "fast": 0}))

    def test_defaults_are_three_indices_10_20_any(self):
        cfg = WIN._normalize_gate({"enabled": True})
        self.assertEqual(cfg["indices"], ["000300", "000852", "399006"])
        self.assertEqual((cfg["fast"], cfg["slow"], cfg["require"]), (10, 20, "any"))

    def test_custom_config_is_preserved(self):
        cfg = WIN._normalize_gate({
            "enabled": True, "indices": ["000300"], "fast": 5, "slow": 30, "require": "all",
        })
        self.assertEqual(cfg, {"enabled": True, "indices": ["000300"], "fast": 5,
                               "slow": 30, "require": "all"})

    def test_invalid_configs_raise(self):
        bad = [
            "not-a-dict",
            {"enabled": True, "indices": []},
            {"enabled": True, "indices": ["0"] * 6},
            {"enabled": True, "indices": ["000300", "000300"]},
            {"enabled": True, "fast": 20, "slow": 10},
            {"enabled": True, "fast": 0},
            {"enabled": True, "slow": 1},
            {"enabled": True, "fast": True},
            {"enabled": True, "fast": 1.5},
            {"enabled": True, "require": "maybe"},
        ]
        for g in bad:
            with self.subTest(gate=g), self.assertRaises(ValueError):
                WIN._normalize_gate(g)

    def test_invalid_gate_rejected_before_db_or_market(self):
        WIN.get_kline = lambda *a, **k: self.fail("非法门禁不应触达行情层")
        with self.assertRaisesRegex(ValueError, "1 <= fast < slow"):
            WIN.scan_winrate(["A"], "s", {}, (10,), 0.11,
                             gate={"enabled": True, "fast": 30, "slow": 10})
        self.assertEqual(self.db.executed, [], "非法参数不应建表/读缓存")


# ---------------------------------------------------------------- SMA 放行日
class TestSmaAllowedDates(_Base):
    def test_flat_series_never_allowed(self):
        self.assertEqual(WIN._sma_allowed_dates(_flat(), 10, 20), set())

    def test_falling_series_never_allowed(self):
        self.assertEqual(WIN._sma_allowed_dates(_falling(), 10, 20), set())

    def test_rising_series_allows_after_slow_warmup(self):
        kl = _rising()
        allowed = WIN._sma_allowed_dates(kl, 10, 20)
        self.assertEqual(len(allowed), len(kl) - 19)  # 前 slow-1 根不足窗口
        self.assertNotIn(kl[18]["date"], allowed)
        self.assertIn(kl[19]["date"], allowed)
        self.assertIn(kl[-1]["date"], allowed)

    def test_flat_then_rising_only_allows_rising_part(self):
        flat, rise = _flat(30), _rising(40, start=date(2024, 1, 31))
        kl = flat + rise
        allowed = WIN._sma_allowed_dates(kl, 10, 20)
        self.assertFalse(any(k["date"] in allowed for k in flat), "横盘段不得放行")
        self.assertTrue(any(k["date"] in allowed for k in rise), "抬升段应放行")

    def test_insufficient_bars_returns_empty(self):
        self.assertEqual(WIN._sma_allowed_dates(_rising(10), 10, 20), set())

    def test_returns_date_strings_not_positions(self):
        allowed = WIN._sma_allowed_dates(_rising(30), 10, 20)
        self.assertTrue(all(isinstance(d, str) and len(d) == 10 for d in allowed))


# ---------------------------------------------------------------- _build_gate
class TestBuildGate(_Base):
    def setUp(self):
        super().setUp()
        self.calls: list[tuple] = []

    def test_index_kline_explicit_type_count_and_window(self):
        cfg = WIN._normalize_gate({"enabled": True, "indices": ["000300"]})
        calls = []

        def f(code, **kw):
            calls.append((code, kw))
            return _rising()
        WIN.get_kline = f
        window = WIN._scan_window()
        WIN._build_gate(cfg, window)
        self.assertEqual(len(calls), 1, "每个门禁指数只拉一次")
        code, kw = calls[0]
        self.assertEqual(code, "000300")
        self.assertEqual(kw["type"], "INDEX", "指数必须显式传 type，_kline_asset_type 不做猜测")
        self.assertEqual(kw["count"], 0, "count 必须 0，默认 50 会截断 5 年窗口")
        self.assertEqual(kw["start_date"], window[0])
        self.assertEqual(kw["end_date"], window[1])

    def test_any_mode_is_union(self):
        cfg = WIN._normalize_gate({
            "enabled": True, "indices": ["000300", "000852"], "require": "any",
        })
        WIN.get_kline = self._gate_kline({"000300": _rising(), "000852": _flat()})
        allowed, summary = WIN._build_gate(cfg, WIN._scan_window())
        self.assertEqual(len(allowed), 101, "any = 并集")
        self.assertEqual(summary["require"], "any")
        self.assertEqual(summary["allowed_days"], 101)
        self.assertEqual(summary["per_index"][1]["allowed_days"], 0)

    def test_all_mode_is_intersection(self):
        cfg = WIN._normalize_gate({
            "enabled": True, "indices": ["000300", "000852"], "require": "all",
        })
        WIN.get_kline = self._gate_kline({"000300": _rising(), "000852": _flat()})
        allowed, summary = WIN._build_gate(cfg, WIN._scan_window())
        self.assertEqual(allowed, set(), "all = 交集，一个全拦截即全拦截")
        self.assertEqual(summary["allowed_days"], 0)
        self.assertEqual(summary["blocked_days"], summary["total_days"])

    def test_summary_fields_and_note(self):
        cfg = WIN._normalize_gate({"enabled": True, "indices": ["000300"]})
        WIN.get_kline = self._gate_kline({"000300": _rising()})
        _, summary = WIN._build_gate(cfg, WIN._scan_window())
        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["total_days"], 120)
        self.assertEqual(summary["blocked_days"], 120 - summary["allowed_days"])
        self.assertEqual(summary["per_index"][0]["bars"], 120)
        self.assertIn("基线仍为全部交易日", summary["note"])

    def test_index_fetch_failure_raises_instead_of_silent_bypass(self):
        cfg = WIN._normalize_gate({"enabled": True, "indices": ["000300"]})
        WIN.get_kline = self._gate_kline({"000300": []})
        with self.assertRaisesRegex(ValueError, "日线不足"):
            WIN._build_gate(cfg, WIN._scan_window())

    def test_index_insufficient_bars_raises(self):
        cfg = WIN._normalize_gate({"enabled": True, "indices": ["000300"]})
        WIN.get_kline = self._gate_kline({"000300": _rising(10)})
        with self.assertRaisesRegex(ValueError, "10 根 < 20 根"):
            WIN._build_gate(cfg, WIN._scan_window())

    def test_gate_failure_surfaces_from_scan_winrate(self):
        WIN.get_kline = self._gate_kline({"000300": [], "000852": [], "399006": []})
        with self.assertRaisesRegex(ValueError, "大盘门禁指数"):
            WIN.scan_winrate(["A"], "s", {}, (10,), 0.11, gate={"enabled": True})
        self.assertEqual(self.db.inserts, [], "门禁失败不得写入任何结果缓存")


# ---------------------------------------------------------------- 端到端 / 日期对齐
class TestScanWithGate(_Base):
    def _baseline_scan(self, gate=None, symbol_klines=None, index_map=None):
        WIN.EVALUATORS["s"] = _eval_at(10, 40, 70, 100)
        if index_map is None:
            index_map = {"000300": _rising(), "000852": _rising(), "399006": _rising()}
        WIN.get_kline = self._gate_kline(index_map, fallback=lambda *a, **k: symbol_klines or _mk())
        return WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11, gate=gate)

    def test_gate_off_is_identical_to_v3(self):
        calls = []

        def f(code, **kw):
            calls.append((code, kw))
            return _mk()
        WIN.get_kline = f
        WIN.EVALUATORS["s"] = _eval_at(10, 40, 70, 100)
        out = WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11)
        self.assertEqual(len(calls), 1, "门禁关闭不得额外拉指数日线")
        self.assertNotIn("type", calls[0][1], "标的不应被误标成 INDEX")
        self.assertIsNone(out["gate"])
        self.assertEqual(out["results"][0]["triggers"], 4)

    def test_gate_disabled_same_as_none(self):
        a = self._baseline_scan()
        self.db.inserts.clear()
        b = self._baseline_scan(gate={"enabled": False})
        self.assertEqual(a["results"], b["results"])
        self.assertIsNone(b["gate"])

    def test_gate_on_triggers_are_subset_of_ungated(self):
        base = self._baseline_scan()
        self.db.inserts.clear()
        # 门禁指数前 60 根横盘（拦截），后 60 根上升（放行）
        gate_kl = _flat(60) + _rising(60, start=date(2024, 3, 1))
        on = self._baseline_scan(
            gate={"enabled": True, "indices": ["000300"], "require": "all"},
            index_map={"000300": gate_kl},
        )
        self.assertLessEqual(on["results"][0]["triggers"], base["results"][0]["triggers"])
        self.assertLessEqual(on["pooled"]["strategy"]["n"], base["pooled"]["strategy"]["n"])
        self.assertTrue(on["gate"]["enabled"])
        self.assertGreater(on["gate"]["blocked_days"], 0)

    def test_date_alignment_no_overlap_blocks_all_not_by_position(self):
        """指数与 ETF 日期完全不重叠：按日期应 0 触发；按位置索引会错误放行 3 个。"""
        far = date(2024, 8, 1)
        out = self._baseline_scan(
            gate={"enabled": True, "indices": ["000300"], "require": "all"},
            symbol_klines=_mk(start=far),
            index_map={"000300": _rising()},  # 指数停在 2024-01 ~ 2024-04
        )
        self.assertEqual(out["results"][0]["triggers"], 0,
                         "门禁按日期对齐；若按位置索引会错误放行 t>=19 的触发点")
        self.assertEqual(out["pooled"]["strategy"]["n"], 0)

    def test_date_alignment_partial_overlap(self):
        """指数只覆盖前 60 天且全程满足 → 仅早于该日期的触发点放行。"""
        out = self._baseline_scan(
            gate={"enabled": True, "indices": ["000300"], "require": "all"},
            index_map={"000300": _rising(60)},  # 2024-01-01 ~ 2024-02-29
        )
        # 触发点 t=10/40/70/100，日期为 d0+t；指数放行 d0+19 ~ d0+59
        self.assertEqual(out["results"][0]["triggers"], 1, "仅 t=40 落在门禁放行区间")
        self.assertLessEqual(out["pooled"]["distinct_signal_days"], 1)

    def test_baseline_is_not_gated(self):
        base = self._baseline_scan()
        self.db.inserts.clear()
        on = self._baseline_scan(
            gate={"enabled": True, "indices": ["000300"], "require": "all"},
            index_map={"000300": _flat()},  # 全拦截
        )
        self.assertEqual(on["pooled"]["baseline"]["n"], base["pooled"]["baseline"]["n"],
                         "基线必须保持全量交易日，否则策略与基线口径不可比")
        self.assertEqual(on["pooled"]["strategy"]["n"], 0)
        self.assertEqual(on["pooled"]["verdict"], "无触发样本，不下结论")

    def test_results_shape_is_unchanged(self):
        out = self._baseline_scan(gate={"enabled": True, "indices": ["000300"]})
        self.assertEqual(set(out["results"][0].keys()), V2_KEYS)
        self.assertNotIn("gate", out["results"][0])
        self.assertNotIn("allowed_dates", out["results"][0])

    def test_pooled_structure_is_unchanged(self):
        base = self._baseline_scan()
        self.db.inserts.clear()
        on = self._baseline_scan(gate={"enabled": True, "indices": ["000300"]})
        self.assertEqual(set(base["pooled"].keys()), set(on["pooled"].keys()))

    def test_gate_all_blocked_still_returns_valid_payload(self):
        out = self._baseline_scan(
            gate={"enabled": True, "indices": ["000300"], "require": "all"},
            index_map={"000300": _flat()},
        )
        self.assertIsNone(out["results"][0]["error"], "门禁全拦截不是错误，是 0 触发")
        self.assertEqual(out["results"][0]["triggers"], 0)
        self.assertEqual(out["pooled"]["symbols"]["valid"], 1)


# ---------------------------------------------------------------- 缓存
class TestCacheKeyAndPayload(_Base):
    def _scan(self, gate=None):
        WIN.EVALUATORS["s"] = _eval_at(10, 40)
        WIN.get_kline = self._gate_kline(
            {"000300": _rising(), "000852": _rising(), "399006": _rising()},
            fallback=lambda *a, **k: _mk(),
        )
        return WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11, gate=gate)

    def test_cache_key_contains_gate_config(self):
        self._scan(gate={"enabled": True, "indices": ["000300"], "require": "all"})
        key = json.loads(self.db.insert_params[3])
        self.assertEqual(key["v"], 5)
        self.assertEqual(key["g"]["indices"], ["000300"])
        self.assertEqual(key["g"]["require"], "all")

    def test_gate_on_off_do_not_share_cache_key(self):
        self._scan()
        off_key = self.db.inserts[-1][3]
        self._scan(gate={"enabled": True})
        on_key = self.db.inserts[-1][3]
        self.assertNotEqual(off_key, on_key, "同日门禁开/关必须落不同缓存行")
        self.assertIsNone(json.loads(off_key)["g"])
        self.assertTrue(json.loads(on_key)["g"]["enabled"])

    def test_disabled_gate_shares_key_with_none(self):
        self._scan()
        none_key = self.db.inserts[-1][3]
        self._scan(gate={"enabled": False})
        self.assertEqual(none_key, self.db.inserts[-1][3])

    def test_different_gate_modes_do_not_share_cache_key(self):
        self._scan(gate={"enabled": True, "require": "any"})
        any_key = self.db.inserts[-1][3]
        self._scan(gate={"enabled": True, "require": "all"})
        self.assertNotEqual(any_key, self.db.inserts[-1][3])

    def test_first_and_cached_response_both_carry_gate(self):
        first = self._scan(gate={"enabled": True})
        self.assertTrue(first["gate"]["enabled"])
        payload = json.dumps({"results": first["results"], "pooled": first["pooled"],
                              "gate": first["gate"]}, ensure_ascii=False)
        self.db.row = (payload,)
        WIN.get_kline = lambda *a, **k: self.fail("命中缓存时不应再取行情")
        hit = WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11,
                               gate={"enabled": True})
        self.assertTrue(hit["from_cache"])
        self.assertEqual(hit["gate"], first["gate"])

    def test_legacy_cached_payload_without_gate_degrades_to_none(self):
        self.db.row = (json.dumps({"results": [{"symbol": "A", "error": None}],
                                   "pooled": None}),)
        WIN.get_kline = lambda *a, **k: self.fail("命中缓存时不应再取行情")
        hit = WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11)
        self.assertIsNone(hit["gate"])

    def test_legacy_bare_list_cache_degrades_to_none(self):
        self.db.row = (json.dumps([{"symbol": "A", "error": None}]),)
        WIN.get_kline = lambda *a, **k: self.fail("命中缓存时不应再取行情")
        hit = WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11)
        self.assertIsNone(hit["gate"])
        self.assertIsNone(hit["pooled"])
        self.assertIsNone(hit["exposure"], "v4 旧缓存无 exposure，必须优雅降级为 null")

    def test_cache_payload_contains_gate(self):
        self._scan(gate={"enabled": True})
        payload = json.loads(self.db.insert_params[4])
        self.assertIn("gate", payload)
        self.assertEqual(set(payload.keys()),
                         {"results", "pooled", "gate", "exposure"})
        self.assertEqual(payload["exposure"]["mode"], "full",
                         "二元组策略必须走满仓口径，不能被误判成分级仓位")


if __name__ == "__main__":
    unittest.main()
