"""index_valuation TTL 缓存 + singleflight + enrich 并行化 离线回归测试。

不依赖 requests / duckdb 等第三方包：先在 sys.modules 注入 requests 桩，
再 import market_service，用猴子补丁替换上游调用计数验证行为。

运行：python scripts/test_index_val_cache.py
退出码 0 = 全部通过。
"""

import sys
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---- requests 桩（测试内禁止真实网络）----
_req = types.ModuleType("requests")
_req.__path__ = []  # 标记为包，允许 from requests.adapters import ...


class _StubExc(Exception):
    pass


_req.exceptions = types.SimpleNamespace(Timeout=_StubExc, ConnectionError=_StubExc)


class _StubAdapter:
    def __init__(self, **kwargs):
        pass


_req_adapters = types.ModuleType("requests.adapters")
_req_adapters.HTTPAdapter = _StubAdapter
_req.adapters = _req_adapters
sys.modules["requests.adapters"] = _req_adapters


class _StubSession:
    def __init__(self):
        self.adapters = {}

    def mount(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        raise AssertionError("测试内不应发起真实网络请求")


_req.Session = _StubSession
sys.modules["requests"] = _req

from services import market_service as ms  # noqa: E402

PASS = []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name} {detail}")
    else:
        print(f"  FAIL {name} {detail}")
        sys.exit(1)


# ---------------------------------------------------------------
# 1. TTL 缓存：连续两次调用只打一次上游；TTL 过期后重打
# ---------------------------------------------------------------
print("[1] TTL 缓存")
calls = {"n": 0}
ms._INDEX_VAL_CACHE.update(data=None, ts=0.0)
ms._INDEX_VAL_INFLIGHT = None


def fake_pd(category, params=None, retries=1, timeout=10):
    calls["n"] += 1
    return [{"index_name": "沪深300"}]


ms._processed_data_request = fake_pd

r1 = ms._fetch_index_valuation_raw()
r2 = ms._fetch_index_valuation_raw()
check("TTL 内第二次命中缓存", calls["n"] == 1, f"上游调用 {calls['n']} 次")
check("返回值透传", r1 == r2 and r1[0]["index_name"] == "沪深300")

# 手工把 ts 提前到 TTL 之外 → 应重新上游
ms._INDEX_VAL_CACHE["ts"] = time.time() - (ms._INDEX_VAL_TTL + 1)
r3 = ms._fetch_index_valuation_raw()
check("TTL 过期后重打上游", calls["n"] == 2)

# force 穿透
r4 = ms._fetch_index_valuation_raw(force=True)
check("force 穿透缓存", calls["n"] == 3)

# ---------------------------------------------------------------
# 2. singleflight：N 个线程并发未命中 → 只放一个上游请求在途
# ---------------------------------------------------------------
print("[2] singleflight")
calls["n"] = 0
ms._INDEX_VAL_CACHE.update(data=None, ts=0.0)
ms._INDEX_VAL_INFLIGHT = None
release = threading.Event()
started = threading.Event()


def slow_pd(category, params=None, retries=1, timeout=10):
    calls["n"] += 1
    started.set()
    release.wait(timeout=5)  # 卡住在途请求，逼出并发竞争
    return [{"index_name": "上证50"}]


ms._processed_data_request = slow_pd
results: list = []
errs: list = []


def worker():
    try:
        results.append(ms._fetch_index_valuation_raw())
    except Exception as e:  # pragma: no cover
        errs.append(e)


threads = [threading.Thread(target=worker) for _ in range(10)]
for t in threads:
    t.start()
started.wait(timeout=5)
time.sleep(0.2)  # 给其余线程进入等待的时间
release.set()
for t in threads:
    t.join(timeout=10)

check("并发 10 线程只打 1 次上游", calls["n"] == 1, f"上游调用 {calls['n']} 次")
check("等待者拿到在途结果", len(results) == 10 and all(r and r[0]["index_name"] == "上证50" for r in results))
check("无异常", not errs, str(errs[:2]))

# ---------------------------------------------------------------
# 3. 失败不写缓存（无负缓存）→ 下次立即重试
# ---------------------------------------------------------------
print("[3] 失败不缓存")
ms._INDEX_VAL_CACHE.update(data=None, ts=0.0)
ms._INDEX_VAL_INFLIGHT = None


def failing_pd(category, params=None, retries=1, timeout=10):
    calls["n"] += 1
    return None


ms._processed_data_request = failing_pd
calls["n"] = 0
ms._fetch_index_valuation_raw()
ms._fetch_index_valuation_raw()
check("失败后不被缓存，连续重试", calls["n"] == 2, f"上游调用 {calls['n']} 次")

# ---------------------------------------------------------------
# 4. _enrich_valuation_with_history 并行化：20 个指数各耗 0.1s，
#    8 并发应在 ~0.5s 内完成（串行需 2s+）；结果逐行正确落值
# ---------------------------------------------------------------
print("[4] enrich 并行化")
snap_calls = {"n": 0}
snap_lock = threading.Lock()


def fake_snapshot(code):
    with snap_lock:
        snap_calls["n"] += 1
    time.sleep(0.1)
    if code == "NO_DATA":
        return None
    return {
        "pe": 12.5,
        "pb": 1.3,
        "pe_percentile": 55.0,
        "pb_percentile": 60.0,
        "pe_samples": 100,
        "pb_samples": 100,
        "as_of": "2026-10-15",
        "chg_1y_pct": 8.2,
        "win_rate": 61.5,
    }


ms._index_pb_pe_snapshot = fake_snapshot

indices = [{"name": f"指数{i}", "code": f"00000{i}"} for i in range(20)]
indices.append({"name": "无数据指数", "code": "NO_DATA"})
indices.append({"name": "无代码指数", "code": ""})
indices.append({"name": "无估值指数", "code": "000999", "hasValuation": False})

t0 = time.time()
out = ms._enrich_valuation_with_history(indices)
elapsed = time.time() - t0

check("每个待补全指数都打了快照", snap_calls["n"] == 21, f"快照调用 {snap_calls['n']} 次")
check("并行显著快于串行", elapsed < 1.0, f"耗时 {elapsed:.2f}s（串行需 ≥2.1s）")
ok_row = out[0]
check("有数据行落值正确",
      ok_row["pe"] == 12.5 and ok_row["pe_percentile"] == 55.0
      and ok_row["category"] == ms._valuation_category(55.0, 12.5)
      and ok_row["pe_as_of"] == "2026-10-15" and ok_row["win_rate"] == 61.5)
nodata = next(i for i in out if i["code"] == "NO_DATA")
check("无历史序列行置 unknown", nodata["category"] == "unknown" and nodata["pe_percentile"] is None)
nocode = next(i for i in out if i["code"] == "")
check("无代码行置 unknown", nocode["category"] == "unknown" and nocode["win_rate"] is None)
noval = next(i for i in out if i.get("hasValuation") is False)
check("hasValuation=False 行不打快照且置 unknown", noval["category"] == "unknown")

print(f"\n全部通过（{len(PASS)} 项）")
