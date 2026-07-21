# 金融数据聚合服务 API 文档

统一金融数据网关，聚合多市场、多数据源行情与基本面数据，提供高可用、低延迟的数据获取能力。

所有内部系统需要获取金融数据时，严禁直接在本地项目引入 Akshare / Pandas / TqSdk / yfinance 等数据源 SDK，必须统一通过本服务的 HTTP 接口调用。

---

## 1. 架构概览

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      客户端 / 前端                            │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP REST (JSON)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI 网关层 (main.py)                    │
│    ┌──────────┬──────────┬──────────┬──────────────────┐    │
│    │ /api/ak  │ /api/quote/* │ /api/us/*  │ /api/monitor/* │    │
│    │ /api/hk/*│ /api/yf/* │ /api/futu/*│ /api/datasource/*│    │
│    └────┬─────┴─────┬────┴─────┬────┴────────┬─────────┘    │
└─────────┼───────────┼──────────┼──────────────┼──────────────┘
          │           │          │              │
     ┌────▼───┐ ┌────▼───┐ ┌───▼────┐  ┌──────▼───────┐
     │Worker  │ │ 线程池  │ │线程池   │  │  直接 HTTP    │
     │进程池   │ │(行情)  │ │(期货分析)│  │  请求数据源    │
     └───┬────┘ └───┬────┘ └───┬────┘  └──────┬───────┘
         │          │          │              │
    ┌────▼──────────▼──────────▼──────────────▼──────┐
    │              数据源层 (Data Sources)              │
    │  ┌─────────┐ ┌──────┐ ┌──────┐ ┌───────────┐   │
    │  │ AkShare │ │ 东财  │ │ 腾讯  │ │ YahooFinance│  │
    │  │ (进程池) │ │ 新浪  │ │ TDX  │ │ Futu OpenD│  │
    │  │ TqSdk   │ │ QQ   │ │ 其他  │ │           │   │
    │  └─────────┘ └──────┘ └──────┘ └───────────┘   │
    └─────────────────────────────────────────────────┘
         │                    │
    ┌────▼────┐          ┌───▼───────┐
    │ Redis   │          │  MySQL     │
    │ (L1缓存) │          │ (L2缓存 +   │
    │         │          │  业务数据)  │
    └─────────┘          └───────────┘
```

### 1.2 核心能力

| 能力 | 说明 |
|------|------|
| **多数据源聚合** | 整合 AkShare、东方财富、腾讯财经、新浪财经、通达信、TqSdk、yfinance、富途 OpenD 等十余个数据源 |
| **全市场覆盖** | A股、港股、美股、期货、期权、基金、债券、外汇、宏观指数、全球市场 |
| **多源容灾** | 实时行情三源容灾（东财 → QQ → 新浪），K线四源容灾（QQ → 新浪 → 东财 → TDX），自动故障切换 |
| **二级缓存** | Redis L1（毫秒级热点缓存）+ MySQL L2（持久化冷备份），自动序列化与过期管理 |
| **进程隔离** | AkShare 在独立 ProcessPoolExecutor 中运行，防止内存泄漏影响网关进程 |
| **健康监控** | 内置监控仪表盘、数据源探活、慢请求追踪、告警系统 |
| **动态路由** | 数据源路由模块支持自动偏好学习、动态优先级调整、手动启用/禁用 |

### 1.3 请求处理流程

```
客户端请求 → FastAPI 路由匹配 → 权限/参数校验
  ├─ /api/ak ──→ 查缓存配置 → L1命中? → L2命中? → Worker进程池 → AkShare
  ├─ /api/quote/* ──→ 数据源路由 → 按容灾链尝试 → 直连行情源HTTP API
  ├─ /api/us/* ──→ 线程池 → 美股数据源
  ├─ /api/hk/* ──→ 线程池 → 港股数据源
  ├─ /api/yf/* ──→ 线程池 → Yahoo Finance
  └─ /api/futu/* ──→ 线程池 → Futu OpenD (需本地运行)
```

### 1.4 缓存架构

| 层级 | 存储 | 延迟 | 容量 | 过期策略 |
|------|------|------|------|----------|
| L1 | Redis | <5ms | 内存有限 | TTL 秒级过期（按方法配置） |
| L2 | MySQL | <50ms | 无限 | 按天增量更新，历史数据持久化 |

缓存配置通过 `/api/config` 接口统一管理，支持每个方法独立配置 L1/L2 开关和 TTL。

### 1.5 数据源容灾机制

每个数据类型维护一个有序的容灾链，请求时按优先级依次尝试：

```
realtime:   eastmoney(首选) → qq(备用) → sina(最后)
kline:      qq(首选) → sina → eastmoney → tdx
spot:       腾讯(首选) → 新浪(备用) → 东财(兜底)
futures:    tqsdk(首选) → akshare(备用)
```

- 成功的数据源会被偏好缓存记录，后续同类型请求优先尝试
- 连续失败的数据源自动降级，成功率恢复后自动回迁
- 支持手动重置/启用/禁用任意数据源

---

## 2. 基础信息

- **服务名称**: 金融数据聚合服务 (Financial Data Gateway)
- **Base URL**: `http://<服务器IP>:8000`
- **数据格式**: 请求参数走 URL Query，返回结果统一为 JSON
- **编码**: UTF-8
- **版本**: v2.0.0
- **启动命令**: `uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2`
- **Python 版本**: 3.10+
- **关键依赖**: FastAPI, akshare, redis, sqlalchemy, pytdx(可选), tqsdk(可选), futu-api(可选)

---

## 3. API 接口列表

### 3.1 健康检查

**路径**: `/health`
**方法**: GET
**功能**: 检查服务本身、数据库、Redis 以及子进程池的状态。

**返回示例**:
```json
{
  "status": "up",
  "components": {
    "db": "ok",
    "redis": "ok",
    "worker": "isolated"
  }
}
```

---

### 3.2 获取 Akshare 数据 (核心接口)

**路径**: `/api/ak`
**方法**: GET
**功能**: 代理调用任何合法的 Akshare 接口，并应用两级缓存策略。

#### 请求参数 (Query Parameters)

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| method | String | 是 | 调用的 Akshare 方法名，如 stock_zh_a_hist |
| [**kwargs] | 动态 | 根据方法 | Akshare 原生业务参数 |

**注意**: L1/L2 缓存策略通过 `/api/config` 接口统一管理，不支持在请求时动态覆盖。

**特殊处理**: 以下方法使用 DB 代理查询（直接从数据库读取，不通过 Akshare worker）：
- `fund_purchase_em` — 基金持仓数据
- `stock_fhps_em` — 分红派息数据
- `index_stock_cons` — 指数成分股数据

#### 响应结构

**成功响应 (HTTP 200)**:
```json
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "日期": "2023-01-03",
      "开盘": 14.5,
      "收盘": 15.2,
      "成交量": 1234567
    }
  ]
}
```

**错误响应 (HTTP 500)**:
```json
{
  "code": 500,
  "message": "Akshare调用失败: 该股票代码不存在...",
  "data": null
}
```

#### X-Data-Expired 响应头

如果触发了 Akshare 源站封控或源站网络超时，且数据库冷备份（L2缓存）中恰好有该请求的历史遗留数据，本服务为了保证业务不中断，会触发降级机制，返回这份旧数据。

此时，HTTP 响应头中会携带 `X-Data-Expired: true`。

前端或业务端可以据此判断返回的数据非实时数据，可按需决定是否向用户展示降级提示。

---

### 3.3 获取方法文档列表

**路径**: `/api/methods`
**方法**: GET
**功能**: 获取所有支持的 Akshare 方法列表及其详细文档说明。

#### 请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| category | String | 否 | 按分类筛选，如 "股票-历史行情"。不传则返回所有方法 |
| method | String | 否 | 按方法名模糊搜索 |

#### 响应示例

```json
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "method": "stock_zh_a_hist",
      "category": "股票-历史行情",
      "description": "获取A股个股历史行情数据",
      "parameters": [...],
      "example_params": { "symbol": "600000", "period": "daily" },
      "http_example_url": null,
      "python_example": "import akshare as ak\ndf = ak.stock_zh_a_hist(symbol=\"600000\")",
      "response_fields": [...],
      "notes": "数据来源于东方财富网",
      "cache_recommendation": null,
      "cache_config": {
        "enable_l1": false,
        "l1_ttl": 3600,
        "enable_l2": false,
        "l2_update_days": 365
      }
    }
  ]
}
```

`cache_config` 字段说明：
- `enable_l1` / `l1_ttl` — L1 Redis 缓存开关及过期时间（秒）
- `enable_l2` / `l2_update_days` — L2 数据库缓存开关及更新天数

---

### 3.4 获取指定方法详情

**路径**: `/api/method/{method_name}`
**方法**: GET
**功能**: 获取指定 Akshare 方法的详细文档。

#### 路径参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| method_name | String | 是 | Akshare 方法名 |

**成功响应**: 同 `/api/methods` 中的单条数据结构。
**错误响应 (HTTP 404)**:
```json
{ "detail": "方法 'invalid_method' 不存在或未配置文档" }
```

---

### 3.5 获取所有分类列表

**路径**: `/api/categories`
**方法**: GET
**功能**: 获取所有方法分类列表，用于前端分类筛选。

```json
{
  "code": 200,
  "message": "success",
  "data": ["债券-信息查询", "外汇-实时行情", "股票-历史行情", ...]
}
```

---

### 3.6 SSE 流式导入方法文档

**路径**: `/api/methods/scrape-docs`
**方法**: POST
**功能**: 通过 SSE (Server-Sent Events) 实时推送爬取/自省进度，将 Akshare 文档导入数据库。

**响应格式**: `text/event-stream`

---

### 3.7 批量更新方法文档

**路径**: `/api/methods/batch-update`
**方法**: POST
**功能**: 批量新增或更新方法文档。支持一次性提交多个方法文档，系统自动判断新增或更新。

#### 请求体 (JSON Array)

```json
[
  {
    "method": "stock_zh_a_hist",
    "category": "股票-历史行情",
    "description": "获取A股个股历史行情数据",
    "parameters": [...],
    "example_params": { "symbol": "600000", "period": "daily" },
    "example_url": "import akshare as ak\ndf = ak.stock_zh_a_hist(symbol=\"600000\")",
    "response_fields": [...],
    "notes": "数据来源于东方财富网",
    "cache_recommendation": { "enable_l1": true, "l1_ttl": 3600, "reason": "..." }
  }
]
```

#### 响应示例

```json
{
  "code": 200,
  "message": "成功处理 10 条数据，新增 8 条，更新 2 条",
  "data": { "total": 10, "success": 8, "updated": 2, "failed": 0, "errors": null }
}
```

---

### 3.8 从文件导入方法文档

**路径**: `/api/methods/import-file`
**方法**: POST
**功能**: 通过上传 JSON 文件的方式批量导入方法文档。

**Content-Type**: `multipart/form-data`
**参数**: `file` — JSON 文件 (.json)

格式与 `/api/methods/batch-update` 相同。

---

### 3.9 获取实时行情快照

**路径**: `/api/quote/realtime`
**方法**: GET
**功能**: 获取股票/指数/ETF 实时行情快照，支持多数据源和自动容灾切换。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | String | 是 | 证券代码纯数字，如 000852 |
| type | String | 否 | index(默认)/stock/etf |
| source | String | 否 | eastmoney(默认)/qq/sina/auto |

#### 响应示例

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "source": "eastmoney", "code": "000852", "name": "中证1000",
    "type": "index", "latest_price": 6234.56, "open_price": 6210.0,
    "pre_close": 6200.0, "high_price": 6250.0, "low_price": 6190.0,
    "price_change": 34.56, "price_change_pct": 0.56,
    "volume": 1234567890, "market_time": "2026-07-21 14:30:00",
    "request_time": "2026-07-21 14:30:01", "delay_seconds": 1.0
  }
}
```

#### 数据源容灾优先级

| source | 说明 |
|--------|------|
| eastmoney | 东方财富（首选，数据最全） |
| qq | 腾讯财经（备用） |
| sina | 新浪财经（最后备用） |
| auto | 自动容灾：eastmoney → qq → sina |

---

### 3.10 获取历史K线数据

**路径**: `/api/quote/kline`
**方法**: GET
**功能**: 获取股票/指数/ETF 历史日线 K 线数据（前复权），多源容灾自动切换。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | String | 是 | 证券代码纯数字 |
| type | String | 否 | INDEX(默认)/STOCK/ETF |
| start_date | String | 否 | YYYY-MM-DD，默认90天前 |
| end_date | String | 否 | YYYY-MM-DD，默认今天 |

**数据源优先级**: QQ(首选) → 新浪 → 东方财富 → TDX(备用)

---

### 3.11 获取通达信高频行情

**路径**: `/api/quote/tdx`
**方法**: GET
**功能**: 通过通达信协议获取低延迟实时行情，支持批量查询。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| codes | String | 否 | 格式: 市场,代码;市场,代码。市场: 0=深圳,1=上海。默认 "1,000905;1,000852" |

```json
{
  "code": 200,
  "message": "success",
  "data": [
    { "code": "000905", "price": 5678.5, "open": 5660.0,
      "high": 5690.0, "low": 5650.0, "vol": 123456789,
      "pre_close": 5660.0, "bid1": 5678.0, "ask1": 5679.0 }
  ]
}
```

**注意**: 依赖 `pytdx` 库，未安装时返回 HTTP 503，不影响其他接口。

---

### 3.12 获取通达信 K 线

**路径**: `/api/quote/tdx/kline`
**方法**: GET
**功能**: 通过通达信协议获取 K 线数据，支持日/周/月维度。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | String | 否 | 证券代码，如 600030（默认值） |
| market | Integer | 否 | 交易所代码：1=上海(默认), 0=深圳 |
| period | String | 否 | K线类型：day(默认)/week/month |
| start | Integer | 否 | 起始位置，默认0 |
| count | Integer | 否 | 获取条数，默认120 |

**调用示例**:
```bash
# 获取上证指数日K线
curl "http://127.0.0.1:8000/api/quote/tdx/kline?code=000001&market=1&period=day&count=10"

# 获取深圳成指周K线
curl "http://127.0.0.1:8000/api/quote/tdx/kline?code=399001&market=0&period=week&count=50"
```

---

### 3.13 通达信服务器测速

**路径**: `/api/quote/tdx/benchmark`
**方法**: POST
**功能**: 对通达信服务器进行并发测速，更新最优服务器列表。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| top_n | Integer | 否 | 返回最优服务器数量，默认5 |
| sample_size | Integer | 否 | 并发测速样本数，默认30 |

```json
{
  "code": 200,
  "message": "测速完成，找到 5 个快服务器",
  "data": [{"ip": "123.456.789.0", "port": 7709}, ...]
}
```

---

### 3.14 获取现货指数价格

**路径**: `/api/quote/spot`
**方法**: GET
**功能**: 获取现货指数的实时价格，主要用于期现对比分析。三级容灾：腾讯 → 新浪 → 东财，内置防屏蔽策略。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| codes | String | 否 | 格式: 名称:代码,名称:代码。默认 "IC:000905,IM:000852" |

```json
{
  "code": 200,
  "message": "success",
  "data": { "IC": 5678.5, "IM": 6234.56, "IF": 3890.12 }
}
```

---

### 3.15 获取期货合约数据

**路径**: `/api/quote/futures`
**方法**: GET
**功能**: 获取指定品种的所有期货合约数据（TqSdk → AkShare），包含价格、到期天数等。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | String | 否 | IC(默认)/IM/IF/IH |

```json
{
  "code": 200,
  "message": "success",
  "data": [
    { "symbol": "IC2506", "price": 5680.0, "days": 15, "year_month": "2025-06" },
    { "symbol": "IC2507", "price": 5670.0, "days": 45, "year_month": "2025-07" }
  ]
}
```

---

### 3.16 市场综合分析

**路径**: `/api/quote/analysis`
**方法**: GET
**功能**: 现货价格 + 期货合约 + 升贴水 + 跨期价差的综合分析数据。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | String | 否 | IC(默认)/IM |

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "spot_price": 5678.5,
    "contracts": [
      { "symbol": "IC2506", "price": 5680.0, "days": 15,
        "basis": 1.5, "basis_pct": 0.03, "annualized": 0.66 }
    ],
    "spreads": [
      { "near_symbol": "IC2506", "far_symbol": "IC2507",
        "spread_price": -10.0, "desc": "结构平稳" }
    ]
  }
}
```

**字段说明**:
- `basis` = 期货价格 - 现货价格（正数=升水，负数=贴水）
- `basis_pct`: 升贴水百分比
- `annualized`: 年化贴水率
- `spread_price`: 跨期价差 = 远月 - 近月

---

### 3.17 查询请求历史日志

**路径**: `/api/request-logs`
**方法**: GET
**功能**: 查询历史请求日志，支持多维度筛选。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| method | String | 否 | 按方法名筛选 |
| cache_hit_type | String | 否 | L1_HIT / L2_HIT / MISS / ERROR_FALLBACK_L2 |
| source | String | 否 | 数据来源筛选 |
| is_slow | Boolean | 否 | 是否仅慢请求 |
| start_date | String | 否 | YYYY-MM-DD，默认7天前 |
| end_date | String | 否 | YYYY-MM-DD，默认今天 |
| page | Integer | 否 | 默认1 |
| page_size | Integer | 否 | 默认50，最大500 |

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "total": 100, "page": 1, "page_size": 50,
    "logs": [
      {
        "request_id": "abc123", "method": "stock_zh_a_hist",
        "params_json": "{\"symbol\": \"600000\"}",
        "enable_l1": true, "l1_ttl_used": 3600,
        "cache_hit_type": "L1_HIT", "call_duration_ms": 15,
        "akshare_duration_ms": null, "status_code": 200,
        "error_message": "",
        "created_at": "2026-07-21 10:30:00"
      }
    ]
  }
}
```

---

### 3.18 获取方法缓存配置

**路径**: `/api/config/{method_name}`
**方法**: GET
**功能**: 获取指定方法的缓存配置信息。

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "method": "stock_zh_a_hist",
    "enable_l1": true, "l1_ttl": 3600,
    "enable_l2": true, "l2_update_days": 365,
    "created_at": "2026-07-20 10:00:00",
    "updated_at": "2026-07-22 15:30:00"
  }
}
```

**错误 (HTTP 404)**: `{ "detail": "方法 'xxx' 的配置不存在" }`

---

### 3.19 查询缓存配置列表

**路径**: `/api/config`
**方法**: GET
**功能**: 分页查询所有方法的缓存配置列表。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| method | String | 否 | 按方法名模糊筛选 |
| enable_l1 | Boolean | 否 | 按L1缓存启用状态筛选 |
| enable_l2 | Boolean | 否 | 按L2缓存启用状态筛选 |
| page | Integer | 否 | 默认1 |
| page_size | Integer | 否 | 默认20，最大500 |

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "total": 50, "page": 1, "page_size": 20,
    "items": [
      { "method": "stock_zh_a_hist", "enable_l1": true, "l1_ttl": 3600,
        "enable_l2": true, "l2_update_days": 365,
        "created_at": "...", "updated_at": "..." }
    ]
  }
}
```

---

### 3.20 更新方法缓存配置

**路径**: `/api/config`
**方法**: POST
**功能**: 创建或更新方法的缓存配置。通过此接口统一管理所有方法的 L1/L2 缓存策略。

#### 请求体

```json
{
  "method": "stock_zh_a_hist",
  "enable_l1": true,
  "l1_ttl": 7200,
  "enable_l2": true,
  "l2_update_days": 180
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| method | String | 是 | Akshare 方法名 |
| enable_l1 | Boolean | 否 | 默认 false |
| l1_ttl | Integer | 否 | 过期时间(秒)，默认 3600 |
| enable_l2 | Boolean | 否 | 默认 true |
| l2_update_days | Integer | 否 | L2 增量更新天数，默认 365 |

---

### 3.21 查询定时任务日志

**路径**: `/api/scheduler-logs`
**方法**: GET
**功能**: 查询定时任务的执行日志（L2 缓存更新、日志清理等）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_type | String | 否 | l2_update / clean_logs |
| status | String | 否 | 按状态筛选（如 success/failed） |
| start_date | String | 否 | YYYY-MM-DD |
| end_date | String | 否 | YYYY-MM-DD |
| page | Integer | 否 | 默认1 |
| page_size | Integer | 否 | 默认20，最大500 |

**注意**: 当前版本定时任务日志仅输出到控制台，未持久化到数据库。`data.logs` 恒为空数组。

---

### 3.22 清空 L1 缓存 (Redis)

**路径**: `/api/cache/l1`
**方法**: DELETE

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| method | String | 否 | 指定方法名则只清空该方法缓存，不传则清空所有 |

```json
{ "code": 200, "message": "成功清空所有L1缓存",
  "data": { "cache_type": "L1", "method": "all", "deleted_keys": 156 } }
```

---

### 3.23 清空 L2 缓存 (MySQL)

**路径**: `/api/cache/l2`
**方法**: DELETE

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| method | String | 否 | 指定方法名则只清空该方法缓存，不传则清空所有 |

```json
{ "code": 200, "message": "成功清空所有L2缓存",
  "data": { "cache_type": "L2", "method": "all", "deleted_records": 1024 } }
```

---

### 3.24 清空所有缓存

**路径**: `/api/cache/all`
**方法**: DELETE

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| method | String | 否 | 指定方法名则只清空该方法的缓存，不传则清空所有 |

```json
{ "code": 200, "message": "成功清空所有缓存",
  "data": { "method": "all", "l1_deleted_keys": 156,
            "l2_deleted_records": 1024, "total_cleared": 1180 } }
```

---

### 3.25 收藏管理

#### 添加收藏
**路径**: `/api/favorites`
**方法**: POST

```json
{ "user_id": "user123", "method": "stock_zh_a_hist", "remark": "A股历史行情" }
```

#### 取消收藏
**路径**: `/api/favorites`
**方法**: DELETE

```json
{ "user_id": "user123", "method": "stock_zh_a_hist" }
```

#### 获取收藏列表
**路径**: `/api/favorites/{user_id}`
**方法**: GET
**参数**: `page`(默认1), `page_size`(默认50)

#### 检查收藏状态
**路径**: `/api/favorites/{user_id}/check/{method_name}`
**方法**: GET

```json
{ "code": 200, "message": "success",
  "data": { "is_favorited": true, "method": "stock_zh_a_hist",
            "remark": "A股历史行情", "created_at": "2026-07-20 10:30:00" } }
```

---

### 3.26 基金持仓管理

#### 查询管理基金代码列表
**路径**: `/api/fund-purchase/codes`
**方法**: GET

#### 新增管理基金代码
**路径**: `/api/fund-purchase/codes`
**方法**: POST
**Body**: `{"fund_code": "000001", "fund_name": "华夏成长混合(可选)", "remark": "可选备注"}`
**说明**: 未传 fund_name 时自动从已抓取数据补全。

#### 修改管理基金代码
**路径**: `/api/fund-purchase/codes/{fund_code}`
**方法**: PUT
**Body**: `{"fund_name": "...", "remark": "..."}`

#### 删除管理基金代码
**路径**: `/api/fund-purchase/codes/{fund_code}`
**方法**: DELETE

#### 手动触发基金数据抓取
**路径**: `/api/fund-purchase/fetch`
**方法**: POST
**功能**: 无需等待定时任务，手动触发 fund_purchase_em 数据抓取入库。

---

### 3.27 市场数据管理

#### 抓取分红派息数据
**路径**: `/api/market-data/fetch-fhps`
**方法**: POST
**功能**: 手动触发 dividend 数据抓取入库。
**Body(可选)**: `{"date": "2026-07-21"}`

#### 抓取指数成分股数据
**路径**: `/api/market-data/fetch-index-cons`
**方法**: POST
**功能**: 手动触发指数成分股数据抓取入库。

---

### 3.28 监控模块 — `/api/monitor/`

#### 综合仪表盘 / 数据源状态 / Redis / DB / 任务 / 告警 / 探活

| 路径 | 方法 | 功能 |
|------|------|------|
| `/api/monitor/dashboard` | GET | 综合监控仪表盘（数据源/Redis/DB/任务状态汇总） |
| `/api/monitor/datasources` | GET | 各数据源健康状态（延迟、成功率、是否在线） |
| `/api/monitor/redis` | GET | Redis 运行状态（内存、连接数、命中率） |
| `/api/monitor/db` | GET | 数据库运行状态（连接池、查询延迟） |
| `/api/monitor/tasks` | GET | 定时任务执行状态（上次执行时间、结果） |
| `/api/monitor/alerts` | GET | 最近告警事件（参数: limit，默认20） |
| `/api/monitor/check` | POST | 手动触发全量健康检查（含接口探活，超时60s） |
| `/api/monitor/probe` | GET | 对每个容灾链发送真实请求验证端到端可用性 |

**仪表盘返回示例**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "datasources": { "total": 12, "healthy": 10, "unhealthy": 2 },
    "redis": { "connected": true, "used_memory_mb": 45.2, "hit_rate": 0.89 },
    "db": { "connected": true, "pool_size": 10, "active_connections": 2 },
    "tasks": { "total": 5, "last_run": "2026-07-21 03:00:00", "success": true }
  }
}
```

#### 慢请求日志查询

**路径**: `/api/monitor/slow-logs`
**方法**: GET
**功能**: 查询慢请求日志（`is_slow=true` 且 `call_duration_ms > 3000`）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| method | String | 否 | 按方法名筛选 |
| source | String | 否 | 按数据来源筛选 |
| start_date | String | 否 | YYYY-MM-DD |
| end_date | String | 否 | YYYY-MM-DD |
| page | Integer | 否 | 默认1 |
| page_size | Integer | 否 | 默认50，最大500 |

#### 数据源调用日志查询

**路径**: `/api/monitor/datasource-logs`
**方法**: GET
**功能**: 查询每个数据源的调用记录，包括延迟、成功/失败、容灾切换。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source_name | String | 否 | 数据源名称筛选 |
| data_type | String | 否 | 数据类型筛选 |
| success | Boolean | 否 | 仅成功/仅失败 |
| start_date | String | 否 | YYYY-MM-DD |
| end_date | String | 否 | YYYY-MM-DD |
| page | Integer | 否 | 默认1 |
| page_size | Integer | 否 | 默认50，最大500 |

#### 请求日志查询 (Monitor 命名空间)

**路径**: `/api/monitor/request-logs`
**方法**: GET
**说明**: 同 `/api/request-logs`（参见 3.17），路径在 `/api/monitor/` 下提供相同功能。

---

### 3.29 数据源路由 — `/api/datasource/`

数据源路由模块提供多数据源的容灾切换、偏好缓存、动态优先级调整等能力。

#### 数据源状态与容灾链查询

| 路径 | 方法 | 功能 |
|------|------|------|
| `/api/datasource/status` | GET | 所有数据源健康状态（在线/离线、延迟、成功率） |
| `/api/datasource/chains` | GET | 所有数据类型（realtime/kline/futures等）的完整容灾链 |

**状态返回示例**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "eastmoney": { "alive": true, "latency_ms": 120, "success_rate": 0.98 },
    "qq": { "alive": true, "latency_ms": 85, "success_rate": 0.95 },
    "sina": { "alive": false, "latency_ms": null, "success_rate": 0.0 }
  }
}
```

**容灾链返回示例**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "realtime": ["eastmoney", "qq", "sina"],
    "kline": ["qq", "sina", "eastmoney", "tdx"],
    "futures": ["tqsdk", "akshare"]
  }
}
```

#### 数据源链路追踪

| 路径 | 方法 | 功能 |
|------|------|------|
| `/api/datasource/trace` | GET | 执行一次数据源请求并返回完整追踪信息 |
| `/api/datasource/trace/sse` | GET | SSE 实时流式追踪数据源请求链（适合前端实时展示） |

**trace 参数**: `data_type`(默认realtime), `code`(默认000852), 以及其他路由参数
**trace/sse 参数**: `data_type`(默认realtime), `code`(默认000852)

**trace 返回示例**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "trace": {
      "data_type": "realtime",
      "code": "000852",
      "chain": ["eastmoney", "qq", "sina"],
      "healthy_chain": ["eastmoney", "qq"],
      "attempts": [
        { "source": "eastmoney", "success": true, "latency_ms": 105, "error": null }
      ],
      "final_source": "eastmoney",
      "success": true,
      "total_latency_ms": 105,
      "remaining_backups": ["qq", "sina"]
    }
  }
}
```

**trace/sse**: 返回 `text/event-stream`，分 phase=chain → phase=attempt(逐个) → phase=complete 三阶段推送。

#### 数据源控制

| 路径 | 方法 | 功能 |
|------|------|------|
| `/api/datasource/reset/{source_name}` | POST | 重置数据源健康状态（清除错误计数） |
| `/api/datasource/enable/{source_name}` | POST | 启用/禁用数据源（参数: enabled=true/false） |

```bash
# 重置东方财富数据源
curl -X POST "http://127.0.0.1:8000/api/datasource/reset/eastmoney"

# 禁用新浪数据源
curl -X POST "http://127.0.0.1:8000/api/datasource/enable/sina?enabled=false"
```

#### 偏好缓存管理

| 路径 | 方法 | 功能 |
|------|------|------|
| `/api/datasource/preferences` | GET | 查询数据源偏好缓存（可选参数: data_type, code） |
| `/api/datasource/preferences` | DELETE | 清除偏好缓存（可选参数: route_key，不传则清空全部） |

```bash
# 查询偏好缓存
curl "http://127.0.0.1:8000/api/datasource/preferences"

# 清除所有偏好
curl -X DELETE "http://127.0.0.1:8000/api/datasource/preferences"
```

#### 动态优先级

| 路径 | 方法 | 功能 |
|------|------|------|
| `/api/datasource/dynamic-priorities` | GET | 查询当前动态优先级得分 |
| `/api/datasource/adjust-priorities` | POST | 手动触发动态优先级重新计算 |

```bash
curl "http://127.0.0.1:8000/api/datasource/dynamic-priorities"
# 返回: { "code": 200, "data": { "eastmoney": 90, "qq": 85, "sina": 60 } }
```

#### 数据源探活

| 路径 | 方法 | 功能 |
|------|------|------|
| `/api/datasource/probe` | POST | SSE 逐个探测所有数据源，实时推送每个源的延迟和状态 |
| `/api/datasource/probe/latest` | GET | 获取最近一次探测结果及时间 |

```bash
# 触发探活（SSE流式返回）
curl -X POST "http://127.0.0.1:8000/api/datasource/probe"

# 获取上次探测结果
curl "http://127.0.0.1:8000/api/datasource/probe/latest"
```

---

### 3.30 美股行情 — `/api/us/`

#### 实时行情
**路径**: `/api/us/realtime` **方法**: GET
**参数**: `code` — 股票代码（必填），如 AAPL、TSLA、SPY

```bash
curl "http://127.0.0.1:8000/api/us/realtime?code=AAPL"
```

#### K线数据
**路径**: `/api/us/kline` **方法**: GET

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | String | 是 | 股票代码，如 AAPL |
| period | String | 否 | day(默认)/week/month |
| count | Integer | 否 | 获取条数，默认120 |

```bash
curl "http://127.0.0.1:8000/api/us/kline?code=AAPL&period=day&count=30"
```

#### 列表
**路径**: `/api/us/list` **方法**: GET
**参数**: `start`(默认0), `count`(默认80)

```bash
curl "http://127.0.0.1:8000/api/us/list?start=0&count=20"
```

---

### 3.31 港股行情 — `/api/hk/`

#### 实时行情
**路径**: `/api/hk/realtime` **方法**: GET

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | String | 是 | 股票代码，如 00700（腾讯）、09988 |
| board | String | 否 | main(主板，默认)/gem(创业板) |

#### K线数据
**路径**: `/api/hk/kline` **方法**: GET

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | String | 是 | 股票代码 |
| board | String | 否 | main(默认)/gem |
| period | String | 否 | day(默认)/week/month |
| count | Integer | 否 | 默认120 |

```bash
curl "http://127.0.0.1:8000/api/hk/realtime?code=00700"
curl "http://127.0.0.1:8000/api/hk/kline?code=00700&period=day&count=50"
```

#### 列表
**路径**: `/api/hk/list` **方法**: GET
**参数**: `start`(默认0), `count`(默认80)

---

### 3.32 全球行情 (yfinance) — `/api/yf/`

#### 实时行情
**路径**: `/api/yf/realtime` **方法**: GET
**参数**: `symbol` — 股票代码（必填），如 AAPL、TSLA、0700.HK、600519.SS

#### K线数据（按周期）
**路径**: `/api/yf/kline` **方法**: GET

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | String | 是 | 股票代码 |
| period | String | 否 | 3mo(默认)/1d/5d/1mo/6mo/1y/5y/max |
| interval | String | 否 | 1d(默认)/1m/5m/15m/30m/1h/1wk/1mo |

```bash
curl "http://127.0.0.1:8000/api/yf/realtime?symbol=AAPL"
curl "http://127.0.0.1:8000/api/yf/kline?symbol=0700.HK&period=1mo&interval=1d"
```

#### K线数据（按日期范围）
**路径**: `/api/yf/kline-range` **方法**: GET

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | String | 是 | 股票代码 |
| start_date | String | 是 | 开始日期 YYYY-MM-DD |
| end_date | String | 是 | 结束日期 YYYY-MM-DD |
| interval | String | 否 | 1d(默认) |

```bash
curl "http://127.0.0.1:8000/api/yf/kline-range?symbol=600519.SS&start_date=2026-01-01&end_date=2026-07-21"
```

---

### 3.33 富途 OpenD 行情 — `/api/futu/`

**前置条件**: 需要本地运行 FutuOpenD 服务端。

#### 实时行情
**路径**: `/api/futu/realtime` **方法**: GET
**参数**: `code` — 股票代码（必填），如 HK.00700、US.AAPL

#### K线数据
**路径**: `/api/futu/kline` **方法**: GET

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | String | 是 | 股票代码 |
| ktype | String | 否 | K线类型：day(默认)/week/month/year |
| count | Integer | 否 | 获取条数，默认120 |

#### 列表
**路径**: `/api/futu/list` **方法**: GET
**参数**: `market` — HK(默认)/US/CN/SG

```bash
curl "http://127.0.0.1:8000/api/futu/realtime?code=HK.00700"
curl "http://127.0.0.1:8000/api/futu/kline?code=US.AAPL&ktype=day&count=50"
```

---

## 4. 第三方数据调用接口汇总

本节汇总所有面向第三方系统提供数据获取能力的接口。

### 4.1 接口总览

| 接口 | 路径 | 方法 | 数据源 | 功能说明 |

### 4.2 两类接口的区别

| 对比项 | `/api/ak` (AkShare代理) | `/api/quote/*` (行情源直连) |
|--------|------------------------|---------------------------|
| 数据来源 | AkShare库（进程池隔离） | 直连各行情源HTTP API |
| 响应速度 | 较慢（进程池+缓存） | 更快（线程池+直连） |
| 缓存支持 | L1 Redis + L2 MySQL | 无缓存，实时获取 |
| 容灾机制 | L2降级 | 多源自动切换 |
| 适用场景 | 通用数据、历史数据 | 需要低延迟的实时行情 |

---

## 5. 前端集成指南

### 5.1 快速开始流程

### 5.2 缓存命中类型说明

### 5.3 错误处理最佳实践

### 5.4 性能优化建议

```javascript
// 1. 使用防抖避免频繁请求
import { debounce } from 'lodash';
const debouncedFetch = debounce(async (symbol) => {
  const data = await fetchStockData(symbol);
  updateChart(data);
}, 500);

// 2. 合理设置缓存时间
await axios.post('http://127.0.0.1:8000/api/config', {
  method: 'stock_zh_a_hist',
  enable_l1: true, l1_ttl: 7200, enable_l2: true
});

// 3. 批量查询时注意并发控制
async function fetchMultipleStocks(symbols) {
  const chunks = _.chunk(symbols, 5);
  const results = [];
  for (const chunk of chunks) {
    const promises = chunk.map(s =>
      axios.get('http://127.0.0.1:8000/api/ak', {
        params: { method: 'stock_zh_a_hist', symbol: s }
      })
    );
    const responses = await Promise.all(promises);
    results.push(...responses.map(r => r.data.data));
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  return results;
}

// 4. 使用数据源路由追踪调试
const trace = await axios.get('http://127.0.0.1:8000/api/datasource/trace', {
  params: { data_type: 'realtime', code: '000852' }
});
console.log('数据源链路:', trace.data.data);
```

---

## 6. 调用示例代码

### 示例 1: 获取 A 股历史行情 (Python)

```python
import requests

url = "http://127.0.0.1:8000/api/ak"
params = {
    "method": "stock_zh_a_hist",
    "symbol": "600000",
    "period": "daily",
    "start_date": "20240101",
    "end_date": "20240201",
    "adjust": "qfq"
}

response = requests.get(url, params=params)
res_data = response.json()

if res_data["code"] == 200:
    if response.headers.get("X-Data-Expired") == "true":
        print("警告: 拉取到了过期的降级数据")
    print("获取到数据条数:", len(res_data["data"]))
else:
    print("获取失败:", res_data["message"])
```

### 示例 2: 实时行情 (cURL)

```bash
# 实时行情（自动容灾）
curl "http://127.0.0.1:8000/api/quote/realtime?code=000852&type=index&source=auto"

# 历史K线
curl "http://127.0.0.1:8000/api/quote/kline?code=000852&type=INDEX&start_date=2024-01-01&end_date=2024-12-31"

# 现货+期货+市场分析
curl "http://127.0.0.1:8000/api/quote/spot?codes=IC:000905,IM:000852"
curl "http://127.0.0.1:8000/api/quote/futures?symbol=IC"
curl "http://127.0.0.1:8000/api/quote/analysis?symbol=IC"
```

### 示例 3: 配置缓存策略 (Python)

```python
import requests

url = "http://127.0.0.1:8000/api/config"

configs = [
    {"method": "stock_zh_a_hist", "enable_l1": True, "l1_ttl": 7200, "enable_l2": True, "l2_update_days": 365},
    {"method": "stock_zh_a_spot_em", "enable_l1": False, "enable_l2": False},
    {"method": "fund_etf_hist_em", "enable_l1": True, "l1_ttl": 3600, "enable_l2": True, "l2_update_days": 180},
]

for config in configs:
    response = requests.post(url, json=config)
    print(f"{config['method']}: {response.json()['message']}")
```

### 示例 4: 查询缓存配置列表

```bash
# 查询指定方法的配置
curl "http://127.0.0.1:8000/api/config/stock_zh_a_hist"

# 分页查询所有配置
curl "http://127.0.0.1:8000/api/config?page=1&page_size=10"
```

### 示例 5: 缓存管理

```bash
# 清空指定方法的L1缓存
curl -X DELETE "http://127.0.0.1:8000/api/cache/l1?method=stock_zh_a_hist"

# 清空所有L2缓存
curl -X DELETE "http://127.0.0.1:8000/api/cache/l2"
```

### 示例 6: 收藏管理

```python
import requests

base = "http://127.0.0.1:8000"

# 添加收藏
requests.post(f"{base}/api/favorites", json={
    "user_id": "user123",
    "method": "stock_zh_a_hist",
    "remark": "常用A股数据"
})

# 获取收藏列表
r = requests.get(f"{base}/api/favorites/user123")
print(r.json()["data"]["favorites"])

# 检查收藏状态
r = requests.get(f"{base}/api/favorites/user123/check/stock_zh_a_hist")
print(r.json()["data"]["is_favorited"])
```

### 示例 7: 监控与数据源路由

```python
import requests

base = "http://127.0.0.1:8000"

# 监控仪表盘
r = requests.get(f"{base}/api/monitor/dashboard")
print(r.json()["data"])

# 数据源链路追踪
r = requests.get(f"{base}/api/datasource/trace", params={
    "data_type": "realtime", "code": "000852"
})
for attempt in r.json()["data"]["trace"]["attempts"]:
    print(f"  {attempt['source']}: {'OK' if attempt['success'] else 'FAIL'} ({attempt['latency_ms']}ms)")

# 查询慢请求日志
r = requests.get(f"{base}/api/monitor/slow-logs", params={
    "page": 1, "page_size": 10
})
print(r.json()["data"])
```

### 示例 8: 美股 / 港股 / 全球行情

```bash
# 美股
curl "http://127.0.0.1:8000/api/us/realtime?code=AAPL"

# 港股
curl "http://127.0.0.1:8000/api/hk/realtime?code=00700"

# 全球行情 (yfinance)
curl "http://127.0.0.1:8000/api/yf/realtime?symbol=AAPL"

# 富途行情（需运行 FutuOpenD）
curl "http://127.0.0.1:8000/api/futu/realtime?code=HK.00700"
```

### 示例 9: 基金持仓管理

```python
import requests

base = "http://127.0.0.1:8000"

# 新增管理基金
requests.post(f"{base}/api/fund-purchase/codes", json={
    "fund_code": "000001", "fund_name": "华夏成长混合"
})

# 查询列表
r = requests.get(f"{base}/api/fund-purchase/codes")
print(r.json()["data"])

# 手动触发抓取
requests.post(f"{base}/api/fund-purchase/fetch")
```

---

## 7. 历史更新记录

### v2.0.0 (2026-07-21)
**新增模块**:
- 监控模块 `/api/monitor/*` (11个端点)：综合仪表盘、数据源状态、Redis/DB/任务状态、告警、探活、慢日志、数据源日志
- 数据源路由模块 `/api/datasource/*` (12个端点)：容灾链管理、动态优先级、偏好缓存、SSE实时追踪、数据源探活
- 美股行情 `/api/us/*`：实时行情、K线、列表
- 港股行情 `/api/hk/*`：实时行情、K线、列表
- 全球行情 `/api/yf/*` (yfinance)：实时行情、K线、日期范围K线
- 富途 OpenD 行情 `/api/futu/*`：实时行情、K线、列表
- 基金持仓管理 `/api/fund-purchase/*`：基金代码CRUD + 手动抓取
- 市场数据管理 `/api/market-data/fetch-*`：分红/成分股数据手动抓取
- SSE文档导入 `/api/methods/scrape-docs`：流式导入
- 缓存配置列表查询 `/api/config` (GET)：分页查询
- TDX K线 `/api/quote/tdx/kline` 及测速 `/api/quote/tdx/benchmark`
- K线数据源扩展：QQ → 新浪 → 东方财富 → TDX 四源容灾

**文档变更**:
- 移除不存在的 `/api/quote/history-analysis` 接口文档
- 移除 v1.2.0 迁移指南（已过时）
- 重构文档结构，统一编号

### v1.5.1 (2026-05-23)
- `/api/quote/spot` 升级三级容灾：腾讯 → 新浪 → 东财
- 防屏蔽策略（随机延迟、轮换User-Agent）

### v1.5.0 (2026-05-15)
- 新增统一行情源模块 `quote_api.py`，三源实时行情
- 新增通达信服务 `tdx_service.py`
- 新增市场分析 `market_service.py`
- 新增7个 `/api/quote/*` 端点

### v1.4.0 (2026-04-29)
- 新增用户收藏功能及4个收藏接口
- 新增数据库表 `t_akshare_user_favorites`

### v1.3.0 (2026-04-28)
- 新增缓存清空接口 (L1/L2/All)
- 修复 timeout 参数类型转换

### v1.2.0 (2026-04-24)
- 移除 `/api/ak` 的 `enable_l1`/`l1_ttl_override` 参数
- 新增请求日志、缓存配置管理、定时任务日志接口

### v1.1.0 (2024-04-22)
- 新增方法文档管理系统
- 新增 `/api/methods`、`/api/method/`、`/api/categories`、batch-update、import-file

### v1.0.0 (初始版本)
- Akshare 数据代理 `/api/ak`
- 二级缓存（Redis L1 + MySQL L2）
- 健康检查 `/health`
- 异步 Worker 进程池
- 降级机制 + X-Data-Expired 响应头
