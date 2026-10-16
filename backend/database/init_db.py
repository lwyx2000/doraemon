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
# 用户绑定 schema 迁移（2026-09-17）
# - biz_users.pk_users(UUID) -> pk_user(BIGINT 自增主键, nextval(seq_user))
# - 所有绑定表 fk_users(UUID) / user_id(VARCHAR) -> fk_user(BIGINT)
# 数据保留：旧 username/UUID 经 biz_users 重新映射；孤儿行删除。幂等，可反复运行。
# ============================================================

def migrate_pk_user_schema(db: Database) -> None:
    """数据保留式迁移：pk_users(UUID) -> pk_user(BIGINT 自增)；fk_users/user_id -> fk_user(BIGINT)。"""
    import re as _re

    bc = {r[0] for r in db.fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?", ["biz_users"]
    )}
    uuid_to_uname: dict = {}
    uname_to_pk: dict = {}

    if "pk_users" in bc:
        print("[Migration] biz_users: pk_users(UUID) -> pk_user(BIGINT 自增)")
        rows = db.fetchall(
            "SELECT pk_users, username, email, password_hash, created_at FROM biz_users"
        )
        uuid_to_uname = {str(r[0]): r[1] for r in rows}
        db.execute("DROP TABLE biz_users")
        db.execute(
            """
            CREATE TABLE biz_users (
                pk_user        BIGINT DEFAULT nextval('seq_user') PRIMARY KEY,
                username       VARCHAR(50) NOT NULL,
                email          VARCHAR(100),
                password_hash  VARCHAR(255) NOT NULL,
                created_at     TIMESTAMP DEFAULT now()
            )
            """
        )
        for r in rows:
            db.execute(
                "INSERT INTO biz_users (username, email, password_hash, created_at) VALUES (?,?,?,?)",
                [r[1], r[2], r[3], r[4]],
            )
        uname_to_pk = dict(db.fetchall("SELECT username, pk_user FROM biz_users"))
    else:
        uname_to_pk = dict(db.fetchall("SELECT username, pk_user FROM biz_users"))

    # 先删旧 fk_users 相关索引，避免列改名后索引失效
    biz_index_sqls = [x for x in INDEXES if "biz_" in x]
    for sql in biz_index_sqls:
        m = _re.search(r"CREATE INDEX IF NOT EXISTS (\w+)", sql)
        if m:
            try:
                db.execute(f"DROP INDEX IF EXISTS {m.group(1)}")
            except Exception:
                pass

    biz_tables = [r[0] for r in db.fetchall(
        "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'biz_%'"
    )]
    for table in biz_tables:
        if table == "biz_users":
            continue
        tc = {r[0] for r in db.fetchall(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]
        )}
        if "fk_users" in tc:
            print(f"[Migration] {table}: fk_users(UUID) -> fk_user(BIGINT)")
            db.execute(f"ALTER TABLE {table} RENAME COLUMN fk_users TO _fk_old")
            db.execute(f"ALTER TABLE {table} ADD COLUMN fk_user BIGINT")
            for (old_uuid,) in db.fetchall(f"SELECT DISTINCT _fk_old FROM {table}"):
                uname = uuid_to_uname.get(str(old_uuid))
                new_pk = uname_to_pk.get(uname) if uname else None
                db.execute(f"UPDATE {table} SET fk_user = ? WHERE _fk_old = ?", [new_pk, old_uuid])
            db.execute(f"DELETE FROM {table} WHERE fk_user IS NULL")
            db.execute(f"ALTER TABLE {table} DROP COLUMN _fk_old")
        elif "user_id" in tc:
            print(f"[Migration] {table}: user_id(username) -> fk_user(BIGINT)")
            db.execute(f"ALTER TABLE {table} RENAME COLUMN user_id TO _fk_old")
            db.execute(f"ALTER TABLE {table} ADD COLUMN fk_user BIGINT")
            for (uname,) in db.fetchall(f"SELECT DISTINCT _fk_old FROM {table}"):
                new_pk = uname_to_pk.get(uname)
                db.execute(f"UPDATE {table} SET fk_user = ? WHERE _fk_old = ?", [new_pk, uname])
            db.execute(f"DELETE FROM {table} WHERE fk_user IS NULL")
            db.execute(f"ALTER TABLE {table} DROP COLUMN _fk_old")

    # 重建 biz_ 索引（现指向 fk_user）
    for sql in biz_index_sqls:
        try:
            db.execute(sql)
        except Exception as e:
            print(f"  [WARN] index recreate skipped: {e}")
    print("[Migration] pk_user / fk_user 迁移完成")


