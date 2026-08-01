# 数据库设计文档（MySQL）

量化投资终端后端业务数据库设计。数据库引擎统一使用 `InnoDB`，字符集 `utf8mb4`，排序规则 `utf8mb4_unicode_ci`。

所有表均包含以下审计字段（下文不再重复列出）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `created_at` | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| `updated_at` | DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

---

## 1. 用户与收藏

### 1.1 `users` — 用户

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | 用户 ID |
| `username` | VARCHAR(64) | NOT NULL, UNIQUE | 用户名 |
| `email` | VARCHAR(128) | UNIQUE | 邮箱 |
| `phone` | VARCHAR(32) | UNIQUE | 手机号 |
| `password_hash` | VARCHAR(255) | NOT NULL | bcrypt 哈希 |
| `avatar_url` | VARCHAR(512) | | 头像 |
| `role` | ENUM('admin','trader','viewer') | NOT NULL DEFAULT 'viewer' | 角色 |
| `last_login_at` | DATETIME | | 最后登录时间 |
| `status` | TINYINT | NOT NULL DEFAULT 1 | 1=启用 0=禁用 |

索引：`uk_username` (UNIQUE), `uk_email` (UNIQUE)

### 1.2 `favorites` — 收藏标的

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `user_id` | BIGINT UNSIGNED | NOT NULL, FK→users.id | 用户 |
| `code` | VARCHAR(32) | NOT NULL | 标的代码 |
| `name` | VARCHAR(128) | NOT NULL | 标的名称 |
| `type` | ENUM('index','lof','closed','reit','cb') | NOT NULL | 标的类型 |
| `note` | VARCHAR(255) | | 备注 |
| `added_at` | DATETIME | NOT NULL DEFAULT CURRENT_TIMESTAMP | 添加时间 |

索引：`idx_user_id` , `uk_user_code_type` (UNIQUE, user_id+code+type)

---

## 2. 宏观与指数

### 2.1 `macro_indicators` — 宏观指标快照

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `trade_date` | DATE | NOT NULL | 交易日 |
| `erp` | DECIMAL(8,4) | NOT NULL | 股权风险溢价（ERP） |
| `erp_percentile_3y` | DECIMAL(6,2) | NOT NULL | ERP 3 年百分位 |
| `erp_percentile_5y` | DECIMAL(6,2) | NOT NULL | ERP 5 年百分位 |
| `erp_percentile_10y` | DECIMAL(6,2) | NOT NULL | ERP 10 年百分位 |
| `dr007` | DECIMAL(8,4) | NOT NULL | DR007 加权利率 |
| `gc001` | DECIMAL(8,4) | NOT NULL | GC001 国债逆回购 |

索引：`uk_trade_date` (UNIQUE), `idx_trade_date`

### 2.2 `indices` — 指数主表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `code` | VARCHAR(32) | NOT NULL, UNIQUE | 指数代码 |
| `name` | VARCHAR(64) | NOT NULL | 指数名称 |
| `category` | ENUM('undervalued','normal','overvalued','opportunity') | NOT NULL DEFAULT 'normal' | 估值分类 |
| `is_custom` | TINYINT(1) | NOT NULL DEFAULT 0 | 是否自定义指数 |

索引：`uk_code` (UNIQUE)

### 2.3 `index_valuation_daily` — 指数估值日数据

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `index_id` | BIGINT UNSIGNED | NOT NULL, FK→indices.id | 指数 |
| `trade_date` | DATE | NOT NULL | 交易日 |
| `level` | DECIMAL(12,4) | NOT NULL | 收盘点位 |
| `change_pct` | DECIMAL(8,4) | NOT NULL | 日涨跌幅 |
| `pe` | DECIMAL(10,4) | | PE(TTM) |
| `pb` | DECIMAL(10,4) | | PB |
| `pe_percentile` | DECIMAL(6,2) | | PE 历史百分位 |
| `pb_percentile` | DECIMAL(6,2) | | PB 历史百分位 |
| `change_3m_pct` | DECIMAL(8,4) | | 近 3 月涨跌幅 |
| `win_rate` | DECIMAL(6,2) | | 历史胜率 |

索引：`uk_index_date` (UNIQUE, index_id+trade_date), `idx_trade_date`

### 2.4 `index_pe_history` — 指数 PE 历史（估值带）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `index_id` | BIGINT UNSIGNED | NOT NULL, FK→indices.id | 指数 |
| `trade_date` | DATE | NOT NULL | 交易日 |
| `pe` | DECIMAL(10,4) | NOT NULL | PE 值 |
| `pct_90` | DECIMAL(10,4) | | 90 分位 |
| `pct_70` | DECIMAL(10,4) | | 70 分位 |
| `pct_50` | DECIMAL(10,4) | | 中位数 |
| `pct_10` | DECIMAL(10,4) | | 10 分位 |

