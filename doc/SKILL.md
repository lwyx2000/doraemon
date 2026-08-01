---
name: akshare-api-caller
description: Call AkShare WebAPI service to fetch financial data without reading documentation. Provides intelligent parameter completion, common usage templates, and automatic error handling for stock market data, futures, indices, ETFs, US/HK stocks, real-time tick streaming (SSE), and kline archiving. Use when needing to get A-share historical data, real-time quotes, futures contracts, tick streams, or any AkShare financial data through the centralized API service.
---

# AkShare API 调用助手

快速调用 AkShare WebAPI 服务获取金融数据，无需查阅接口文档。

## 服务地址

```
Base URL: http://<服务器IP>:8000
```

**使用前确认**：检查服务是否运行
```bash
curl http://192.168.3.53:8000/health
# 预期返回: {"status": "up", "components": {"db": "ok", "redis": "ok", "worker": "isolated"}}
```

---

## 方法参数查询接口

调用 AkShare 接口前，可通过以下接口查询方法的参数定义、示例参数和返回字段，避免传参错误。

### 1. 获取所有方法列表

**路径**: `GET /api/methods`

```python
# 查询所有方法（含参数定义和示例参数）
response = requests.get("http://192.168.3.53:8000/api/methods")
methods = response.json()["data"]
# 返回: [{"method": "stock_zh_a_hist", "category": "股票", "parameters": [...], "example_params": {...}, ...}, ...]

# 按分类筛选
response = requests.get("http://192.168.3.53:8000/api/methods", params={"category": "股票"})

# 模糊搜索方法名
response = requests.get("http://192.168.3.53:8000/api/methods", params={"method": "stock_zh_a"})
```

### 2. 获取指定方法详细文档

**路径**: `GET /api/method/{method_name}`

```python
# 查询 stock_zh_a_hist 的完整参数文档
response = requests.get("http://192.168.3.53:8000/api/method/stock_zh_a_hist")
doc = response.json()["data"]
# 返回:
# {
#   "method": "stock_zh_a_hist",
#   "category": "股票",
#   "description": "A股历史行情",
#   "parameters": [
#     {"name": "symbol", "type": "str", "required": true, "description": "股票代码"},
#     {"name": "period", "type": "str", "required": true, "description": "周期: daily/weekly/monthly"},
#     {"name": "start_date", "type": "str", "required": false, "description": "开始日期 YYYYMMDD"},
#     {"name": "end_date", "type": "str", "required": false, "description": "结束日期 YYYYMMDD"},
#     ...
#   ],
#   "example_params": {"symbol": "000001", "period": "daily", "start_date": "20240101", "end_date": "20240601"},
#   "response_fields": [{"name": "日期", "type": "str"}, {"name": "开盘", "type": "float"}, ...]
# }
```

### 3. 获取方法分类列表

**路径**: `GET /api/categories`

```python
# 查询所有可用分类
response = requests.get("http://192.168.3.53:8000/api/categories")
categories = response.json()["data"]
# 返回: ["股票", "基金", "期货", "指数", "宏观经济", ...]
```

### 使用流程

```
1. GET /api/categories          → 了解有哪些分类
2. GET /api/methods?category=股票 → 查看该分类下的所有方法
3. GET /api/method/stock_zh_a_hist → 查看具体方法的参数定义和示例
4. GET /api/ak?method=stock_zh_a_hist&symbol=000001&... → 按文档传参调用
```

---

## 核心接口调用

### 1. 获取 AkShare 数据（通用接口）

**路径**: `GET /api/ak`

#### 调用格式
```
http://<服务器IP>:8000/api/ak?method=<方法名>&<参数1>=<值1>&<参数2>=<值2>
```

#### 常用场景模板

##### 📈 A股历史行情
```python
import requests

# 获取平安银行日线数据
response = requests.get(
    "http://192.168.3.53:8000/api/ak",
    params={
        "method": "stock_zh_a_hist",
        "symbol": "600000",
        "period": "daily",      # daily/weekly/monthly
        "start_date": "20240101",
        "end_date": "20241231"
    }
)
data = response.json()["data"]
# 返回: [{"日期": "2024-01-02", "开盘": 10.5, "收盘": 10.8, ...}, ...]
```

##### 📊 ETF 历史数据
```python
# 获取沪深300ETF数据
response = requests.get(
    "http://192.168.3.53:8000/api/ak",
    params={
        "method": "fund_etf_hist_em",
        "symbol": "510300",
        "period": "daily"
    }
)
```

##### 🏦 实时行情快照
```python
# 获取A股实时行情
response = requests.get(
    "http://192.168.3.53:8000/api/ak",
    params={
        "method": "stock_zh_a_spot_em"
    }
)
```

##### 📉 股指期货数据
```python
# 获取中证500期货合约
response = requests.get(
    "http://192.168.3.53:8000/api/ak",
    params={
        "method": "futures_zh_realtime",
        "symbol": "IC"
    }
)
```

---

### 2. 行情源直连接口（更低延迟）

#### 实时行情快照
```python
# 东方财富源（首选）
response = requests.get(
    "http://192.168.3.53:8000/api/quote/realtime",
    params={
        "code": "000852",      # 中证1000指数
        "type": "index",       # index/stock/etf
        "source": "eastmoney"  # eastmoney/qq/sina/auto
    }
)
# 返回标准化行情数据
```

