"""DuckDB connection manager for QuantTerminal Pro.

Usage:
    from database.connection import get_db

    db = get_db()
    rows = db.fetchall("SELECT * FROM base_indices")
    db.close()

并发模型（2026-09-25 改造）：
- 单「写连接」：所有写入 / DDL / 执行（execute / executemany）都走它，并被一把 RLock
  串行化，避免多线程并发写同一连接触发 GIL 死锁（见历史定位）。
- 线程级「只读连接」：每个工作线程首次读时懒创建一个 read_only 连接并绑定到该线程。
  DuckDB 支持「多连接并发读 + 单写」，线程级隔离确保同一只读连接不被多线程并发使用，
  因此读路径既不需要 RLock，也不会 reintroduce GIL 死锁，且读吞吐不再被写锁串行压成单线程。
- 读连接创建失败（如文件尚未就绪）→ 自动退回写连接（仍在 RLock 保护下），保证不崩。
"""

import duckdb
import threading
from pathlib import Path
from typing import Any, Optional

from core.config import DB_PATH as _CONFIGURED_DB_PATH


# Default database file path: 优先使用 core.config.DB_PATH（支持 DB_PATH 环境变量覆盖），
# 否则回退到 backend/database/quantterminal.duckdb
DEFAULT_DB_PATH = Path(_CONFIGURED_DB_PATH)

# 线程级存储：每个工作线程专属的只读连接
_thread_local = threading.local()


class Database:
    """DuckDB database connection wrapper with a write connection + per-thread read connections."""

    def __init__(self, db_path: Optional[str | Path] = None, read_pool_size: int = 8):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        # 写连接：写入 / DDL / execute / executemany 的唯一入口
        self._write_conn: Optional[duckdb.DuckDBPyConnection] = None
        # 写串行锁（重入，避免并发写同一连接导致 GIL 死锁）
        self._write_lock = threading.RLock()
        # 读写连接注册表锁 + 所有已创建的只读连接（用于关闭 / 兜底）
        self._read_registry_lock = threading.Lock()
        self._read_conns: list[duckdb.DuckDBPyConnection] = []
        self._read_pool_size = max(1, read_pool_size)
        self._connect_write()

    def _connect_write(self) -> None:
        """Establish the write connection, creating the file if it doesn't exist."""
        self._write_conn = duckdb.connect(str(self.db_path))

    def _get_read_conn(self) -> duckdb.DuckDBPyConnection:
        """Return the current thread's dedicated read connection.

        线程级隔离：每个线程首次读时创建一个普通连接并绑定到该线程，后续复用。
        使用普通（非 read_only）连接 + DuckDB 的 MVCC 快照隔离：多连接并发读安全，
        且读与单写连接并发时读到的是已提交快照（不会出现 read_only 模式下
        「并发写导致读返回空 / query cancelled」的一致性缺陷）。

        注意：读连接只用于 SELECT；写统一走写连接 + 写锁，二者连接隔离，互不冲突。
        """
        conn = getattr(_thread_local, "read_conn", None)
        if conn is None:
            try:
                conn = duckdb.connect(str(self.db_path))
            except Exception:
                # 读连接创建失败（文件未就绪等）→ 退回写连接（仍在写锁保护下）
                return self._write_conn  # type: ignore
            with self._read_registry_lock:
                self._read_conns.append(conn)
            _thread_local.read_conn = conn
        return conn

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """兼容旧调用：返回写连接。新代码应优先使用 fetch*/execute。"""
        if self._write_conn is None:
            self._connect_write()
        return self._write_conn  # type: ignore

    def execute(self, sql: str, params: Optional[list | dict] = None) -> duckdb.DuckDBPyConnection:
        """Execute a SQL statement (写入 / DDL)。走写连接，串行化避免 GIL 死锁。"""
        with self._write_lock:
            if params:
                return self._write_conn.execute(sql, params)  # type: ignore
            return self._write_conn.execute(sql)  # type: ignore

    def executemany(self, sql: str, params_seq: list[list | dict]) -> duckdb.DuckDBPyConnection:
        """Execute the same SQL against a sequence of parameter sets (写入)。走写连接，一次持锁批量写。"""
        with self._write_lock:
            return self._write_conn.executemany(sql, params_seq)  # type: ignore

    def fetchall(self, sql: str, params: Optional[list | dict] = None) -> list[tuple]:
        """Execute query and return all rows. 走当前线程只读连接（无锁，并发读）。"""
        conn = self._get_read_conn()
        if params:
            return conn.execute(sql, params).fetchall()
        return conn.execute(sql).fetchall()

    def fetchone(self, sql: str, params: Optional[list | dict] = None) -> Optional[tuple]:
        """Execute query and return a single row. 走当前线程只读连接（无锁，并发读）。"""
        conn = self._get_read_conn()
        if params:
            return conn.execute(sql, params).fetchone()
        return conn.execute(sql).fetchone()

    def fetch_df(self, sql: str, params: Optional[list | dict] = None):
        """Execute query and return results as a pandas DataFrame. 走当前线程只读连接。"""
        conn = self._get_read_conn()
        if params:
            return conn.execute(sql, params).df()
        return conn.execute(sql).df()

    def close(self) -> None:
        """Close the write connection and all read connections."""
        with self._write_lock:
            if self._write_conn:
                self._write_conn.close()
                self._write_conn = None
        with self._read_registry_lock:
            for c in self._read_conns:
                try:
                    c.close()
                except Exception:
                    pass
            self._read_conns = []
        _thread_local.read_conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        result = self.fetchone(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [table_name],
        )
        return result is not None and result[0] > 0

    def list_tables(self) -> list[str]:
        """List all tables in the database."""
        rows = self.fetchall(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        )
        return [row[0] for row in rows]

    def table_row_count(self, table_name: str) -> int:
        """Get the row count of a table."""
        result = self.fetchone(f"SELECT count(*) FROM {table_name}")
        return result[0] if result else 0


# Module-level singleton
_db_instance: Optional[Database] = None


def get_db(db_path: Optional[str | Path] = None) -> Database:
    """Get a Database instance.

    Args:
        db_path: Path to the .duckdb file. Defaults to backend/database/quantterminal.duckdb.

    Returns:
        Database connection wrapper.
    """
    global _db_instance
    if _db_instance is None or db_path is not None:
        _db_instance = Database(db_path)
    return _db_instance


def close_db() -> None:
    """Close the module-level database connection."""
    global _db_instance
    if _db_instance is not None:
        _db_instance.close()
        _db_instance = None
