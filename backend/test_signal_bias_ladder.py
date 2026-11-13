"""BIAS 乖离分级减仓（bias_ladder）回归测试（标准库 unittest，不触网）。

权威口径来自用户技能 bias-position-strategy/scripts/bias_strategy.py：
    BIAS(N) = (close − MA_N) / MA_N × 100%
    BIAS20 > 10% → ×0.5；BIAS20 > 15% → 再 ×0.5；BIAS60 > 20% → 再 ×0.5（独立）
本测试用**独立重写的参考实现**（不复用项目的 _sma）逐日对拍 exposure，
防止「自己实现、自己验证」的同义反复。

覆盖：
1. 注册表 / 参数 schema / 默认值与技能一致
2. 四档 1.0 / 0.5 / 0.25 / 0.125 均可出现，且与参考实现逐日一致
3. BIAS60 独立触发：BIAS20 两档未触发时仍减半到 0.5
4. position 与 _eval_bias 同参数完全一致（触发点可比）、signals 带仓位说明
5. 前 n-1 根 MA 不足不减仓（保守满仓）；exposure 长度/取值契约
6. 无未来函数：截断 K 线后前 k 根 position 与 exposure 逐位一致
7. generate_signal 能解包三元组并透出 current_exposure；二元组策略退化为 0/1
8. 边界参数不抛异常

运行：python -m unittest backend/test_signal_bias_ladder.py -v
"""
from __future__ import annotations

import importlib.util
import math
import random
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


