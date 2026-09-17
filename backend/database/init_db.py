"""Database initialization script for QuantTerminal Pro.

Creates all sequences, tables, and indexes in the DuckDB database file.

Usage:
    cd backend
    python -m database.init_db              # Create tables (idempotent)
    python -m database.init_db --rebuild    # Drop and recreate everything
    python -m database.init_db --verify     # Only verify existing schema
"""

import argparse
import sys
from pathlib import Path

# Ensure the backend directory is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.connection import Database, DEFAULT_DB_PATH
from database.schema import (
    SEQUENCES,
    TABLES,
    INDEXES,
    DROP_TABLES,
    DROP_SEQUENCES,
)


def create_sequences(db: Database) -> int:
    """Create all sequences. Returns the count created."""
    count = 0
    for sql in SEQUENCES:
        db.execute(sql)
        count += 1
    return count


def create_tables(db: Database) -> int:
    """Create all tables. Returns the count created."""
    count = 0
    for sql in TABLES:
        db.execute(sql)
        count += 1
    return count


def create_indexes(db: Database) -> int:
    """Create all indexes. Returns the count created."""
    count = 0
    for sql in INDEXES:
        try:
            db.execute(sql)
            count += 1
        except Exception as e:
            print(f"  [WARN] Index creation skipped: {e}")
    return count


def ensure_schema(db: Database) -> None:
    """幂等确保全部序列 / 表 / 索引存在（应用启动时调用，无需手动 init_db）。

    所有 DDL 均为 IF NOT EXISTS，重复执行安全：新库全量建表，
    旧库缺哪张表（如 base_sw_sector_daily）就补哪张。
    """
    for sql in SEQUENCES:
        db.execute(sql)
    for sql in TABLES:
        db.execute(sql)
    for sql in INDEXES:
        try:
            db.execute(sql)
        except Exception as e:
            print(f"  [WARN] Index creation skipped: {e}")


def drop_all(db: Database) -> None:
    """Drop all tables and sequences for a clean rebuild."""
    print("Dropping existing tables...")
    for sql in DROP_TABLES:
        db.execute(sql)

    print("Dropping existing sequences...")
    for sql in DROP_SEQUENCES:
        db.execute(sql)


def verify_schema(db: Database) -> None:
    """Print a verification report of the database schema."""
    tables = db.list_tables()
    print(f"\n{'=' * 60}")
    print(f"  Database: {db.db_path}")
    print(f"  Tables: {len(tables)}")
    print(f"{'=' * 60}")

    base_tables = sorted([t for t in tables if t.startswith("base_")])
    biz_tables = sorted([t for t in tables if t.startswith("biz_")])

    print(f"\n  Data Source Tables (base_): {len(base_tables)}")
    for t in base_tables:
        col_count = db.fetchone(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = ?",
            [t],
        )[0]
        row_count = db.table_row_count(t)
        print(f"    {t:<40} {col_count:>3} cols   {row_count:>6} rows")

    print(f"\n  Business Tables (biz_): {len(biz_tables)}")
    for t in biz_tables:
        col_count = db.fetchone(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = ?",
            [t],
        )[0]
        row_count = db.table_row_count(t)
        print(f"    {t:<40} {col_count:>3} cols   {row_count:>6} rows")

    # Index count
    idx_rows = db.fetchall(
        "SELECT index_name FROM duckdb_indexes() WHERE schema_name = 'main' ORDER BY index_name"
    )
    print(f"\n  Indexes: {len(idx_rows)}")

    # Sequence count
    seq_rows = db.fetchall(
        "SELECT sequence_name FROM duckdb_sequences() WHERE schema_name = 'main' ORDER BY sequence_name"
    )
    print(f"  Sequences: {len(seq_rows)}")

    # File size
    db_path = Path(db.db_path)
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"  File size: {size_mb:.2f} MB")

    print(f"{'=' * 60}\n")


