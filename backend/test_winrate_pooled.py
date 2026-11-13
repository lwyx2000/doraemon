"""胜率扫描 v3 回归测试（标准库 unittest，stub 掉数据库与行情网关，不触网）。

覆盖：
1. 5 年窗口显式传给 get_kline；SCAN_SCHEMA_VERSION 必须升到 3（否则旧缓存无 pooled）
2. Wilson 95% CI 的已知值 / 空样本 / 极端样本
3. pooled 汇总口径：基线 = 全部交易日、策略 = 触发样本、去重信号日、IS/OOS、
   超额 pp、direction / verdict、失败标的计数、caveats
4. results 单标的数组结构相对 v2 **完全不变**（前端表格与 CSV 零改动）
5. 缓存：写入含 pooled、命中返回 pooled + 交集、v2 裸数组兼容、单只异常隔离不留白
6. 边界：空 horizons 回退、自定义 horizons、成本透传

运行：python -m unittest backend/test_winrate_pooled.py -v
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
        spec = importlib.util.spec_from_file_location("_winrate_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


WIN = _load_winrate_service()


class _DB:
    """最小 SQLite 连接替身：记录 INSERT，可预置缓存命中行。"""

    def __init__(self, row=None):
        self.row = row
        self.executed: list[tuple] = []
        self.insert_params: list | None = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if params and "INSERT INTO biz_winrate_scan" in sql:
            self.insert_params = params

    def fetchone(self, sql, params=None):
        return self.row


def _mk(n=120, drift=0.001, offset=0, start=10.0):
    """单调递增日线；offset 用来让不同标的的信号日落在不同日期。"""
    out, price = [], start
    d0 = date(2024, 1, 1) + timedelta(days=offset)
    for i in range(n):
        price *= 1.0 + drift
        out.append({
            "date": (d0 + timedelta(days=i)).isoformat(),
            "open": round(price, 6), "close": round(price, 6),
            "high": round(price, 6), "low": round(price, 6), "volume": 1000,
        })
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


def _detail(symbol="X", bars=120, error=None, baseline=(1.0, -1.0, 1.0, -1.0),
            strategy=(1.0, 1.0, -1.0), is_rets=(1.0, 1.0), oos_rets=(-1.0,),
            signal_days=("2024-01-10", "2024-01-11", "2024-01-12")):
    return {
        "symbol": symbol, "bars": bars, "error": error,
        "baseline": list(baseline), "strategy": list(strategy),
        "is_rets": list(is_rets), "oos_rets": list(oos_rets),
        "signal_days": list(signal_days),
    }


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


# ---------------------------------------------------------------- 窗口 / 版本
class TestWindowAndSchema(_Base):
    def test_scan_window_spans_five_years(self):
        s, e = WIN._scan_window()
        d0 = date.fromisoformat(s)
        d1 = date.fromisoformat(e)
        self.assertEqual((d1 - d0).days, 365 * 5)
        self.assertEqual(len(s), 10)
        self.assertEqual(len(e), 10)

    def test_schema_version_is_three(self):
        self.assertEqual(WIN.SCAN_SCHEMA_VERSION, 3)
        self.assertEqual(WIN.SCAN_LOOKBACK_YEARS, 5)
        self.assertEqual(WIN.MIN_SAMPLES, 20, "MIN_SAMPLES 仍为单标的显示阈值，不得改")

    def test_scan_symbol_sends_explicit_five_year_window(self):
        calls = []
        WIN.get_kline = lambda *a, **k: (calls.append((a, k)) or _mk())
        WIN.EVALUATORS["s"] = _eval_at(10, 40)
        start, end = WIN._scan_window()
        result, detail = WIN._scan_symbol("510300", "s", {}, (5, 10, 20), 0.11, (start, end), 10)
        self.assertIsNone(result["error"])
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args, ("510300",))
        self.assertEqual(kwargs["count"], 0)
        self.assertEqual(kwargs["start_date"], start)
        self.assertEqual(kwargs["end_date"], end)
        self.assertEqual(detail["bars"], 120)

    def test_scan_end_to_end_passes_window(self):
        calls = []
        WIN.get_kline = lambda *a, **k: (calls.append(k) or _mk())
        WIN.EVALUATORS["s"] = _eval_at(10, 40, 70)
        out = WIN.scan_winrate(["A", "B"], "s", {}, (5, 10, 20), 0.11)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c["count"] == 0 and "start_date" in c for c in calls))
        self.assertFalse(out["from_cache"])
        self.assertIn("pooled", out)


# ---------------------------------------------------------------- Wilson CI
class TestWilson(_Base):
    def test_known_n20_k12(self):
        """n=20 / 60% 的 Wilson 95% CI 必须是 [38.7, 78.1]，证明点估计不可信。"""
        self.assertEqual(WIN._wilson(12, 20), [38.7, 78.1])

    def test_empty_returns_none(self):
        self.assertIsNone(WIN._wilson(0, 0))

    def test_all_wins_upper_below_100(self):
        lo, hi = WIN._wilson(10, 10)
        self.assertLess(lo, 100)
        self.assertGreater(lo, 60)
        self.assertLessEqual(hi, 100)
        self.assertEqual(hi, 100.0)

    def test_no_wins_lower_is_zero(self):
        lo, hi = WIN._wilson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertLess(hi, 40)

    def test_large_sample_interval_is_narrow(self):
        lo, hi = WIN._wilson(19920, 41924)  # ≈47.5%，与线上市场基线同量级
        self.assertLessEqual(hi - lo, 1.0)  # 保留 1 位小数后约 1.0pp
        self.assertLess(lo, 47.5)
        self.assertGreater(hi, 47.5)


# ---------------------------------------------------------------- pooled 纯函数
class TestPooledSummary(_Base):
    def _run(self, details, requested=2, hz=10, cost=0.11):
        return WIN._pooled_summary(details, requested, hz, ("2021-01-01", "2026-01-01"), cost)

    def test_pool_stats_empty(self):
        st = WIN._pool_stats([])
        self.assertEqual(st, {"n": 0, "wins": 0, "win_rate": None, "ci95": None, "avg_ret": None})

    def test_pool_stats_values(self):
        st = WIN._pool_stats([-1.0, 2.0, 3.0, -2.0])
        self.assertEqual(st["n"], 4)
        self.assertEqual(st["wins"], 2)
        self.assertEqual(st["win_rate"], 50.0)
        self.assertEqual(st["avg_ret"], 0.5)
        self.assertIsNotNone(st["ci95"])

    def test_baseline_and_strategy_are_separate_populations(self):
        p = self._run([_detail()])
        self.assertEqual(p["baseline"]["n"], 4)
        self.assertEqual(p["baseline"]["win_rate"], 50.0)
        self.assertEqual(p["strategy"]["n"], 3)
        self.assertEqual(p["strategy"]["win_rate"], 66.7)
        self.assertEqual(p["excess_pp"], 16.7)

    def test_distinct_signal_days_dedupes_across_symbols(self):
        d1 = _detail("A", signal_days=("2024-01-10", "2024-01-11", "2024-01-12"))
        d2 = _detail("B", signal_days=("2024-01-10", "2024-01-11", "2024-01-12"))
        p = self._run([d1, d2])
        self.assertEqual(p["strategy"]["n"], 6)
        self.assertEqual(p["distinct_signal_days"], 3)
        self.assertEqual(p["cluster_ratio"], 2.0)

    def test_failed_symbols_excluded_from_all_stats(self):
        good = _detail("A")
        bad = _detail("B", error="K线数据不足（至少40根）", baseline=(99.0,),
                      strategy=(99.0,), is_rets=(99.0,), oos_rets=(99.0,), signal_days=("2099-01-01",))
        p = self._run([good, bad], requested=3)
        self.assertEqual(p["symbols"], {"requested": 3, "valid": 1, "failed": 1})
        self.assertEqual(p["baseline"]["n"], 4)
        self.assertEqual(p["strategy"]["n"], 3)
        self.assertEqual(p["distinct_signal_days"], 3)

    def test_is_oos_and_decay(self):
        p = self._run([_detail()])
        self.assertEqual(p["is_oos"]["is"]["win_rate"], 100.0)
        self.assertEqual(p["is_oos"]["oos"]["win_rate"], 0.0)
        self.assertEqual(p["is_oos"]["decay_pp"], -100.0)

    def test_data_window_bars_median(self):
        p = self._run([_detail("A", bars=100), _detail("B", bars=300), _detail("C", bars=200)])
        self.assertEqual(p["data_window"]["bars_median"], 200)
        self.assertEqual(p["data_window"]["years"], 5)
        self.assertEqual(p["horizon"], 10)

    def test_verdict_insufficient_samples(self):
        d = _detail(strategy=(1.0,), is_rets=(1.0,), oos_rets=(), signal_days=("2024-01-10",))
        p = self._run([d])
        self.assertEqual(p["verdict"], "样本不足，不下结论")
        self.assertFalse(p["significant"])

    def test_verdict_no_triggers(self):
        d = _detail(strategy=(), is_rets=(), oos_rets=(), signal_days=())
        p = self._run([d])
        self.assertEqual(p["verdict"], "无触发样本，不下结论")
        self.assertIsNone(p["cluster_ratio"])

    def test_verdict_clustered_signals(self):
        d = _detail(strategy=[1.0] * 25, is_rets=[1.0] * 25, oos_rets=(),
                    signal_days=("2024-01-10",) * 25)
        p = self._run([d])
        self.assertEqual(p["verdict"], "信号集中在少数交易日，样本不独立")

    def test_direction_above_baseline(self):
        # 基线 47.5%，策略 60% 且 n 足够大 → CI 下界应高于基线
        d = _detail(
            baseline=[1.0] * 475 + [-1.0] * 525,
            strategy=[1.0] * 600 + [-1.0] * 400,
            is_rets=[1.0] * 500, oos_rets=[1.0] * 100 + [-1.0] * 400,
            signal_days=[f"2024-{i // 28 + 1:02d}-{i % 28 + 1:02d}" for i in range(1000)],
        )
        p = self._run([d])
        self.assertEqual(p["baseline"]["win_rate"], 47.5)
        self.assertEqual(p["strategy"]["win_rate"], 60.0)
        self.assertEqual(p["direction"], "above")
        self.assertTrue(p["significant"])
        self.assertEqual(p["verdict"], "相对基线有统计显著超额（仅本样本）")

    def test_direction_below_baseline(self):
        d = _detail(
            baseline=[1.0] * 600 + [-1.0] * 400,
            strategy=[1.0] * 300 + [-1.0] * 700,
            is_rets=[1.0] * 300, oos_rets=[-1.0] * 700,
            signal_days=[f"2024-{i // 28 + 1:02d}-{i % 28 + 1:02d}" for i in range(1000)],
        )
        p = self._run([d])
        self.assertEqual(p["direction"], "below")
        self.assertEqual(p["verdict"], "相对基线显著偏弱")

    def test_direction_none_when_ci_spans_baseline(self):
        d = _detail(
            baseline=[1.0] * 500 + [-1.0] * 500,
            strategy=[1.0] * 50 + [-1.0] * 50,
            is_rets=[1.0] * 50, oos_rets=[-1.0] * 50,
            signal_days=[f"2024-{i // 28 + 1:02d}-{i % 28 + 1:02d}" for i in range(100)],
        )
        p = self._run([d])
        self.assertEqual(p["direction"], "none")
        self.assertEqual(p["verdict"], "与基线无统计显著差异")

    def test_caveats_expose_non_independence_and_scope(self):
        p = self._run([_detail()])
        self.assertEqual(len(p["caveats"]), 5)
        self.assertTrue(any("不独立" in c for c in p["caveats"]))
        self.assertTrue(any("walk-forward" in c for c in p["caveats"]))


# ---------------------------------------------------------------- results 结构 / 缓存
class TestResultsAndCache(_Base):
    def _scan(self, symbols=("A", "B")):
        WIN.get_kline = lambda *a, **k: _mk()
        WIN.EVALUATORS["s"] = _eval_at(10, 40, 70, 100)
        return WIN.scan_winrate(list(symbols), "s", {}, (5, 10, 20), 0.11)

    def test_results_shape_is_identical_to_v2(self):
        out = self._scan()
        for r in out["results"]:
            self.assertEqual(set(r.keys()), V2_KEYS)
            self.assertNotIn("baseline", r)
            self.assertNotIn("signal_days", r)
        self.assertEqual(len(out["results"]), 2)

    def test_pooled_n_equals_sum_of_single_symbol_10d_samples(self):
        out = self._scan()
        self.assertEqual(
            out["pooled"]["strategy"]["n"],
            sum(r["stats_10d"]["samples"] for r in out["results"]),
        )

    def test_baseline_is_all_trading_days_not_triggers(self):
        out = self._scan(("A",))
        n = 120
        expected_per_symbol = len(range(1, n - 10 - 1))
        self.assertEqual(out["pooled"]["baseline"]["n"], expected_per_symbol)
        self.assertGreater(out["pooled"]["baseline"]["n"], out["pooled"]["strategy"]["n"])

    def test_cache_write_contains_results_and_pooled(self):
        self._scan()
        self.assertIsNotNone(self.db.insert_params)
        params_json = self.db.insert_params[3]
        self.assertEqual(json.loads(params_json)["v"], 3)
        payload = json.loads(self.db.insert_params[4])
        self.assertIn("results", payload)
        self.assertIn("pooled", payload)
        self.assertIsInstance(payload["results"], list)

    def test_cache_hit_returns_pooled_and_symbol_intersection(self):
        first = self._scan(("A", "B"))
        payload = json.dumps({"results": first["results"], "pooled": first["pooled"]}, ensure_ascii=False)
        self.db.row = (payload,)
        hit = self._scan(("A",))
        self.assertTrue(hit["from_cache"])
        self.assertEqual([r["symbol"] for r in hit["results"]], ["A"])
        self.assertEqual(hit["pooled"], first["pooled"])

    def test_cache_hit_legacy_bare_list_is_compatible(self):
        self.db.row = (json.dumps([{"symbol": "A", "error": None}]),)
        WIN.get_kline = lambda *a, **k: self.fail("命中缓存时不应再取行情")
        hit = self._scan(("A",))
        self.assertTrue(hit["from_cache"])
        self.assertIsNone(hit["pooled"])

    def test_single_symbol_exception_is_printed_and_isolated(self):
        def flaky(code, **kw):
            if code == "A":
                raise RuntimeError("gateway 504")
            return _mk()
        WIN.get_kline = flaky
        WIN.EVALUATORS["s"] = _eval_at(10, 40)
        out = WIN.scan_winrate(["A", "B"], "s", {}, (5, 10, 20), 0.11)
        self.assertIn("gateway 504", out["results"][0]["error"])
        self.assertIsNone(out["results"][1]["error"])
        self.assertEqual(out["pooled"]["symbols"], {"requested": 2, "valid": 1, "failed": 1})
        self.assertTrue(any("扫描异常" in str(c) for c in self.printed.call_args_list))

    def test_cost_pct_changes_win_rate(self):
        # 极小 drift，成本从 0 抬到 5% 时全部样本转负，胜率必须掉到 0
        WIN.get_kline = lambda *a, **k: _mk(drift=0.0001)
        WIN.EVALUATORS["s"] = _eval_at(10, 40, 70)
        zero = WIN.scan_winrate(["A"], "s", {"x": 1}, (10,), 0.0)
        self.db.insert_params = None
        high = WIN.scan_winrate(["A"], "s", {"x": 2}, (10,), 5.0)
        self.assertEqual(zero["pooled"]["strategy"]["win_rate"], 100.0)
        self.assertEqual(high["pooled"]["strategy"]["win_rate"], 0.0)

    def test_empty_horizons_is_rejected(self):
        WIN.get_kline = lambda *a, **k: self.fail("非法参数不应触达行情层")
        with self.assertRaisesRegex(ValueError, "horizons 不能为空"):
            WIN.scan_winrate(["A"], "s", {}, (), 0.11)

    def test_all_losses_no_longer_raises_zero_division(self):
        """既有缺陷回归：全部样本亏损时 payoff=0，_kelly 曾抛 ZeroDivisionError。"""
        self.assertEqual(WIN._kelly(0.0, 0.0), (0.0, 0.0))
        st = WIN._stats([-1.0, -2.0, -3.0])
        self.assertEqual(st["win_rate"], 0.0)
        self.assertEqual(st["payoff"], 0.0)
        self.assertEqual(st["kelly"], 0.0)

    def test_custom_horizons_pool_hz_falls_back_to_first(self):
        WIN.get_kline = lambda *a, **k: _mk()
        WIN.EVALUATORS["s"] = _eval_at(10, 40)
        out = WIN.scan_winrate(["A"], "s", {}, (5,), 0.11)
        self.assertEqual(out["pooled"]["horizon"], 5)


if __name__ == "__main__":
    unittest.main()