索引：`uk_index_date` (UNIQUE, index_id+trade_date)

---

## 3. 基金（LOF / 封闭 / QDII）

### 3.1 `funds` — 基金主表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `code` | VARCHAR(32) | NOT NULL, UNIQUE | 基金代码 |
| `name` | VARCHAR(128) | NOT NULL | 基金名称 |
| `type` | ENUM('lof','closed','qdii') | NOT NULL | 类型 |
| `maturity` | VARCHAR(32) | | 到期日（封闭基金） |
| `remaining_term` | VARCHAR(32) | | 剩余期限描述 |

索引：`uk_code` (UNIQUE), `idx_type`

### 3.2 `fund_realtime_daily` — 基金实时行情日数据

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `fund_id` | BIGINT UNSIGNED | NOT NULL, FK→funds.id | 基金 |
| `trade_date` | DATE | NOT NULL | 交易日 |
| `price` | DECIMAL(10,4) | NOT NULL | 市价 |
| `iopv` | DECIMAL(10,4) | | IOPV 净值 |
| `premium_pct` | DECIMAL(8,4) | NOT NULL | 折溢价率 |
| `premium_percentile` | DECIMAL(6,2) | | 折溢价历史百分位 |
| `net_arbitrage_yield` | DECIMAL(8,4) | | 净套利收益率 |
| `annualized` | DECIMAL(8,4) | | 年化收益 |
| `est_ytm` | DECIMAL(8,4) | | 预估到期收益率 |
| `volume` | BIGINT UNSIGNED | | 成交量 |

索引：`uk_fund_date` (UNIQUE, fund_id+trade_date), `idx_type_date` (经 fund_id 关联 type)

---

## 3b. ETF 基金（集思录策略）

### 3b.1 `etf_funds` — ETF 主表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `code` | VARCHAR(32) | NOT NULL, UNIQUE | ETF 代码 |
| `name` | VARCHAR(128) | NOT NULL | ETF 名称 |
| `category` | ENUM('broad','industry','cross_border','theme') | NOT NULL | 宽基/行业/跨境/主题 |
| `sub_category` | VARCHAR(64) | | 子类（如 证券、医药、纳斯达克100） |
| `track_index` | VARCHAR(64) | | 跟踪指数代码 |
| `subscribe_limit` | VARCHAR(64) | | 申购限额描述 |

索引：`uk_code` (UNIQUE), `idx_category` (category)

### 3b.2 `etf_daily` — ETF 日行情

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `etf_id` | BIGINT UNSIGNED | NOT NULL, FK→etf_funds.id | ETF |
| `trade_date` | DATE | NOT NULL | 交易日 |
| `price` | DECIMAL(10,4) | NOT NULL | 市价 |
| `iopv` | DECIMAL(10,4) | | IOPV 净值 |
| `premium_pct` | DECIMAL(8,4) | NOT NULL | 折溢价率 |
| `premium_percentile` | DECIMAL(6,2) | | 折溢价历史百分位 |
| `net_arbitrage_yield` | DECIMAL(8,4) | | 净套利收益率 |
| `volume` | BIGINT UNSIGNED | | 成交量 |
| `pe` | DECIMAL(10,4) | | 跟踪指数 PE |
| `pe_percentile` | DECIMAL(6,2) | | PE 历史百分位 |
| `dividend_rate` | DECIMAL(6,2) | | 股息率 |
| `momentum_score` | DECIMAL(6,2) | | 动量得分（20日加权） |

索引：`uk_etf_date` (UNIQUE, etf_id+trade_date), `idx_trade_date`

### 3b.3 `etf_grid_params` — 网格交易参数

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `etf_id` | BIGINT UNSIGNED | NOT NULL, FK→etf_funds.id, UNIQUE | ETF |
| `grid_low` | DECIMAL(10,4) | NOT NULL | 网格下限价 |
| `grid_high` | DECIMAL(10,4) | NOT NULL | 网格上限价 |
| `grid_step` | DECIMAL(6,2) | NOT NULL | 网格间距(%) |
| `grid_yield_est` | DECIMAL(8,4) | | 预估年化收益(%) |
| `updated_date` | DATE | NOT NULL | 最近更新日 |

索引：`uk_etf_id` (UNIQUE)

---

## 4. 可转债