#### 历史K线数据
```python
# 获取前复权日线数据
response = requests.get(
    "http://192.168.3.53:8000/api/quote/kline",
    params={
        "code": "000852",
        "type": "INDEX",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31"
    }
)
# 返回: [{"date": "2024-01-02", "open": 6100, "close": 6150, ...}, ...]
```

#### 现货指数价格（期现对比）
```python
# 获取IC/IM现货价格
response = requests.get(
    "http://192.168.3.53:8000/api/quote/spot",
    params={
        "codes": "IC:000905,IM:000852"
    }
)
# 返回: {"IC": 5678.5, "IM": 6234.56}
```

#### 期货合约列表
```python
# 获取IC品种所有合约
response = requests.get(
    "http://192.168.3.53:8000/api/quote/futures",
    params={
        "symbol": "IC"
    }
)
# 返回: [{"symbol": "IC2506", "price": 5680, "days": 15, ...}, ...]
```

#### 市场综合分析（升贴水+跨期价差）
```python
response = requests.get(
    "http://192.168.3.53:8000/api/quote/analysis",
    params={
        "symbol": "IC"
    }
)
# 返回现货价格、合约列表、升贴水、跨期价差
```

#### 期货历史综合分析（现货+期货+基差走势）
```python
response = requests.get(
    "http://192.168.3.53:8000/api/quote/history-analysis",
    params={
        "symbol": "IC"
    }
)
# 返回: 现货历史、期货合约列表、基差走势数据
```

#### 通达信高频行情
```python
# 获取指定代码的实时行情（市场:0=深圳,1=上海）
response = requests.get(
    "http://192.168.3.53:8000/api/quote/tdx",
    params={
        "codes": "1,000905;1,000852"
    }
)
# 返回: [{"code": "000905", "price": 5680, "open": 5700, ...}, ...]
```

#### 通达信K线数据
```python
response = requests.get(
    "http://192.168.3.53:8000/api/quote/tdx/kline",
    params={
        "market": 1,         # 0=深圳, 1=上海
        "code": "600030",
        "period": "day",     # day/week/month
        "start": 0,          # 起始位置(0=最新)
        "count": 120         # 返回条数(最大800)
    }
)
```

#### 通达信服务器测速
```python
response = requests.post(
    "http://192.168.3.53:8000/api/quote/tdx/benchmark",
    params={
        "top_n": 5,
        "sample_size": 30
    }
)
# 返回最快的 top_n 个TDX服务器
```

---

### 3. 数据库代理接口（DB 缓存）

以下接口采用**定时抓取+数据库代理**模式：后端定时抓取全量数据存入数据库，前端调用时从数据库查询返回，避免直接调用 akshare 大数据量接口。

#### 基金申购数据（fund_purchase_em）

后端在交易日 9:30、14:30、17:30 自动抓取全量基金申购数据存入数据库。

```python
response = requests.get(
    "http://192.168.3.53:8000/api/ak",
    params={"method": "fund_purchase_em"}
)
data = response.json()["data"]
# 返回: [{"基金代码": "000001", "基金简称": "华夏成长混合", "最新净值/万份收益": 1.308, ...}, ...]
# 仅返回白名单中配置的基金，白名单为空时返回空数组
```

#### 分红派息数据（stock_fhps_em）

```python
response = requests.get(
    "http://192.168.3.53:8000/api/ak",
    params={
        "method": "stock_fhps_em",
        "date": "20241231"       # 可选：指定分红数据年份，默认最新
    }
)
# 数据库无数据时自动回退实时调用并异步入库
```

#### 指数成分股数据（index_stock_cons / index_stock_cons_weight_csindex）

```python
# 有权重版（优先）
response = requests.get(
    "http://192.168.3.53:8000/api/ak",
    params={
        "method": "index_stock_cons_weight_csindex",
        "symbol": "000300"       # 沪深300
    }
)
# 降级为无权重版
response = requests.get(
    "http://192.168.3.53:8000/api/ak",
    params={
        "method": "index_stock_cons",
        "symbol": "000300"
    }
)
```

#### 管理基金代码白名单

前端通过以下接口管理需要返回的基金代码。**白名单只控制查询过滤，添加代码时不会写入基金申购数据**，数据由定时任务自动填充。

##### 查询所有管理基金代码
```python
response = requests.get("http://192.168.3.53:8000/api/fund-purchase/codes")
# 返回: {"code": 200, "message": "success", "data": [{"fund_code": "000001", "fund_name": "华夏成长混合", "remark": "...", "created_at": "2024-01-01 00:00:00", "updated_at": null}, ...]}
```

##### 新增管理基金代码
```python
response = requests.post(
    "http://192.168.3.53:8000/api/fund-purchase/codes",
    json={
        "fund_code": "000001",       # 必填
        "fund_name": "华夏成长混合",  # 可选
        "remark": "重点关注"          # 可选
    }
)
# 返回: {"code": 200, "message": "success", "data": {"fund_code": "000001", "fund_name": "华夏成长混合", "remark": "重点关注"}}
```

