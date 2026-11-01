"""Business (biz_*) SQLite schema + idempotent data migration from DuckDB.

Why SQLite for biz_*: biz_* 表是 OLTP 式高频小事务（用户 / 持仓 / 预警 / 配置 / 任务注册表），
SQLite（ACID、WAL 读写并发）比列存 OLAP 的 DuckDB 更合适；且与 base_* 行情/估值分析数据
完全分离，互不抢锁。DuckDB 只保留 base_*。

迁移策略（关键，保证线上数据安全）：
- 启动期调用 init_biz_database()：先用静态 DDL 建好全部 biz_* + job_registry 表（IF NOT EXISTS），
  再从「同一进程内已持锁的 DuckDB 连接」反射线上 biz_* 表的真实列与数据，按列名对齐拷进 SQLite。
- 反射会兜底任何静态 DDL 漏列的字段（ALTER ADD COLUMN），并按 DuckDB 真实列拷贝，
  因此不受运行时 ALTER 加列（如 biz_holdings 的 is_closed/close_price 等软删除列）影响。
- 每个表只在 SQLite 为空时才拷贝（幂等）；重启后 SQLite 文件在 /data 持久卷上保留，不再重复拷。
- 静态 DDL 同时保障「全新部署（DuckDB 也无 biz_ 数据）」时表依然存在。

类型映射：INT/BIGINT→INTEGER；DECIMAL/DOUBLE/FLOAT→REAL；其余（VARCHAR/UUID/JSON/
TIMESTAMP/DATE/BOOLEAN）→TEXT。值转换：uuid→str、datetime/date→isoformat、(dict/list)→json.dumps。
"""

import json
import uuid as _uuid
from datetime import datetime, date
from typing import Any

from database.sqlite_connection import get_biz_db
from database.sqlite_connection import BizDatabase


# ============================================================
# Static SQLite DDL — all biz_* tables + job_registry
# （类型用 SQLite 亲和类型；pk 用 TEXT 或 INTEGER；app 写入时显式自带 pk）
# ============================================================

