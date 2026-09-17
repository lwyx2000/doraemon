"""DuckDB schema definitions for QuantTerminal Pro.

Naming conventions:
  - Data source tables:  base_  prefix (market data from external providers)
  - Business tables:     biz_   prefix (user data, strategies, alerts, AI)
  - Primary key column:  pk_  + table name without prefix
  - Foreign key column:  fk_  + referenced table name without prefix
  - No foreign key constraints (integrity managed at application layer)

Table count: 15 data source tables + 10 business tables = 25 total.
"""

# ============================================================
# Sequences (for auto-increment primary keys)
# ============================================================

SEQUENCES = [
    "CREATE SEQUENCE IF NOT EXISTS seq_base_indices START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_index_valuations START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_kline_data START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_funds START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_fund_daily_quotes START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_etf_funds START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_etf_daily_quotes START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_stocks START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_convertible_bonds START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_cb_daily_quotes START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_stock_daily_quotes START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_reits START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_reit_daily_quotes START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_macro_indicators START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_macro_daily START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_biz_alert_events START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_biz_ai_configs START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_user START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_base_sw_sector_daily START 1",
]

# ============================================================
# Table Definitions
# ============================================================

TABLES = [
    # ================================================
    # Data Source Tables (base_)
    # ================================================

    # 1. 指数基本信息 — 每个指数一条记录，不随时间变化
    """
    CREATE TABLE IF NOT EXISTS base_indices (
        pk_indices        INTEGER DEFAULT nextval('seq_base_indices') PRIMARY KEY,
        code              VARCHAR(20) NOT NULL,
        name              VARCHAR(50) NOT NULL,
        market            VARCHAR(10) NOT NULL,
        category          VARCHAR(20),
        created_at        TIMESTAMP DEFAULT now()
    )
    """,

    # 2. 指数每日估值 — 每个交易日写入估值快照，用于 PE/PB 百分位计算
    """
    CREATE TABLE IF NOT EXISTS base_index_valuations (
        pk_index_valuations   BIGINT DEFAULT nextval('seq_base_index_valuations') PRIMARY KEY,
        fk_indices            INTEGER NOT NULL,
        trade_date            DATE NOT NULL,
        level                 DECIMAL(12,2) NOT NULL,
        change_pct            DECIMAL(6,2),
        pe                    DECIMAL(8,2),
        pb                    DECIMAL(8,2),
        pe_percentile         DECIMAL(5,1),
        pb_percentile         DECIMAL(5,1),
        category              VARCHAR(20),
        change_3m_pct         DECIMAL(6,2),
        win_rate              DECIMAL(5,1)
    )
    """,

    # 3. K 线行情 — 指数和 ETF 的日 K 线数据，用于趋势分析、网格回测
    """
    CREATE TABLE IF NOT EXISTS base_kline_data (
        pk_kline_data     BIGINT DEFAULT nextval('seq_base_kline_data') PRIMARY KEY,
        code              VARCHAR(20) NOT NULL,
        trade_date        DATE NOT NULL,
        open              DECIMAL(12,4) NOT NULL,
        close             DECIMAL(12,4) NOT NULL,
        high              DECIMAL(12,4) NOT NULL,
        low               DECIMAL(12,4) NOT NULL,
        volume            BIGINT,
        source            VARCHAR(20)
    )
    """,

    # 4. 基金基本信息 — LOF/QDII/封闭基金元数据
    """
    CREATE TABLE IF NOT EXISTS base_funds (
        pk_funds          INTEGER DEFAULT nextval('seq_base_funds') PRIMARY KEY,
        code              VARCHAR(20) NOT NULL,
        name              VARCHAR(100) NOT NULL,
        type              VARCHAR(10) NOT NULL,
        credit_rating     VARCHAR(10),
        is_lof_convertible BOOLEAN DEFAULT FALSE,
        underlying_type   VARCHAR(30),
        maturity          DATE,
        created_at        TIMESTAMP DEFAULT now()
    )
    """,

    # 5. 基金每日行情 — 含折溢价、申购限额、套利收益等动态字段
    """
    CREATE TABLE IF NOT EXISTS base_fund_daily_quotes (
        pk_fund_daily_quotes    BIGINT DEFAULT nextval('seq_base_fund_daily_quotes') PRIMARY KEY,
        fk_funds                INTEGER NOT NULL,
        trade_date              DATE NOT NULL,
        price                   DECIMAL(10,4) NOT NULL,
        iopv                    DECIMAL(10,4) NOT NULL,
        nav                     DECIMAL(10,4),
        premium_pct             DECIMAL(6,2),
        premium_percentile      DECIMAL(5,1),
        net_arbitrage_yield     DECIMAL(6,2),
        volume                  BIGINT,
        subscribe_limit         VARCHAR(50),
        daily_volatility        DECIMAL(4,2),
        holding_days            SMALLINT,
        is_suspended            BOOLEAN DEFAULT FALSE,
        remaining_term          VARCHAR(30),
        annualized              DECIMAL(6,2),
        est_ytm                 DECIMAL(6,2)
    )
    """,

    # 6. ETF 基本信息
    """
    CREATE TABLE IF NOT EXISTS base_etf_funds (
        pk_etf_funds      INTEGER DEFAULT nextval('seq_base_etf_funds') PRIMARY KEY,
        code              VARCHAR(20) NOT NULL,
        name              VARCHAR(100) NOT NULL,
        category          VARCHAR(20) NOT NULL,
        sub_category      VARCHAR(30),
        created_at        TIMESTAMP DEFAULT now()
    )
    """,

    # 7. ETF 每日行情 — 含折溢价套利、网格交易、行业轮动、估值定投四大策略字段
    """
    CREATE TABLE IF NOT EXISTS base_etf_daily_quotes (
        pk_etf_daily_quotes     BIGINT DEFAULT nextval('seq_base_etf_daily_quotes') PRIMARY KEY,
        fk_etf_funds            INTEGER NOT NULL,
        trade_date              DATE NOT NULL,
        price                   DECIMAL(10,4) NOT NULL,
        iopv                    DECIMAL(10,4) NOT NULL,
        premium_pct             DECIMAL(6,2),
        volume                  BIGINT,
        premium_percentile      DECIMAL(5,1),
        net_arbitrage_yield     DECIMAL(6,2),
        subscribe_limit         VARCHAR(50),
        daily_volatility        DECIMAL(4,2),
        holding_days            SMALLINT,
        is_suspended            BOOLEAN DEFAULT FALSE,
        grid_low                DECIMAL(10,4),
        grid_high               DECIMAL(10,4),
        grid_step               DECIMAL(4,1),
        grid_yield_est          DECIMAL(6,2),
        momentum_score          SMALLINT,
        pe                      DECIMAL(8,2),
        pe_percentile           DECIMAL(5,1),
        val_category            VARCHAR(20),
        dividend_rate           DECIMAL(5,2)
    )
    """,

    # 8. 正股基本信息
    """
    CREATE TABLE IF NOT EXISTS base_stocks (
        pk_stocks         INTEGER DEFAULT nextval('seq_base_stocks') PRIMARY KEY,
        code              VARCHAR(10) NOT NULL,
        name              VARCHAR(50) NOT NULL,
        is_st_risk        BOOLEAN DEFAULT FALSE,
        altman_z_score    DECIMAL(5,2),
        pledge_rate       DECIMAL(5,2)
    )
    """,

    # 9. 可转债基本信息 — 含条款触发总天数等静态字段
    """
    CREATE TABLE IF NOT EXISTS base_convertible_bonds (
        pk_convertible_bonds      INTEGER DEFAULT nextval('seq_base_convertible_bonds') PRIMARY KEY,
        code                      VARCHAR(10) NOT NULL,
        name                      VARCHAR(50) NOT NULL,
        fk_stocks                 INTEGER,
        rating                    VARCHAR(10),
        remaining_years           DECIMAL(4,1),
        is_in_conversion_period   BOOLEAN DEFAULT FALSE,
        total_redemption_days     SMALLINT,
        total_putback_days        SMALLINT,
        total_revision_days       SMALLINT
    )
    """,

    # 10. 可转债每日行情 — 含价格、转股价值、溢价率、波动率、条款触发进度
    """
    CREATE TABLE IF NOT EXISTS base_cb_daily_quotes (
        pk_cb_daily_quotes        BIGINT DEFAULT nextval('seq_base_cb_daily_quotes') PRIMARY KEY,
        fk_convertible_bonds      INTEGER NOT NULL,
        trade_date                DATE NOT NULL,
        price                     DECIMAL(10,3) NOT NULL,
        change_pct                DECIMAL(6,2),
        conv_value                DECIMAL(10,2),
        premium_pct               DECIMAL(6,2),
        ytm                       DECIMAL(6,2),
        double_low_score          DECIMAL(8,2),
        iv                        DECIMAL(5,2),
        hv                        DECIMAL(5,2),
        tag                       VARCHAR(30),
        tag_type                  VARCHAR(20),
        redemption_days           SMALLINT,
        putback_days              SMALLINT,
        revision_days             SMALLINT,
        stock_limit_up            BOOLEAN DEFAULT FALSE,
        stock_suspended           BOOLEAN DEFAULT FALSE
    )
    """,

    # 11. 正股每日行情
    """
    CREATE TABLE IF NOT EXISTS base_stock_daily_quotes (
        pk_stock_daily_quotes     BIGINT DEFAULT nextval('seq_base_stock_daily_quotes') PRIMARY KEY,
        fk_stocks                 INTEGER NOT NULL,
        trade_date                DATE NOT NULL,
        price                     DECIMAL(10,3) NOT NULL,
        change_pct                DECIMAL(6,2)
    )
    """,

    # 12. REITs 基本信息
    """
    CREATE TABLE IF NOT EXISTS base_reits (
        pk_reits          INTEGER DEFAULT nextval('seq_base_reits') PRIMARY KEY,
        code              VARCHAR(10) NOT NULL,
        name              VARCHAR(100) NOT NULL,
        project_name      VARCHAR(100),
        asset_type        VARCHAR(30),
        created_at        TIMESTAMP DEFAULT now()
    )
    """,

    # 13. REITs 每日行情 — 含 NAV、分红率、IRR、出租率、DSCR、杠杆率
    """
    CREATE TABLE IF NOT EXISTS base_reit_daily_quotes (
        pk_reit_daily_quotes     BIGINT DEFAULT nextval('seq_base_reit_daily_quotes') PRIMARY KEY,
        fk_reits                 INTEGER NOT NULL,
        trade_date               DATE NOT NULL,
        market_price             DECIMAL(10,4) NOT NULL,
        nav                      DECIMAL(10,4),
        annual_distribution      DECIMAL(8,4),
        dividend_rate            DECIMAL(5,2),
        irr                      DECIMAL(5,2),
        occupancy_rate           DECIMAL(5,1),
        occupancy_trend          DECIMAL(5,1),
        dscr                     DECIMAL(4,2),
        leverage_ratio           DECIMAL(5,1),
        volume                   BIGINT
    )
    """,

    # 14. 宏观指标定义
    """
    CREATE TABLE IF NOT EXISTS base_macro_indicators (
        pk_macro_indicators   INTEGER DEFAULT nextval('seq_base_macro_indicators') PRIMARY KEY,
        code                  VARCHAR(20) NOT NULL,
        name                  VARCHAR(50) NOT NULL,
        description           TEXT
    )
    """,

    # 15. 宏观指标每日值 — 含 3/5/10 年百分位
    """
    CREATE TABLE IF NOT EXISTS base_macro_daily (
        pk_macro_daily       BIGINT DEFAULT nextval('seq_base_macro_daily') PRIMARY KEY,
        fk_macro_indicators  INTEGER NOT NULL,
        trade_date           DATE NOT NULL,
        value                DECIMAL(10,4) NOT NULL,
        percentile_3y        DECIMAL(5,1),
        percentile_5y        DECIMAL(5,1),
        percentile_10y       DECIMAL(5,1)
    )
    """,

    # 15.5 申万一级行业每日快照 — 存储每日行业涨跌幅/PE/PB/股息率，用于历史走势和相对强度
    """
    CREATE TABLE IF NOT EXISTS base_sw_sector_daily (
        pk_sw_sector_daily  BIGINT DEFAULT nextval('seq_base_sw_sector_daily') PRIMARY KEY,
        sector_code         VARCHAR(20) NOT NULL,
        sector_name         VARCHAR(50) NOT NULL,
        trade_date          DATE NOT NULL,
        price               DECIMAL(12,4),
        prev_close          DECIMAL(12,4),
        change_pct          DECIMAL(6,2),
        pe                  DECIMAL(8,2),
        ttm_pe              DECIMAL(8,2),
        pb                  DECIMAL(8,2),
        dividend_yield      DECIMAL(5,2),
        count               SMALLINT
    )
    """,

    # ================================================
    # Business Tables (biz_)
    # ================================================

    # 16. 用户表
    """
    CREATE TABLE IF NOT EXISTS biz_users (
        pk_user          BIGINT DEFAULT nextval('seq_user') PRIMARY KEY,
        username         VARCHAR(50) NOT NULL,
        email            VARCHAR(100),
        password_hash    VARCHAR(255) NOT NULL,
        created_at       TIMESTAMP DEFAULT now(),
        must_change_password  BOOLEAN DEFAULT FALSE,
        token_version        INTEGER DEFAULT 0
    )
    """,

    # 17. 自选股
    """
    CREATE TABLE IF NOT EXISTS biz_favorites (
        pk_favorites     UUID DEFAULT uuid() PRIMARY KEY,
        fk_user BIGINT NOT NULL,
        code             VARCHAR(20) NOT NULL,
        name             VARCHAR(100) NOT NULL,
        type             VARCHAR(10) NOT NULL,
        note             TEXT,
        added_at         TIMESTAMP DEFAULT now()
    )
    """,

    # 18. 投资组合
    """
    CREATE TABLE IF NOT EXISTS biz_portfolios (
        pk_portfolios    UUID DEFAULT uuid() PRIMARY KEY,
        fk_user BIGINT NOT NULL,
        name             VARCHAR(50) NOT NULL,
        created_at       TIMESTAMP DEFAULT now()
    )
    """,

    # 19. 持仓明细
    """
    CREATE TABLE IF NOT EXISTS biz_portfolio_items (
        pk_portfolio_items   UUID DEFAULT uuid() PRIMARY KEY,
        fk_portfolios        UUID NOT NULL,
        code                 VARCHAR(20) NOT NULL,
        name                 VARCHAR(100) NOT NULL,
        type                 VARCHAR(10) NOT NULL,
        quantity             DECIMAL(16,4) NOT NULL,
        cost_price           DECIMAL(10,4) NOT NULL,
        added_at             TIMESTAMP DEFAULT now()
    )
    """,

    # 19.1 多券商统一持仓（持仓分析页）—— 实际由 holdings_service 首次使用时懒创建，此处仅作文档化
    """
    CREATE TABLE IF NOT EXISTS biz_holdings (
        id               VARCHAR PRIMARY KEY,
        fk_user BIGINT NOT NULL,
        code             VARCHAR(20) NOT NULL,
        name             VARCHAR(100) NOT NULL,
        type             VARCHAR(20) NOT NULL,
        broker           VARCHAR(50) DEFAULT '',
        account          VARCHAR(50) DEFAULT '',
        quantity         DOUBLE NOT NULL,
        cost_price       DOUBLE NOT NULL,
            manual_price     DOUBLE,
            stop_loss_pct    DOUBLE,
            take_profit_pct  DOUBLE,
            open_date        VARCHAR(10),
            currency         VARCHAR(8) DEFAULT 'CNY',
            created_at       VARCHAR,
            updated_at       VARCHAR,
            fair_value       DOUBLE,
            grid_lower       DOUBLE,
            grid_upper       DOUBLE,
            grid_step        DOUBLE
        )
        """,

    # 19.2 券商列表（持仓页筛选/导入选用）—— 实际由 broker_account_service 首次使用时懒创建，此处仅作文档化
    # 2026-08 重构：此表仅存券商名称，账户名拆到 biz_account_names 独立表
    """
    CREATE TABLE IF NOT EXISTS biz_broker_accounts (
        id               VARCHAR PRIMARY KEY,
        fk_user BIGINT NOT NULL,
        broker           VARCHAR(50) NOT NULL,
        account          VARCHAR(50) DEFAULT '',
        created_at       VARCHAR,
        updated_at       VARCHAR
    )
    """,

    # 19.2b 账户名列表（独立表，持仓页编辑时选用）—— 由 account_name_service 懒创建
    """
    CREATE TABLE IF NOT EXISTS biz_account_names (
        id               VARCHAR PRIMARY KEY,
        fk_user BIGINT NOT NULL,
        name             VARCHAR(50) NOT NULL,
        created_at       VARCHAR,
        updated_at       VARCHAR
    )
    """,

    # 19.3 持仓每日快照（历史盈亏曲线）
    """
    CREATE TABLE IF NOT EXISTS biz_holding_snapshots (
        id                 VARCHAR PRIMARY KEY,
        fk_user BIGINT NOT NULL,
        snap_date          VARCHAR(10) NOT NULL,
        total_market_value DOUBLE,
        total_cost         DOUBLE,
        total_pnl          DOUBLE,
        total_pnl_pct      DOUBLE,
        daily_pnl          DOUBLE,
        holding_count      INTEGER,
        priced_count       INTEGER,
        created_at         VARCHAR
    )
    """,

    # 20. 筛选策略（自定义策略 CRUD）—— 由 strategy_service 懒创建，此处仅作文档化
    """
    CREATE TABLE IF NOT EXISTS biz_strategies (
        id            VARCHAR PRIMARY KEY,
        fk_user BIGINT NOT NULL,
        name          VARCHAR(50) NOT NULL,
        target_asset  VARCHAR(10) NOT NULL,
        rules         JSON,
        sort_by       VARCHAR(50),
        sort_order    VARCHAR(4) DEFAULT 'asc',
        limit_count   INTEGER,
        active        BOOLEAN DEFAULT TRUE,
        ai_tracking   BOOLEAN DEFAULT FALSE,
        created_at    TIMESTAMP DEFAULT now()
    )
    """,

    # 21. 策略规则
    """
    CREATE TABLE IF NOT EXISTS biz_strategy_rules (
        pk_strategy_rules   UUID DEFAULT uuid() PRIMARY KEY,
        fk_strategies       UUID NOT NULL,
        field               VARCHAR(30) NOT NULL,
        operator            VARCHAR(10) NOT NULL,
        value               VARCHAR(100) NOT NULL,
        logic               VARCHAR(5) NOT NULL
    )
    """,

    # 22. 预警规则
    """
    CREATE TABLE IF NOT EXISTS biz_alert_rules (
        pk_alert_rules   UUID DEFAULT uuid() PRIMARY KEY,
        fk_user BIGINT NOT NULL,
        name             VARCHAR(50) NOT NULL,
        type             VARCHAR(10) NOT NULL,
        target           VARCHAR(50) NOT NULL,
        condition        VARCHAR(10) NOT NULL,
        value            DECIMAL(12,4) NOT NULL,
        channels         JSON NOT NULL,
        active           BOOLEAN DEFAULT TRUE
    )
    """,

    # 23. 预警触发事件
    """
    CREATE TABLE IF NOT EXISTS biz_alert_events (
        pk_alert_events    BIGINT DEFAULT nextval('seq_biz_alert_events') PRIMARY KEY,
        fk_alert_rules     UUID NOT NULL,
        triggered_at       TIMESTAMP NOT NULL DEFAULT now(),
        target_code        VARCHAR(20),
        target_name        VARCHAR(100),
        actual_value       DECIMAL(12,4),
        message            TEXT,
        is_read            BOOLEAN DEFAULT FALSE
    )
    """,

    # 24. AI 分析报告
    """
    CREATE TABLE IF NOT EXISTS biz_ai_reports (
        pk_ai_reports       UUID DEFAULT uuid() PRIMARY KEY,
        fk_user BIGINT NOT NULL,
        report_date         DATE NOT NULL,
        macro_assessment    TEXT,
        strategy_matches    JSON,
        arbitrage_alerts    JSON,
        created_at          TIMESTAMP DEFAULT now()
    )
    """,

    # 25. AI 配置
    """
    CREATE TABLE IF NOT EXISTS biz_ai_configs (
        pk_ai_configs     INTEGER DEFAULT nextval('seq_biz_ai_configs') PRIMARY KEY,
        fk_user BIGINT NOT NULL,
        provider          VARCHAR(30) NOT NULL,
        api_key           VARCHAR(255),
        endpoint          VARCHAR(255),
        temperature       DECIMAL(3,2) DEFAULT 0.70,
        cron_expression   VARCHAR(50),
        enabled           BOOLEAN DEFAULT FALSE
    )
    """,
]