##### 修改管理基金代码
```python
response = requests.put(
    "http://192.168.3.53:8000/api/fund-purchase/codes/000001",
    json={
        "fund_name": "新名称",
        "remark": "新备注"
    }
)
```

##### 删除管理基金代码
```python
response = requests.delete("http://192.168.3.53:8000/api/fund-purchase/codes/000001")
# 返回: {"code": 200, "data": {"fund_code": "000001"}}
```

> **自动补全**：新增基金代码时如果不传 `fund_name`，后端会自动从已抓取的基金申购数据中查找补全。

##### 手动触发数据抓取
```python
# 无需等待定时任务，手动触发一次 fund_purchase_em 抓取并入库
response = requests.post("http://192.168.3.53:8000/api/fund-purchase/fetch")
# 返回: {"code": 200, "message": "success", "data": "fund_purchase_em 数据抓取任务已执行完成"}
# 注意：非交易日不会抓取，可通过定时任务自动跳过
```

---

## 常用方法速查表

### 股票相关
| 方法名 | 用途 | 关键参数 |
|--------|------|----------|
| `stock_zh_a_hist` | A股历史行情 | symbol, period, start_date, end_date |
| `stock_zh_a_spot_em` | A股实时行情 | 无 |
| `stock_individual_info_em` | 个股基本信息 | symbol |

### 基金/ETF
| 方法名 | 用途 | 关键参数 |
|--------|------|----------|
| `fund_etf_hist_em` | ETF历史数据 | symbol, period |
| `fund_open_fund_daily_em` | 开放式基金净值 | 无 |
| `fund_purchase_em` | 基金申购数据（DB代理） | 无（自动按白名单过滤） |
| `stock_fhps_em` | 股票分红派息数据（DB代理） | date |

### 期货
| 方法名 | 用途 | 关键参数 |
|--------|------|----------|
| `futures_zh_realtime` | 期货实时行情 | symbol (IC/IM/IF/IH) |
| `futures_zh_daily_sina` | 期货历史数据 | symbol |

### 指数
| 方法名 | 用途 | 关键参数 |
|--------|------|----------|
| `stock_zh_index_daily_em` | 指数历史数据 | symbol (000852/000905等) |
| `index_stock_cons` | 指数成分股（DB代理） | symbol |
| `index_stock_cons_weight_csindex` | 指数成分股（含权重，DB代理） | symbol |

---

## 缓存策略配置

**重要**：首次使用方法前，建议配置缓存策略以提升性能。

### 配置缓存
```python
# 为高频访问的方法启用缓存
requests.post(
    "http://192.168.3.53:8000/api/config",
    json={
        "method": "stock_zh_a_hist",
        "enable_l1": True,      # 启用Redis缓存
        "l1_ttl": 7200,         # 缓存2小时
        "enable_l2": True,      # 启用数据库缓存
        "l2_update_days": 365   # 保留1年历史
    }
)
```

### 缓存策略建议
| 数据类型 | L1缓存 | L1 TTL | L2缓存 | 说明 |
|----------|--------|--------|--------|------|
| 历史行情 | ✅ | 7200s | ✅ | 变化频率低，适合长缓存 |
| 实时行情 | ❌ | - | ❌ | 需要最新数据 |
| 期货合约 | ✅ | 300s | ✅ | 盘中频繁更新 |
| 指数数据 | ✅ | 3600s | ✅ | 相对稳定 |

---

## 错误处理

### 常见错误及解决方案

#### 1. 股票代码不存在
```json
{"code": 500, "message": "Akshare内部错误: 该股票代码不存在"}
```
**解决**：检查股票代码是否正确（6位数字）

#### 2. 日期参数格式错误
```json
{"code": 500, "message": "日期格式不正确，应使用 YYYYMMDD 格式"}
```
**解决**：确保日期格式为 `20240101`（无横杠）

#### 3. 非交易日请求
```json
{"code": 500, "message": "可能是以下原因导致\n1. 日期参数可能不是交易日"}
```
**解决**：不指定日期参数，返回最新数据；或选择最近的交易日

#### 4. 超时错误
```json
{"code": 500, "message": "调用 xxx 超时 (30s)"}
```
**解决**：减少请求数据量（缩短日期范围），或稍后重试

### 降级数据处理
当 AkShare 源站失败时，如果 L2 缓存有历史数据，会返回旧数据并在响应头中标记：
```python
response = requests.get("http://192.168.3.53:8000/api/ak?...")
if response.headers.get("X-Data-Expired") == "true":
    print("警告：返回的是历史降级数据")
```

---

## 高级用法

### 批量获取多只股票
```python
import concurrent.futures

symbols = ["600000", "600036", "000001"]

def fetch_stock(symbol):
    return requests.get(
        "http://192.168.3.53:8000/api/ak",
        params={"method": "stock_zh_a_hist", "symbol": symbol}
    ).json()["data"]

with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(fetch_stock, symbols))
```