BIZ_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS biz_users (
        pk_user          INTEGER PRIMARY KEY,
        username         TEXT NOT NULL,
        email            TEXT,
        password_hash    TEXT NOT NULL,
        created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
        must_change_password INTEGER DEFAULT 0,
        token_version    INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_favorites (
        pk_favorites     TEXT PRIMARY KEY,
        fk_user          INTEGER NOT NULL,
        code             TEXT NOT NULL,
        name             TEXT NOT NULL,
        type             TEXT NOT NULL,
        note             TEXT,
        added_at         TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_portfolios (
        pk_portfolios    TEXT PRIMARY KEY,
        fk_user          INTEGER NOT NULL,
        name             TEXT NOT NULL,
        created_at       TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_portfolio_items (
        pk_portfolio_items TEXT PRIMARY KEY,
        fk_portfolios     TEXT NOT NULL,
        code              TEXT NOT NULL,
        name              TEXT NOT NULL,
        type              TEXT NOT NULL,
        quantity          REAL NOT NULL,
        cost_price        REAL NOT NULL,
        added_at          TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_holdings (
        id               TEXT PRIMARY KEY,
        fk_user          INTEGER NOT NULL,
        code             TEXT NOT NULL,
        name             TEXT NOT NULL,
        type             TEXT NOT NULL,
        broker           TEXT DEFAULT '',
        account          TEXT DEFAULT '',
        quantity         REAL NOT NULL,
        cost_price       REAL NOT NULL,
        manual_price     REAL,
        stop_loss_pct    REAL,
        take_profit_pct  REAL,
        open_date        TEXT,
        currency         TEXT DEFAULT 'CNY',
        created_at       TEXT,
        updated_at       TEXT,
        fair_value       REAL,
        grid_lower       REAL,
        grid_upper       REAL,
        grid_step        REAL,
        is_closed        INTEGER DEFAULT 0,
        closed_at        TEXT,
        realized_pnl     REAL,
        close_price      REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_terminals (
        id               TEXT PRIMARY KEY,
        fk_user          INTEGER NOT NULL,
        name             TEXT NOT NULL,
        remark           TEXT DEFAULT '',
        created_at       TEXT,
        updated_at       TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_brokers (
        id               TEXT PRIMARY KEY,
        fk_terminal      TEXT NOT NULL,
        name             TEXT NOT NULL,
        account          TEXT NOT NULL,
        remark           TEXT DEFAULT '',
        created_at       TEXT,
        updated_at       TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_account_names (
        id               TEXT PRIMARY KEY,
        fk_user          INTEGER NOT NULL,
        name             TEXT NOT NULL,
        created_at       TEXT,
        updated_at       TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_holding_snapshots (
        id                 TEXT PRIMARY KEY,
        fk_user            INTEGER NOT NULL,
        snap_date          TEXT NOT NULL,
        total_market_value REAL,
        total_cost         REAL,
        total_pnl          REAL,
        total_pnl_pct      REAL,
        daily_pnl          REAL,
        holding_count      INTEGER,
        priced_count       INTEGER,
        created_at         TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_strategies (
        id            TEXT PRIMARY KEY,
        fk_user       INTEGER NOT NULL,
        name          TEXT NOT NULL,
        target_asset  TEXT NOT NULL,
        rules         TEXT,
        sort_by       TEXT,
        sort_order    TEXT DEFAULT 'asc',
        limit_count   INTEGER,
        active        INTEGER DEFAULT 1,
        ai_tracking   INTEGER DEFAULT 0,
        created_at    TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_strategy_rules (
        pk_strategy_rules TEXT PRIMARY KEY,
        fk_strategies     TEXT NOT NULL,
        field             TEXT NOT NULL,
        operator          TEXT NOT NULL,
        value             TEXT NOT NULL,
        logic             TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_alert_rules (
        pk_alert_rules   TEXT PRIMARY KEY,
        fk_user          INTEGER NOT NULL,
        name             TEXT NOT NULL,
        type             TEXT NOT NULL,
        target           TEXT NOT NULL,
        condition        TEXT NOT NULL,
        value            REAL NOT NULL,
        channels         TEXT NOT NULL,
        active           INTEGER DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_alert_events (
        pk_alert_events  INTEGER PRIMARY KEY,
        fk_alert_rules   TEXT NOT NULL,
        triggered_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        target_code      TEXT,
        target_name      TEXT,
        actual_value     REAL,
        message          TEXT,
        is_read          INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_ai_reports (
        pk_ai_reports    TEXT PRIMARY KEY,
        fk_user          INTEGER NOT NULL,
        report_date      TEXT NOT NULL,
        macro_assessment TEXT,
        strategy_matches TEXT,
        arbitrage_alerts TEXT,
        created_at       TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_ai_configs (
        pk_ai_configs    INTEGER PRIMARY KEY,
        fk_user          INTEGER NOT NULL,
        provider         TEXT NOT NULL,
        api_key          TEXT,
        endpoint         TEXT,
        temperature      REAL DEFAULT 0.70,
        cron_expression  TEXT,
        enabled          INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_config (
        key         TEXT NOT NULL PRIMARY KEY,
        value_json  TEXT,
        updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_winrate_scan (
        id           TEXT PRIMARY KEY,
        scan_date    TEXT,
        strategy_id  TEXT,
        params_json  TEXT,
        result_json  TEXT,
        created_at   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_library_subscriptions (
        id           TEXT PRIMARY KEY,
        fk_user      INTEGER,
        library_id   TEXT,
        params_json  TEXT,
        created_at   TEXT,
        updated_at   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_library_snapshots (
        id           TEXT PRIMARY KEY,
        fk_user      INTEGER,
        library_id   TEXT,
        snap_date    TEXT,
        payload_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS biz_signal_subscriptions (
        id           TEXT PRIMARY KEY,
        fk_user      INTEGER,
        symbol       TEXT,
        name         TEXT,
        strategy_id  TEXT,
        params_json  TEXT,
        created_at   TEXT,
        updated_at   TEXT
    )
    """,
    # 用户导入的知识库文档：与 backend/knowledge/ 内置文档双源合并，
    # 落 SQLite 持久卷（容器重建不丢），AI 解读/问答按启用态挂载。
    """
    CREATE TABLE IF NOT EXISTS biz_knowledge_docs (
        id          TEXT PRIMARY KEY,
        fk_user     INTEGER,
        title       TEXT NOT NULL,
        content     TEXT NOT NULL,
        tags        TEXT,
        enabled     INTEGER DEFAULT 1,
        char_count  INTEGER DEFAULT 0,
        created_at  TEXT,
        updated_at  TEXT
    )
    """,
    # 任务注册表：持久化后台任务执行状态，重启后保留（原内存态重启清零的根因）。
    """
    CREATE TABLE IF NOT EXISTS job_registry (
        job_id        TEXT PRIMARY KEY,
        name          TEXT NOT NULL,
        schedule      TEXT DEFAULT '',
        job_type      TEXT DEFAULT 'unknown',
        enabled       INTEGER DEFAULT 1,
        triggerable   INTEGER DEFAULT 0,
        last_status   TEXT DEFAULT 'never',
        last_run_at   TEXT,
        last_duration_ms REAL,
        last_error    TEXT,
        next_run_at   TEXT,
        run_count     INTEGER DEFAULT 0,
        fail_count    INTEGER DEFAULT 0,
        updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

BIZ_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_biz_users_username ON biz_users(username)",
    "CREATE INDEX IF NOT EXISTS idx_biz_fav_users ON biz_favorites(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_biz_pi_portfolios ON biz_portfolio_items(fk_portfolios)",
    "CREATE INDEX IF NOT EXISTS idx_biz_strat_users ON biz_strategies(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_biz_holdings_users ON biz_holdings(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_biz_terminal_users ON biz_terminals(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_biz_brokers_terminal ON biz_brokers(fk_terminal)",
    "CREATE INDEX IF NOT EXISTS idx_biz_acctname_users ON biz_account_names(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_biz_snap_users ON biz_holding_snapshots(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_biz_ar_users ON biz_alert_rules(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_biz_ae_rule_time ON biz_alert_events(fk_alert_rules, triggered_at)",
    "CREATE INDEX IF NOT EXISTS idx_biz_air_users_date ON biz_ai_reports(fk_user, report_date)",
    "CREATE INDEX IF NOT EXISTS idx_biz_aiconfig_users ON biz_ai_configs(fk_user)",
]


def _map_type(duck_type: str) -> str:
    dt = duck_type.upper()
    if "INT" in dt or dt in ("BIGINT", "SMALLINT", "TINYINT"):
        return "INTEGER"
    if "DECIMAL" in dt or "DOUBLE" in dt or "FLOAT" in dt or "REAL" in dt:
        return "REAL"
    return "TEXT"


def _conv_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, _uuid.UUID):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def _conv_row(row: tuple) -> list:
    return [_conv_value(x) for x in row]


def _ensure_biz_tables(biz: BizDatabase) -> None:
    for sql in BIZ_TABLES:
        biz.execute(sql)
    for sql in BIZ_INDEXES:
        try:
            biz.execute(sql)
        except Exception as e:  # noqa: BLE001
            print(f"  [biz-sqlite] index skipped: {e}")


def _migrate_biz_data(duck, biz: BizDatabase) -> None:
    """从「同一进程内已持锁的 DuckDB 连接」反射 biz_* 表，按列名对齐拷入 SQLite（幂等）。"""
    try:
        tables = [
            r[0]
            for r in duck.fetchall(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE 'biz_%' ORDER BY table_name"
            )
        ]
    except Exception as e:  # noqa: BLE001
        print(f"  [biz-sqlite] skip DuckDB reflection ({e})")
        return

    # 旧 biz_broker_accounts 已迁移为 biz_terminals + biz_brokers，
    # 不再从 DuckDB 反射回写（避免旧表被重新建出）。
    SKIP_TABLES = {"biz_broker_accounts", "biz_broker_accounts_legacy"}
    for t in tables:
        if t in SKIP_TABLES:
            continue
        cols = duck.fetchall(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [t],
        )
        if not cols:
            continue
        col_names = [c[0] for c in cols]
        quoted = ", ".join(f'"{c}"' for c in col_names)

        # 若 SQLite 尚无该表，按反射列建表（兜底静态 DDL 漏列）
        if not biz.table_exists(t):
            col_defs = ", ".join(f'"{cn}" {_map_type(ct)}' for cn, ct in cols)
            biz.execute(f'CREATE TABLE IF NOT EXISTS "{t}" ({col_defs})')
        else:
            existing = {r[1] for r in biz.fetchall(f'PRAGMA table_info("{t}")')}
            for cn, ct in cols:
                if cn not in existing:
                    biz.execute(
                        f'ALTER TABLE "{t}" ADD COLUMN "{cn}" {_map_type(ct)}'
                    )

        # 仅当 SQLite 为空时才拷（重启后已有数据则跳过）
        if biz.table_row_count(t) == 0:
            try:
                rows = duck.fetchall(f'SELECT {quoted} FROM "{t}"')
            except Exception as e:  # noqa: BLE001
                print(f"  [biz-sqlite] read {t} failed: {e}")
                continue
            if rows:
                converted = [_conv_row(r) for r in rows]
                placeholders = ",".join("?" * len(col_names))
                biz.executemany(
                    f'INSERT INTO "{t}" ({quoted}) VALUES ({placeholders})',
                    converted,
                )
                print(f"  [biz-sqlite] migrated {t}: {len(rows)} rows")
            else:
                print(f"  [biz-sqlite] {t}: empty in DuckDB, nothing to copy")
        else:
            print(f"  [biz-sqlite] {t}: already populated, skip copy")


def _migrate_broker_accounts_to_terminals(biz: BizDatabase) -> None:
    """幂等：把旧 biz_broker_accounts（broker/account/code）迁移为 biz_terminals + biz_brokers。

    - 旧 broker（券商名）→ biz_brokers.name；
    - 旧 code（BRK-xxxx，外部上传接口历史用的券商标识）→ biz_brokers.account（现由客户端自传）；
    - 旧 account（子账户）→ biz_brokers.remark（旧模型没有终端概念，每用户建一个默认终端）；
    - 迁移完成后把旧表改名 biz_broker_accounts_legacy 留档（不再被任何代码读取）。
    仅在「旧表存在 且 biz_terminals 为空」时执行，保证重启幂等。
    """
    if not biz.table_exists("biz_broker_accounts"):
        return
    if biz.table_row_count("biz_terminals") > 0:
        # 已迁移过（或新部署已有终端），仅做兜底改名，避免旧表残留被误读
        if biz.table_exists("biz_broker_accounts"):
            biz.execute("ALTER TABLE biz_broker_accounts RENAME TO biz_broker_accounts_legacy")
        return

    print("[biz-sqlite] migrating biz_broker_accounts -> biz_terminals + biz_brokers")
    rows = biz.fetchall(
        "SELECT id, fk_user, broker, account, code, created_at, updated_at "
        "FROM biz_broker_accounts ORDER BY fk_user, created_at",
        [],
    )
    default_terminal_by_user: dict[str, str] = {}
    now = datetime.now().isoformat()

    def _ensure_default_terminal(fk_user: str) -> str:
        tid = default_terminal_by_user.get(fk_user)
        if tid:
            return tid
        tid = str(_uuid.uuid4())
        biz.execute(
            "INSERT INTO biz_terminals (id, fk_user, name, remark, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [tid, fk_user, "默认终端", "", now, now],
        )
        default_terminal_by_user[fk_user] = tid
        return tid

    for r in rows:
        (old_id, fk_user, broker, old_account, code, created_at, updated_at) = r
        fk_user = str(fk_user)
        terminal_id = _ensure_default_terminal(fk_user)
        # account = 旧 code（历史外部上传标识）；无 code 时用旧 account；再无则兜底用 broker
        new_account = (code or "").strip() or (old_account or "").strip() or (broker or "").strip()
        remark = (old_account or "").strip() if (code or "").strip() else ""
        biz.execute(
            "INSERT INTO biz_brokers (id, fk_terminal, name, account, remark, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [str(_uuid.uuid4()), terminal_id, broker or "", new_account, remark, created_at or now, updated_at or now],
        )

    # 旧表改名留档
    biz.execute("ALTER TABLE biz_broker_accounts RENAME TO biz_broker_accounts_legacy")
    print(f"[biz-sqlite] broker migration done: {len(rows)} brokers under {len(default_terminal_by_user)} terminals")


def init_biz_database() -> None:
    """幂等初始化业务 SQLite 库：建表 + 券商迁移 + 从 DuckDB 拷贝现有业务数据。"""
    biz = get_biz_db()
    print(f"[biz-sqlite] initializing at {biz.db_path}")
    _ensure_biz_tables(biz)
    _migrate_broker_accounts_to_terminals(biz)
    # 从已持锁的 DuckDB 连接读（与 base_* 同一连接，绝不产生第二把锁）
    try:
        from database.connection import get_db

        duck = get_db()
        _migrate_biz_data(duck, biz)
    except Exception as e:  # noqa: BLE001
        print(f"[biz-sqlite] data migration skipped: {e}")
    print("[biz-sqlite] initialization complete")
