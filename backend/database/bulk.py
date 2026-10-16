"""DuckDB 字面量批量写入公共工具。

背景（2026-10-14 实测，duckdb 1.5.6 本地 / 1.5.x 53 容器同病理）：
    「参数化绑定」插入存在严重性能病理——单行 execute ~2-23ms、
    executemany ~20-55ms/行（53 容器 55.7ms/行），而「字面量多行 VALUES」
    仅 ~0.10-0.42ms/行（快 130-260 倍）。批量写一律走字面量。
    全部取值均来自受控数据，仍按 SQL 标准转义（单引号翻倍、NaN/inf→NULL）防注入。

用法：
    from database.bulk import bulk_insert

    bulk_insert(
        db,
        "INSERT INTO t (a, b, c) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
        rows,  # list[list]，与占位符一一对应
    )

契约：
    - sql 为标准形态 "INSERT INTO ... VALUES (?, ...) [ON CONFLICT ...]"，
      占位组被替换为字面量 VALUES 列表，其余部分（含 ON CONFLICT 后缀）原样保留
    - 非标准形态（无占位组）退回参数化 executemany（仅限异常路径，量小可接受）
    - batch 控制单条 SQL 的 VALUES 行数，默认 200（规避过长 SQL）
"""

from __future__ import annotations

from typing import Any


def sql_literal(v: Any) -> str:
    """Python 值 → SQL 字面量。

    None → NULL；bool → TRUE/FALSE；int/float → repr（NaN/inf → NULL，
    DuckDB DOUBLE 支持但业务上视为缺失）；其余 → 单引号字符串（' 翻倍转义）。
    """
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return "NULL"
        return repr(f)
    return "'" + str(v).replace("'", "''") + "'"


def bulk_insert(db, sql: str, rows: list[list], batch: int = 200) -> None:
    """批量插入：字面量多行 VALUES（避开 duckdb 1.5.x 参数化慢路径，见 sql_literal）。

    sql 为标准形态 "INSERT INTO t (cols) VALUES (?, ?, ...) [ON CONFLICT DO NOTHING]"，
    占位组被替换为字面量 VALUES 列表，其余部分（含 ON CONFLICT 后缀）原样保留。
    非标准形态（无占位符）退回参数化 executemany（仅限异常路径，量小可接受）。
    """
    if not rows:
        return
    n_ph = sql.count("?")
    ph_group = "(" + ", ".join(["?"] * n_ph) + ")"
    if n_ph == 0 or ph_group not in sql:
        db.executemany(sql, rows)
        return
    prefix, _, suffix = sql.partition(ph_group)
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        values = ", ".join(
            "(" + ", ".join(sql_literal(v) for v in r) + ")" for r in chunk
        )
        db.execute(prefix + values + suffix)
