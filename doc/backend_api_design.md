# 后台接口设计文档（Python / FastAPI）

量化投资终端业务层 RESTful API 设计，对应前端 10 个业务页面。

- **框架**：FastAPI（Python 3.11+）
- **数据库**：MySQL 8.0（SQLAlchemy 2.0 ORM）
- **缓存**：Redis（热点行情、配置）
- **鉴权**：JWT Bearer Token
- **响应规范**：统一 `{ code, message, data }` 结构

## 0. 通用约定

### 0.1 统一响应

```json
{ "code": 200, "message": "ok", "data": <T> }
```

错误响应：`code` 非 200，`message` 为错误描述，`data` 为 null。

### 0.2 分页参数

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数（最大 100） |

响应：`{ list: T[], total: int, page: int, page_size: int }`

### 0.3 鉴权

除 `/auth/login` 外所有接口需 Header：

```
Authorization: Bearer <jwt_token>
```

### 0.4 路由前缀

所有业务接口前缀 `/api/v1`。

---

## 1. 鉴权模块

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 登录获取 token |
| POST | `/auth/refresh` | 刷新 token |
| GET | `/auth/me` | 当前用户信息 |

### POST `/auth/login`

请求：
```json
{ "username": "string", "password": "string" }
```

响应 data：
```json
{ "token": "string", "expires_at": "2026-07-24T18:00:00Z", "user": { "id": 1, "username": "string", "role": "trader" } }
```

---

## 2. Dashboard — 宏观看板

对应页面：`/dashboard`

### 2.1 GET `/api/v1/macro`

获取宏观指标快照（ERP、DR007、GC001 等）。

响应 data：
```json
{
  "erp": 3.45,
  "erp_percentile_3y": 82.5,
  "erp_percentile_5y": 75.3,
  "erp_percentile_10y": 68.1,
  "dr007": 1.85,
  "gc001": 2.15,
  "indices": [ { /* IndexValuation */ } ]
}
```

### 2.2 GET `/api/v1/macro/history?metric=erp&years=3`

获取宏观指标历史序列，用于图表。

| 参数 | 类型 | 说明 |
|------|------|------|
| `metric` | string | `erp` / `dr007` / `gc001` |
| `years` | int | 回溯年数，默认 3 |

响应 data：`Array<{ date: string, value: number }>`

### 2.3 GET `/api/v1/macro/refresh`

手动刷新宏观数据（触发数据源拉取）。

响应 data：`{ refreshed_at: "2026-07-24T14:00:00Z", indices_count: 8 }`

---

## 3. IndexAnalysis — 指数估值分析

对应页面：`/index-analysis`

### 3.1 GET `/api/v1/indices`

获取宽基指数估值列表。

查询参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `time_window` | string | `1Y` / `3Y` / `5Y` / `全部` |
| `val_method` | string | `PE (TTM)` / `PB (MRQ)` / `PS` / `股息率` |

响应 data：`Array<IndexValuation>`

```json
{
  "name": "沪深300", "code": "000300.SH", "level": 3856.21,
  "change_pct": 0.85, "pe": 11.4, "pb": 1.22,
  "pe_percentile": 12.4, "pb_percentile": 8.5,
  "category": "undervalued", "change_3m_pct": 3.2, "win_rate": 68
}
```

### 3.2 GET `/api/v1/indices/{code}/pe-band?window=3Y`

获取指数 PE 估值带历史数据（用于 ECharts 折线图 + 分位线）。

响应 data：
```json
{
  "labels": ["2021-05", "2021-09", ...],
  "pe_data": [18.5, 17.2, ...],
  "p90": 18.2, "p70": 15.4, "p50": 13.8, "p10": 10.5
}
```

### 3.3 POST `/api/v1/indices`

添加自定义指数。

请求：
```json
{ "name": "中证红利低波", "code": "930904.CSI" }
```

### 3.4 GET `/api/v1/indices/export?format=csv`

导出指数估值数据。

| 参数 | 说明 |
|------|------|
| `format` | `csv` / `xlsx` |

响应：文件流（Content-Type: text/csv）

---

## 4. LofFunds — LOF/QDII 基金

对应页面：`/lof-funds`

### 4.1 GET `/api/v1/funds?type=lof`

获取 LOF / QDII 基金列表（实时折溢价扫描）。

