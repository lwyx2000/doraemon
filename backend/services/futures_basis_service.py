"""商品期货期现基差 —— **诊断字段，不参与估值公式**。

## 为什么不做「基差还原」（2026-11-03 复核《无敌哥估值说明文档》2.4 后确定）

文档 2.4 建议「用期货推 EST 时要扣掉基差升水」（并给了 NQ 年化 4.1%、ES 3.6% 的实值）。
逐条核对本项目后确认**不能这么改**：

1. 走期货口径的只有 2 只，且它们的业绩基准**本身就是期货价格指数**：
   - 161226 国投瑞银白银期货LOF → 上期所白银期货（AG0）
   - 159985 豆粕ETF华夏 → 大商所豆粕期货价格指数（M0）
   用结算价推净值是**正确口径**。若按 2.4 扣掉基差，等于把一个正确的值改错：
   实测 2026-10-30 M 主力基差率 −2.12%，扣上去就是凭空 2% 的净误差。
2. 文档 2.4 的 NQ/ES 升水针对的是「**用指数期货推现货指数**」的场景。
   本项目美股腿一律用 QQQ/SPY/XOP 等 ETF **现货价**（见 qdii_baskets.json），
   不存在这一层；日经腿改吃现货口径（_load_jp_daily_sync）。所以这个坑在本项目不存在。

结论：**基差不是估值误差源，而是一个独立的持有期信息**——期货贴水（back）时滚动
换月有正展期收益，升水（contango）时有负展期收益。所以这里只把基差率挂出来供判断，
一行都不进 est_nav。

## 数据源
数据网关 `futures_spot_price_daily`（AkShare）→ 现货价 / 近月 / 主力 / 基差 / 基差率。
该接口按「日期段 + 品种」返回全市场，一次调用覆盖 AG、M 等所有品种，因此按天缓存。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from services.akshare_client import akshare_request

# 基差一天只变一次（收盘后发布），6h 缓存足够；失败后 30min 再试，别在请求路径上反复重试
_BASIS_TTL = 6 * 3600
_BASIS_RETRY_AFTER_FAIL = 30 * 60

_cache: dict[str, object] = {"ts": 0.0, "data": {}}
_lock = threading.Lock()
_warming = False

# 基差率绝对值超过这个数就提示「月差异常」——商品期货主力基差率常态在 ±10% 内，
# 超出多半是近月逼仓、合约切换或现货报价口径变化，此时基差数字不宜直接解读。
_EXTREME_RATE = 10.0


def _f(v) -> float | None:
    try:
        x = float(v)
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _product_code(symbol: str) -> str:
    """合约符号 → 品种代码：AG0 → AG，M0 → M，m2611 → M。"""
    s = str(symbol or "").strip().upper()
    return s.rstrip("0123456789")


def _is_contract_alias(sym: str) -> bool:
    """只处理「连续/主力」类符号（AG0/M0）；具体月份合约不做基差挂载。"""
    s = str(sym or "")
    return s.endswith("0") and not s[:-1].isdigit()


def get_basis_map(force: bool = False) -> dict[str, dict]:
    """取当前可用的期现基差（品种代码 → 明细）。失败返回空 dict，绝不抛。"""
    now = time.time()
    with _lock:
        ts = float(_cache.get("ts") or 0)
        data = _cache.get("data") or {}
        if not force and ts and (now - ts) < _BASIS_TTL:
            return data  # type: ignore[return-value]
        if not force and ts and (now - ts) < _BASIS_TTL + _BASIS_RETRY_AFTER_FAIL and not data:
            return {}  # 刚失败过，退避期内不再打扰网关

    # 基差按自然日发布，往前取 10 天覆盖长假（春节/国庆期间最新一期可能是节前）
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    rows = akshare_request(
        "futures_spot_price_daily",
        {"start_day": start, "end_day": end},
        retries=1,
        timeout=40,
    )
    out: dict[str, dict] = {}
    if isinstance(rows, list):
        # 同一品种多天 → 只保留最新那天（接口按日期升序返回的可能性更大，但仍显式比较）
        for r in rows:
            if not isinstance(r, dict):
                continue
            prod = _product_code(str(r.get("symbol") or ""))
            d = str(r.get("date") or "")
            if not prod or len(d) != 8:
                continue
            d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            prev = out.get(prod)
            if prev and prev["date"] >= d:
                continue
            out[prod] = {
                "date": d,
                "spot": _f(r.get("spot_price")),
                "near_contract": r.get("near_contract"),
                "near_price": _f(r.get("near_contract_price")),
                "dominant_contract": r.get("dominant_contract"),
                "dominant_price": _f(r.get("dominant_contract_price")),
                "near_basis_rate": _f(r.get("near_basis_rate")),
                "dom_basis_rate": _f(r.get("dom_basis_rate")),
            }

    with _lock:
        _cache["ts"] = time.time()
        _cache["data"] = out
    if out:
        print(f"[FuturesBasis] 基差命中 {len(out)} 个品种（{len(out)} 条最新日期）")
    else:
        print("[FuturesBasis] 基差接口未返回数据（本期跳过，不影响估值）")
    return out


def warm_async() -> None:
    """后台预热，避免首个 /funds 请求陪等 40s 的网关调用。"""
    global _warming
    with _lock:
        if _warming:
            return
        _warming = True

    def _run() -> None:
        global _warming
        try:
            get_basis_map()
        except Exception as e:  # 预热失败只是没有诊断字段，绝不能影响列表
            print(f"[FuturesBasis] 预热失败（忽略）: {type(e).__name__}: {e}")
        finally:
            with _lock:
                _warming = False

    threading.Thread(target=_run, name="futures-basis-warm", daemon=True).start()


_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "qdii_baskets.json"
_symbol_map: dict[str, str] = {}
_symbol_map_ts: float = 0.0


def _futures_symbol_map() -> dict[str, str]:
    """fund_code → 期货合约（如 161226 → AG0），只取 method == 'futures' 的条目。

    配置是随代码发布的静态文件，按 mtime 缓存即可，不必每次读盘。
    """
    global _symbol_map, _symbol_map_ts
    try:
        mt = _CONFIG_PATH.stat().st_mtime
    except OSError:
        return _symbol_map
    if _symbol_map and mt <= _symbol_map_ts:
        return _symbol_map
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        funds = raw.get("funds") or {}
        out: dict[str, str] = {}
        for code, cfg in funds.items():
            if not isinstance(cfg, dict) or cfg.get("method") != "futures":
                continue
            sym = str((cfg.get("futures") or {}).get("symbol") or "")
            if sym:
                out[str(code)] = sym
        _symbol_map = out
        _symbol_map_ts = mt
        return out
    except Exception as e:
        print(f"[FuturesBasis] 期货配置读取失败（跳过配置通道）: {type(e).__name__}: {e}")
        return _symbol_map


def attach_basis_diagnostics(funds: list[dict]) -> int:
    """给期货口径的基金挂基差诊断字段。

    识别方式双通道：
      ① `est_method == 'futures'`（正常路径，由 cross_border_valuation 打上）；
      ② 直接读 `config/qdii_baskets.json` 里 `method == 'futures'` 的条目。
    为什么需要 ②：篮子快照是**全有或全无**的——任一条腿（如日经日K）取不到，
    `_ensure_snapshot()` 就返回 None，整批 est_* 都不会挂，连带基差也消失。
    基差只依赖网关的期现接口，不该被别国指数的取数故障拖死。

    写入（均**不参与** est_nav 计算）：
      est_basis_rate  主力基差率 %（正的=现货升水/期货贴水，负的=期货升水）
      est_basis_curve 'back'(期货贴水，换月有正展期收益) / 'contango'(期货升水，有负展期收益)
      est_basis_date  基差数据日期（YYYY-MM-DD）
      est_basis_note  月差异常时的文字提示，正常为 None
    """
    if not funds:
        return 0

    cfg_map = _futures_symbol_map()
    targets: list[tuple[dict, str]] = []
    for f in funds:
        sym = str(f.get("est_futures_symbol") or "") if str(f.get("est_method") or "") == "futures" else ""
        if not sym:
            sym = cfg_map.get(str(f.get("code") or ""), "")
        if sym:
            targets.append((f, sym))
    if not targets:
        return 0

    # 缓存从未成功过 → 不在 /funds 请求路径上陪等网关（该接口实测可到 40s）。
    # 转后台预热，本轮到下一轮列表刷新自然就有值；启动时 job 也会主动预热一次。
    if not float(_cache.get("ts") or 0):
        warm_async()
        return 0

    basis = get_basis_map()
    if not basis:
        return 0
    hit = 0
    for f, sym in targets:
        if not _is_contract_alias(sym):
            continue
        b = basis.get(_product_code(sym))
        if not b:
            continue
        rate = b.get("dom_basis_rate")
        if rate is None:
            continue
        pct = round(float(rate) * 100.0, 2)
        f["est_basis_rate"] = pct
        # 基差 = 现货 − 期货。basis_rate < 0 → 期货高于现货 → contango（升水）
        f["est_basis_curve"] = "contango" if pct < 0 else "back"
        f["est_basis_date"] = b.get("date")
        f["est_basis_note"] = (
            f"主力基差率 {pct:+.2f}% 超出常态区间，可能近月逼仓或合约切换，基差不宜直接解读"
            if abs(pct) > _EXTREME_RATE
            else None
        )
        hit += 1

    if hit:
        print(f"[FuturesBasis] 基差诊断挂载 {hit} 只")
    return hit
