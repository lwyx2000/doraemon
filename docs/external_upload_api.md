# 持仓 / 成交 外部上传接口（无鉴权，机器 / 程序调用）

> 用途：供其它程序批量上传持仓与成交数据，无需 JWT 登录。
> 服务端口：后端 `:8001`（`docker-compose` 映射视部署而定，前端经 nginx `:9080` 反代到 `/api/v1`）。
> 完整前缀：`/api/v1`。

## 通用约定

- 用户定位：请求体里用 `user_id`（整数，对应用户表 `pk_user`）**或** `username`（字符串）二选一指明归属用户。两者都缺 / 不存在 → `400`。
- 留痕：`source` 字段标记来源程序（任意字符串，如 `"my_bot"`），写入历史表便于追溯；缺省为 `"api"`。
- **券商标识 `broker_code`（整批必传）**：请求体**顶层**传一个 `broker_code`（形如 `BRK-1A2B3C`，来自前端「持仓分析 → 券商管理」tab 自动生成），**整批统一归属该券商**。不要再给每个 item 传 `broker`（即便传了也会被忽略，实际券商名由 `broker_code` 解析得到并逐条回填）。`broker_code` 缺失或不属于该用户 → **整批条目进入 `failed`、不写入任何数据**（详见各接口响应说明）。
- 响应统一结构：`{ "code": 0, "message": "ok", "data": {...} }`（`ApiResponse`）。

---

## 1. 持仓上传（增量合并 + 覆盖留痕）

`POST /api/v1/holdings/import/api` — **无鉴权**

语义（按需求）：
- 增量合并（merge）：按 `code + type + account` 去重；已存在 → 覆盖更新，新增 → 插入。
- 覆盖更新前，旧行写入 `biz_holdings_history` 表留痕（满足「旧的数据存到数据表中，记录下」）。
- 新接口不删除任何历史行，仅打快照。

### 字段（每个 item）

> 顶层必传 `broker_code`（见上方通用约定），整批统一券商；下方 `broker` 列由后端按 `broker_code` 解析逐条回填，**无需逐条传**。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | ✅ | 证券代码 |
| `name` | string | ✅ | 证券名称 |
| `type` | string | ✅ | `stock` / `etf` / `fund_otc` / `option` / `future` / `hk_stock` |
| `quantity` | number | ✅ | 持仓数量 |
| `cost_price` | number | ✅ | 成本价 |
| `broker` | string | 否 | 券商（**由顶层 `broker_code` 解析填充、逐条覆盖，不传或传了均忽略**） |
| `account` | string | 否 | 子账户（普通 / 两融等） |
| `open_date` | string | 否 | 建仓日期 |
| `currency` | string | 否 | 币种，默认 `CNY` |
| `stop_loss_pct` / `take_profit_pct` | number | 否 | 止损 / 止盈比例 |

### 请求示例

```bash
curl -X POST 'http://192.168.3.53:9080/api/v1/holdings/import/api' \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": 1,
    "source": "my_bot",
    "broker_code": "BRK-1A2B3C",
    "items": [
      {
        "code": "510300",
        "name": "沪深300ETF",
        "type": "etf",
        "account": "普通",
        "quantity": 10000,
        "cost_price": 3.85,
        "open_date": "2026-01-05",
        "currency": "CNY"
      },
      {
        "code": "600519",
        "name": "贵州茅台",
        "type": "stock",
        "account": "普通",
        "quantity": 100,
        "cost_price": 1680.0
      }
    ]
  }'
```

> 也可用 `username` 定位：`{ "username": "sos", "broker_code": "BRK-1A2B3C", "source": "my_bot", "items": [...] }`
> `broker_code` 缺失或非法时响应为 `{ "added": 0, "updated": 0, "failed": [ { "index": 0, "code": "", "reason": "broker_code 缺失或非法（不属于该用户）" }, ... ] }`，整批不入库。

### 响应（data 部分）

```json
{ "added": 2, "updated": 0, "failed": [] }
```

---

## 2. 成交上传（按交易日全量覆盖）

`POST /api/v1/trades/import` — **无鉴权**

语义（按需求）：
- 独立表 `biz_trades`，按 `(user, trade_date)` 维度：**先 DELETE 该用户该日全部旧记录，再全量 INSERT** → 同一天重复上传 = 覆盖；
- **新 trade_date 直接全量新增**，互不干扰；
- 历史交易日数据保留不删（成交表本身即各日期全量快照）；
- `trade_date` 必填，格式 `YYYY-MM-DD`，否则 `400`。

### 字段（每个 item）

> 顶层必传 `broker_code`（见上方通用约定），整批统一券商；下方 `broker` 由后端按 `broker_code` 解析逐条回填，**无需逐条传**。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | ✅ | 证券代码 |
| `direction` | string | ✅ | `buy` / `sell` |
| `price` | number | ✅ | 成交价（>0） |
| `quantity` | number | ✅ | 成交数量（>0） |
| `name` | string | 否 | 证券名称 |
| `type` | string | 否 | 默认 `stock` |
| `broker` / `account` | string | 否 | 券商由顶层 `broker_code` 解析填充（逐条覆盖）；`account` 仍为逐条子账户 |
| `amount` | number | 否 | 成交额；缺省自动 `price*quantity` 四舍五入 2 位 |
| `fee` | number | 否 | 手续费 |
| `trade_time` | string | 否 | 成交时间 `YYYY-MM-DD HH:MM:SS` |

### 请求示例（上传某交易日全部成交）

```bash
curl -X POST 'http://192.168.3.53:9080/api/v1/trades/import' \
  -H 'Content-Type: application/json' \
  -d '{
    "username": "sos",
    "source": "my_bot",
    "broker_code": "BRK-1A2B3C",
    "trade_date": "2026-10-28",
    "items": [
      {
        "code": "510300",
        "name": "沪深300ETF",
        "type": "etf",
        "account": "普通",
        "direction": "buy",
        "price": 3.92,
        "quantity": 5000,
        "trade_time": "2026-10-28 09:45:12"
      },
      {
        "code": "600519",
        "name": "贵州茅台",
        "type": "stock",
        "account": "普通",
        "direction": "sell",
        "price": 1700.5,
        "quantity": 100,
        "fee": 15.2,
        "trade_time": "2026-10-28 14:30:08"
      }
    ]
  }'
```

### 响应（data 部分）

```json
{ "deleted": 0, "inserted": 2, "failed": [] }
```

> `deleted` = 该用户该日原有记录数（新日期为 0）；`inserted` = 本次写入行数；`failed` = 校验失败明细。

---

## 3. 辅助查询接口

### 3.1 查看成交记录
`GET /api/v1/trades?user_id=1&trade_date=2026-10-28` — 可按 `username` 或 `trade_date` 过滤。

### 3.2 列出所有成交交易日
`GET /api/v1/trades/dates?username=sos` — 返回升序去重交易日列表。

### 3.3 查看持仓覆盖历史（需登录）
`GET /api/v1/holdings/history/archive?hold_id=<可选>` — 浏览器 / 带 JWT 调用，按归档时间倒序查看被覆盖的旧持仓快照（`biz_holdings_history`）。

---

## 部署注意

- 代码尚未提交 / 部署（本次为本地实现）。上线需走标准流程：
  `commit → git bundle → scp 53 → 53 git fetch+ff → 代推 GitHub → 宿主 npm run build → docker compose build frontend && up -d --force-recreate frontend`（后端镜像一并重建以纳入新路由）。
- `biz_trades` 与 `biz_holdings_history` 表均为 `CREATE TABLE IF NOT EXISTS` 幂等建表，首次请求自动落库，无需手动迁移。