### 监控请求日志
```python
# 查看最近请求的性能数据，支持多种筛选条件
response = requests.get(
    "http://192.168.3.53:8000/api/request-logs",
    params={
        "method": "stock_zh_a_hist",    # 可选：按方法名筛选
        "cache_hit_type": "l1",          # 可选：l1/l2/miss
        "source": "akshare",             # 可选：按数据源筛选
        "is_slow": True,                 # 可选：仅慢请求
        "start_date": "2024-01-01",      # 可选：开始日期
        "end_date": "2024-12-31",        # 可选：结束日期
        "page": 1,
        "page_size": 10
    }
)
data = response.json()["data"]
logs = data["logs"]
for log in logs:
    print(f"{log['method']}: {log['call_duration_ms']}ms, cache: {log['cache_hit_type']}")
# 每个日志条目包含: request_id, method, call_duration_ms, akshare_duration_ms,
# cache_hit_type, source, status_code, error_message, is_slow, created_at, 等
```

### 查看/清空缓存

#### 查看缓存配置
```python
# 查询所有方法的缓存配置
response = requests.get("http://192.168.3.53:8000/api/config")
# 支持分页和筛选: ?method=stock_zh_a_hist&page=1&page_size=20

# 查询单个方法的缓存配置
response = requests.get("http://192.168.3.53:8000/api/config/stock_zh_a_hist")
```

#### 清空 L1 缓存（Redis）
```python
# 清空指定方法的L1缓存
requests.delete(
    "http://192.168.3.53:8000/api/cache/l1",
    params={"method": "stock_zh_a_hist"}
)

# 清空所有L1缓存
requests.delete("http://192.168.3.53:8000/api/cache/l1")
```

#### 清空 L2 缓存（数据库）
```python
# 清空指定方法的L2缓存
requests.delete(
    "http://192.168.3.53:8000/api/cache/l2",
    params={"method": "stock_zh_a_hist"}
)

# 清空所有L2缓存
requests.delete("http://192.168.3.53:8000/api/cache/l2")
```

#### 同时清空 L1+L2
```python
requests.delete("http://192.168.3.53:8000/api/cache/all")
```

---

## 快速开始 checklist

- [ ] 确认服务地址和端口（默认 8000）
- [ ] 测试健康检查接口 `/health`
- [ ] 根据业务需求配置缓存策略 `/api/config`
- [ ] 选择合适的接口（通用 `/api/ak` 或行情源直连 `/api/quote/*`）
- [ ] 如需实时 Tick 推送，使用 SSE 接口 `/api/stream/ticks`
- [ ] 如需日K历史归档，配置 `/api/kline-archive/configs`
- [ ] 处理可能的降级数据（检查 `X-Data-Expired` 响应头）
- [ ] 添加错误处理和重试逻辑

---

## 完整示例：获取股指期货升贴水分析

```python
import requests
import json

BASE_URL = "http://192.168.3.53:8000"

# 1. 配置缓存策略
requests.post(f"{BASE_URL}/api/config", json={
    "method": "futures_zh_realtime",
    "enable_l1": True,
    "l1_ttl": 300,
    "enable_l2": True
})

# 2. 获取现货价格
spot_resp = requests.get(f"{BASE_URL}/api/quote/spot", params={
    "codes": "IC:000905,IM:000852"
})
spots = spot_resp.json()["data"]
print(f"IC现货: {spots['IC']}, IM现货: {spots['IM']}")

# 3. 获取期货合约
futures_resp = requests.get(f"{BASE_URL}/api/quote/futures", params={
    "symbol": "IC"
})
contracts = futures_resp.json()["data"]
print(f"IC近月合约: {contracts[0]['symbol']} @ {contracts[0]['price']}")

# 4. 获取综合分析（升贴水+跨期价差）
analysis_resp = requests.get(f"{BASE_URL}/api/quote/analysis", params={
    "symbol": "IC"
})
analysis = analysis_resp.json()["data"]
print(f"基差: {analysis['contracts'][0]['basis']}")
print(f"年化贴水率: {analysis['contracts'][0]['annualized']}%")
```

---

## 注意事项

1. **不要直接引入 AkShare**：所有金融数据必须通过本 API 服务获取
2. **合理配置缓存**：历史数据开启缓存，实时数据关闭缓存
3. **注意降级数据**：检查 `X-Data-Expired` 响应头
4. **控制请求频率**：避免短时间内大量请求导致 IP 被封
5. **错误重试**：遇到超时或网络错误时，实现指数退避重试
6. **`_spot_em` 实时行情接口优先用 `/api/quote/realtime`**：`stock_zh_a_spot_em`、`fund_etf_spot_em`、`fund_lof_spot_em` 等全量快照接口走的是爬东方财富网页，容器环境容易被反爬断连。改用行情源直连接口更稳定且自带容灾：

| 避免使用 | 推荐替代 | 说明 |
|----------|----------|------|
| `/api/ak?method=stock_zh_a_spot_em` | `/api/quote/realtime?code=000001&type=stock` | 单只/多只查询，东财→腾讯→新浪→TDX自动容灾 |
| `/api/ak?method=fund_etf_spot_em` | `/api/quote/realtime?code=510300&type=etf` | ETF实时行情 |
| `/api/ak?method=fund_lof_spot_em` | `/api/quote/realtime?code=162411&type=stock` | LOF在场内交易，按股票代码查 |

