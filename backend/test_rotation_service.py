"""组合层动量轮动（档 C / rotation_service）回归测试（标准库 unittest，不触网）。

权威口径来源：用户技能 momentum-buy-signal / weekly-band-workflow /
bias-position-strategy 的 scripts/*.py。本地探针
``.tmp_verify/verify_rotation_vs_skill.py`` 已把本模块与**真实技能脚本**在
4 组参数、1750 根合成数据上逐点对拍零差异；本测试文件把技能脚本算法
**独立重写为参考实现**（不 import 项目代码、不依赖用户本机路径），
因此可在 53 生产镜像内自包含运行，同时防止「自己实现、自己验证」的同义反复。

覆盖：
1. 常量 / 预设资产池与技能脚本一致
2. _roc / _daily_returns / _pearson / _safe 边界（None、0、NaN、Inf）
3. _bias_position 全档位 + _bias_by_date 与独立 MA 参考实现逐日对拍
4. _align 按日期并集对齐，绝不前向填充，晚上市标的 coverage 正确
5. _stats / _max_drawdown 边界与数值有限性
6. **lag=0 与技能脚本参考实现逐点对拍**：4 组参数下 eq_rot / eq_ew /
   信号日期 / 选中集合 / 最大回撤零差异
7. **lag=1 无前视**：信号日单日暴涨不被计入新持仓；lag=0 确实会（前视）
8. min_return=0 不被 falsy 吞掉（技能脚本 `min_return or -1e9` 的 bug）
9. BIAS 降权：档位生效、降权部分为现金；成本按 turnover 计
10. run_rotation 组装层：JSON 严格无 NaN、结构完整、空仓有显式动作、
    缓存命中、参数护栏、取数失败 fail-fast、公共交易日不足 fail-fast

运行：python -m unittest backend/test_rotation_service.py -v
"""
from __future__ import annotations

