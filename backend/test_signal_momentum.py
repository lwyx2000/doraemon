"""动量/突破类策略回归测试（标准库 unittest，不依赖行情网关/数据库）。

覆盖：
1. STRATEGY_CATALOG 与 EVALUATORS 一一对应（漏注册会让前端可选、扫描报未知策略）
2. 评估器契约：position 长度 == klines 长度，signals 带可读 reason
3. **无未来函数**：截断 K 线后，前 k 根的状态必须与全量结果逐位一致
4. 行情层无成交额字段时策略仍可运行，且不伪造金额
5. 非法/边界参数全 flat 不抛异常；既有 7 个策略行为不受影响

运行：python -m unittest backend/test_signal_momentum.py -v
"""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

NEW_IDS = (
    "turtle_breakout", "high_tight_flag", "volume_breakout",
    "pullback_ma", "tight_range",
)
OLD_IDS = ("trend", "ma_cross", "macd", "boll", "rsi", "bias", "grid")


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _load_signal_service():
    """按文件路径加载，stub 掉数据库与行情网关，纯逻辑测试不触网。"""
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
        spec = importlib.util.spec_from_file_location("_sig_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


SIG = _load_signal_service()


def _mk(n=200, start=10.0, drift=0.001, vol=1000.0, jumps=None):
    """构造单调递增的 OHLCV；jumps={index: 涨幅比例}，可注入突破/放量日。"""
    jumps = jumps or {}
    out, price = [], start
    for i in range(n):
        price *= 1.0 + drift + jumps.get(i, 0.0)
        out.append({
            "date": f"2025-{i // 28 + 1:02d}-{i % 28 + 1:02d}",
            "open": round(price * 0.995, 4),
            "close": round(price, 4),
            "high": round(price * 1.01, 4),
            "low": round(price * 0.99, 4),
            "volume": vol,
        })
    return out


def _run(strategy_id, klines, params=None):
    closes = [k["close"] for k in klines]
    return SIG.EVALUATORS[strategy_id](klines, closes, params or {})


def _flag_klines():
    """旗形需要「连续两日」急涨；单日跳涨不满足条件。"""
    return _mk(n=140, drift=0.002, jumps={60: 0.06, 61: 0.06, 62: 0.06})


def _pullback_klines():
    """缓跌 → 放量上穿 → 冲高 → 缩量回撤 → 横盘企稳（全程不破均线）。"""
    rows, price = [], 10.0

    def add(step, n, vol):
        nonlocal price
        for _ in range(n):
            price *= 1 + step
            rows.append({
                "date": "2025-01-01", "open": price * 0.998, "close": price,
                "high": price * 1.005, "low": price * 0.995, "volume": vol,
            })

    add(-0.002, 40, 1000)
    add(0.020, 10, 9000)
    add(0.005, 20, 9000)
    add(-0.004, 8, 1000)
    add(0.0005, 42, 1000)
    return rows


class TestRegistry(unittest.TestCase):
    def test_catalog_matches_evaluators(self):
        catalog_ids = {s["id"] for s in SIG.STRATEGY_CATALOG}
        self.assertEqual(catalog_ids, set(SIG.EVALUATORS))
        self.assertEqual(len(catalog_ids), len(OLD_IDS) + len(NEW_IDS))
        for sid in NEW_IDS:
            self.assertIn(sid, catalog_ids)

    def test_new_entries_have_schema(self):
        for s in SIG.STRATEGY_CATALOG:
            self.assertTrue(s.get("name") and s.get("desc"), s["id"])
            self.assertTrue(s.get("category"), s["id"])
            for p in s["params"]:
                self.assertIn("key", p)
                self.assertIn("label", p)
                self.assertIn("default", p)
                self.assertIn("type", p)

    def test_new_entries_document_data_limitations(self):
        by_id = {s["id"]: s for s in SIG.STRATEGY_CATALOG}
        self.assertIn("成交额", by_id["volume_breakout"]["desc"])
        self.assertIn("50 根", by_id["turtle_breakout"]["desc"])
        self.assertIn("120", by_id["pullback_ma"]["desc"])
        self.assertIn("ATR", by_id["tight_range"]["desc"])


class TestEvaluatorContract(unittest.TestCase):
    def test_position_length_and_signal_shape(self):
        klines = _mk()
        for sid in NEW_IDS:
            with self.subTest(strategy=sid):
                pos, signals = _run(sid, klines)
                self.assertEqual(len(pos), len(klines))
                self.assertTrue(set(pos) <= {"flat", "long"})
                for s in signals:
                    self.assertIn(s["type"], ("buy", "sell"))
                    self.assertIsInstance(s["reason"], str)
                    self.assertTrue(s["reason"])
                    self.assertIn("date", s)

    def test_no_lookahead_prefix_invariance(self):
        """核心：任何策略在 truncated K 线上的前 k 根状态必须与全量完全一致。"""
        klines = _mk(jumps={40: 0.05, 80: 0.04, 120: 0.06, 160: 0.03})
        for sid in NEW_IDS:
            with self.subTest(strategy=sid):
                full_pos, _ = _run(sid, klines)
                for cut in (30, 90, 150):
                    sub_pos, _ = _run(sid, klines[:cut])
                    self.assertEqual(sub_pos, full_pos[:cut],
                                     f"{sid} 在 cut={cut} 处出现未来函数")

    def test_no_amount_field_is_not_required(self):
        """行情层只有 OHLCV；不得出现依赖/伪造 amount 的隐式假设。"""
        klines = _mk()
        self.assertNotIn("amount", klines[0])
        for sid in NEW_IDS:
            with self.subTest(strategy=sid):
                pos, _ = _run(sid, klines)
                self.assertEqual(len(pos), len(klines))

    def test_missing_optional_fields_do_not_crash(self):
        klines = [{k: v for k, v in row.items() if k not in ("open", "low", "volume")}
                  for row in _mk(n=90)]
        for sid in NEW_IDS:
            with self.subTest(strategy=sid):
                pos, _ = _run(sid, klines)
                self.assertEqual(len(pos), len(klines))

    def test_invalid_params_all_flat(self):
        klines = _mk(n=120)
        bad = {
            "turtle_breakout": {"breakout_n": 0},
            "high_tight_flag": {"flag_far": 5, "flag_near": 10},
            "volume_breakout": {"vol_ma": 0},
            "pullback_ma": {"pullback_ma": 0},
            "tight_range": {"tight_window": 0},
        }
        for sid, params in bad.items():
            with self.subTest(strategy=sid):
                pos, signals = _run(sid, klines, params)
                self.assertEqual(pos, ["flat"] * len(klines))
                self.assertEqual(signals, [])

    def test_flag_near_zero_cannot_read_future_bar(self):
        """near=0 会让窗口触及 i+1；必须安全退化为全 flat，不得越界或偷看未来。"""
        klines = _mk(n=120)
        pos, signals = _run("high_tight_flag", klines,
                            {"flag_near": 0, "flag_base_ratio": 1.0,
                             "flag_gain_pct": 0.0, "flag_min_bars": 30})
        self.assertEqual(pos, ["flat"] * len(klines))
        self.assertEqual(signals, [])


class TestTriggers(unittest.TestCase):
    def test_turtle_breakout_fires_on_new_high(self):
        klines = _mk(drift=0.0005, jumps={150: 0.12})
        pos, signals = _run("turtle_breakout", klines)
        self.assertIn("long", pos)
        self.assertTrue(any(s["type"] == "buy" for s in signals))
        self.assertEqual(pos[0], "flat", "前 60 根不足以判突破，必须为空仓")

    def test_volume_breakout_requires_volume_confirmation(self):
        klines = _mk(drift=0.0, jumps={100: 0.06})
        pos_flat, _ = _run("volume_breakout", klines)
        self.assertNotIn("long", pos_flat, "无量能配合时不得触发")

        for k in klines:
            k["volume"] = 1000
        klines[100]["volume"] = 8000
        pos_hot, signals = _run("volume_breakout", klines)
        self.assertEqual(pos_hot[100], "long")
        self.assertTrue(any(s["type"] == "buy" and "放量上涨" in s["reason"]
                            for s in signals))

    def test_tight_range_fires_on_interval_expansion(self):
        klines = _mk(drift=0.0, jumps={100: 0.15})
        pos, signals = _run("tight_range", klines)
        self.assertEqual(pos[100], "long")
        self.assertTrue(any(s["type"] == "buy" for s in signals))

    def test_all_new_strategies_can_fire_with_relaxed_params(self):
        """放宽到 ETF 可用的参数后，5 个策略都不应是永不触发的死代码。

        两个形态类策略各需自己的形态数据：旗形要连续两日急涨，回踩要
        有真实回撤段；共用一条单调上涨曲线会永远不触发。
        """
        base = _mk(n=220, drift=0.0015, vol=1000,
                   jumps={40: 0.05, 70: 0.05, 100: 0.06, 140: 0.04, 180: 0.05})
        for idx in (40, 70, 100, 140, 180):
            base[idx]["volume"] = 9000
        data = {
            "turtle_breakout": base,
            "volume_breakout": base,
            "tight_range": base,
            "high_tight_flag": _flag_klines(),
            "pullback_ma": _pullback_klines(),
        }
        params = {
            "turtle_breakout": {"breakout_n": 20},
            "high_tight_flag": {"flag_min_bars": 30, "flag_far": 20,
                                "flag_near": 3, "flag_base_ratio": 1.01,
                                "flag_gain_pct": 1.0},
            "volume_breakout": {"vol_gain_pct": 1.0, "vol_ratio": 1.5},
            "pullback_ma": {"pullback_ma": 20, "pullback_lookback": 60,
                            "pullback_min_gap": 2, "pullback_max_gap": 50,
                            "pullback_shrink": 2.0, "pullback_retrace": 0.995},
            "tight_range": {"tight_window": 10, "tight_ratio": 1.03,
                            "tight_min_bars": 30},
        }
        for sid, p in params.items():
            with self.subTest(strategy=sid):
                pos, _ = _run(sid, data[sid], p)
                self.assertIn("long", pos, f"{sid} 在宽松参数下仍无信号")


class TestExistingStrategiesUnaffected(unittest.TestCase):
    def test_old_seven_smoke(self):
        klines = _mk(n=150)
        params = {"grid": {"grid_lower": 9.0, "grid_upper": 20.0, "grid_step": 0.5}}
        for sid in OLD_IDS:
            with self.subTest(strategy=sid):
                pos, signals = _run(sid, klines, params.get(sid))
                self.assertEqual(len(pos), len(klines))
                self.assertIsInstance(signals, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