### 4.1 `convertible_bonds` — 可转债主表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `code` | VARCHAR(32) | NOT NULL, UNIQUE | 转债代码 |
| `name` | VARCHAR(64) | NOT NULL | 转债名称 |
| `stock_code` | VARCHAR(32) | | 正股代码 |
| `stock_name` | VARCHAR(64) | | 正股名称 |
| `rating` | VARCHAR(16) | | 信用评级 |
| `remaining_years` | DECIMAL(6,2) | | 剩余年限 |
| `tag` | VARCHAR(32) | | 标签 |
| `tag_type` | ENUM('double_low','undervalued','high_risk','stable_yield','mean_reversion','defensive') | | 标签类型 |

索引：`uk_code` (UNIQUE), `idx_stock_code`

### 4.2 `convertible_bond_daily` — 可转债日行情

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `bond_id` | BIGINT UNSIGNED | NOT NULL, FK→convertible_bonds.id | 转债 |
| `trade_date` | DATE | NOT NULL | 交易日 |
| `price` | DECIMAL(10,4) | NOT NULL | 转债价格 |
| `change_pct` | DECIMAL(8,4) | | 涨跌幅 |
| `conv_value` | DECIMAL(10,4) | | 转股价值 |
| `premium_pct` | DECIMAL(8,4) | | 转股溢价率 |
| `ytm` | DECIMAL(8,4) | | 到期收益率 |
| `double_low_score` | DECIMAL(10,4) | | 双低值 |

索引：`uk_bond_date` (UNIQUE, bond_id+trade_date)

### 4.3 `convertible_bond_clauses` — 可转债条款触发进度

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `bond_id` | BIGINT UNSIGNED | NOT NULL, FK→convertible_bonds.id, UNIQUE | 转债 |
| `redemption_days` | INT | NOT NULL DEFAULT 0 | 强赎触发累计天数 |
| `total_redemption_days` | INT | NOT NULL DEFAULT 30 | 强赎触发总天数阈值 |
| `putback_days` | INT | DEFAULT 0 | 回售触发累计天数 |
| `total_putback_days` | INT | DEFAULT 30 | 回售触发总天数阈值 |
| `revision_days` | INT | DEFAULT 0 | 下修条件累计天数 |
| `total_revision_days` | INT | DEFAULT 15 | 下修条件总天数阈值 |
| `updated_date` | DATE | NOT NULL | 最近更新交易日 |

索引：`uk_bond_id` (UNIQUE)

### 4.4 `stock_risk` — 正股风控指标

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `stock_code` | VARCHAR(32) | NOT NULL, UNIQUE | 正股代码 |
| `stock_name` | VARCHAR(64) | | 正股名称 |
| `altman_z_score` | DECIMAL(8,4) | | Altman Z-Score |
| `pledge_rate` | DECIMAL(6,2) | | 质押率 |
| `is_st_risk` | TINYINT(1) | NOT NULL DEFAULT 0 | 是否 ST 风险 |
| `updated_date` | DATE | NOT NULL | 最近更新交易日 |

索引：`uk_stock_code` (UNIQUE)

---

## 5. 公募 REITs

### 5.1 `reits` — REITs 主表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `code` | VARCHAR(32) | NOT NULL, UNIQUE | REITs 代码 |
| `name` | VARCHAR(128) | NOT NULL | 名称 |
| `project_name` | VARCHAR(128) | | 底层项目名称 |

索引：`uk_code` (UNIQUE)

### 5.2 `reit_daily` — REITs 日行情

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `reit_id` | BIGINT UNSIGNED | NOT NULL, FK→reits.id | REITs |
| `trade_date` | DATE | NOT NULL | 交易日 |
| `market_price` | DECIMAL(10,4) | NOT NULL | 市价 |
| `annual_distribution` | DECIMAL(10,4) | | 年分红 |
| `dividend_rate` | DECIMAL(8,4) | | 分红率 |
| `irr` | DECIMAL(8,4) | | 内部收益率 |
| `occupancy_rate` | DECIMAL(6,2) | | 出租率 |

索引：`uk_reit_date` (UNIQUE, reit_id+trade_date)

---

## 6. 策略管理

### 6.1 `strategies` — 策略

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `uuid` | CHAR(36) | NOT NULL, UNIQUE | 对外 UUID |
| `name` | VARCHAR(128) | NOT NULL | 策略名称 |
| `target_asset` | ENUM('cb','lof','reit') | NOT NULL | 目标资产 |
| `active` | TINYINT(1) | NOT NULL DEFAULT 1 | 启用状态 |
| `created_at` | DATETIME | NOT NULL DEFAULT CURRENT_TIMESTAMP | |

