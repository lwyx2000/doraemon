"""SQLite connection manager for QuantTerminal Pro — business / transaction (biz_*) tables.

Rationale (2026-10-08): biz_* 表（用户 / 持仓 / 预警 / 配置 / 任务注册表等）是 OLTP 式
高频小事务状态，SQLite（ACID、WAL 读写并发）比列存 OLAP 的 DuckDB 更合适，且可与
base_* 分析数据完全解耦、互不抢锁。详见 database/init_sqlite.py 的迁移说明。

API 刻意与 database.connection.Database 对齐（execute / fetchall / fetchone /
executemany / conn / close / table_exists / list_tables / table_row_count / db_path），
降低 service 层改动成本。

并发模型：单「写连接」+ RLock 串行写；每线程一个「只读连接」。WAL 模式下读不阻塞写、
写不阻塞读。sqlite3 连接设 check_same_thread=False 以便跨线程复用写连接。
"""

import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from core.config import BIZ_DB_PATH as _CONFIGURED_BIZ_DB_PATH


DEFAULT_BIZ_DB_PATH = Path(_CONFIGURED_BIZ_DB_PATH)
_thread_local = threading.local()


class BizDatabase:
    """SQLite database connection wrapper: one write connection + per-thread read connections."""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_BIZ_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_conn: Optional[sqlite3.Connection] = None
        self._write_lock = threading.RLock()
        self._read_registry_lock = threading.Lock()
        self._read_conns: list[sqlite3.Connection] = []
        self._connect_write()
        # WAL：读不阻塞写、写不阻塞读；busy_timeout 避免并发写偶发 SQLITE_BUSY；
        # 外键关闭（业务完整性在应用层保证，与 DuckDB 时代一致）。
        self._write_conn.execute("PRAGMA journal_mode=WAL")
        self._write_conn.execute("PRAGMA busy_timeout=5000")
        self._write_conn.execute("PRAGMA foreign_keys=OFF")

    def _connect_write(self) -> None:
        self._write_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)

    def _get_read_conn(self) -> sqlite3.Connection:
        conn = getattr(_thread_local, "biz_read_conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            with self._read_registry_lock:
                self._read_conns.append(conn)
            _thread_local.biz_read_conn = conn
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        """兼容旧调用：返回写连接。新代码应优先使用 fetch*/execute。"""
        if self._write_conn is None:
            self._connect_write()
        return self._write_conn  # type: ignore

    def execute(self, sql: str, params: Optional[list | tuple | dict] = None) -> sqlite3.Cursor:
        """Execute a write/DDL statement. 走写连接并在 RLock 内 commit。"""
        with self._write_lock:
            cur = self._write_conn.execute(sql, params) if params else self._write_conn.execute(sql)  # type: ignore
            self._write_conn.commit()  # type: ignore
            return cur

    def executemany(self, sql: str, params_seq: list[list | tuple]) -> sqlite3.Cursor:
        with self._write_lock:
            cur = self._write_conn.executemany(sql, params_seq)  # type: ignore
            self._write_conn.commit()  # type: ignore
            return cur

    def fetchall(self, sql: str, params: Optional[list | tuple | dict] = None) -> list[tuple]:
        conn = self._get_read_conn()
        cur = conn.execute(sql, params) if params else conn.execute(sql)
        return cur.fetchall()

    def fetchone(self, sql: str, params: Optional[list | tuple | dict] = None) -> Optional[tuple]:
        conn = self._get_read_conn()
        cur = conn.execute(sql, params) if params else conn.execute(sql)
        return cur.fetchone()

    def close(self) -> None:
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
        _thread_local.biz_read_conn = None

    def table_exists(self, table_name: str) -> bool:
        result = self.fetchone(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name = ?",
            [table_name],
        )
        return result is not None and result[0] > 0

    def list_tables(self) -> list[str]:
        rows = self.fetchall("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [row[0] for row in rows]

    def table_row_count(self, table_name: str) -> int:
        try:
            result = self.fetchone(f"SELECT count(*) FROM {table_name}")
            return result[0] if result else 0
        except Exception:
            return 0


_db_instance: Optional[BizDatabase] = None


def get_biz_db(db_path: Optional[str | Path] = None) -> BizDatabase:
    """Get the business (SQLite) database instance (module-level singleton)."""
    global _db_instance
    if _db_instance is None or db_path is not None:
        _db_instance = BizDatabase(db_path)
    return _db_instance


def close_biz_db() -> None:
    """Close the module-level business database connection."""
    global _db_instance
    if _db_instance is not None:
        _db_instance.close()
        _db_instance = None