| 参数 | 类型 | 说明 |
|------|------|------|
| `type` | string | `lof` / `qdii` / `all` |
| `min_premium` | number | 最小溢价率筛选 |
| `max_premium` | number | 最大溢价率筛选 |

响应 data：`Array<FundItem>`

```json
{
  "name": "易方达中小盘LOF", "code": "161121.SZ",
  "type": "lof", "price": 2.345, "iopv": 2.310,
  "premium_pct": 1.52, "premium_percentile": 78,
  "net_arbitrage_yield": 1.12, "volume": 1234567
}
```

### 4.2 GET `/api/v1/funds/{code}/history?days=30`

获取基金折溢价历史（用于收敛趋势图）。

响应 data：`Array<{ date: string, premium: number, iopv: number }>`

### 4.3 GET `/api/v1/funds/export?type=lof`

导出基金数据为 CSV。

---

## 5. ClosedFunds — 封闭基金

对应页面：`/closed-funds`

### 5.1 GET `/api/v1/funds/closed`

获取封闭基金列表（含剩余期限、折价率、到期收益）。

响应 data：`Array<FundItem>`（含 `remaining_term`、`est_ytm`、`maturity`）

### 5.2 POST `/api/v1/funds`

添加封闭基金标的。

请求：
```json
{ "name": "科创封闭1年", "code": "508056.SH", "type": "closed" }
```

### 5.3 DELETE `/api/v1/funds/{code}`

删除自定义标的。

### 5.4 GET `/api/v1/funds/closed/convergence`

获取折价收敛趋势数据。

响应 data：`Array<{ period: string, convergence: number }>`

---

## 5b. EtfFunds — ETF 基金策略

对应页面：`/etf-funds`（集思录 ETF 策略：折溢价套利 / 网格交易 / 行业轮动 / 估值定投）

### 5b.1 GET `/api/v1/etf-funds`

获取 ETF 基金列表（含 4 种策略所需数据）。

查询参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `category` | string | `broad` / `industry` / `cross_border` / `theme` |
| `strategy` | string | `arbitrage` / `grid` / `rotation` / `valuation`（按策略筛选） |
| `min_premium` | number | 最小折溢价率（绝对值） |

响应 data：`Array<EtfFund>`

```json
{
  "name": "华夏纳指100ETF", "code": "513100.SH",
  "category": "cross_border", "sub_category": "纳斯达克100",
  "price": 1.856, "iopv": 1.632, "premium_pct": 13.73,
  "volume": 2150000,
  "premium_percentile": 95, "net_arbitrage_yield": 3.82,
  "subscribe_limit": "限购 100 元",
  "grid_low": 1.65, "grid_high": 1.95, "grid_step": 2, "grid_yield_est": 18.5,
  "momentum_score": 88,
  "pe": 32.5, "pe_percentile": 78, "val_category": "overvalued"
}
```

### 5b.2 GET `/api/v1/etf-funds/arbitrage`

折溢价套利扫描（跨境 ETF 高溢价机会）。

响应 data：`Array<EtfFund>`（`|premium_pct| > 0.5`，按绝对值降序）

### 5b.3 GET `/api/v1/etf-funds/grid`

网格交易推荐（高波动行业/跨境 ETF + 网格参数）。

响应 data：`Array<EtfFund>`（含 `grid_low`、`grid_high`、`grid_step`、`grid_yield_est`）

### 5b.4 GET `/api/v1/etf-funds/rotation`

行业轮动排名（按动量得分降序）。

响应 data：`Array<EtfFund>`（含 `momentum_score`、`pe_percentile`）

### 5b.5 GET `/api/v1/etf-funds/valuation`

估值定投推荐（按 PE 百分位升序）。

响应 data：`Array<EtfFund>`（含 `pe`、`pe_percentile`、`val_category`、`dividend_rate`）

### 5b.6 GET `/api/v1/etf-funds/{code}/history?days=180`

获取 ETF 折溢价/价格历史。

响应 data：`Array<{ date: string, premium: number, price: number, iopv: number }>`

### 5b.7 POST `/api/v1/etf-funds/{code}/grid-params`

更新网格交易参数。

请求：
```json
{ "grid_low": 1.65, "grid_high": 1.95, "grid_step": 2 }
```

### 5b.8 GET `/api/v1/etf-funds/export?strategy=arbitrage`