> 如果必须通过 `/api/ak` 调用 `_spot_em` 接口，后端已内置反爬对策（UA轮换+连接伪装+最多5次指数退避重试），但不保证100%有效。

---

## 美股行情接口 — /api/us/

基于 easy-tdx (TCP端口7727) 获取美股数据，降级到 akshare。

### 实时行情
```python
response = requests.get("http://192.168.3.53:8000/api/us/realtime", params={"code": "AAPL"})
# 返回: {"code": 200, "data": {"source": "easy_tdx_ex", "code": "AAPL", "latest_price": 195.5, ...}}
```

### K线数据
```python
response = requests.get("http://192.168.3.53:8000/api/us/kline", params={
    "code": "AAPL", "period": "day", "count": 120
})
# period: day/week/month
```

### 美股列表
```python
response = requests.get("http://192.168.3.53:8000/api/us/list", params={"start": 0, "count": 80})
```

---

## 港股行情接口 — /api/hk/

基于 easy-tdx (TCP端口7727) 获取港股数据，降级到 akshare。

### 实时行情
```python
response = requests.get("http://192.168.3.53:8000/api/hk/realtime", params={
    "code": "00700", "board": "main"  # board: main/gem/index
})
```

### K线数据
```python
response = requests.get("http://192.168.3.53:8000/api/hk/kline", params={
    "code": "00700", "board": "main", "period": "day", "count": 120
})
```

### 港股列表
```python
response = requests.get("http://192.168.3.53:8000/api/hk/list", params={"start": 0, "count": 80})
```

---

## yfinance 全球行情接口 — /api/yf/

基于 Yahoo Finance API，覆盖全球主要市场（美股/港股/A股/日股/欧股等）。

### 实时行情
```python
# 美股
response = requests.get("http://192.168.3.53:8000/api/yf/realtime", params={"symbol": "AAPL"})
# 港股
response = requests.get("http://192.168.3.53:8000/api/yf/realtime", params={"symbol": "0700.HK"})
# A股
response = requests.get("http://192.168.3.53:8000/api/yf/realtime", params={"symbol": "600519.SS"})
```

### K线数据
```python
# period: 1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max
# interval: 1m/2m/5m/15m/30m/60m/90m/1h/1d/5d/1wk/1mo/3mo
response = requests.get("http://192.168.3.53:8000/api/yf/kline", params={
    "symbol": "AAPL", "period": "3mo", "interval": "1d"
})
```

### 按日期范围K线
```python
response = requests.get("http://192.168.3.53:8000/api/yf/kline-range", params={
    "symbol": "AAPL", "start_date": "2024-01-01", "end_date": "2024-12-31", "interval": "1d"
})
```

---

## 富途 OpenD 行情接口 — /api/futu/

通过富途 OpenD 网关获取港股/美股行情。**需要本地运行 FutuOpenD 网关**（默认 127.0.0.1:33333）。

### 实时行情
```python
response = requests.get("http://192.168.3.53:8000/api/futu/realtime", params={"code": "HK.00700"})
# 代码格式: HK.00700, US.AAPL, SH.600519, SZ.000858
```

### K线数据
```python
response = requests.get("http://192.168.3.53:8000/api/futu/kline", params={
    "code": "HK.00700", "ktype": "day", "count": 120
})
# ktype: 1m/5m/15m/30m/60m/day/week/month
```

### 股票列表
```python
response = requests.get("http://192.168.3.53:8000/api/futu/list", params={"market": "HK"})
# market: HK/US/SH/SZ
```

---

## 监控接口 — /api/monitor/

### 综合仪表盘
```python
response = requests.get("http://192.168.3.53:8000/api/monitor/dashboard")
# 返回: overall_status, datasources, redis, db, system, recent_alerts
```

### 数据源状态
```python
response = requests.get("http://192.168.3.53:8000/api/monitor/datasources")
```

### Redis 状态
```python
response = requests.get("http://192.168.3.53:8000/api/monitor/redis")
```

### 数据库状态
```python
response = requests.get("http://192.168.3.53:8000/api/monitor/db")
```

### 定时任务状态
```python
response = requests.get("http://192.168.3.53:8000/api/monitor/tasks")
# 返回: 最近 100 条定时任务执行记录（task_id/status/duration_ms/error/timestamp）
```

### 手动健康检查（含接口探活）
```python
response = requests.post("http://192.168.3.53:8000/api/monitor/check")
# 返回: healthy, issues, probes (7条容灾链端到端探测结果)
```

### 接口探活
```python
response = requests.get("http://192.168.3.53:8000/api/monitor/probe")
# 对每条容灾链发真实请求，返回 ok/latency_ms/source/error
```

### 最近告警
```python
response = requests.get("http://192.168.3.53:8000/api/monitor/alerts", params={"limit": 10})
```

### 慢请求日志
```python
response = requests.get("http://192.168.3.53:8000/api/monitor/slow-logs", params={
    "method": "stock_zh_a_hist",   # 可选
    "source": "akshare",           # 可选
    "start_date": "2024-01-01",    # 可选
    "end_date": "2024-12-31",      # 可选
    "page": 1,
    "page_size": 20
})
# 返回 is_slow=True (call_duration_ms > 3000) 的请求，按耗时降序
```