def _load_signal_service():
    path = Path(__file__).with_name("services") / "signal_service.py"
    stubs = {
        "database": _mod("database"),
        "database.sqlite_connection": _mod(
            "database.sqlite_connection", get_biz_db=lambda: None
        ),
        "services": _mod("services"),
        "services.market_service": _mod(
            "services.market_service", get_kline=lambda *a, **k: []
        ),
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("_sig_ladder_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


SIG = _load_signal_service()


def _k(closes):
    return [{"date": f"2025-{i // 28 + 1:02d}-{i % 28 + 1:02d}",
             "open": c, "close": c, "high": c, "low": c, "volume": 1000.0}
            for i, c in enumerate(closes)]


def _run(closes, params=None):
    klines = _k(closes)
    return klines, SIG.EVALUATORS["bias_ladder"](klines, closes, params or {})


def _bias_at(closes, i, n):
    if i < n - 1:
        return None
    ma = sum(closes[i - n + 1:i + 1]) / n
    return (closes[i] - ma) / ma * 100 if ma else None


def _reference_ladder(closes, n=20, long_n=60, t1=10.0, t2=15.0, t3=20.0):
    """按技能 compute_signals 公式独立重写（不调用项目任何辅助函数）。"""
    out = []
    for i in range(len(closes)):
        f = 1.0
        if i >= n - 1:
            ma = sum(closes[i - n + 1:i + 1]) / n
            if ma:
                b = (closes[i] - ma) / ma * 100
                if b > t1:
                    f *= 0.5
                if b > t2:
                    f *= 0.5
        if i >= long_n - 1:
            ma = sum(closes[i - long_n + 1:i + 1]) / long_n
            if ma:
                b = (closes[i] - ma) / ma * 100
                if b > t3:
                    f *= 0.5
        out.append(f)
    return out


def _jump():
    """平稳 70 根 → 跳涨 20% → 再涨；覆盖 1.0 / 0.5 / 0.25。"""
    return [10.0] * 70 + [12.0] * 60 + [12.5] * 60


def _low_price():
    """低价 ETF：四档全覆盖，含 0.125。"""
    return [0.5] * 70 + [0.62] * 60 + [0.58] * 60


def _bias60_only():
    """长期低位 → 快速拉升到 16 并横盘：BIAS20 已跟上（不触发），BIAS60 仍 >20%。"""
    return [10.0] * 100 + [10.0 + 0.3 * i for i in range(1, 21)] + [16.0] * 40


class TestRegistry(unittest.TestCase):
    def test_catalog_entry_and_defaults(self):
        by_id = {s["id"]: s for s in SIG.STRATEGY_CATALOG}
        self.assertIn("bias_ladder", by_id)
        self.assertIn("bias_ladder", SIG.EVALUATORS)
        entry = by_id["bias_ladder"]
        self.assertTrue(entry["name"] and entry["desc"] and entry["category"])
        defaults = {p["key"]: p["default"] for p in entry["params"]}
        # 与技能 WINDOW20/WINDOW60、三档阈值、入场口径逐项一致
        self.assertEqual(defaults, {
            "bias_n": 20, "bias_threshold": -3, "ladder_long": 60,
            "ladder_t1": 10, "ladder_t2": 15, "ladder_t3": 20,
        })
        for p in entry["params"]:
            for key in ("key", "label", "default", "type"):
                self.assertIn(key, p)

    def test_only_ladder_returns_triple(self):
        closes = _jump()
        for sid, fn in SIG.EVALUATORS.items():
            with self.subTest(strategy=sid):
                raw = fn(_k(closes), closes, {})
                self.assertEqual(len(raw), 3 if sid == "bias_ladder" else 2)


class TestLadderLevels(unittest.TestCase):
    def test_matches_reference_on_multiple_series(self):
        rnd = random.Random(4242)
        p, walk = 10.0, []
        for _ in range(260):
            p *= 1 + rnd.uniform(-0.03, 0.032)
            walk.append(p)
        series = {
            "jump": _jump(),
            "low_price": _low_price(),
            "bias60_only": _bias60_only(),
            "sine": [10.0 + 2.0 * math.sin(i / 9.0) for i in range(260)],
            "walk": walk,
        }
        for name, closes in series.items():
            with self.subTest(series=name):
                _, (_, _, exposure) = _run(closes)
                ref = _reference_ladder(closes)
                self.assertEqual(len(exposure), len(closes))
                for i, (got, want) in enumerate(zip(exposure, ref)):
                    self.assertEqual(got, want, f"{name} 第 {i} 根档位不一致")

    def test_all_four_levels_reachable(self):
        _, (_, _, exposure) = _run(_low_price())
        self.assertEqual(set(exposure), {1.0, 0.5, 0.25, 0.125})

    def test_bias60_triggers_independently(self):
        """BIAS60 是独立档：BIAS20 已回落不触发时，仍须单独把仓位减半。

        技能里 BIAS60 的作用正是补「两波行情中 BIAS20 背离不触发」的漏，
        因此不能要求 BIAS20 全程未触发，只需存在「BIAS20 不触发 / BIAS60 触发」
        的交易日，且关掉 BIAS60 档后这些天必须回到满仓。
        """
        closes = _bias60_only()
        _, (_, _, exposure) = _run(closes)
        _, (_, _, no60) = _run(closes, {"ladder_t3": 1000.0})
        independent = []
        for i, f in enumerate(exposure):
            b20, b60 = _bias_at(closes, i, 20), _bias_at(closes, i, 60)
            if b20 is not None and b20 <= 10.0 and b60 is not None and b60 > 20.0:
                independent.append(i)
                self.assertEqual(f, 0.5, f"第 {i} 根 BIAS60 独立触发却未减半")
                self.assertEqual(no60[i], 1.0, f"第 {i} 根关掉 BIAS60 后应回到满仓")
        self.assertTrue(independent, "必须存在 BIAS20 未触发、BIAS60 独立减半的交易日")
        self.assertIn(0.5, exposure)

    def test_custom_thresholds(self):
        closes = _jump()
        params = {"ladder_t1": 3.0, "ladder_t2": 6.0, "ladder_t3": 8.0}
        _, (_, _, exposure) = _run(closes, params)
        self.assertEqual(exposure, _reference_ladder(closes, t1=3.0, t2=6.0, t3=8.0))


class TestContract(unittest.TestCase):
    def test_position_matches_plain_bias(self):
        closes = _jump()
        klines = _k(closes)
        position, _, _ = SIG.EVALUATORS["bias_ladder"](klines, closes, {})
        plain, _ = SIG.EVALUATORS["bias"](klines, closes, {})
        self.assertEqual(position, plain, "触发点必须与 bias 策略一致，否则无法做满仓/分级对照")

    def test_exposure_shape_and_warmup(self):
        closes = _jump()
        klines, (position, signals, exposure) = _run(closes)
        self.assertEqual(len(position), len(klines))
        self.assertEqual(len(exposure), len(klines))
        self.assertEqual(set(exposure) - {1.0, 0.5, 0.25, 0.125}, set())
        # 前 19 根 MA20 不足，一律保守满仓；前 59 根 MA60 也不足
        self.assertEqual(exposure[:19], [1.0] * 19)
        for s in signals:
            self.assertIn("目标仓位", s["reason"])
            self.assertIn(s["type"], ("buy", "sell"))

    def test_no_lookahead_prefix_stable(self):
        closes = _low_price()
        _, (full_pos, _, full_exp) = _run(closes)
        for cut in (80, 120, 150, 190):
            with self.subTest(cut=cut):
                _, (pos, _, exp) = _run(closes[:cut])
                self.assertEqual(pos, full_pos[:cut])
                self.assertEqual(exp, full_exp[:cut])

    def test_boundary_params_do_not_raise(self):
        closes = _jump()
        for params in ({"bias_n": 0}, {"ladder_long": 0},
                       {"ladder_t1": -1, "ladder_t2": -1, "ladder_t3": -1},
                       {"bias_threshold": 100}):
            with self.subTest(params=params):
                _, (pos, _, exp) = _run(closes, params)
                self.assertEqual(len(pos), len(closes))
                self.assertEqual(len(exp), len(closes))


class TestGenerateSignal(unittest.TestCase):
    def setUp(self):
        self._orig = SIG.get_kline

    def tearDown(self):
        SIG.get_kline = self._orig

    def test_triple_unpacked_and_exposure_exposed(self):
        closes = _low_price()
        SIG.get_kline = lambda *a, **k: _k(closes)
        out = SIG.generate_signal("510300", "bias_ladder", {})
        self.assertNotIn("error", out)
        self.assertIn("current_exposure", out)
        self.assertEqual(out["current_exposure"], round(_run(closes)[1][2][-1], 4))
        self.assertIn(out["current_position"], ("long", "flat"))

    def test_binary_strategy_exposure_is_zero_or_one(self):
        closes = _jump()
        SIG.get_kline = lambda *a, **k: _k(closes)
        for sid in ("bias", "trend", "turtle_breakout"):
            with self.subTest(strategy=sid):
                out = SIG.generate_signal("510300", sid, {})
                self.assertEqual(out["current_exposure"],
                                 1.0 if out["current_position"] == "long" else 0.0)

    def test_empty_kline_shape_kept(self):
        SIG.get_kline = lambda *a, **k: []
        out = SIG.generate_signal("510300", "bias_ladder", {})
        self.assertIn("error", out)
        self.assertIsNone(out["current_exposure"])
        self.assertIsNone(out["current_position"])


if __name__ == "__main__":
    unittest.main()