导出 ETF 数据 CSV。

| 参数 | 说明 |
|------|------|
| `strategy` | `arbitrage` / `grid` / `rotation` / `valuation` |

---

## 6. ConvertibleBonds — 可转债

对应页面：`/convertible-bonds`

### 6.1 GET `/api/v1/convertible-bonds`

获取可转债列表（含条款触发进度、正股风控）。

查询参数（筛选）：

| 参数 | 类型 | 说明 |
|------|------|------|
| `price_min` / `price_max` | number | 价格区间 |
| `premium_min` / `premium_max` | number | 溢价率区间 |
| `rating` | string | 信用评级 |
| `ytm_min` | number | YTM 下限 |
| `years_max` | number | 剩余年限上限 |
| `double_low_max` | number | 双低值上限 |
| `zscore_min` | number | Z-Score 下限 |

响应 data：`Array<ConvertibleBond>`

```json
{
  "name": "AlphaLogic CB", "code": "123456.SZ",
  "price": 118.5, "change_pct": 0.42,
  "conv_value": 152.3, "premium_pct": -22.1,
  "ytm": 3.85, "remaining_years": 2.5, "rating": "AA+",
  "redemption_days": 15, "total_redemption_days": 30,
  "putback_days": 5, "total_putback_days": 30,
  "revision_days": 0, "total_revision_days": 15,
  "double_low_score": 140.5,
  "tag": "双低", "tag_type": "double_low",
  "altman_z_score": 3.21, "pledge_rate": 28.5,
  "is_st_risk": false, "stock_name": "AlphaLogic", "stock_code": "300001.SZ"
}
```

### 6.2 GET `/api/v1/convertible-bonds/market-stats`

获取市场统计（中位价格、中位溢价）。

响应 data：`{ median_price: 118.42, median_premium: 35.1 }`

### 6.3 GET `/api/v1/convertible-bonds/stock-warnings`

获取正股风险预警列表。

响应 data：`Array<{ bond_name: string, stock_name: string, z_score: number, pledge_rate: number, is_st: boolean }>`

### 6.4 GET `/api/v1/convertible-bonds/export`

导出可转债数据 CSV。

---

## 7. Reits — 公募 REITs

对应页面：`/reits`

### 7.1 GET `/api/v1/reits`

获取 REITs 列表。

响应 data：`Array<ReitItem>`

```json
{
  "name": "华安张江REIT", "code": "508000.SH",
  "market_price": 2.85, "annual_distribution": 0.15,
  "dividend_rate": 5.26, "irr": 6.12,
  "occupancy_rate": 92.5, "project_name": "张江光大园"
}
```

### 7.2 GET `/api/v1/reits/{code}/history?days=180`

获取 REITs 分红率/IRR 历史。

---

## 8. PortfolioWatchlist — 投资组合

对应页面：`/portfolio-watchlist`

### 8.1 GET `/api/v1/portfolios/{id}/items?tab=lof`

获取组合标的列表（按 tab 筛选）。

| 参数 | 说明 |
|------|------|
| `tab` | `index` / `lof` / `closed` / `cb` |

响应 data：`Array<FundItem>`

### 8.2 POST `/api/v1/portfolios/{id}/items`

添加标的到组合。

请求：
```json
{ "name": "科创50ETF", "code": "588000.SH", "type": "lof" }
```

### 8.3 DELETE `/api/v1/portfolios/{id}/items/{code}`

从组合移除标的。

### 8.4 GET `/api/v1/portfolios/{id}/allocation`

获取资产配置（饼图数据）。

响应 data：`Array<{ name: string, value: number }>`

### 8.5 GET `/api/v1/portfolios/{id}/convergence`

获取折价收敛趋势（折线图）。

### 8.6 GET `/api/v1/portfolios/{id}/correlation`

获取相关性矩阵。

响应 data：`{ labels: string[], matrix: number[][] }`

### 8.7 GET `/api/v1/portfolios/{id}/export?tab=lof`

导出组合数据 CSV。

---

## 9. StrategyCenter — 策略中心

对应页面：`/strategy-center`

### 9.1 GET `/api/v1/strategies?target_asset=cb`

获取策略列表。

| 参数 | 说明 |
|------|------|
| `target_asset` | `cb` / `lof` / `reit` / 不传=全部 |