### 数据源调用日志
```python
response = requests.get("http://192.168.3.53:8000/api/monitor/datasource-logs", params={
    "source_name": "eastmoney",    # 可选
    "data_type": "realtime",       # 可选
    "success": False,              # 可选
    "start_date": "2024-01-01",    # 可选
    "end_date": "2024-12-31",      # 可选
    "page": 1,
    "page_size": 50
})
# 返回每次数据源调用的成功/失败/延迟/降级记录
```

### 定时任务日志
```python
response = requests.get("http://192.168.3.53:8000/api/scheduler-logs", params={
    "task_type": "fetch_",       # 可选：按任务ID模糊搜索
    "status": "success",         # 可选：success/failure
    "start_date": "2024-01-01",  # 可选
    "end_date": "2024-12-31",    # 可选
    "page": 1,
    "page_size": 20
})
```

### 请求日志（监控入口）
```python
response = requests.get("http://192.168.3.53:8000/api/monitor/request-logs", params={
    "method": "stock_zh_a_hist",
    "cache_hit_type": "l1",        # 可选: l1/l2/miss
    "source": "akshare",           # 可选
    "is_slow": True,               # 可选
    "start_date": "2024-01-01",    # 可选
    "end_date": "2024-12-31",      # 可选
    "page": 1,
    "page_size": 50
})
# 同 /api/request-logs，但路径统一在 /api/monitor/ 下
```

---

## 数据源管理接口 — /api/datasource/

### 查看所有数据源状态
```python
response = requests.get("http://192.168.3.53:8000/api/datasource/status")
```

### 查看容灾链配置
```python
response = requests.get("http://192.168.3.53:8000/api/datasource/chains")
# 返回: {"us_realtime": ["easy_tdx_us", "akshare_us", "yfinance", "futu"], ...}
```

### 重置数据源健康状态
```python
response = requests.post("http://192.168.3.53:8000/api/datasource/reset/eastmoney")
```

### 启用/禁用数据源
```python
response = requests.post("http://192.168.3.53:8000/api/datasource/enable/sina?enabled=false")
```

### 查询数据源偏好缓存
```python
# 系统会自动记住每个接口+代码上次成功的数据源，下次优先从该数据源取
response = requests.get("http://192.168.3.53:8000/api/datasource/preferences")
# 可按 data_type 或 code 筛选
response = requests.get("http://192.168.3.53:8000/api/datasource/preferences", params={"data_type": "us_realtime"})
```

### 清除数据源偏好缓存
```python
# 清除全部
response = requests.delete("http://192.168.3.53:8000/api/datasource/preferences")
# 清除指定项
response = requests.delete("http://192.168.3.53:8000/api/datasource/preferences", params={"route_key": "us_realtime:AAPL"})
```

### 查看动态优先级
```python
response = requests.get("http://192.168.3.53:8000/api/datasource/dynamic-priorities")
# 系统每5分钟根据健康状态和延迟自动调整数据源优先级
```

### 手动触发动态优先级调整
```python
response = requests.post("http://192.168.3.53:8000/api/datasource/adjust-priorities")
```

### 逐个探测所有数据源（SSE 流式推送进度）

逐个调用各数据源做简单测试，更新健康状态。接口通过 **SSE (Server-Sent Events)** 实时推送每条探测进度，避免超时。

```python
import requests
import json

url = "http://192.168.3.53:8000/api/datasource/probe"
response = requests.post(url, stream=True)

for line in response.iter_lines():
    if line:
        line = line.decode("utf-8")
        if line.startswith("data: "):
            event = json.loads(line[6:])
            phase = event["phase"]
            if phase == "start":
                print(f"开始探测，共 {event['total']} 个数据源")
            elif phase == "progress":
                result = event["result"]
                status = "OK" if result["ok"] else f"FAIL({result.get('error','')})"
                print(f"[{event['done']}/{event['total']}] {event['name']}: {status} ({result['latency_ms']}ms)")
            elif phase == "complete":
                print(f"探测完成: {event['message']}")
                results = event["results"]  # 完整结果字典
```

**SSE 事件格式：**

| phase | 字段 | 说明 |
|-------|------|------|
| `start` | `total` | 数据源总数 |
| `progress` | `name`, `result`, `done`, `total` | 单个数据源探测结果 |
| `complete` | `results`, `done`, `total`, `duration_ms` | 全部完成，含完整结果字典 |

### 查看最近一次探测结果

探测完成后结果自动写入 `t_datasource_probe_log` 表，可通过此接口获取：

```python
response = requests.get("http://192.168.3.53:8000/api/datasource/probe/latest")
# 返回:
# {
#   "code": 200,
#   "data": {
#     "results": { "eastmoney": {"ok": true, ...}, ... },
#     "summary": {"total": 12, "ok": 10, "fail": 2},
#     "duration_ms": 8543,
#     "created_at": "2026-06-20 15:30:00"
#   }
# }
```

---

## 数据源容灾链总览