import importlib.util
import json
import math
import random
import sys
import types
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _load_rotation_service():
    """独立加载被测模块，stub 掉 market_service（避免拉起 requests / DB）。"""
    path = Path(__file__).with_name("services") / "rotation_service.py"
    stubs = {
        "services": _mod("services"),
        "services.market_service": _mod(
            "services.market_service", get_kline=lambda *a, **k: []
        ),
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("_rotation_service_under_test", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return mod


R = _load_rotation_service()


# --------------------------------------------------------------------------- #
# 独立参考实现：逐行复刻用户技能 momentum_buy.rotation_backtest（不复用项目代码）
# --------------------------------------------------------------------------- #
def _ref_trailing(series, n):
    out = [None] * len(series)
    for i in range(n, len(series)):
        if series[i] is None or series[i - n] in (None, 0):
            continue
        out[i] = series[i] / series[i - n] - 1.0
    return out


def _ref_daily(series):
    out = [None] * len(series)
    for i in range(1, len(series)):
        if series[i] is None or series[i - 1] in (None, 0):
            continue
        out[i] = series[i] / series[i - 1] - 1.0
    return out


def _ref_maxdd(eq):
    peak, m = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        m = min(m, v / peak - 1)
    return m


def _ref_rotation_backtest(dates, assets, closes, lookback, rebalance, top,
                           min_return=None, always_pick=True):
    n = len(dates)
    rets = {a: _ref_trailing(closes[a], lookback) for a in assets}
    dret = {a: _ref_daily(closes[a]) for a in assets}
    signals, eq_rot, eq_ew = [], [1.0], [1.0]
    hold_rot = set(assets)
    for i in range(1, n):
        if i >= lookback and (i - lookback) % rebalance == 0:
            ranked = [(a, rets[a][i]) for a in assets if rets[a][i] is not None]
            ranked.sort(key=lambda t: t[1], reverse=True)
            if always_pick or (ranked and ranked[0][1] > (min_return or -1e9)):
                sel = [a for a, _ in ranked[:top]]
            else:
                sel = []
            hold_rot = set(sel)
            signals.append((dates[i], sel, {a: rets[a][i] for a, _ in ranked}))

        def period_return(hold):
            if not hold:
                return 0.0
            rs = [dret[a][i] for a in hold if dret[a][i] is not None]
            return sum(rs) / len(rs) if rs else 0.0

        eq_rot.append(eq_rot[-1] * (1 + period_return(hold_rot)))
        eq_ew.append(eq_ew[-1] * (1 + period_return(set(assets))))
    return signals, eq_rot, eq_ew, _ref_maxdd(eq_rot), _ref_maxdd(eq_ew)


def _ref_bias_position(b20, b60):
    pos, trig = 1.0, []
    if b20 is not None and b20 > 0.10:
        pos *= 0.5
        trig.append("BIAS20>10%")
    if b20 is not None and b20 > 0.15:
        pos *= 0.5
        trig.append("BIAS20>15%")
    if b60 is not None and b60 > 0.20:
        pos *= 0.5
        trig.append("BIAS60>20%")
    return pos, trig


# --------------------------------------------------------------------------- #
# 合成数据
# --------------------------------------------------------------------------- #
def _synth(n=320, n_assets=4, seed=20261114):
    """确定性合成：不同漂移 + 周期轮动 + 小噪声，保证 ROC 排名会切换。"""
    rnd = random.Random(seed)
    dates = [f"D{i:04d}" for i in range(n)]
    assets = [f"A{i}" for i in range(n_assets)]
    closes = {}
    for j, a in enumerate(assets):
        px, series = 10.0 + j, []
        for i in range(n):
            px *= (1 + 0.0004 * (j - 1) + 0.006 * math.sin(i / 17.0 + j * 1.7)
                   + rnd.uniform(-0.004, 0.004))
            series.append(px)
        closes[a] = series
    return dates, assets, closes


def _pool(closes, dates, assets):
    return {
        a: [{"date": d, "close": c} for d, c in zip(dates, closes[a])]
        for a in assets
    }


def _ledger(dates, assets, closes, **kw):
    p = dict(lookback=20, rebalance=5, top=1, min_return=None, cost_bps=0.0,
             bias_overlay=False, bias_maps=None, execution_lag=1)
    p.update(kw)
    return R._rotation_ledger(dates, closes, assets, **p)


# --------------------------------------------------------------------------- #
class TestConstantsAndPresets(unittest.TestCase):
    def test_constants_match_skill(self):
        self.assertEqual(R.DEFAULT_LOOKBACK, 20)
        self.assertEqual(R.DEFAULT_REBALANCE, 5)
        self.assertEqual(R.DEFAULT_TOP, 1)
        self.assertEqual(R.CORR_WARN, 0.5)
        self.assertEqual(R.TRADING_DAYS, 242)
        self.assertEqual(R.BIAS_LEVELS, (1.0, 0.5, 0.25, 0.125))

    def test_presets_match_skill(self):
        p = {x["key"]: x["symbols"] for x in R.get_presets()}
        self.assertEqual(p, {
            "four-asset": ["510300", "511010", "513100", "518880"],
            "28": ["510300", "563300"],
            "chuang-hongli": ["159915", "515080"],
        })
        self.assertTrue(all(x["name"] for x in R.get_presets()))


class TestNumericHelpers(unittest.TestCase):
    def test_safe_filters_nan_inf(self):
        self.assertIsNone(R._safe(float("nan")))
        self.assertIsNone(R._safe(float("inf")))
        self.assertIsNone(R._safe(None))
        self.assertEqual(R._safe(3), 3.0)

    def test_roc_matches_reference(self):
        s = [1.0, 2.0, None, 4.0, 8.0, 0.0, 3.0]
        self.assertEqual(R._roc(s, 2), _ref_trailing(s, 2))
        self.assertEqual(R._roc(s, 1), _ref_trailing(s, 1))

    def test_daily_returns_matches_reference(self):
        s = [1.0, 2.0, None, 4.0, 0.0, 3.0]
        self.assertEqual(R._daily_returns(s), _ref_daily(s))

    def test_pearson(self):
        x = [0.01, -0.02, 0.03, -0.01, 0.0]
        self.assertAlmostEqual(R._pearson(x, x), 1.0, places=12)
        self.assertAlmostEqual(R._pearson(x, [-v for v in x]), -1.0, places=12)
        self.assertIsNone(R._pearson([1.0], [1.0]))
        self.assertIsNone(R._pearson([1.0] * 5, [2.0] * 5))
        # None 点被跳过，不伪造 0 收益
        self.assertAlmostEqual(
            R._pearson([1.0, None, 2.0, 3.0], [2.0, 9.0, 4.0, 6.0]),
            R._pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]), places=12)

    def test_max_drawdown_and_stats(self):
        eq = [1.0, 1.2, 0.9, 1.1, 0.6, 0.8]
        self.assertAlmostEqual(R._max_drawdown(eq), 0.6 / 1.2 - 1, places=12)
        st = R._stats(eq)
        for k in ("total_return_pct", "annualized_pct", "max_drawdown_pct",
                  "volatility_pct", "sharpe", "calmar"):
            self.assertIn(k, st)
        self.assertAlmostEqual(st["total_return_pct"], -20.0, places=9)
        self.assertLess(st["max_drawdown_pct"], 0)
        # 单点序列不得炸 NaN
        single = R._stats([1.0])
        self.assertTrue(all(v is None or math.isfinite(v) for v in single.values()))