响应 data：`Array<Strategy>`

```json
{
  "id": "uuid-string", "name": "双低可转债轮动",
  "target_asset": "cb", "active": true, "createdAt": "2026-07-01",
  "rules": [
    { "id": "r1", "field": "价格", "operator": "<", "value": "120", "logic": "AND" },
    { "id": "r2", "field": "转股溢价率", "operator": "<", "value": "20", "logic": "AND" }
  ]
}
```

### 9.2 POST `/api/v1/strategies`

创建策略。

请求：
```json
{
  "name": "双低可转债轮动",
  "target_asset": "cb",
  "rules": [
    { "field": "价格", "operator": "<", "value": "120", "logic": "AND" }
  ]
}
```

### 9.3 PUT `/api/v1/strategies/{id}`

更新策略（含规则）。

### 9.4 DELETE `/api/v1/strategies/{id}`

删除策略。

### 9.5 POST `/api/v1/strategies/{id}/clone`

克隆策略。

### 9.6 PATCH `/api/v1/strategies/{id}/toggle`

启用/暂停策略。

### 9.7 POST `/api/v1/strategies/{id}/backtest`

提交回测任务（异步）。

响应 data：`{ backtest_id: "string", status: "pending" }`

### 9.8 GET `/api/v1/strategies/{id}/backtests`

获取策略历史回测结果列表。

### 9.9 GET `/api/v1/strategies/templates`

获取策略模板库。

### 9.10 POST `/api/v1/strategies/batch?action=enable-all`

批量操作。

| 参数 | 说明 |
|------|------|
| `action` | `enable-all` / `pause-all` / `backtest-all` / `delete-paused` |

---

## 10. AiDecisionHub — AI 决策

对应页面：`/ai-decision`

### 10.1 GET `/api/v1/ai/config`

获取 AI 配置（API Key 脱敏返回）。

### 10.2 PUT `/api/v1/ai/config`

更新 AI 配置。

请求：
```json
{
  "provider": "deepseek",
  "api_key": "sk-xxx",
  "endpoint": "https://api.deepseek.com/v1",
  "model": "deepseek-chat",
  "temperature": 0.7,
  "cron_expression": "0 0 9 * * 1-5",
  "enabled": true
}
```

### 10.3 POST `/api/v1/ai/test-connection`

测试 AI 服务连接。

响应 data：`{ success: true, latency_ms: 850, model: "deepseek-chat" }`

### 10.4 POST `/api/v1/ai/reports/generate`

触发 AI 报告生成（流式返回）。

响应：`text/event-stream`（SSE）

```
data: {"type":"macro","content":"当前宏观..."}
data: {"type":"strategy","strategyName":"双低轮动","items":[...]}
data: {"type":"alert","name":"...","premium":5.2}
data: {"type":"done"}
```

### 10.5 GET `/api/v1/ai/reports?limit=10`

获取历史 AI 报告列表。

### 10.6 GET `/api/v1/ai/reports/{date}`

获取指定日期报告详情（含策略匹配、套利预警）。

### 10.7 POST `/api/v1/ai/reports/{date}/export`

导出报告为文本/PDF。

### 10.8 POST `/api/v1/ai/reports/{date}/share`

分享报告（生成分享链接）。

响应 data：`{ share_url: "https://..." }`

---

## 11. AlertCenter — 预警中心

对应页面：`/alert-center`

### 11.1 GET `/api/v1/alerts/signals?severity=high`

获取实时预警信号。

| 参数 | 说明 |
|------|------|
| `severity` | `high` / `medium` / `low` / 不传=全部 |
| `acknowledged` | bool，是否已确认 |

响应 data：
```json
[{
  "id": "s1", "type": "premium", "title": "溢价率突破5%",
  "desc": "161129.SZ 当前溢价率 6.25%", "severity": "high",
  "time": "14:22:05"
}]
```

### 11.2 GET `/api/v1/alerts/rules`

获取预警规则列表。

### 11.3 POST `/api/v1/alerts/rules`

创建预警规则。

请求：
```json
{
  "name": "溢价率异动预警", "type": "premium",
  "target": "全部标的", "condition": "above", "value": 5,
  "channels": ["popup", "dingtalk"]
}
```

### 11.4 PUT `/api/v1/alerts/rules/{id}`

更新规则。