def init_database(
    db_path: str | Path | None = None,
    rebuild: bool = False,
    verify_only: bool = False,
) -> None:
    """Initialize the database with all schema objects."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    db = Database(path)

    if verify_only:
        verify_schema(db)
        db.close()
        return

    if rebuild:
        drop_all(db)

    print(f"Initializing database at: {path}")
    print(f"  File exists: {path.exists()}")
    print()

    # Step 1: Sequences
    print("[1/3] Creating sequences...")
    seq_count = create_sequences(db)
    print(f"  Created {seq_count} sequences")

    # Step 2: Tables
    print("[2/3] Creating tables...")
    table_count = create_tables(db)
    print(f"  Created {table_count} tables")

    # Step 3: Indexes
    print("[3/3] Creating indexes...")
    idx_count = create_indexes(db)
    print(f"  Created {idx_count} indexes")

    # Verify
    verify_schema(db)

    db.close()
    print("Database initialization complete.")



# ============================================================
# 用户绑定迁移（2026-09-17）
# 历史表以 user_id VARCHAR 存用户名；现统一改为 fk_users UUID 引用 biz_users.pk_users，
# 使 username 后续可变更而不影响持仓 / 设置 / 自选等绑定。幂等：已迁移的表自动跳过。
# ============================================================

_USER_BINDING_TABLES = [
    "biz_holdings",
    "biz_broker_accounts",
    "biz_account_names",
    "biz_holding_snapshots",
    "biz_strategies",
    "biz_signal_subscriptions",
    "biz_library_subscriptions",
    "biz_library_snapshots",
]


def migrate_user_binding(db: Database) -> None:
    """一次性幂等迁移：user_id(username) -> fk_users(pk_users UUID)。"""
    for table in _USER_BINDING_TABLES:
        exists = db.fetchone(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        )
        if not exists:
            continue
        cols = {r[0] for r in db.fetchall(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]
        )}
        if "user_id" not in cols or "fk_users" in cols:
            continue  # 已迁移或本来就用 fk_users
        print(f"[Migration] {table}: user_id -> fk_users")
        # 旧索引若依赖 user_id 需先删（仅 biz_strategies 有 idx_strat_users）
        if table == "biz_strategies":
            try:
                db.execute("DROP INDEX IF EXISTS idx_strat_users")
            except Exception:
                pass
        db.execute(f"ALTER TABLE {table} ADD COLUMN fk_users UUID")
        # 经 biz_users 映射 username -> pk_users（pk 转字符串以写入 UUID 列）
        pk_map = {u: str(p) for u, p in db.fetchall(
            "SELECT username, pk_users FROM biz_users"
        )}
        rows = db.fetchall(f"SELECT id, user_id FROM {table}")
        updated = 0
        for rid, uname in rows:
            pk = pk_map.get(uname)
            if pk:
                db.execute(f"UPDATE {table} SET fk_users = ? WHERE id = ?", [pk, rid])
                updated += 1
        # 无法归属的孤儿行删除（无对应用户）
        orphan = db.fetchone(f"SELECT count(*) FROM {table} WHERE fk_users IS NULL")
        if orphan and orphan[0]:
            print(f"[Migration] {table}: 删除 {orphan[0]} 条无主记录")
            db.execute(f"DELETE FROM {table} WHERE fk_users IS NULL")
        db.execute(f"ALTER TABLE {table} DROP COLUMN user_id")
        print(f"[Migration] {table}: 完成（映射 {updated} 行）")


def main():
    parser = argparse.ArgumentParser(description="Initialize QuantTerminal Pro DuckDB database")
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to the .duckdb file (default: backend/database/quantterminal.duckdb)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop all tables and sequences before creating (destructive!)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only verify the existing schema, do not create anything",
    )
    args = parser.parse_args()

    init_database(
        db_path=args.db_path,
        rebuild=args.rebuild,
        verify_only=args.verify,
    )


if __name__ == "__main__":
    main()