索引：`uk_uuid` (UNIQUE), `idx_target_active` (target_asset+active)

### 6.2 `strategy_rules` — 策略规则

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `strategy_id` | BIGINT UNSIGNED | NOT NULL, FK→strategies.id ON DELETE CASCADE | 策略 |
| `sort_order` | INT | NOT NULL DEFAULT 0 | 顺序 |
| `field` | VARCHAR(64) | NOT NULL | 字段名（如 价格、双低值） |
| `operator` | VARCHAR(16) | NOT NULL | 操作符（>, <, =, 属于, 不属于） |
| `value` | VARCHAR(64) | NOT NULL | 阈值 |
| `logic` | ENUM('AND','OR') | NOT NULL DEFAULT 'AND' | 与前一规则的逻辑关系 |

索引：`idx_strategy_id` , `uk_strategy_order` (UNIQUE, strategy_id+sort_order)

### 6.3 `strategy_backtests` — 策略回测结果

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `strategy_id` | BIGINT UNSIGNED | NOT NULL, FK→strategies.id | 策略 |
| `backtest_date` | DATE | NOT NULL | 回测日期 |
| `sharpe` | DECIMAL(8,4) | | 夏普比率 |
| `max_drawdown` | DECIMAL(8,4) | | 最大回撤 |
| `calmar` | DECIMAL(8,4) | | 卡玛比率 |
| `win_rate` | DECIMAL(6,2) | | 胜率 |
| `annual_return` | DECIMAL(8,4) | | 年化收益 |
| `result_json` | JSON | | 完整结果数据 |

索引：`idx_strategy_date` (strategy_id+backtest_date)

---

## 7. 预警中心

### 7.1 `alert_rules` — 预警规则

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `name` | VARCHAR(128) | NOT NULL | 规则名称 |
| `type` | ENUM('price','premium','discount','ytm') | NOT NULL | 监控类型 |
| `target` | VARCHAR(255) | NOT NULL | 监控标的（代码或"全部标的"） |
| `condition` | ENUM('above','below','crosses') | NOT NULL | 触发条件 |
| `value` | DECIMAL(16,4) | NOT NULL | 触发阈值 |
| `channels` | JSON | NOT NULL | 通知渠道数组（如 ["popup","dingtalk"]） |
| `active` | TINYINT(1) | NOT NULL DEFAULT 1 | 启用状态 |

索引：`idx_active_type` (active+type)

### 7.2 `alert_signals` — 实时预警信号

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `rule_id` | BIGINT UNSIGNED | FK→alert_rules.id | 触发规则 |
| `type` | VARCHAR(32) | NOT NULL | 信号类型 |
| `title` | VARCHAR(255) | NOT NULL | 标题 |
| `desc` | TEXT | | 描述 |
| `severity` | ENUM('high','medium','low') | NOT NULL DEFAULT 'medium' | 严重级别 |
| `triggered_at` | DATETIME | NOT NULL DEFAULT CURRENT_TIMESTAMP | 触发时间 |
| `acknowledged` | TINYINT(1) | NOT NULL DEFAULT 0 | 是否已确认 |

索引：`idx_triggered_at` , `idx_severity_ack` (severity+acknowledged)

### 7.3 `alert_history` — 预警历史

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `rule_name` | VARCHAR(128) | NOT NULL | 规则名称 |
| `target` | VARCHAR(64) | NOT NULL | 标的 |
| `value` | VARCHAR(64) | NOT NULL | 触发值 |
| `triggered_at` | DATETIME | NOT NULL | 触发时间 |
| `status` | ENUM('active','resolved') | NOT NULL DEFAULT 'active' | 状态 |

索引：`idx_triggered_at` , `idx_status` (status)

---

## 8. AI 决策

### 8.1 `ai_configs` — AI 配置

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `provider` | VARCHAR(32) | NOT NULL | 服务商（deepseek/openai/claude） |
| `api_key` | VARCHAR(255) | NOT NULL | API Key（加密存储） |
| `endpoint` | VARCHAR(512) | | 自定义端点 |
| `model` | VARCHAR(64) | | 模型名 |
| `temperature` | DECIMAL(4,2) | NOT NULL DEFAULT 0.7 | 温度 |
| `cron_expression` | VARCHAR(64) | NOT NULL DEFAULT '0 0 9 * * 1-5' | 调度表达式 |
| `enabled` | TINYINT(1) | NOT NULL DEFAULT 0 | 是否启用自动调度 |

索引：`uk_provider` (UNIQUE)

