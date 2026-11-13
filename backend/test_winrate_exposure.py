"""胜率扫描 v5：可选分级仓位（exposure）契约与逐日账本回归测试。

标准库 unittest，stub 掉数据库与行情网关，纯逻辑不触网。

覆盖：
1. _normalize_eval：二元组 → exposure=None（满仓快速路径）；三元组严格校验
   长度 / 有限数值 / 0~1 区间，非法一律 fail-fast，绝不静默夹紧
2. _holding_return：
   - exposure=None 时与 v4 原公式**精确相等**（既有 12 策略零变化的根基）
   - exposure≡1 时望远镜积恒等于满仓公式（口径只有一套）
   - T-1 目标仓位决定 T 日收益（无前视，对齐技能 backtest 的 pos=target[i-1]）
   - 成本按 turnover：单调减仓路径总 turnover ≡ 2（不额外收费），回补加仓才增加
3. _exposure_summary：full / ladder / 全失败标的三种形态
4. _scan_symbol：results 结构不变、基线不受 exposure 影响、单只异常隔离
5. scan_winrate：首次 / 缓存命中 / 旧缓存降级都正确透出 exposure，schema=v5，
   大盘门禁与分级仓位可共存

运行：python -m unittest backend/test_winrate_exposure.py -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

V2_KEYS = {"symbol", "error", "triggers", "stats_5d", "stats_10d", "stats_20d", "yearly_10d"}


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _load_winrate_service():
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
        spec = importlib.util.spec_from_file_location("_winrate_exposure_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


WIN = _load_winrate_service()


class _DB:
    def __init__(self, row=None):
        self.row = row
        self.executed = []
        self.inserts = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if params and "INSERT INTO biz_winrate_scan" in sql:
            self.inserts.append(list(params))

    def fetchone(self, sql, params=None):
        return self.row

    @property
    def insert_params(self):
        return self.inserts[-1] if self.inserts else None


def _mk(n=120, drift=0.004):
    """确定性递增日线，保证触发样本可成交、收益为正。"""
    dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]
    out, price = [], 10.0
    for d in dates:
        price *= 1.0 + drift
        out.append({"date": d, "open": price, "close": price,
                    "high": price * 1.01, "low": price * 0.99, "volume": 1000})
    return out


def _eval_binary(*triggers):
    """二元组评估器：在指定索引 flat→long，每次持仓 3 天。"""
    def f(klines, closes, params):
        pos = ["flat"] * len(klines)
        for t in triggers:
            for j in range(t, min(t + 3, len(pos))):
                pos[j] = "long"
        return pos, []
    return f


def _eval_ladder(*triggers, level=0.5):
    """三元组评估器：与 _eval_binary 同触发点，exposure 恒为 level。"""
    def f(klines, closes, params):
        pos, sig = _eval_binary(*triggers)(klines, closes, params)
        return pos, sig, [level] * len(klines)
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
        WIN.get_kline = lambda *a, **k: _mk()


# ---------------------------------------------------------------- 契约归一化
class TestNormalizeEval(_Base):
    def test_binary_returns_full_position_fast_path(self):
        pos = ["flat", "long", "flat"]
        got_pos, exposure = WIN._normalize_eval((pos, []), 3)
        self.assertIs(got_pos, pos)
        self.assertIsNone(exposure, "二元组必须走满仓快速路径，保证 v4 数值逐字节一致")

    def test_triple_returns_validated_exposure(self):
        pos = ["flat", "long", "long"]
        got_pos, exposure = WIN._normalize_eval((pos, [], [0, 0.5, 1]), 3)
        self.assertIs(got_pos, pos)
        self.assertEqual(exposure, [0.0, 0.5, 1.0])
        self.assertTrue(all(isinstance(x, float) for x in exposure))

    def test_invalid_shapes_raise(self):
        pos = ["flat", "long", "flat"]
        bad = [
            None, "abc", (pos,), (pos, [], [], []),
            (["flat"], [], [0.5]),                       # position 长度不符
            (pos, [], None),                             # exposure=None
            (pos, [], [0.5, 0.5]),                      # exposure 长度不符
            (pos, [], [0.5, 0.5, 0.5, 0.5]),
        ]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                WIN._normalize_eval(raw, 3)

    def test_invalid_exposure_values_raise(self):
        pos = ["flat", "long", "flat"]
        # 取值越界 / 非有限数属于数据校验错误 → ValueError
        bad_ranges = [
            [0.5, -0.1, 0.5], [0.5, 1.1, 0.5],
            [0.5, float("nan"), 0.5], [0.5, float("inf"), 0.5],
        ]
        for exp in bad_ranges:
            with self.subTest(exp=exp), self.assertRaises(ValueError):
                WIN._normalize_eval((pos, [], exp), 3)
        # 元素类型不对属于类型错误 → TypeError（ruff TRY004 / 专业做法）
        bad_types = [[0.5, "0.5", 0.5], [0.5, True, 0.5], [0.5, None, 0.5]]
        for exp in bad_types:
            with self.subTest(exp=exp), self.assertRaises(TypeError):
                WIN._normalize_eval((pos, [], exp), 3)


# ---------------------------------------------------------------- 逐日账本
class TestHoldingReturn(_Base):
    CLOSES: ClassVar[list[float]] = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    BUY, SELL = 1, 4

    def _v4(self, cost=0.11):
        return (self.CLOSES[self.SELL] / self.CLOSES[self.BUY] - 1) * 100 - cost

    def test_none_is_bit_identical_to_v4_formula(self):
        got = WIN._holding_return(self.CLOSES, self.BUY, self.SELL, None, 0.11)
        self.assertEqual(got, self._v4(), "二元组路径必须精确等于 v4 公式，不能走浮点近似")

    def test_all_one_is_telescoping_equivalent(self):
        got = WIN._holding_return(self.CLOSES, self.BUY, self.SELL,
                                  [1.0] * 6, 0.11)
        self.assertAlmostEqual(got, self._v4(), places=9,
                               msg="w≡1 时望远镜积应恒等于满仓公式（口径只有一套）")

    def test_t_minus_one_lag_no_lookahead(self):
        """w[t]=exposure[t-1]：第 2 日起清零，则只有 [buy,buy+1] 一段收益参与。"""
        exp = [1.0, 1.0, 0.0, 0.0, 0.0, 0.0]
        got = WIN._holding_return(self.CLOSES, self.BUY, self.SELL, exp, 0.0)
        want = (self.CLOSES[2] / self.CLOSES[1] - 1) * 100
        self.assertAlmostEqual(got, want, places=9)
        # 若误用 exposure[t]（当日），第一段也会被清零，结果应为 0
        self.assertNotAlmostEqual(got, 0.0, places=6)

    def test_zero_exposure_means_no_trade_no_cost(self):
        got = WIN._holding_return(self.CLOSES, self.BUY, self.SELL,
                                  [0.0] * 6, 0.11)
        self.assertEqual(got, 0.0)

    def test_monotonic_ladder_cost_equals_full_round_trip(self):
        """只减不加：总 turnover ≡ 2×w[buy]，减仓本身不额外收费。"""
        exp = [1.0, 1.0, 0.5, 0.25, 0.25, 0.25]
        gross = WIN._holding_return(self.CLOSES, self.BUY, self.SELL, exp, 0.0)
        net = WIN._holding_return(self.CLOSES, self.BUY, self.SELL, exp, 0.11)
        self.assertAlmostEqual(gross - net, 0.11, places=9)

    def test_reloading_increases_turnover_cost(self):
        """回补加仓是额外交易，成本必须高于只减不加。"""
        exp = [1.0, 1.0, 0.25, 1.0, 1.0, 1.0]
        gross = WIN._holding_return(self.CLOSES, self.BUY, self.SELL, exp, 0.0)
        net = WIN._holding_return(self.CLOSES, self.BUY, self.SELL, exp, 0.11)
        self.assertAlmostEqual(gross - net, 0.11 * 3.5 / 2, places=9)

    def test_lower_exposure_scales_return(self):
        half = WIN._holding_return(self.CLOSES, self.BUY, self.SELL, [0.5] * 6, 0.0)
        full = WIN._holding_return(self.CLOSES, self.BUY, self.SELL, [1.0] * 6, 0.0)
        self.assertGreater(full, half)
        self.assertGreater(half, 0.0)

    def test_zero_cost_is_pure_price_return(self):
        got = WIN._holding_return(self.CLOSES, self.BUY, self.SELL, None, 0.0)
        self.assertEqual(got, (14.0 / 11.0 - 1) * 100)


# ---------------------------------------------------------------- 顶层摘要
class TestExposureSummary(_Base):
    @staticmethod
    def _detail(mode="full", levels=None, total=100.0, bars=100, error=None):
        return {"error": error, "exposure_mode": mode,
                "exposure_levels": levels or [],
                "exposure_sum": total, "exposure_bars": bars}

    def test_full_mode(self):
        s = WIN._exposure_summary([self._detail()], "bias")
        self.assertEqual(s["mode"], "full")
        self.assertEqual(s["levels"], [])
        self.assertEqual(s["avg_exposure"], 1.0)
        self.assertIn("满仓", s["note"])
        self.assertEqual(s["strategy_id"], "bias")

    def test_ladder_mode_levels_descending(self):
        ds = [self._detail("ladder", [1.0, 0.5, 0.25], 60.0),
              self._detail("ladder", [1.0, 0.125], 40.0)]
        s = WIN._exposure_summary(ds, "bias_ladder")
        self.assertEqual(s["mode"], "ladder")
        self.assertEqual(s["levels"], [1.0, 0.5, 0.25, 0.125])
        self.assertEqual(s["avg_exposure"], 0.5)
        self.assertIn("T-1", s["note"])

    def test_all_failed_symbols_do_not_crash(self):
        s = WIN._exposure_summary([self._detail(error="boom", total=0.0, bars=0)], "s")
        self.assertEqual(s["mode"], "full")
        self.assertIsNone(s["avg_exposure"])

    def test_failed_symbols_excluded_from_average(self):
        s = WIN._exposure_summary([self._detail(),
                                   self._detail(error="boom", total=0.0, bars=0)], "s")
        self.assertEqual(s["avg_exposure"], 1.0)


# ---------------------------------------------------------------- 单标的扫描
class TestScanSymbol(_Base):
    WINDOW = ("2020-01-01", "2026-11-14")

    def test_binary_strategy_keeps_v2_shape_and_full_mode(self):
        WIN.EVALUATORS["s"] = _eval_binary(10, 40, 70, 100)
        result, detail = WIN._scan_symbol("A", "s", {}, (5, 10, 20), 0.11,
                                          self.WINDOW, 10)
        self.assertEqual(set(result), V2_KEYS)
        self.assertIsNone(result["error"])
        self.assertEqual(detail["exposure_mode"], "full")
        self.assertEqual(detail["exposure_levels"], [])
        self.assertEqual(detail["exposure_sum"], float(detail["bars"]))
        self.assertGreater(len(detail["baseline"]), 0)

    def test_ladder_strategy_uses_exposure_and_keeps_shape(self):
        WIN.EVALUATORS["s"] = _eval_ladder(10, 40, 70, 100, level=0.5)
        result, detail = WIN._scan_symbol("A", "s", {}, (5, 10, 20), 0.11,
                                          self.WINDOW, 10)
        self.assertEqual(set(result), V2_KEYS)
        self.assertIsNone(result["error"])
        self.assertEqual(detail["exposure_mode"], "ladder")
        self.assertEqual(detail["exposure_levels"], [0.5])
        self.assertGreater(len(detail["strategy"]), 0)

    def test_baseline_identical_with_or_without_exposure(self):
        WIN.EVALUATORS["s"] = _eval_binary(10, 40, 70, 100)
        _, d_full = WIN._scan_symbol("A", "s", {}, (5, 10, 20), 0.11, self.WINDOW, 10)
        WIN.EVALUATORS["s"] = _eval_ladder(10, 40, 70, 100, level=0.25)
        _, d_ladder = WIN._scan_symbol("A", "s", {}, (5, 10, 20), 0.11, self.WINDOW, 10)
        self.assertEqual(d_full["baseline"], d_ladder["baseline"],
                         "市场基线必须保持满仓，不能随策略仓位变化")
        self.assertEqual(d_full["signal_days"], d_ladder["signal_days"],
                         "触发点由 position 决定，不能受 exposure 影响")

    def test_ladder_return_differs_from_full_but_keeps_trigger_count(self):
        WIN.EVALUATORS["s"] = _eval_binary(10, 40, 70, 100)
        r_full, d_full = WIN._scan_symbol("A", "s", {}, (5, 10, 20), 0.11, self.WINDOW, 10)
        WIN.EVALUATORS["s"] = _eval_ladder(10, 40, 70, 100, level=0.25)
        r_ladder, d_ladder = WIN._scan_symbol("A", "s", {}, (5, 10, 20), 0.11, self.WINDOW, 10)
        self.assertEqual(r_full["triggers"], r_ladder["triggers"])
        self.assertNotEqual(d_full["strategy"], d_ladder["strategy"])
        self.assertLess(sum(d_ladder["strategy"]), sum(d_full["strategy"]),
                        "低仓位在上涨行情里应显著降低收益")

    def test_explicit_all_one_matches_full_path(self):
        WIN.EVALUATORS["s"] = _eval_binary(10, 40, 70, 100)
        r_full, d_full = WIN._scan_symbol("A", "s", {}, (5, 10, 20), 0.11, self.WINDOW, 10)
        WIN.EVALUATORS["s"] = _eval_ladder(10, 40, 70, 100, level=1.0)
        r_one, d_one = WIN._scan_symbol("A", "s", {}, (5, 10, 20), 0.11, self.WINDOW, 10)
        self.assertEqual(d_one["exposure_mode"], "ladder")
        for a, b in zip(d_full["strategy"], d_one["strategy"]):
            self.assertAlmostEqual(a, b, places=9, msg="w≡1 应与满仓口径一致")
        self.assertEqual(r_full["triggers"], r_one["triggers"])

    def test_invalid_exposure_isolated_to_one_symbol(self):
        def bad(klines, closes, params):
            pos, sig = _eval_binary(10)(klines, closes, params)
            return pos, sig, [0.5] * (len(klines) - 1)  # 长度不符
        WIN.EVALUATORS["s"] = bad
        result, detail = WIN._scan_symbol("A", "s", {}, (5, 10, 20), 0.11, self.WINDOW, 10)
        self.assertIsNotNone(result["error"])
        self.assertIn("exposure 长度", result["error"])
        self.assertEqual(set(result), V2_KEYS)
        self.assertIsNotNone(detail["error"])

    def test_out_of_range_exposure_fails_fast(self):
        def bad(klines, closes, params):
            pos, sig = _eval_binary(10)(klines, closes, params)
            return pos, sig, [1.5] * len(klines)
        WIN.EVALUATORS["s"] = bad
        result, _ = WIN._scan_symbol("A", "s", {}, (5, 10, 20), 0.11, self.WINDOW, 10)
        self.assertIn("0~1", result["error"])


# ---------------------------------------------------------------- 端到端 / 缓存
class TestScanWinrate(_Base):
    def test_schema_version_is_five(self):
        self.assertEqual(WIN.SCAN_SCHEMA_VERSION, 5)

    def test_first_scan_returns_and_persists_exposure(self):
        WIN.EVALUATORS["s"] = _eval_ladder(10, 40, 70, 100, level=0.5)
        out = WIN.scan_winrate(["A", "B"], "s", {}, (5, 10, 20), 0.11)
        self.assertFalse(out["from_cache"])
        self.assertEqual(out["exposure"]["mode"], "ladder")
        self.assertEqual(out["exposure"]["levels"], [0.5])
        self.assertEqual(out["exposure"]["avg_exposure"], 0.5)
        payload = json.loads(self.db.insert_params[4])
        self.assertEqual(set(payload), {"results", "pooled", "gate", "exposure"})
        self.assertEqual(payload["exposure"]["mode"], "ladder")
        key = json.loads(self.db.insert_params[3])
        self.assertEqual(key["v"], 5)

    def test_full_mode_exposure_summary(self):
        WIN.EVALUATORS["s"] = _eval_binary(10, 40, 70, 100)
        out = WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11)
        self.assertEqual(out["exposure"]["mode"], "full")
        self.assertEqual(out["exposure"]["levels"], [])
        self.assertEqual(out["exposure"]["avg_exposure"], 1.0)

    def test_cache_hit_returns_same_exposure(self):
        WIN.EVALUATORS["s"] = _eval_ladder(10, 40, 70, 100, level=0.25)
        first = WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11)
        self.db.row = (json.dumps({"results": first["results"],
                                   "pooled": first["pooled"], "gate": None,
                                   "exposure": first["exposure"]},
                                  ensure_ascii=False),)
        WIN.get_kline = lambda *a, **k: self.fail("命中缓存时不应再取行情")
        hit = WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11)
        self.assertTrue(hit["from_cache"])
        self.assertEqual(hit["exposure"], first["exposure"])

    def test_legacy_cache_without_exposure_degrades_to_none(self):
        self.db.row = (json.dumps({"results": [{"symbol": "A", "error": None}],
                                   "pooled": None, "gate": None}, ensure_ascii=False),)
        hit = WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11)
        self.assertIsNone(hit["exposure"])

    def test_gate_and_ladder_coexist(self):
        WIN.EVALUATORS["s"] = _eval_ladder(10, 40, 70, 100, level=0.5)
        WIN.get_kline = lambda *a, **k: _mk()
        out = WIN.scan_winrate(["A"], "s", {}, (5, 10, 20), 0.11,
                               gate={"enabled": True, "indices": ["000300"],
                                     "require": "all"})
        self.assertTrue(out["gate"]["enabled"])
        self.assertEqual(out["exposure"]["mode"], "ladder")
        self.assertEqual(set(out["results"][0]), V2_KEYS)


if __name__ == "__main__":
    unittest.main()