| 数据类型 | 容灾链 |
|----------|--------|
| A股实时 | eastmoney → qq → sina → tdx → yfinance → futu → finshare |
| A股K线 | qq → sina → eastmoney → tdx → yfinance → futu → finshare |
| 美股实时 | easy_tdx_us → akshare_us → yfinance → futu |
| 美股K线 | easy_tdx_us → akshare_us → yfinance → futu |
| 港股实时 | easy_tdx_hk → akshare_hk → yfinance → futu → finshare |
| 港股K线 | easy_tdx_hk → akshare_hk → yfinance → futu → finshare |
| 美股列表 | easy_tdx_us → akshare_us |
| 港股列表 | easy_tdx_hk → akshare_hk |
| 基金 | akshare → finshare |
| 期货 | akshare |
| 指数成分股 | akshare |
| 分红派息 | akshare |

### 智能路由机制

系统内置三层智能路由，自动选择最优数据源：

1. **偏好缓存**：系统记住每个接口+代码上次成功的数据源，下次直接优先从该数据源取数据
2. **动态优先级**：每5分钟根据各数据源的健康状态和平均延迟自动调整优先级（HEALTHY+低延迟加分，DEGRADED/UNAVAILABLE减分）
3. **容灾链降级**：偏好缓存的数据源失败时，自动按动态优先级走容灾链，成功后更新偏好缓存

---

## Tick 实时流 SSE 接口 — /api/stream/ticks

每 5 秒采集一次行情数据（TDX 优先，自动降级到东财/腾讯/新浪），通过 Redis Stream + SSE 推送给客户端。客户端只需持有一条 HTTP 长连接即可持续接收更新。

### 订阅 Tick 流（SSE）

```python
import requests
import json

# 订阅 IM（中证1000）和 IC（中证500）的实时 Tick 流
response = requests.get(
    "http://192.168.3.53:8000/api/stream/ticks",
    params={"codes": "IM,IC"},
    stream=True
)

for line in response.iter_lines():
    if line:
        line = line.decode("utf-8")
        if line.startswith("data: "):
            event = json.loads(line[6:])
            phase = event.get("phase")
            if phase == "snapshot":
                # 首次连接立即返回当前缓存快照
                print(f"快照: {event['data']}")
            elif phase == "update":
                # 后续每 5 秒推送增量更新
                print(f"更新: {event['data']}")
        elif line.startswith(":"):
            # 心跳保活注释，忽略
            pass
```

**SSE 事件格式：**

| phase | 字段 | 说明 |
|-------|------|------|
| `snapshot` | `data` | 首次连接立即返回的当前缓存快照 |
| `update` | `data`, `msg_id` | 每 5 秒推送的增量更新 |
| 心跳 | - | `: heartbeat\n\n` 注释行，保活用 |

**支持的 symbol：**

| symbol | 代码 | 说明 |
|--------|------|------|
| `IM` | 000852 | 中证1000指数 |
| `IC` | 000905 | 中证500指数 |
| `IF` | 000300 | 沪深300指数 |
| `IH` | 000016 | 上证50指数 |

> 也可传入任意 symbol，系统会自动注册并用 symbol 本身作为代码查询。

### 查询 Tick 采集器状态

```python
response = requests.get("http://192.168.3.53:8000/api/stream/ticks/status")
# 返回: {"code": 200, "data": {"collect_count": 120, "fail_count": 2, "success_rate": 98.3, ...}}
```

**状态字段说明：**

| 字段 | 说明 |
|------|------|
| `collect_count` | 总采集次数 |
| `fail_count` | 失败次数 |
| `success_rate` | 成功率（%） |
| `last_collect_ts` | 最近采集时间戳 |
| `tdx_timeout` | TDX 调用超时（秒） |
| `symbols` | 已注册的 symbol 列表 |

---

## 日K归档接口 — /api/kline-archive/

支持添加/删除/查询归档标的、查询已归档日K、手动回填、标的搜索。系统每天自动归档已配置标的的日K数据到数据库。

### 查询归档配置列表

```python
response = requests.get("http://192.168.3.53:8000/api/kline-archive/configs", params={
    "market": "CN",       # 可选: CN/US/HK
    "enabled": True        # 可选: 仅返回启用的
})
# 返回: [{"canonical_code": "000852", "market": "CN", "name": "中证1000", "adjust": "qfq", ...}, ...]
```

### 添加归档配置（含自动回填）

```python
response = requests.post(
    "http://192.168.3.53:8000/api/kline-archive/configs",
    json={
        "canonical_code": "000852",     # 必填: 标的代码
        "market": "CN",                # 必填: CN/US/HK
        "name": "中证1000",            # 可选: 标的名称
        "adjust": "qfq",               # 可选: qfq/hfq/none (默认 qfq)
        "period": "1d",                # 可选: 1d/1w/1M (默认 1d)
        "history_days": 365,            # 可选: 回填历史天数 (默认 365)
        "remark": "重点跟踪",           # 可选: 备注
        "enable_backfill": True         # 可选: 是否自动回填历史数据 (默认 True)
    }
)
```

### 删除归档配置

```python
response = requests.delete(
    "http://192.168.3.53:8000/api/kline-archive/configs",
    params={"canonical_code": "000852", "adjust": "qfq", "period": "1d"}
)
# 注意：删除配置不会删除已落库的日K数据
```

### 查询已归档日K数据

