"""DuckDB connection manager for QuantTerminal Pro.

Usage:
    from database.connection import get_db

    db = get_db()
    rows = db.fetchall("SELECT * FROM base_indices")
    db.close()
"""

import duckdb
from pathlib import Path
from typing import Any, Optional

from core.config import DB_PATH as _CONFIGURED_DB_PATH


# Default database file path: 优先使用 core.config.DB_PATH（支持 DB_PATH 环境变量覆盖），
# 否则回退到 backend/database/quantterminal.duckdb
DEFAULT_DB_PATH = Path(_CONFIGURED_DB_PATH)


class Database:
    """DuckDB database connection wrapper.

    DuckDB connections are thread-safe for concurrent reads.
    For write operations, use a single connection or manage locks externally.
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        self._connect()

    def _connect(self) -> None:
        """Establish database connection, creating the file if it doesn't exist."""
        self._conn = duckdb.connect(str(self.db_path))

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._connect()
        return self._conn  # type: ignore

    def execute(self, sql: str, params: Optional[list | dict] = None) -> duckdb.DuckDBPyConnection:
        """Execute a SQL statement with optional parameters."""
        if params:
            return self.conn.execute(sql, params)
        return self.conn.execute(sql)

    def fetchall(self, sql: str, params: Optional[list | dict] = None) -> list[tuple]:
        """Execute query and return all rows."""
        result = self.execute(sql, params)
        return result.fetchall()

    def fetchone(self, sql: str, params: Optional[list | dict] = None) -> Optional[tuple]:
        """Execute query and return a single row."""
        result = self.execute(sql, params)
        return result.fetchone()

    def fetch_df(self, sql: str, params: Optional[list | dict] = None):
        """Execute query and return results as a pandas DataFrame."""
        result = self.execute(sql, params)
        return result.df()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

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
