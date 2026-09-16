"""指数 PB/PE 月度历史取数（唯一数据源：AkShare WebAPI 指数估值接口）。

数据流
------
    本模块 ──HTTP──> AkShare WebAPI  GET /api/index-valuation/{code}/history
                          │
                          ├─ Redis 缓存（TTL 2 小时，命中即毫秒返回）
                          └─ MySQL t_index_valuation（唯一真源，交易日 18:35 定时增量）

接口返回（保持与旧 legulegu 派生序列同构，上层 valuation_service 零改动）：
    {"code","name",
     "pb":[{"date":"YYYY-MM-DD","pb":float,"index_value":float|None}],
     "pe":[{"date":"YYYY-MM-DD","pe_ttm":float,"pe_static":float,"index_value":float|None}],
     "months":{"pb":n,"pe":n},"source","updated_at","cache":"redis|mysql"}

约定
----
**本模块不使用任何本地文件缓存**：数据一律来自数据接口。
取数失败返回空序列，由上层按「真实优先、失败返回空」处理，绝不使用 mock。
"""

from __future__ import annotations

from services.akshare_client import akshare_api_get

#: 参与取数的宽基指数（与 aksharewebapi ``market/index_pbpe_service.INDEX_UNIVERSE`` 对齐）
BACKFILL_CODES = [
    "000016", "000300", "000009", "399673", "000905",
    "000010", "399324", "399330", "000852", "000015",
    "000903", "000906",
]

#: 业务路径前缀
_API_PREFIX = "/api/index-valuation"


def get_index_pb_pe_meta(csindex_code: str,
                         start: str | None = None,
                         end: str | None = None,
                         timeout: int = 15) -> dict | None:
    """取完整响应体（含 months/source/cache 等元信息），失败返回 None。"""
    code = str(csindex_code or "").strip()
    if not code:
        return None
    params: dict = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    data = akshare_api_get(f"{_API_PREFIX}/{code}/history",
                           params=params or None, timeout=timeout)
    if not isinstance(data, dict):
        return None
    return data


def get_index_pb_pe(csindex_code: str,
                    start: str | None = None,
                    end: str | None = None) -> tuple[list, list]:
    """对外主入口：返回 ``(pb_rows, pe_rows)``。

    pb_rows: ``[{"date","pb","index_value"}]``（按日期升序）
    pe_rows: ``[{"date","pe_ttm","pe_static","index_value"}]``（按日期升序）

    接口不可用或指数无数据时返回 ``([], [])``。
    """
    data = get_index_pb_pe_meta(csindex_code, start=start, end=end)
    if not data:
        return [], []

    pb_rows = data.get("pb") or []
    pe_rows = data.get("pe") or []
    if not isinstance(pb_rows, list) or not isinstance(pe_rows, list):
        return [], []

    pb_rows = sorted((r for r in pb_rows if isinstance(r, dict) and r.get("date")),
                     key=lambda x: x["date"])
    pe_rows = sorted((r for r in pe_rows if isinstance(r, dict) and r.get("date")),
                     key=lambda x: x["date"])
    return pb_rows, pe_rows


if __name__ == "__main__":
    import sys

    codes = sys.argv[1].split(",") if len(sys.argv) > 1 else BACKFILL_CODES
    bad = []
    for c in codes:
        d = get_index_pb_pe_meta(c)
        if not d:
            bad.append(c)
            print(f"{c}: 取数失败")
            continue
        pb, pe = d.get("pb") or [], d.get("pe") or []
        print(f"{c}({d.get('name')}): pb={len(pb)} pe={len(pe)} "
              f"cache={d.get('cache')} source={d.get('source')} "
              f"最新={pb[-1] if pb else None}")
    print(f"完成: {len(codes) - len(bad)}/{len(codes)} 成功" + (f"，失败 {bad}" if bad else ""))