# ============================================================
# 用户安全列迁移（2026-09-18）
# - biz_users 增加 must_change_password（强制改密）/ token_version（令牌失效版本号）
# 幂等：列已存在则跳过。
# ============================================================

def migrate_user_security_columns(db: Database) -> None:
    """为 biz_users 增加安全相关列（幂等）：must_change_password / token_version。"""
    cols = {r[0] for r in db.fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'biz_users'"
    )}
    if "must_change_password" not in cols:
        db.execute(
            "ALTER TABLE biz_users ADD COLUMN must_change_password BOOLEAN DEFAULT FALSE"
        )
        print("[Migration] biz_users: added must_change_password")
    if "token_version" not in cols:
        db.execute(
            "ALTER TABLE biz_users ADD COLUMN token_version INTEGER DEFAULT 0"
        )
        print("[Migration] biz_users: added token_version")
    if "must_change_password" in cols and "token_version" in cols:
        print("[Migration] biz_users 安全列已就绪")


def repair_sw_sector_table(db: Database) -> dict:
    """修复 base_sw_sector_daily 表存储损坏（2026-10-15 线上事故）。

    事故形态：该表磁盘块损坏，任何写入（INSERT / UPSERT / FORCE CHECKPOINT）
    都触发 duckdb native 段错误 → backend 每 1-2 分钟崩溃重启 →
    宏观看板整页 502。经**生产库副本隔离实验**确诊：同库其他表写入与
    checkpoint 均正常，仅此表崩溃；DROP 该表后 checkpoint 恢复。

    触发方式：env ``REPAIR_SW_SECTOR_TABLE=1``（一次性，修复后应移除）。
    方案（数据无损）：CTAS 备份 → DROP → 按 schema.py 原 DDL 重建 → 灌回 → 删备份。
    读路径全程无害（已实证）；备份/灌回写入走新块，安全。
    """
    bak = "base_sw_sector_daily_repair_bak"
    try:
        db.execute(f"DROP TABLE IF EXISTS {bak}")
        db.execute(f"CREATE TABLE {bak} AS SELECT * FROM base_sw_sector_daily")
        n_bak = db.fetchone(f"SELECT count(*) FROM {bak}")[0]

        db.execute("DROP TABLE base_sw_sector_daily")

        # 按 schema.py 原样重建（表 DDL + 关联索引），避免与 schema 漂移
        ddl = next(t for t in TABLES if "base_sw_sector_daily" in t)
        db.execute(ddl)
        for idx in INDEXES:
            if "base_sw_sector_daily" in idx:
                db.execute(idx)

        # 灌回（PK 列走 DEFAULT nextval，不显式插入）
        db.execute(
            "INSERT INTO base_sw_sector_daily "
            "(sector_code, sector_name, trade_date, price, prev_close, change_pct, "
            " pe, ttm_pe, pb, dividend_yield, count) "
            f"SELECT sector_code, sector_name, trade_date, price, prev_close, change_pct, "
            f" pe, ttm_pe, pb, dividend_yield, count FROM {bak}"
        )
        n_new = db.fetchone("SELECT count(*) FROM base_sw_sector_daily")[0]
        db.execute(f"DROP TABLE {bak}")

        # ⚠️ 不要在此处 FORCE CHECKPOINT（2026-10-15 实测）：生产库 WAL 含崩溃循环
        # 期间写入的残留条目，checkpoint 合并时 duckdb native 空转（99% CPU 无进展，
        # 非报错而是纯 hang，try/except 抓不到）。DROP/INSERT 均为 autocommit 已落 WAL，
        # 数据安全性不依赖 checkpoint；WAL  consolidation 由 duckdb 自动 checkpoint 负责。
        print(f"[RepairSW] base_sw_sector_daily 已重建：备份 {n_bak} 行 → 恢复 {n_new} 行")
        return {"ok": n_new == n_bak, "backup_rows": n_bak, "restored_rows": n_new}
    except Exception as e:  # noqa: BLE001
        print(f"[RepairSW] 修复失败: {type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


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