### 11.5 DELETE `/api/v1/alerts/rules/{id}`

删除规则。

### 11.6 PATCH `/api/v1/alerts/rules/{id}/toggle`

启用/禁用规则。

### 11.7 GET `/api/v1/alerts/history?page=1&page_size=20`

获取预警历史。

### 11.8 GET `/api/v1/alerts/history/{id}`

获取历史详情。

### 11.9 GET `/api/v1/alerts/templates`

获取规则模板库。

### 11.10 POST `/api/v1/alerts/templates/{name}/import`

导入规则模板。

---

## 12. 公共接口

### 12.1 GET `/api/v1/favorites`

获取收藏列表。

### 12.2 POST `/api/v1/favorites`

添加收藏。

### 12.3 DELETE `/api/v1/favorites/{id}`

取消收藏。

### 12.4 GET `/api/v1/health`

健康检查。

响应：`{ status: "ok", db: "ok", redis: "ok", timestamp: "..." }`

---

## 13. 错误码规范

| code | 含义 |
|------|------|
| 200 | 成功 |
| 400 | 参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 409 | 冲突（如重复添加） |
| 422 | 业务校验失败 |
| 429 | 限流 |
| 500 | 服务器错误 |

---

## 14. 项目结构建议

```
backend/
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── core/
│   │   ├── config.py           # 配置（env）
│   │   ├── database.py         # SQLAlchemy 引擎/会话
│   │   ├── security.py         # JWT 工具
│   │   └── deps.py             # 依赖注入（当前用户等）
│   ├── models/                 # SQLAlchemy 模型
│   │   ├── user.py
│   │   ├── index.py
│   │   ├── fund.py
│   │   ├── convertible_bond.py
│   │   ├── reit.py
│   │   ├── strategy.py
│   │   ├── alert.py
│   │   └── ai.py
│   ├── schemas/                # Pydantic 模型（请求/响应）
│   │   ├── ...
│   ├── api/v1/                 # 路由
│   │   ├── auth.py
│   │   ├── macro.py
│   │   ├── indices.py
│   │   ├── funds.py
│   │   ├── convertible_bonds.py
│   │   ├── reits.py
│   │   ├── portfolios.py
│   │   ├── strategies.py
│   │   ├── ai.py
│   │   └── alerts.py
│   ├── services/               # 业务逻辑
│   │   ├── ...
│   └── utils/
│       └── ...
├── alembic/                    # 数据库迁移
├── requirements.txt
└── .env
```

### 依赖清单（requirements.txt）

```
fastapi>=0.110
uvicorn[standard]>=0.27
sqlalchemy>=2.0
pymysql>=1.1
alembic>=1.13
redis>=5.0
pyjwt>=2.8
passlib[bcrypt]>=4.1
pydantic>=2.6
python-multipart>=0.0.9
httpx>=0.27
akshare>=1.12
apscheduler>=3.10
```

---

## 15. 接口与页面映射速查

| 页面 | 主要接口 |
|------|---------|
| Dashboard | `GET /macro`, `GET /macro/history` |
| IndexAnalysis | `GET /indices`, `GET /indices/{code}/pe-band`, `POST /indices` |
| LofFunds | `GET /funds?type=lof`, `GET /funds/{code}/history` |
| EtfFunds | `GET /etf-funds`, `GET /etf-funds/arbitrage`, `GET /etf-funds/grid`, `GET /etf-funds/rotation`, `GET /etf-funds/valuation` |
| ClosedFunds | `GET /funds/closed`, `POST /funds`, `GET /funds/closed/convergence` |
| ConvertibleBonds | `GET /convertible-bonds`, `GET /convertible-bonds/market-stats`, `GET /convertible-bonds/stock-warnings` |
| Reits | `GET /reits`, `GET /reits/{code}/history` |
| PortfolioWatchlist | `GET /portfolios/{id}/items`, `POST /portfolios/{id}/items`, `GET /portfolios/{id}/allocation` |
| StrategyCenter | `GET/POST/PUT/DELETE /strategies`, `POST /strategies/{id}/backtest` |
| AiDecisionHub | `GET/PUT /ai/config`, `POST /ai/test-connection`, `POST /ai/reports/generate` |
| AlertCenter | `GET /alerts/signals`, `GET/POST/PUT/DELETE /alerts/rules`, `GET /alerts/history` |
