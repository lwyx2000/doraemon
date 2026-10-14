# QuantTerminal Pro — 项目技术文档

> **量化终端 Pro — 套利交易分析平台**
> 版本：1.0.0 | 最后更新：2026-08-15

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [技术栈](#3-技术栈)
4. [目录结构](#4-目录结构)
5. [后端详解](#5-后端详解)
6. [前端详解](#6-前端详解)
7. [数据库设计](#7-数据库设计)
8. [API 接口文档](#8-api-接口文档)
9. [数据源与容灾策略](#9-数据源与容灾策略)
10. [套利分析引擎](#10-套利分析引擎)
11. [部署与运行](#11-部署与运行)
12. [环境变量配置](#12-环境变量配置)

---

## 1. 项目概述

### 1.1 系统定位

QuantTerminal Pro（代号 Doraemon）是一个专为 **A股低风险套利、可转债轮动及大类资产配置** 设计的量化投资分析平台。系统 **不直接分析单只股票**，而是将正股数据作为可转债的定价支撑。

### 1.2 核心能力

| 模块 | 能力描述 |
|------|----------|
| 宏观看板 | ERP（股权风险溢价）、DR007/GC001 资金利率、核心指数估值百分位热力图 |
| LOF/ETF 套利 | 实时扫描场内基金折溢价状态，捕捉套利机会，量化 T+N 风险敞口 |
| 封闭基金分析 | 折价收敛路径分析、流动性风险评估、底层持仓信用风险 |
| 可转债扫描 | 多因子筛选（双低、YTM、溢价率）、转股套利可行性、IV/HV 波动率分析、条款触发进度 |
| 公募 REITs | NAV 溢折价套利、分红可持续性评估、流动性风险量化 |
| 策略管理 | 无代码/低代码策略构建器，支持多条件 AND/OR 逻辑组合 |
| AI 决策 | 基于真实行情数据生成每日投资决策报告，结合策略匹配与套利告警 |
| 预警中心 | 基于阈值的价格/折溢价/收益率报警，支持多渠道通知 |

### 1.3 数据流向

```
[AkShare WebAPI (192.168.3.53:8000)] ──> [FastAPI 后端 (8001)]
                                               │
                           ┌───────────────────┼───────────────────┐
                           ▼                   ▼                   ▼
                    [行情数据获取]      [套利分析引擎]      [DuckDB 本地存储]
                           │                   │                   │
                           └───────────┬───────┘                   │
                                       ▼                           │
                              [REST API (/api/v1)]                 │
                                       │                           │
                                       ▼                           │
                          [Vue 3 前端 (5173/5174)]  ◄──────────────┘
```

---

## 2. 系统架构

### 2.1 整体架构

系统采用 **前后端分离** 架构：

- **后端**：Python FastAPI，端口 8001，提供 RESTful API
- **前端**：Vue 3 + Vite + Naive UI，端口 5173（开发）/ 静态部署（生产）
- **数据库**：DuckDB（嵌入式分析型数据库），存储在 `backend/database/quantterminal.duckdb`
- **数据源**：AkShare WebAPI（运行在 192.168.3.53:8000），提供 A 股实时行情数据

### 2.2 后端分层架构

```
backend/
├── main.py              # FastAPI 应用入口，注册路由、CORS、生命周期
├── core/
│   ├── config.py        # 全局配置（环境变量、常量）
│   └── deps.py          # FastAPI 依赖注入（JWT 认证）
├── routers/             # API 路由层（12 个路由模块）
│   ├── auth_router.py
│   ├── market_router.py
│   ├── fund_router.py
│   ├── etf_router.py
│   ├── convertible_bond_router.py
│   ├── reits_router.py
│   ├── favorite_router.py
│   ├── portfolio_router.py
│   ├── strategy_router.py
│   ├── alert_router.py
│   ├── ai_router.py
│   └── monitor_router.py
├── services/            # 业务逻辑层（13 个服务模块）
│   ├── akshare_client.py     # 共享 AkShare WebAPI 客户端
│   ├── auth_service.py
│   ├── market_service.py
│   ├── fund_service.py
│   ├── etf_service.py
│   ├── convertible_bond_service.py
│   ├── reits_service.py
│   ├── favorite_service.py
│   ├── portfolio_service.py
│   ├── strategy_service.py
│   ├── alert_service.py
│   ├── ai_service.py
│   └── monitor_service.py
├── utils/               # 分析工具层
│   ├── arbitrage.py            # 套利可行性分析
│   ├── closed_fund.py          # 封闭基金分析
│   ├── convertible_bond.py    # 可转债分析
│   └── reits.py               # REITs 分析
├── models.py            # Pydantic 数据模型（请求/响应 Schema）
├── mock_data.py         # Mock 数据（离线模式）
├── database/
│   ├── connection.py    # DuckDB 连接管理
│   ├── schema.py        # 数据库 Schema（25 张表）
│   ├── init_db.py       # 数据库初始化脚本
│   └── quantterminal.duckdb  # DuckDB 数据文件
└── requirements.txt     # Python 依赖
```

### 2.3 前端架构

```
frontend/src/
├── main.ts              # 应用入口
├── App.vue              # 根组件
├── router/
│   └── index.ts         # Vue Router 路由配置（12 个页面）
├── layouts/
│   ├── AppLayout.vue   # 主布局（侧边栏 + 头部 + 内容区）
│   ├── AppHeader.vue   # 顶部导航栏
│   └── AppSidebar.vue  # 侧边导航栏
├── pages/               # 页面组件（12 个）
│   ├── Dashboard.vue          # 大类资产配置看板
│   ├── IndexAnalysis.vue      # 指数估值分析
│   ├── LofFunds.vue           # LOF 基金套利扫描
│   ├── ClosedFunds.vue        # 封闭基金
│   ├── ConvertibleBonds.vue   # 可转债扫描
│   ├── EtfFunds.vue           # ETF 基金策略
│   ├── Reits.vue              # 公募 REITs 分析
│   ├── PortfolioWatchlist.vue # 投资组合自选
│   ├── StrategyCenter.vue     # 策略管理中心
│   ├── AiDecisionHub.vue      # AI 决策中心
│   ├── AlertCenter.vue        # 预警中心
│   └── DataSources.vue        # 数据来源
├── components/          # 公共组件（18 个）
│   ├── BaseChart.vue          # ECharts 基础图表
│   ├── BoardSectorPanel.vue   # 板块涨幅面板
│   ├── FundFlowPanel.vue      # 资金流向面板
│   ├── FundRankingPanel.vue   # 基金排行面板
│   ├── MarketOverview.vue     # 市场概览面板
│   ├── ZTStatsPanel.vue       # 涨跌停统计面板
│   ├── DataPanel.vue          # 通用数据面板
│   ├── GlossaryPanel.vue      # 术语面板
│   ├── LoadingState.vue       # 加载状态
│   ├── SectionFallback.vue    # 错误兜底
│   ├── SectionSkeleton.vue    # 骨架屏
│   ├── StatCard.vue            # 统计卡片
│   ├── PageHeader.vue         # 页面头部
│   ├── TabBar.vue             # 标签栏
│   ├── CategoryTag.vue        # 分类标签
│   ├── FieldHelp.vue          # 字段帮助
│   ├── IconButton.vue         # 图标按钮
│   └── PercentileIndicator.vue # 百分位指示器
├── composables/         # 组合式函数（8 个）
│   ├── useApi.ts              # API 请求封装
│   ├── useMockData.ts         # Mock 数据
│   ├── useMarketData.ts       # 市场数据
│   ├── useDarkMode.ts         # 暗色模式
│   ├── useSidebar.ts          # 侧边栏状态
│   ├── useFieldHelp.ts       # 字段帮助
│   ├── glossaryContent.ts    # 术语内容
│   └── helpContent.ts        # 帮助内容
├── utils/               # 工具函数（7 个）
│   ├── api.ts                 # API 客户端
│   ├── echarts.ts             # ECharts 配置
│   ├── export.ts              # 数据导出
│   ├── arbitrage.ts           # 套利分析（前端版本）
│   ├── closedFund.ts          # 封闭基金分析（前端版本）
│   ├── convertibleBond.ts     # 可转债分析（前端版本）
│   └── reits.ts               # REITs 分析（前端版本）
├── types/
│   └── index.ts         # TypeScript 类型定义
└── style.css            # 全局样式
```

---

## 3. 技术栈

### 3.1 后端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | 运行时 |
| FastAPI | ≥0.110.0 | Web 框架 |
| Uvicorn | ≥0.27.0 | ASGI 服务器 |
| Pydantic | ≥2.6.0 | 数据验证 |
| DuckDB | ≥0.9.0 | 嵌入式分析数据库 |
| python-jose | ≥3.3.0 | JWT 认证 |
| passlib | ≥1.7.4 | 密码哈希 |
| requests | - | HTTP 客户端（调用 AkShare WebAPI） |

### 3.2 前端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | ^3.5.39 | 前端框架 |
| Vue Router | ^4.5.1 | 路由管理 |
| Naive UI | ^2.43.1 | UI 组件库 |
| ECharts | ^6.1.0 | 图表可视化 |
| Vue-ECharts | ^8.0.1 | Vue ECharts 封装 |
| @vicons/ionicons5 | ^0.13.0 | 图标库 |
| TypeScript | ~6.0.2 | 类型安全 |
| Vite | ^8.1.1 | 构建工具 |

---

## 4. 目录结构

```
doraemon/
├── backend/                    # 后端代码
│   ├── core/                   # 核心配置与依赖
│   ├── database/               # 数据库（DuckDB）
│   ├── routers/                # API 路由（12 模块）
│   ├── services/               # 业务逻辑（13 模块）
│   ├── utils/                  # 分析工具（4 模块）
│   ├── main.py                 # 应用入口
│   ├── models.py               # Pydantic 模型
│   ├── mock_data.py            # Mock 数据
│   └── requirements.txt        # Python 依赖
├── frontend/                   # 前端代码
│   ├── src/
│   │   ├── components/         # 公共组件（18 个）
│   │   ├── composables/        # 组合式函数（8 个）
│   │   ├── layouts/            # 布局组件（3 个）
│   │   ├── pages/              # 页面组件（12 个）
│   │   ├── router/             # 路由配置
│   │   ├── types/              # 类型定义
│   │   ├── utils/              # 工具函数（7 个）
│   │   ├── App.vue             # 根组件
│   │   └── main.ts             # 入口
│   ├── package.json            # Node 依赖
│   └── vite.config.ts          # Vite 配置
├── doc/                        # 项目文档
├── docs/                       # 设计文档（HTML 格式）
│   ├── api-design/             # API 设计文档
│   └── database-design/        # 数据库设计文档
├── ui/                         # UI 原型设计
└── package.json                # 根级依赖
```

---

## 5. 后端详解

### 5.1 应用入口 (`main.py`)

FastAPI 应用入口负责：
- **生命周期管理**：启动时连接数据库（或进入 Mock 模式），关闭时释放连接
- **CORS 中间件**：允许前端开发服务器（5173/5174）及所有来源（开发环境）
- **路由注册**：12 个业务路由模块统一挂载在 `/api/v1` 前缀下
- **健康检查**：`/health` 和 `/` 端点

运行命令：
```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

### 5.2 配置管理 (`core/config.py`)

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| `DB_PATH` | `DB_PATH` | `backend/database/quantterminal.duckdb` | DuckDB 文件路径 |
| `JWT_SECRET` | `JWT_SECRET` | `quantterminal-secret-key-change-in-production` | JWT 签名密钥 |
| `JWT_ALGORITHM` | - | `HS256` | JWT 算法 |
| `JWT_EXPIRE_HOURS` | `JWT_EXPIRE_HOURS` | `24` | Token 有效期（小时） |
| `API_PREFIX` | - | `/api/v1` | API 路由前缀 |
| `APP_NAME` | - | `QuantTerminal Pro` | 应用名称 |
| `APP_VERSION` | - | `1.0.0` | 应用版本 |
| `USE_MOCK_DATA` | `USE_MOCK_DATA` | `false` | 是否使用 Mock 数据 |
| `AKSHARE_API_BASE` | `AKSHARE_API_BASE` | `http://192.168.3.53:8000` | AkShare WebAPI 地址 |

### 5.3 认证系统 (`core/deps.py`)

采用 **JWT + OAuth2 Password Bearer** 认证方案：

- `create_access_token(data)`：创建 JWT Token，有效期 24 小时
- `get_current_user(token)`：验证 Token 并返回用户 ID
  - **开发模式**：未携带 Token 时返回 `demo-user`，保证受保护接口在未登录时也可正常返回数据
  - 有效 Token 优先于 demo 用户
  - 生产环境应恢复为：无效 Token 返回 401
- `get_optional_user(token)`：可选认证，Token 无效返回 None

### 5.4 API 路由层

所有路由统一使用 `ApiResponse[T]` 包装响应：

```python
class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: Optional[T] = None
    meta: Optional[dict[str, Any]] = None  # 数据来源标记
```

`meta` 字段携带数据来源信息（`isMock`、`dataSource`、`mockTime`、`updateTime`），供前端展示"模拟/真实数据"横幅。

#### 路由模块总览

| 路由模块 | 前缀 | 标签 | 认证 | 主要端点 |
|----------|------|------|------|----------|
| `auth_router` | `/api/v1/auth` | auth | 无 | `POST /login` |
| `market_router` | `/api/v1/market` | market | 无 | `GET /macro/indicators`, `GET /overview`, `GET /board-sectors`, `GET /fund-flows`, `GET /zt-stats`, `GET /fund-ranking`, `GET /indices`, `GET /indices/{code}/history`, `GET /quote/kline` |
| `fund_router` | `/api/v1` | funds | 无 | `GET /funds`, `GET /funds/closed/analysis` |
| `etf_router` | `/api/v1/etf` | etfs | 无 | `GET /etfs`, `GET /etfs/arbitrage` |
| `cb_router` | `/api/v1/cb` | convertible-bonds | 无 | `GET /convertible-bonds`, `GET /convertible-bonds/{code}` |
| `reits_router` | `/api/v1/reits` | reits | 无 | `GET /reits` |
| `favorite_router` | `/api/v1/favorites` | favorites | JWT | `GET /`, `POST /`, `DELETE /{id}` |
| `portfolio_router` | `/api/v1/portfolios` | portfolios | JWT | `GET /`, `POST /{id}/items` |
| `strategy_router` | `/api/v1/strategies` | strategies | JWT | `GET /`, `POST /`, `PUT /{id}`, `DELETE /{id}`, `POST /{id}/execute` |
| `alert_router` | `/api/v1/alerts` | alerts | JWT | `GET /rules`, `POST /rules`, `PUT /rules/{id}`, `DELETE /rules/{id}`, `GET /events`, `PUT /events/{id}/read` |
| `ai_router` | `/api/v1/ai` | ai | JWT | `GET /reports`, `POST /reports/generate`, `GET /config`, `PUT /config` |
| `monitor_router` | `/api/v1/monitor` | monitor | 无 | `GET /dashboard`, `GET /config/{method}`, `POST /config` |

### 5.5 服务层

#### 5.5.1 数据获取服务

**AkShare WebAPI 客户端** (`services/akshare_client.py`)

统一封装对 AkShare WebAPI 的调用，遵循 **"真实优先、失败返回 None"** 原则：
- `akshare_request(method, params, retries, timeout)`：调用 `/api/ak` 通用接口
- 自动重试（默认 3 次，超时 30 秒）
- 失败返回 None，上层应返回空/缺省结构，**绝不使用 mock 数据填充**

**Market Service** (`services/market_service.py`)

市场数据服务提供三种 API 调用方式：
- `_akshare_request()`：调用 `/api/ak` 通用 AkShare 接口
- `_processed_data_request()`：调用 `/api/processed_data` 加工数据接口（如 `index_valuation`、`board`、`fund_flow`、`market_stats`、`zt_pool`、`fund_rank`）
- `_quote_request()`：调用 `/api/quote/*` 行情直连接口

核心功能：
- `get_macro_indicators_with_meta()`：宏观指标（ERP / DR007 / GC001），含 1 小时缓存
- `get_market_overview_with_meta()`：市场概况（指数行情 + 涨跌家数 + 成交额）
- `get_board_sectors_with_meta()`：板块涨幅排行（按涨跌幅降序取前 6）
- `get_fund_flows_with_meta()`：资金流向（含降级策略：东财不可用时改用板块代理）
- `get_zt_stats_with_meta()`：涨跌停统计
- `get_fund_ranking_with_meta()`：基金涨跌排行
- `get_indices_with_meta()`：指数估值列表（含 PE/PB 百分位分类）
- `get_index_history()` / `get_kline()`：K 线历史数据

**Fund Service** (`services/fund_service.py`)

LOF/QDII/封闭基金数据服务：
- `get_funds()`：基金列表（含套利分析），支持类型/溢价率/可行性过滤
- `get_closed_fund_analysis()`：封闭基金深度分析（按评分降序）
- `get_closed_funds_real()`：封闭基金真实数据获取
  - 优先集思录封基列表（字段最全），失败回退 53 fund_rank + 腾讯行情补全
- `_get_closed_quotes_tencent()`：腾讯 qt.gtimg.cn 封闭基金场内行情
- `get_fund_nav_eastmoney()`：天天基金净值源（1 小时缓存）

**ETF Service** (`services/etf_service.py`)

ETF 基金数据服务：
- `get_etfs()`：ETF 列表（含套利分析），支持分类/策略/溢价率过滤
- `get_etf_arbitrage_opportunities()`：ETF 套利机会（溢价率 > 0，按可行性和净收益排序）
- 数据源：53 fund_rank(etf)

**Convertible Bond Service** (`services/convertible_bond_service.py`)

可转债数据服务：
- `get_convertible_bonds()`：可转债列表（含转股套利 + 波动率分析），支持多因子过滤
- `get_convertible_bond_detail(code)`：可转债详情
- 数据源策略：东方财富 `bond_zh_cov`（全量 ~1000+ 只）→ 集思录 `bond_cb_jsl` 兜底
- 字段补全：
  - 双低值：按 价格 + |溢价率| 近似（集思录定义）
  - 剩余年限：由申购日期 + 6 年估算
  - YTM：教科书近似公式 `YTM ≈ [C + (F−P)/n] / [(F+P)/2]`，标记 `ytm_approx=True`

**REITs Service** (`services/reits_service.py`)

公募 REITs 数据服务：
- `get_reits()`：REITs 列表（含深度分析），支持资产类型/分红率/NAV/可持续性过滤
- 数据源策略：53 东财 `reits_realtime_em` → 腾讯 qt.gtimg.cn 兜底（含 5 分钟冷却期）
- 基本面字段（分红率/IRR/出租率等）AkShare 实时接口无法获取，统一返回 null

#### 5.5.2 用户数据服务

**Favorite Service** (`services/favorite_service.py`)

用户自选股 CRUD，支持 Mock 模式和 DuckDB 持久化。

**Portfolio Service** (`services/portfolio_service.py`)

用户投资组合管理，支持 Mock 模式和 DuckDB 持久化。

**Strategy Service** (`services/strategy_service.py`)

策略管理 CRUD + 执行引擎：
- 策略创建支持多条件 AND 逻辑组合
- 字段映射：中文规则字段 → 数据集字段（如 "价格" → "price"）
- 策略执行：根据 `target_asset` 选择数据集（cb/lof/etf/reit），逐条匹配规则
- 支持操作符：`<`、`>`、`<=`、`>=`、`==`、`属于`（逗号分隔成员检查）

**Alert Service** (`services/alert_service.py`)

预警规则 CRUD + 事件管理（内存态实现）。

**AI Service** (`services/ai_service.py`)

AI 报告生成 + 配置管理：
- `generate_ai_report()`：基于真实行情数据生成报告
  - 宏观判断取自真实 ERP（失败则如实说明数据缺失）
  - 策略匹配取自已激活策略的执行结果
  - 套利告警取自真实 ETF 数据（溢价率 > 5% 阈值）
- 配置管理：支持 OpenAI/DeepSeek/Claude 等模型，含 Cron 定时任务配置

**Monitor Service** (`services/monitor_service.py`)

系统监控仪表盘 + 缓存配置管理（内存态实现）。

---

## 6. 前端详解

### 6.1 路由配置

12 个页面路由，均采用 **懒加载**（`() => import(...)`）：

| 路径 | 组件 | 标题 | 图标 |
|------|------|------|------|
| `/dashboard` | Dashboard | 大类资产配置看板 | dashboard |
| `/index-analysis` | IndexAnalysis | 指数估值分析 | analytics |
| `/lof-funds` | LofFunds | LOF基金套利扫描 | account_balance |
| `/closed-funds` | ClosedFunds | 封闭基金 | lock |
| `/convertible-bonds` | ConvertibleBonds | 可转债扫描 | currency_exchange |
| `/etf-funds` | EtfFunds | ETF基金策略 | swap_horiz |
| `/portfolio-watchlist` | PortfolioWatchlist | 投资组合自选 | star |
| `/reits` | Reits | 公募REITs分析 | account_balance |
| `/alert-center` | AlertCenter | 预警中心 | notifications |
| `/strategy-center` | StrategyCenter | 策略管理中心 | tune |
| `/ai-decision` | AiDecisionHub | AI决策中心 | psychology |
| `/data-sources` | DataSources | 数据来源 | server |

根路径 `/` 自动重定向到 `/dashboard`。

### 6.2 API 客户端 (`utils/api.ts`)

- 基础地址：`VITE_API_BASE` 环境变量，默认 `http://192.168.3.53:8001`
- `requestWithMeta<T>()`：发送请求并返回 `{ data, meta }`，`meta` 为后端数据来源标记
- `request<T>()`：简化版，仅返回 `data`
- `ApiError`：自定义错误类，携带 HTTP 状态码和响应体
- AI 报告字段适配：后端 snake_case → 前端 camelCase

### 6.3 组合式函数

- `useAsyncData<T>(fetcher)`：封装 API 调用，提供 `data`、`loading`、`error`、`refresh` 响应式状态
- `useAsyncMock<T>(mockData, delay)`：Mock 异步 composable，模拟网络延迟
- `useMarketData()`：市场数据获取
- `useDarkMode()`：暗色模式切换
- `useSidebar()`：侧边栏状态管理（移动端开/关）

### 6.4 布局组件

**AppLayout**：主布局，包含侧边栏 + 顶部导航 + 内容区  
**AppHeader**：顶部导航栏  
**AppSidebar**：侧边导航栏，12 个导航项，响应式设计（桌面 240px / 平板 200px / 移动端抽屉）

---

## 7. 数据库设计

### 7.1 概述

使用 **DuckDB** 嵌入式分析数据库，共 **25 张表**：
- 15 张数据源表（`base_` 前缀）：存储外部行情数据
- 10 张业务表（`biz_` 前缀）：存储用户数据、策略、预警、AI

### 7.2 命名规范

| 规则 | 示例 | 说明 |
|------|------|------|
| 数据源表前缀 | `base_` | 来自外部数据源的行情数据 |
| 业务表前缀 | `biz_` | 用户数据、策略、预警等 |
| 主键列名 | `pk_` + 表名 | 如 `pk_indices` |
| 外键列名 | `fk_` + 引用表名 | 如 `fk_stocks` |
| 无外键约束 | - | 完整性在应用层管理 |

### 7.3 数据源表 (15 张)

| 表名 | 说明 | 关键字段 |
|------|------|----------|
| `base_indices` | 指数基本信息 | code, name, market, category |
| `base_index_valuations` | 指数每日估值 | pe, pb, pe_percentile, pb_percentile |
| `base_kline_data` | K 线行情 | open, close, high, low, volume |
| `base_funds` | 基金基本信息 | code, name, type, credit_rating |
| `base_fund_daily_quotes` | 基金每日行情 | price, iopv, premium_pct, net_arbitrage_yield |
| `base_etf_funds` | ETF 基本信息 | code, name, category, sub_category |
| `base_etf_daily_quotes` | ETF 每日行情 | 含套利/网格/轮动/定投四策略字段 |
| `base_stocks` | 正股基本信息 | code, name, is_st_risk, altman_z_score |
| `base_convertible_bonds` | 可转债基本信息 | code, name, rating, remaining_years |
| `base_cb_daily_quotes` | 可转债每日行情 | price, conv_value, premium_pct, ytm, iv, hv |
| `base_stock_daily_quotes` | 正股每日行情 | price, change_pct |
| `base_reits` | REITs 基本信息 | code, name, project_name, asset_type |
| `base_reit_daily_quotes` | REITs 每日行情 | market_price, nav, dividend_rate, irr |
| `base_macro_indicators` | 宏观指标定义 | code, name, description |
| `base_macro_daily` | 宏观指标每日值 | value, percentile_3y/5y/10y |

### 7.4 业务表 (10 张)

| 表名 | 说明 | 关键字段 |
|------|------|----------|
| `biz_users` | 用户表 | username, email, password_hash |
| `biz_favorites` | 自选股 | user_id, code, name, type, note |
| `biz_portfolios` | 投资组合 | user_id, name |
| `biz_portfolio_items` | 持仓明细 | portfolio_id, code, quantity, cost_price |
| `biz_strategies` | 筛选策略 | user_id, name, target_asset, active |
| `biz_strategy_rules` | 策略规则 | strategy_id, field, operator, value, logic |
| `biz_alert_rules` | 预警规则 | user_id, name, type, target, condition, value, channels |
| `biz_alert_events` | 预警触发事件 | rule_id, triggered_at, target_code, actual_value |
| `biz_ai_reports` | AI 分析报告 | user_id, report_date, macro_assessment |
| `biz_ai_configs` | AI 配置 | user_id, provider, api_key, temperature, cron_expression |

### 7.5 索引设计

- **唯一索引**：代码唯一约束（如 `uq_indices_code`）、复合唯一约束（标的 + 交易日仅一条快照）
- **核心查询索引**：按标的 + 日期范围查询（`idx_iv_index_date` 等）
- **用户数据索引**：按用户 ID 查询（`idx_fav_users` 等）
- **筛选优化索引**：双低筛选（价格 + 溢价率）、折价排序、高溢价套利

### 7.6 数据库初始化

```bash
cd backend
python -m database.init_db              # 创建表（幂等）
python -m database.init_db --rebuild    # 删除并重建
python -m database.init_db --verify     # 仅验证现有 Schema
```

---

## 8. API 接口文档

### 8.1 通用响应格式

```json
{
  "code": 200,
  "message": "success",
  "data": { ... },
  "meta": {
    "isMock": false,
    "dataSource": "AkShare WebAPI (192.168.3.53:8000)",
    "updateTime": "2026-08-15 14:30:00"
  }
}
```

### 8.2 认证接口

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/v1/auth/login` | 用户登录，返回 JWT Token | 无 |

### 8.3 市场数据接口

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/api/v1/market/macro/indicators` | 宏观指标（ERP/DR007/GC001） | - |
| GET | `/api/v1/market/overview` | 市场概况（指数+涨跌+成交额） | - |
| GET | `/api/v1/market/board-sectors` | 板块涨幅排行 | - |
| GET | `/api/v1/market/fund-flows` | 资金流向 | - |
| GET | `/api/v1/market/zt-stats` | 涨跌停统计 | - |
| GET | `/api/v1/market/fund-ranking` | 基金涨跌排行 | - |
| GET | `/api/v1/market/indices` | 指数估值列表 | `category`, `date` |
| GET | `/api/v1/market/indices/{code}/history` | 指数 K 线历史 | `code`, `start_date`, `end_date` |
| GET | `/api/v1/market/quote/kline` | 个股/ETF K 线 | `code`, `type`, `start_date`, `end_date` |

### 8.4 基金接口

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/api/v1/funds` | 基金列表（含套利分析） | `type`, `min_premium`, `feasibility`, `date` |
| GET | `/api/v1/funds/closed/analysis` | 封闭基金分析 | - |

### 8.5 ETF 接口

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/api/v1/etf/etfs` | ETF 列表 | `category`, `strategy`, `min_premium`, `feasibility` |
| GET | `/api/v1/etf/etfs/arbitrage` | ETF 套利机会 | - |

### 8.6 可转债接口

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/api/v1/cb/convertible-bonds` | 可转债列表 | `price_min/max`, `premium_max`, `rating`, `ytm_min`, `double_low_max`, `feasibility`, `vol_signal` |
| GET | `/api/v1/cb/convertible-bonds/{code}` | 可转债详情 | `code` |

### 8.7 REITs 接口

| 方法 | 路径 | 说明 | 参数 |
|------|------|------|------|
| GET | `/api/v1/reits/reits` | REITs 列表 | `asset_type`, `min_dividend`, `nav_level`, `sustainability` |

### 8.8 自选股接口 (需认证)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/favorites` | 获取自选列表 |
| POST | `/api/v1/favorites` | 添加自选 |
| DELETE | `/api/v1/favorites/{id}` | 删除自选 |

### 8.9 投资组合接口 (需认证)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/portfolios` | 获取组合列表 |
| POST | `/api/v1/portfolios/{id}/items` | 添加持仓 |

### 8.10 策略接口 (需认证)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/strategies` | 获取策略列表 |
| POST | `/api/v1/strategies` | 创建策略 |
| PUT | `/api/v1/strategies/{id}` | 更新策略 |
| DELETE | `/api/v1/strategies/{id}` | 删除策略 |
| POST | `/api/v1/strategies/{id}/execute` | 执行策略筛选 |

### 8.11 预警接口 (需认证)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/alerts/rules` | 获取预警规则列表 |
| POST | `/api/v1/alerts/rules` | 创建预警规则 |
| PUT | `/api/v1/alerts/rules/{id}` | 更新预警规则 |
| DELETE | `/api/v1/alerts/rules/{id}` | 删除预警规则 |
| GET | `/api/v1/alerts/events` | 获取预警事件（分页） |
| PUT | `/api/v1/alerts/events/{id}/read` | 标记事件已读 |

### 8.12 AI 接口 (需认证)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/ai/reports` | 获取 AI 报告列表（分页） |
| POST | `/api/v1/ai/reports/generate` | 生成 AI 报告 |
| GET | `/api/v1/ai/config` | 获取 AI 配置 |
| PUT | `/api/v1/ai/config` | 更新 AI 配置 |

### 8.13 监控接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/monitor/monitor/dashboard` | 系统仪表盘 |
| GET | `/api/v1/monitor/config/{method}` | 获取缓存配置 |
| POST | `/api/v1/monitor/config` | 更新缓存配置 |

---

## 9. 数据源与容灾策略

### 9.1 数据源架构

系统从 **AkShare WebAPI** (运行在 192.168.3.53:8000) 获取真实行情数据，提供三类 API 入口：

| 入口 | 路径 | 用途 | 典型 category |
|------|------|------|---------------|
| 通用 AkShare 接口 | `/api/ak` | 调用 akshare 原始方法 | `stock_zh_index_daily`, `bond_zh_cov` |
| 加工数据接口 | `/api/processed_data` | 获取预处理后的聚合数据 | `index_valuation`, `board`, `fund_flow`, `market_stats`, `zt_pool`, `fund_rank` |
| 行情直连接口 | `/api/quote/*` | 专用行情接口 | `quote/realtime`, `quote/kline` |

### 9.2 多源容灾链

系统采用 **多数据源 + 降级容灾** 策略，确保数据可用性：

| 数据类型 | 主源 | 降级源 | 容灾策略 |
|----------|------|--------|----------|
| 指数估值 | 53 processed_data/index_valuation | - | 失败返回空列表 |
| 板块涨幅 | 53 processed_data/board(industry_spot) | - | 失败返回空列表 |
| 资金流向 | 53 processed_data/fund_flow(market) | 53 board(industry_spot) 代理 | 东财大盘主力净流入不可用时改用板块代理 |
| 涨跌停 | 53 processed_data/zt_pool | - | 失败返回空结构 |
| 基金排行 | 53 processed_data/fund_rank | - | 失败返回空列表 |
| 封闭基金 | 53 jisilu/closed_fund | 53 fund_rank(closed) + 腾讯 qt.gtimg.cn | 集思录优先，失败回退 53+腾讯 |
| 可转债 | 东方财富 bond_zh_cov | 集思录 bond_cb_jsl | 主源全量 ~1000+，兜底 30 条 |
| ETF | 53 processed_data/fund_rank(etf) | - | 失败返回空列表 |
| REITs | 53 东财 reits_realtime_em | 腾讯 qt.gtimg.cn | 东财源被掐后进入 5 分钟冷却期直连腾讯 |
| 基金净值 | 53 fund_rank | 天天基金 pingzhongdata | 53 未给净值时降级天天基金 CDN |

### 9.3 缓存策略

| 缓存对象 | 缓存位置 | TTL | 说明 |
|----------|----------|-----|------|
| 宏观指标 (DR007/GC001/ERP) | 后端内存 (`_MACRO_CACHE`) | 1 小时 | 日内变化小，避免重复请求 |
| 天天基金净值 | 后端内存 (`_NAV_CACHE`) | 1 小时 | 净值日频更新 |
| 东财 REITs 源不可用标记 | 后端内存 (`_EASTMONEY_REITS_DEAD_UNTIL`) | 5 分钟 | 冷却期内跳过东财直连腾讯 |

### 9.4 数据真实性原则

系统严格遵循 **"真实优先、失败返回空"** 原则：

1. **默认连接真实数据源**：`USE_MOCK_DATA=false`（默认）
2. **取数失败返回空/缺省结构**：绝不使用 mock 数据填充（仅 `USE_MOCK_DATA=true` 时使用）
3. **缺失字段返回 null**：不虚构数值（如 REITs 基本面字段、成交额等）
4. **近似值明确标注**：如可转债 YTM 近似估算标记 `ytm_approx=True`
5. **数据来源标记**：通过 `ApiResponse.meta` 返回 `isMock`、`dataSource` 供前端展示

---

## 10. 套利分析引擎

### 10.1 LOF/ETF 折溢价套利 (`utils/arbitrage.py`)

**核心问题**：
1. 申购限额产品收益归零（QDII/跨境 ETF 外汇额度限制）
2. T+N 敞口量化（跨境 ETF T+2 结算，净值波动风险）

**交易成本模型**：
| 成本项 | 费率 |
|--------|------|
| 申购费率 | 0.15% |
| 卖出佣金 | 0.03% |
| 冲击成本 | 0.05% |
| **总成本** | **0.23%** |

**资金容量分级**：
| 等级 | 条件 | 标签 | 可行性 |
|------|------|------|--------|
| A | 无限购或 > 1 万元 | 无限购/限购 N 元 | 可行 |
| B | ≤ 1 万元 | 限购 N 元 | 有风险 |
| C | ≤ 1 千元或暂停申购 | 限购 N 元/暂停申购 | 不可行 |

**风险量化**（95% 单边 VaR）：
```
风险敞口 = 1.65 × 日波动率 × √持有天数
```

**可行性判定逻辑**：
1. 停牌 → 不可行
2. 资金等级 C → 不可行，收益归零
3. 调整后收益下限 < 0 → 有风险（T+N 敞口可能吞噬利润）
4. 资金等级 B → 有风险
5. 其他 → 可行

### 10.2 封闭基金分析 (`utils/closed_fund.py`)

**三维分析**：
1. **流动性风险**：成交额 < 10 万 → 极差；< 30 万 → 一般；≥ 30 万 → 充足
2. **折价收敛路径**：
   - 转 LOF → 确定收敛
   - 剩余 < 180 天 → 大概率收敛
   - 其他 → 不确定
3. **底层信用风险**：AAA → 安全；AA 系 → 关注；无评级 → 风险

**评分模型**（满分 100）：
| 维度 | 权重 | 评分逻辑 |
|------|------|----------|
| 年化收敛收益率 | 40 分 | min(收敛收益率 × 3, 40) |
| 收敛确定性 | 25 分 | 确定 25 / 大概率 15 / 不确定 5 |
| 流动性 | 20 分 | 充足 20 / 一般 10 / 极差 0 |
| 信用风险 | 15 分 | 安全 15 / 关注 8 / 风险 0 |

### 10.3 可转债分析 (`utils/convertible_bond.py`)

#### 10.3.1 转股套利可行性

套利路径：买入可转债 → 转股 → 卖出正股

**四大阻断条件**：
1. 正股停牌 → 转股后无法卖出
2. 正股涨停 → 无法卖出
3. 未进入转股期 → 无法转股
4. T+1 隔夜风险 > 套利收益

**可行性判定**：
| 条件 | 结果 |
|------|------|
| 非负溢价 | 不适用 (n/a) |
| 停牌/涨停/未进转股期 | 不可行 |
| 隔夜风险 > 套利收益 | 有风险 |
| 其他（负溢价且无阻断） | 可行 |

#### 10.3.2 波动率分析 (IV vs HV)

| 信号 | 条件 | 含义 | 建议 |
|------|------|------|------|
| IV 低估 | IV < HV × 0.85 | 转债期权被低估 | 买入转债 + 融券正股做 Delta 对冲 |
| IV 高估 | IV > HV × 1.15 | 转债期权被高估 | 卖出转债或做空期权部分 |
| 合理 | 0.85 ≤ IV/HV ≤ 1.15 | 波动率合理 | 无套利信号 |
| 数据缺失 | IV=0 或 HV=0 | 数据不足 | 无法判断 |

### 10.4 REITs 分析 (`utils/reits.py`)

**三维分析**：
1. **NAV 溢折价套利**：
   - 溢价率 < -3% → 折价（安全垫）
   - 溢价率 > 3% → 溢价（追高风险）
   - ±3% 以内 → 合理区间

2. **分红可持续性**（DSCR + 出租率趋势 + 杠杆率）：
   - DSCR < 1.2 → +2 分风险
   - 出租率下降 > 3% → +2 分风险
   - 杠杆率 > 40% → +2 分风险
   - 风险分 ≥ 3 → 可持续性差；≥ 1 → 需关注；0 → 可持续

3. **流动性风险**：成交量 < 50 万 → 极差；< 150 万 → 一般；≥ 150 万 → 充足

**评分模型**（满分 100）：
| 维度 | 权重 |
|------|------|
| 分红率 | min(分红率 × 5, 30) |
| IRR | min(IRR × 3, 10) |
| NAV 级别 | 折价 20 / 合理 10 / 溢价 0 |
| 可持续性 | 可持续 25 / 关注 12 / 差 0 |
| 流动性 | 充足 15 / 一般 8 / 极差 0 |

---

## 11. 部署与运行

### 11.1 后端部署

```bash
# 1. 安装依赖
cd backend
pip install -r requirements.txt

# 2. 初始化数据库（首次）
python -m database.init_db

# 3. 启动服务（开发模式）
uvicorn main:app --reload --host 0.0.0.0 --port 8001

# 4. 启动服务（生产模式）
uvicorn main:app --host 0.0.0.0 --port 8001
```

API 文档自动生成：
- Swagger UI: `http://localhost:8001/docs`
- ReDoc: `http://localhost:8001/redoc`

### 11.2 前端部署

```bash
# 1. 安装依赖
cd frontend
npm install

# 2. 开发模式启动
npm run dev

# 3. 生产构建
npm run build

# 4. 预览构建结果
npm run preview
```

### 11.3 端口规划

| 服务 | 端口 | 说明 |
|------|------|------|
| AkShare WebAPI | 8000 | 金融数据聚合服务（192.168.3.53） |
| 后端 API | 8001 | FastAPI 应用 |
| 前端开发服务器 | 5173 | Vite dev server |
| 前端备选端口 | 5174 | Vite dev server（端口冲突时） |

---

## 12. 环境变量配置

### 12.1 后端环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DB_PATH` | `backend/database/quantterminal.duckdb` | DuckDB 数据文件路径 |
| `JWT_SECRET` | `quantterminal-secret-key-change-in-production` | JWT 签名密钥（生产环境必须修改） |
| `JWT_EXPIRE_HOURS` | `24` | Token 有效期（小时） |
| `USE_MOCK_DATA` | `false` | 是否使用 Mock 数据模式 |
| `AKSHARE_API_BASE` | `http://192.168.3.53:8000` | AkShare WebAPI 地址 |

### 12.2 前端环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `VITE_API_BASE` | `http://192.168.3.53:8001` | 后端 API 地址 |

前端 `.env.example` 示例：
```
VITE_API_BASE=http://localhost:8001
```

### 12.3 Mock 数据模式

设置 `USE_MOCK_DATA=true` 启用离线模式：
- 后端不连接数据库和 AkShare WebAPI
- 所有接口返回 `mock_data.py` 中的预设数据
- 受保护接口使用固定 demo 用户 (`demo-user`)
- 适用于纯演示/离线场景

---

## 附录

### A. 示例用户

| 用户名 | 密码 | 说明 |
|--------|------|------|
| `trader` | `trader123` | 演示用户 |

### B. 相关文档

| 文档 | 路径 | 说明 |
|------|------|------|
| PRD 需求文档 | `doc/readme.md` | 产品需求文档（含 7 个核心页面设计） |
| API 设计文档 | `docs/api-design/api-design.html` | API 设计 HTML 文档 |
| 数据库设计文档 | `docs/database-design/database-design.html` | 数据库设计 HTML 文档 |
| 后端 API 设计 | `doc/backend_api_design.md` | 后端 API Markdown 文档 |
| 数据库设计 | `doc/database_design.md` | 数据库 Markdown 文档 |