class TestBias(unittest.TestCase):
    def test_all_levels_match_reference(self):
        cases = [(0.0, 0.0), (0.09, 0.0), (0.101, 0.0), (0.16, 0.0),
                 (0.0, 0.21), (0.16, 0.21), (0.11, 0.19), (-0.2, -0.3),
                 (None, None), (None, 0.25), (0.12, None)]
        for b20, b60 in cases:
            with self.subTest(b20=b20, b60=b60):
                self.assertEqual(R._bias_position(b20, b60),
                                 _ref_bias_position(b20, b60))
        self.assertEqual(R._bias_position(0.16, 0.21)[0], 0.125)

    def test_bias_by_date_matches_independent_ma(self):
        rnd = random.Random(4242)
        closes = [10.0]
        for _ in range(179):
            closes.append(closes[-1] * (1 + rnd.uniform(-0.02, 0.025)))
        dates = [f"D{i:03d}" for i in range(len(closes))]
        bars = [{"date": d, "close": c} for d, c in zip(dates, closes)]
        got = R._bias_by_date(bars)
        self.assertEqual(min(got), "D059")   # 前 59 根不足 MA60
        for i in range(59, len(closes)):
            ma20 = sum(closes[i - 19:i + 1]) / 20
            ma60 = sum(closes[i - 59:i + 1]) / 60
            exp = (closes[i] / ma20 - 1, closes[i] / ma60 - 1)
            self.assertAlmostEqual(got[dates[i]][0], exp[0], places=12)
            self.assertAlmostEqual(got[dates[i]][1], exp[1], places=12)


class TestAlign(unittest.TestCase):
    def test_union_dates_no_forward_fill(self):
        pool = {
            "A": [{"date": "D001", "close": 1.0}, {"date": "D003", "close": 3.0}],
            "B": [{"date": "D002", "close": 2.0}, {"date": "D003", "close": 4.0}],
        }
        dates, closes, cov = R._align(pool)
        self.assertEqual(dates, ["D001", "D002", "D003"])
        self.assertEqual(closes["A"], [1.0, None, 3.0])
        self.assertEqual(closes["B"], [None, 2.0, 4.0])
        self.assertEqual({c["symbol"]: c["bars"] for c in cov}, {"A": 2, "B": 2})
        self.assertTrue(next(c for c in cov if c["symbol"] == "B")["listed_late"])

    def test_zero_or_missing_close_dropped(self):
        pool = {"A": [{"date": "D001", "close": 0.0}],
                "B": [{"date": "D002", "close": 1.0}]}
        # 0 价不会被 _align 过滤（由 _fetch_pool 过滤），但必须原样保留为有效数值
        dates, closes, _ = R._align(pool)
        self.assertEqual(closes["A"], [0.0, None])