### 8.2 `ai_reports` — AI 决策报告

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `report_date` | DATE | NOT NULL, UNIQUE | 报告日期 |
| `macro_assessment` | TEXT | NOT NULL | 宏观评估全文 |
| `created_at` | DATETIME | NOT NULL DEFAULT CURRENT_TIMESTAMP | |

索引：`uk_report_date` (UNIQUE)

### 8.3 `ai_report_strategy_matches` — AI 报告策略匹配

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `report_id` | BIGINT UNSIGNED | NOT NULL, FK→ai_reports.id ON DELETE CASCADE | 报告 |
| `strategy_name` | VARCHAR(128) | NOT NULL | 策略名称 |
| `item_name` | VARCHAR(128) | NOT NULL | 标的名称 |
| `reason` | TEXT | NOT NULL | 推荐理由 |
| `sort_order` | INT | NOT NULL DEFAULT 0 | 顺序 |

索引：`idx_report_id` (report_id)

### 8.4 `ai_report_arbitrage_alerts` — AI 报告套利预警

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `report_id` | BIGINT UNSIGNED | NOT NULL, FK→ai_reports.id ON DELETE CASCADE | 报告 |
| `name` | VARCHAR(128) | NOT NULL | 标的名称 |
| `premium` | DECIMAL(8,4) | NOT NULL | 折溢价 |
| `net_yield` | DECIMAL(8,4) | NOT NULL | 净收益率 |
| `assessment` | TEXT | NOT NULL | 评估 |

索引：`idx_report_id` (report_id)

---

## 9. 投资组合

### 9.1 `portfolios` — 组合

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `user_id` | BIGINT UNSIGNED | NOT NULL, FK→users.id | 用户 |
| `name` | VARCHAR(128) | NOT NULL | 组合名称 |
| `description` | VARCHAR(255) | | 描述 |

索引：`idx_user_id`

### 9.2 `portfolio_items` — 组合标的

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT | |
| `portfolio_id` | BIGINT UNSIGNED | NOT NULL, FK→portfolios.id ON DELETE CASCADE | 组合 |
| `code` | VARCHAR(32) | NOT NULL | 标的代码 |
| `name` | VARCHAR(128) | NOT NULL | 标的名称 |
| `type` | ENUM('index','lof','closed','reit','cb') | NOT NULL | 类型 |
| `weight` | DECIMAL(6,2) | DEFAULT 0 | 权重 |
| `added_at` | DATETIME | NOT NULL DEFAULT CURRENT_TIMESTAMP | |

索引：`uk_portfolio_code` (UNIQUE, portfolio_id+code)

---

## 10. ER 关系概览

```
users ──< favorites
users ──< portfolios ──< portfolio_items

indices ──< index_valuation_daily
indices ──< index_pe_history

funds ──< fund_realtime_daily

etf_funds ──< etf_daily
etf_funds ──┬──< etf_grid_params

convertible_bonds ──< convertible_bond_daily
convertible_bonds ──┬──< convertible_bond_clauses
                    └──> stock_risk (via stock_code)

reits ──< reit_daily

strategies ──< strategy_rules
strategies ──< strategy_backtests

alert_rules ──< alert_signals
alert_rules ──< alert_history

ai_reports ──< ai_report_strategy_matches
ai_reports ──< ai_report_arbitrage_alerts
```

---

## 11. 初始化 SQL 脚本

```sql
-- 建议所有 DECIMAL 字段根据业务精度调整，示例：
-- 价格/收益率：DECIMAL(10,4) 精确到 0.0001
-- 百分位/胜率：DECIMAL(6,2) 精确到 0.01
-- 涨跌幅：DECIMAL(8,4) 精确到 0.01%

-- 数据库初始化
CREATE DATABASE IF NOT EXISTS `doraemon`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `doraemon`;

-- 表创建语句按上述 1-9 节顺序编写，建表前请先创建外键依赖的父表。
-- 所有 JSON 字段（channels、result_json）需 MySQL 5.7+。
```

---

## 12. 数据保留与分区策略

| 表 | 策略 |
|----|------|
| `*_daily` 行情表 | 按 `trade_date` 月度分区，保留 5 年，超期归档到冷存储 |
| `alert_signals` | 保留 90 天，超期迁移到 `alert_history` |
| `alert_history` | 保留 2 年 |
| `ai_reports` 及子表 | 永久保留 |
| `strategy_backtests` | 永久保留 |

---

## 13. 索引设计原则

1. **唯一索引**：业务唯一键（code、uuid、date 组合）
2. **联合索引**：高频查询的 (parent_id + trade_date) 组合
3. **覆盖索引**：列表查询只取索引列的场景
4. **避免过度索引**：写多读少的表（如行情落地表）仅保留必要索引