```python
response = requests.get("http://192.168.3.53:8000/api/kline-archive/kline", params={
    "canonical_code": "000852",      # 必填
    "start_date": "2024-01-01",      # 可选
    "end_date": "2024-12-31",        # 可选
    "adjust": "qfq",                # 可选 (默认 qfq)
    "period": "1d",                 # 可选 (默认 1d)
    "limit": 1000                    # 可选 (默认 1000)
})
# 返回: [{"date": "2024-01-02", "open": 6100, "high": 6150, "low": 6080, "close": 6120, "volume": 12345678, ...}, ...]
```

### 手动触发历史回填

```python
response = requests.post(
    "http://192.168.3.53:8000/api/kline-archive/backfill",
    json={
        "canonical_code": "AAPL",
        "market": "US",
        "adjust": "qfq",
        "period": "1d",
        "history_days": 180
    }
)
# 返回: {"code": 200, "message": "回填完成，写入 120 条", "data": {"count": 120}}
```

### 搜索标的物（代码补全）

```python
response = requests.get("http://192.168.3.53:8000/api/kline-archive/search", params={
    "keyword": "中证",       # 搜索关键词
    "market": "CN",          # 可选: CN/US/HK
    "limit": 20              # 可选 (默认 20)
})
# 返回: [{"code": "000852", "name": "中证1000", "market": "CN"}, ...]
```

### 查询标的物码表

```python
response = requests.get("http://192.168.3.53:8000/api/kline-archive/instruments", params={
    "market": "CN",          # 可选
    "keyword": "000",         # 可选
    "limit": 100             # 可选 (默认 100)
})
```

### 手动触发一次日K归档

```python
response = requests.post("http://192.168.3.53:8000/api/kline-archive/run")
# 不等待定时任务，立即执行一次归档
# 返回: {"code": 200, "message": "归档完成", "data": {...}}
```

---

## 数据源链路追踪 — /api/datasource/trace

执行一次数据源请求并返回完整的请求链追踪信息，包括每次尝试的记录、最终成功的数据源和剩余备用源。

### 一次性追踪（返回完整结果）

```python
response = requests.get("http://192.168.3.53:8000/api/datasource/trace", params={
    "data_type": "realtime",    # realtime/kline/futures/hk_realtime/us_realtime 等
    "code": "000852",           # 证券代码
    "type_": "index"            # 可选: index/stock/etf
})
# 返回: {"code": 200, "data": {"trace": {"full_chain": [...], "healthy_chain": [...], "attempts": [...], "final_source": "eastmoney", ...}, "data": {...}}}
```

### SSE 实时流式追踪

```python
response = requests.get(
    "http://192.168.3.53:8000/api/datasource/trace/sse",
    params={"data_type": "realtime", "code": "000852"},
    stream=True
)

for line in response.iter_lines():
    if line:
        line = line.decode("utf-8")
        if line.startswith("data: "):
            event = json.loads(line[6:])
            phase = event.get("phase")
            if phase == "chain":
                # 显示完整的容灾链和健康链
                print(f"容灾链: {event['full_chain']}")
                print(f"健康链: {event['healthy_chain']}")
            elif phase == "attempt":
                # 每次尝试一个数据源，实时推送
                status = "OK" if event.get("success") else "FAIL"
                print(f"  [{event['source']}] {status} ({event.get('latency_ms', 0)}ms)")
            elif phase == "complete":
                # 最终结果
                print(f"最终数据源: {event.get('final_source')}")
                print(f"总延迟: {event.get('total_latency_ms', 0)}ms")
```

**SSE 事件格式：**

| phase | 字段 | 说明 |
|-------|------|------|
| `chain` | `full_chain`, `healthy_chain`, `health_status` | 初始链信息 |
| `attempt` | `source`, `success`, `latency_ms`, `error` | 每次数据源尝试 |
| `complete` | `success`, `final_source`, `remaining_backups`, `total_latency_ms` | 最终结果 |

---

## 获取更多帮助

- 查看所有支持的方法：`GET /api/methods`
- 查看方法详细文档：`GET /api/method/{method_name}`
- 查看方法分类：`GET /api/categories`
- 从官方文档爬取更新方法参数：`POST /api/methods/scrape-docs`

### 爬取/更新方法参数文档

当需要更新 AkShare 方法参数信息时，可从akshare包直接提取或从官方文档爬取并入库。接口返回 **SSE 流式事件**，实时推送进度：

```python
import requests
import json

url = "http://192.168.3.53:8000/api/methods/scrape-docs"

# 方式1（推荐）：introspect 模式 - 从akshare包直接提取，无需网络，950+方法
resp = requests.post(url, stream=True, json={"mode": "introspect"})  # 默认 mode=scrape，需显式指定
for line in resp.iter_lines():
    if line:
        line = line.decode("utf-8")
        if line.startswith("data: "):
            event = json.loads(line[6:])
            print(event)

# 方式2：scrape 模式 - 爬取官方文档页面（需要网络访问）
resp = requests.post(url, stream=True, json={"mode": "scrape"})

# 方式3：scrape 指定页面
requests.post(url, stream=True, json={"mode": "scrape", "pages": ["stock/stock", "fund/fund_public"]})
```