class TestSkillParity(unittest.TestCase):
    """lag=0 必须逐点复刻技能脚本，这是「口径没跑偏」的锚。"""

    def test_four_parameter_sets_bitwise_parity(self):
        for lb, rb, k, seed in [(20, 5, 1, 20261114), (20, 5, 2, 777),
                                (10, 3, 1, 4242), (60, 10, 2, 9999)]:
            with self.subTest(lb=lb, rb=rb, k=k, seed=seed):
                dates, assets, closes = _synth(320, 4, seed)
                s_sig, s_eq, s_eweq, s_mdd, s_ewmdd = _ref_rotation_backtest(
                    dates, assets, closes, lb, rb, k, None, True)
                mine = _ledger(dates, assets, closes, lookback=lb, rebalance=rb,
                               top=k, execution_lag=0)
                self.assertEqual(len(s_eq), len(mine["eq_rot"]))
                for a, b in zip(s_eq, mine["eq_rot"]):
                    self.assertAlmostEqual(a, b, places=12)
                for a, b in zip(s_eweq, mine["eq_ew"]):
                    self.assertAlmostEqual(a, b, places=12)
                self.assertAlmostEqual(s_mdd, R._max_drawdown(mine["eq_rot"]), places=12)
                self.assertAlmostEqual(s_ewmdd, R._max_drawdown(mine["eq_ew"]), places=12)
                self.assertEqual([x[0] for x in s_sig],
                                 [x["date"] for x in mine["signals"]])
                self.assertEqual([x[1] for x in s_sig],
                                 [x["selected"] for x in mine["signals"]])

    def test_lag1_no_lookahead(self):
        """i=20 选 A；i=25 B 暴涨 50% 成为冠军。lag=0 吃到当日涨幅（前视），
        lag=1 只能从 i=26 起反映，i=25 仍是 A 的收益。"""
        n, dates, assets = 30, [f"D{i:03d}" for i in range(30)], ["A", "B"]
        closes = {"A": [10.0 * (1 + 0.001 * i) for i in range(n)],
                  "B": [10.0] * 25 + [15.0] * 5}
        l0 = _ledger(dates, assets, closes, rebalance=5, execution_lag=0)
        l1 = _ledger(dates, assets, closes, rebalance=5, execution_lag=1)
        self.assertEqual(l0["signals"][0]["selected"], ["A"])
        self.assertEqual(l0["signals"][1]["selected"], ["B"])
        self.assertEqual(l1["signals"][1]["selected"], ["B"])
        self.assertGreater(l0["eq_rot"][25] / l0["eq_rot"][24] - 1, 0.4)
        self.assertLess(l1["eq_rot"][25] / l1["eq_rot"][24] - 1, 0.02)
        self.assertLess(l1["eq_rot"][26] / l1["eq_rot"][25] - 1, 0.01)

    def test_min_return_zero_not_swallowed_by_falsy(self):
        dates, assets, _ = _synth(120, 3, 31337)
        flat = {a: [10.0 * (1 - 0.001 * i) for i in range(len(dates))] for a in assets}
        res = _ledger(dates, assets, flat, min_return=0.0, execution_lag=1)
        self.assertTrue(res["signals"])
        self.assertTrue(all(not s["selected"] for s in res["signals"]))

    def test_no_forward_fill_early_listing(self):
        dates = [f"D{i:03d}" for i in range(100)]
        closes = {"A": [10.0 + 0.01 * i for i in range(100)],
                  "B": [None] * 60 + [20.0 + 0.02 * (i - 60) for i in range(60, 100)]}
        res = _ledger(dates, ["A", "B"], closes, execution_lag=1)
        self.assertTrue(all("B" not in s["selected"]
                            for s in res["signals"] if s["date"] < "D080"))
        self.assertTrue(any("B" in s["selected"]
                            for s in res["signals"] if s["date"] >= "D080"))
        # 等权基准缺失日不把资金摊给 A（不会变成 2 倍杠杆）
        self.assertAlmostEqual(res["eq_ew"][1] / res["eq_ew"][0] - 1,
                               (10.01 / 10.0 - 1) * 0.5, places=9)


class TestOverlayAndCost(unittest.TestCase):
    def test_bias_overlay_reduces_weights(self):
        dates, assets, closes = _synth(240, 4, 555)
        # 强单调上涨会持续触发 BIAS20>10%/15%、BIAS60>20%
        ramp = {a: [10.0 * (1.012 ** i) for i in range(len(dates))] for a in assets}
        pool = _pool(ramp, dates, assets)
        maps = {a: R._bias_by_date(pool[a]) for a in assets}
        plain = _ledger(dates, assets, ramp, execution_lag=1)
        over = _ledger(dates, assets, ramp, bias_overlay=True, bias_maps=maps,
                       execution_lag=1)
        self.assertTrue(any(
            any(v["target_position"] < 1.0 for v in s["bias"].values())
            for s in over["signals"]))
        self.assertLess(over["eq_rot"][-1], plain["eq_rot"][-1])

    def test_cost_reduces_equity_and_tracks_turnover(self):
        dates, assets, closes = _synth(240, 4, 888)
        free = _ledger(dates, assets, closes, cost_bps=0, execution_lag=1)
        paid = _ledger(dates, assets, closes, cost_bps=10, execution_lag=1)
        self.assertGreater(free["total_turnover"], 0)
        self.assertGreater(paid["total_cost"], 0)
        self.assertLess(paid["eq_rot"][-1], free["eq_rot"][-1])
        self.assertEqual(free["total_cost"], 0.0)
        self.assertAlmostEqual(paid["total_cost"],
                               paid["total_turnover"] * 10 / 10000, places=12)

    def test_zero_cost_parity_still_holds_with_overlay_off(self):
        dates, assets, closes = _synth(200, 4, 123)
        got = _ledger(dates, assets, closes, execution_lag=0)["eq_rot"]
        ref = _ref_rotation_backtest(dates, assets, closes, 20, 5, 1)[1]
        self.assertEqual(len(got), len(ref))
        for a, b in zip(got, ref):
            self.assertAlmostEqual(a, b, places=12)


