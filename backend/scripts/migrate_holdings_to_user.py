"""One-off migration: move holdings data from the demo user to a real user.

背景：认证为进程内内存存储（auth_service），JWT 的 sub 即用户名，
get_current_user 返回的 user_id 就是用户名（如 "sos"）。
而早期未登录时 get_current_user 回退为 DEMO_USER_ID（UUID），
故历史持仓挂在 "00000000-0000-0000-0000-000000000001" 下。

Usage (backend must be stopped, DuckDB single-writer):
    cd backend
    python -m scripts.migrate_holdings_to_user sos

Moves rows in biz_holdings / biz_holding_snapshots whose user_id equals the
demo user UUID to the target username. Prints a summary;
use --dry-run to preview without writing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

# 与 core.deps.DEMO_USER_ID 保持一致
DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"
DB_PATH = Path(__file__).resolve().parent.parent / "database" / "quantterminal.duckdb"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", nargs="?", default="sos", help="目标用户名（默认 sos，即登录后的 user_id）")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入")
    args = parser.parse_args()
    target = args.username.strip()

    conn = duckdb.connect(str(DB_PATH))

    # 源数据（demo 用户）
    h_count = conn.execute(
        "SELECT count(*) FROM biz_holdings WHERE user_id = ?", [DEMO_USER_ID]
    ).fetchone()[0]
    s_count = conn.execute(
        "SELECT count(*) FROM biz_holding_snapshots WHERE user_id = ?", [DEMO_USER_ID]
    ).fetchone()[0]
    print(f"待迁移: biz_holdings {h_count} 条, biz_holding_snapshots {s_count} 条 (源: {DEMO_USER_ID})")

    # 目标用户是否已有数据（避免覆盖）
    t_h = conn.execute(
        "SELECT count(*) FROM biz_holdings WHERE user_id = ?", [target]
    ).fetchone()[0]
    t_s = conn.execute(
        "SELECT count(*) FROM biz_holding_snapshots WHERE user_id = ?", [target]
    ).fetchone()[0]
    print(f"目标用户 '{target}' 现有: biz_holdings {t_h} 条, snapshots {t_s} 条")

    if args.dry_run:
        print("\n[DRY-RUN] 未写入任何数据。")
        conn.close()
        return 0

    if h_count == 0 and s_count == 0:
        print("没有可迁移的数据（demo 用户下为空）。")
        conn.close()
        return 0

    if t_h > 0 or t_s > 0:
        print("[警告] 目标用户已有持仓/快照数据，继续将合并（不做覆盖去重）。")

    conn.execute(
        "UPDATE biz_holdings SET user_id = ? WHERE user_id = ?",
        [target, DEMO_USER_ID],
    )
    conn.execute(
        "UPDATE biz_holding_snapshots SET user_id = ? WHERE user_id = ?",
        [target, DEMO_USER_ID],
    )

    # 校验
    after_h = conn.execute(
        "SELECT count(*) FROM biz_holdings WHERE user_id = ?", [target]
    ).fetchone()[0]
    after_s = conn.execute(
        "SELECT count(*) FROM biz_holding_snapshots WHERE user_id = ?", [target]
    ).fetchone()[0]
    left_h = conn.execute(
        "SELECT count(*) FROM biz_holdings WHERE user_id = ?", [DEMO_USER_ID]
    ).fetchone()[0]

    conn.close()
    print(f"迁移完成: 目标用户持仓 {after_h} 条, 快照 {after_s} 条; demo 剩余 {left_h} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