# ============================================================
# Index Definitions
# ============================================================

INDEXES = [
    # --- Unique indexes (替代 UNIQUE 约束) ---

    # 代码唯一约束
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_indices_code ON base_indices(code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_funds_code ON base_funds(code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_etf_funds_code ON base_etf_funds(code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_stocks_code ON base_stocks(code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_convertible_bonds_code ON base_convertible_bonds(code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_reits_code ON base_reits(code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_macro_indicators_code ON base_macro_indicators(code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON biz_users(username)",

    # 复合唯一约束: 同一标的同一交易日仅一条快照
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_iv_index_date ON base_index_valuations(fk_indices, trade_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_kline_code_date ON base_kline_data(code, trade_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_fdq_fund_date ON base_fund_daily_quotes(fk_funds, trade_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_edq_etf_date ON base_etf_daily_quotes(fk_etf_funds, trade_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cdq_cb_date ON base_cb_daily_quotes(fk_convertible_bonds, trade_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_sdq_stock_date ON base_stock_daily_quotes(fk_stocks, trade_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rdq_reit_date ON base_reit_daily_quotes(fk_reits, trade_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_md_indicator_date ON base_macro_daily(fk_macro_indicators, trade_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_sw_sector_code_date ON base_sw_sector_daily(sector_code, trade_date)",

    # --- 核心查询索引 (按标的 + 日期范围查询) ---

    "CREATE INDEX IF NOT EXISTS idx_iv_index_date ON base_index_valuations(fk_indices, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_kline_code_date ON base_kline_data(code, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fdq_fund_date ON base_fund_daily_quotes(fk_funds, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_edq_etf_date ON base_etf_daily_quotes(fk_etf_funds, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_cdq_cb_date ON base_cb_daily_quotes(fk_convertible_bonds, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sdq_stock_date ON base_stock_daily_quotes(fk_stocks, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rdq_reit_date ON base_reit_daily_quotes(fk_reits, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_md_indicator_date ON base_macro_daily(fk_macro_indicators, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sw_sector_date ON base_sw_sector_daily(trade_date DESC, change_pct DESC)",

    # --- 用户数据索引 ---

    "CREATE INDEX IF NOT EXISTS idx_fav_users ON biz_favorites(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_pi_portfolios ON biz_portfolio_items(fk_portfolios)",
    "CREATE INDEX IF NOT EXISTS idx_strat_users ON biz_strategies(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_holdings_users ON biz_holdings(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_broker_users ON biz_broker_accounts(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_acctname_users ON biz_account_names(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_snap_users ON biz_holding_snapshots(fk_user)",

    "CREATE INDEX IF NOT EXISTS idx_ar_users ON biz_alert_rules(fk_user)",
    "CREATE INDEX IF NOT EXISTS idx_ae_rule_time ON biz_alert_events(fk_alert_rules, triggered_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_air_users_date ON biz_ai_reports(fk_user, report_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_aiconfig_users ON biz_ai_configs(fk_user)",

    # --- 筛选优化索引 (高频查询场景) ---

    # 可转债双低筛选: 价格 + 溢价率
    "CREATE INDEX IF NOT EXISTS idx_cdq_double_low ON base_cb_daily_quotes(trade_date, price, premium_pct)",
    # 基金折价排序
    "CREATE INDEX IF NOT EXISTS idx_fdq_discount ON base_fund_daily_quotes(trade_date, premium_pct)",
    # ETF 高溢价套利
    "CREATE INDEX IF NOT EXISTS idx_edq_premium ON base_etf_daily_quotes(trade_date, premium_pct DESC)",
]

# ============================================================
# Drop statements (for clean re-creation)
# ============================================================

DROP_TABLES = [
    "DROP TABLE IF EXISTS biz_account_names",
    "DROP TABLE IF EXISTS biz_holding_snapshots",
    "DROP TABLE IF EXISTS biz_holdings",
    "DROP TABLE IF EXISTS biz_ai_configs",
    "DROP TABLE IF EXISTS biz_ai_reports",
    "DROP TABLE IF EXISTS biz_alert_events",
    "DROP TABLE IF EXISTS biz_alert_rules",
    "DROP TABLE IF EXISTS biz_strategy_rules",
    "DROP TABLE IF EXISTS biz_strategies",
    "DROP TABLE IF EXISTS biz_portfolio_items",
    "DROP TABLE IF EXISTS biz_portfolios",
    "DROP TABLE IF EXISTS biz_favorites",
    "DROP TABLE IF EXISTS biz_users",
    "DROP TABLE IF EXISTS base_sw_sector_daily",
    "DROP TABLE IF EXISTS base_macro_daily",
    "DROP TABLE IF EXISTS base_macro_indicators",
    "DROP TABLE IF EXISTS base_reit_daily_quotes",
    "DROP TABLE IF EXISTS base_reits",
    "DROP TABLE IF EXISTS base_stock_daily_quotes",
    "DROP TABLE IF EXISTS base_cb_daily_quotes",
    "DROP TABLE IF EXISTS base_convertible_bonds",
    "DROP TABLE IF EXISTS base_stocks",
    "DROP TABLE IF EXISTS base_etf_daily_quotes",
    "DROP TABLE IF EXISTS base_etf_funds",
    "DROP TABLE IF EXISTS base_fund_daily_quotes",
    "DROP TABLE IF EXISTS base_funds",
    "DROP TABLE IF EXISTS base_kline_data",
    "DROP TABLE IF EXISTS base_index_valuations",
    "DROP TABLE IF EXISTS base_indices",
]

DROP_SEQUENCES = [
    "DROP SEQUENCE IF EXISTS seq_base_indices",
    "DROP SEQUENCE IF EXISTS seq_base_index_valuations",
    "DROP SEQUENCE IF EXISTS seq_base_kline_data",
    "DROP SEQUENCE IF EXISTS seq_base_funds",
    "DROP SEQUENCE IF EXISTS seq_base_fund_daily_quotes",
    "DROP SEQUENCE IF EXISTS seq_base_etf_funds",
    "DROP SEQUENCE IF EXISTS seq_base_etf_daily_quotes",
    "DROP SEQUENCE IF EXISTS seq_base_stocks",
    "DROP SEQUENCE IF EXISTS seq_base_convertible_bonds",
    "DROP SEQUENCE IF EXISTS seq_base_cb_daily_quotes",
    "DROP SEQUENCE IF EXISTS seq_base_stock_daily_quotes",
    "DROP SEQUENCE IF EXISTS seq_base_reits",
    "DROP SEQUENCE IF EXISTS seq_base_reit_daily_quotes",
    "DROP SEQUENCE IF EXISTS seq_base_macro_indicators",
    "DROP SEQUENCE IF EXISTS seq_base_macro_daily",
    "DROP SEQUENCE IF EXISTS seq_biz_alert_events",
    "DROP SEQUENCE IF EXISTS seq_biz_ai_configs",
    "DROP SEQUENCE IF EXISTS seq_user",
    "DROP SEQUENCE IF EXISTS seq_base_sw_sector_daily",
]