class TestValidateAndRun(unittest.TestCase):
    def test_validate_guards(self):
        base = ["510300", "510500"]
        bad = [
            (["510300"], {}),
            (base, {"top": 3}),
            (base, {"lookback": 1}),
            (base, {"rebalance": 0}),
            (base, {"years": 99}),
            (base, {"cost_bps": 999}),
            (base, {"execution_lag": 2}),
            ([f"S{i}" for i in range(21)], {}),  # 超过 MAX_SYMBOLS 上限
        ]
        for syms, kw in bad:
            with self.subTest(syms=syms, kw=kw):
                p = dict(symbols=syms, lookback=20, rebalance=5, top=1, years=5,
                         cost_bps=0, execution_lag=1)
                p.update(kw)
                with self.assertRaises(ValueError):
                    R._validate(**p)
        self.assertEqual(R._validate(base + base, 20, 5, 1, 5, 0, 1), base)

    def _fake_pool(self, n=300):
        # 必须是互不相同的合法 YYYY-MM-DD；_align 会按 [:10] 截断日期
        dates = [(date(2021, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]
        assets = ["A", "B", "C"]
        rnd = random.Random(2026)
        closes = {}
        for j, a in enumerate(assets):
            px, series = 10.0 + j, []
            for i in range(n):
                px *= 1 + 0.0005 * (j - 1) + 0.005 * math.sin(i / 13 + j) + rnd.uniform(-0.003, 0.003)
                series.append(px)
            closes[a] = series
        return dates, assets, closes

    def test_run_rotation_structure_and_json(self):
        dates, assets, closes = self._fake_pool()
        pool = _pool(closes, dates, assets)
        with patch.object(R, "_fetch_pool", return_value=(pool, ("S", "E"))):
            res = R.run_rotation(assets, use_cache=False)
        raw = json.dumps(res, allow_nan=False)  # 裸 NaN 会在此抛 ValueError
        self.assertGreater(len(raw), 1000)
        self.assertEqual(res["config"]["execution_lag"], 1)
        self.assertEqual(res["window"]["trading_days"], len(dates))
        self.assertEqual(len(res["equity_curve"]), len(dates))
        self.assertEqual(len(res["coverage"]), 3)
        self.assertTrue(res["latest"]["actions"])
        self.assertTrue(all(s["effective_date"] is None or s["effective_date"] > s["date"]
                            for s in res["signals"]))
        self.assertGreaterEqual(len(res["caveats"]), 6)
        for block in (res["metrics"]["rotation"], res["metrics"]["equal_weight"]):
            for v in block.values():
                self.assertTrue(v is None or math.isfinite(v))

    def test_run_rotation_cash_stance_explicit(self):
        dates, assets, closes = self._fake_pool(200)
        flat = {a: [10.0 * (1 - 0.001 * i) for i in range(len(dates))] for a in assets}
        pool = _pool(flat, dates, assets)
        with patch.object(R, "_fetch_pool", return_value=(pool, ("S", "E"))):
            res = R.run_rotation(assets, min_return=0.0, use_cache=False)
        self.assertEqual(res["latest"]["stance"], "cash")
        self.assertEqual(res["latest"]["selected"], [])
        self.assertEqual(res["latest"]["actions"][0]["symbol"], "CASH")

    def test_run_rotation_fail_fast_on_fetch_error(self):
        with patch.object(R, "_fetch_pool", side_effect=ValueError("X 无有效日线")):
            with self.assertRaises(ValueError):
                R.run_rotation(["A", "B"], use_cache=False)

    def test_run_rotation_fail_fast_on_short_window(self):
        dates = [f"D{i:03d}" for i in range(40)]
        pool = {a: [{"date": d, "close": 1.0} for d in dates] for a in ("A", "B")}
        with patch.object(R, "_fetch_pool", return_value=(pool, ("S", "E"))):
            with self.assertRaisesRegex(ValueError, "公共交易日"):
                R.run_rotation(["A", "B"], use_cache=False)

    def test_cache_hit_returns_same_object(self):
        dates, assets, closes = self._fake_pool(120)
        pool = _pool(closes, dates, assets)
        R.clear_cache()
        with patch.object(R, "_fetch_pool", return_value=(pool, ("S", "E"))) as fp:
            a = R.run_rotation(assets, use_cache=True)
            b = R.run_rotation(assets, use_cache=True)
        self.assertIs(a, b)
        self.assertEqual(fp.call_count, 1)
        R.clear_cache()


if __name__ == "__main__":
    unittest.main(verbosity=2)
