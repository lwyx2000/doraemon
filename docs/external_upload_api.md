# 持仓 / 成交 外部上传接口（无鉴权，机器 / 程序调用）

> 用途：供其它程序批量上传持仓与成交数据，无需 JWT 登录。
> 服务端口：后端 `:8001`（`docker-compose` 映射视部署而定，前端经 nginx `:9080` 反代到 `/api/v1`）。
> 完整前缀：`/api/v1`。
>
> **相关文档**：页面内使用的交割单导入（Excel/CSV，需 JWT）、交易台账查询与分品种费率统计见
> [`trading_import_api.md`](./trading_import_api.md)。该组接口写入 `biz_settlements`，
> 并会把本文件第 2 节的 `biz_trades` 每日成交作为补充源合并分析。两者的鉴权方式与用户定位方式不同，不要混用。

## 通用约定

- 用户定位：请求体里用 `user_id`（整数，对应用户表 `pk_user`）**或** `username`（字符串）二选一指明归属用户。两者都缺 / 不存在 → `400`。
- 留痕：`source` 字段标记来源程序（任意字符串，如 `"my_bot"`），写入历史表便于追溯；缺省为 `"api"`。
- **券商与终端模型（`account` 客户端自传）**：
  - 一个**终端（terminal）**可挂多个**券商（broker）**；券商以 `account`（券商资金账号，由调用方自传，作为主标识）唯一确定。
  - 请求体**顶层**传 `account`（必填，整批统一归属该券商）。可选 `broker_name`（券商展示名，首次出现且需新建券商时写入）、`terminal`（所属终端名，缺省自动建「默认终端」）、`remark`（备注）。
  - 解析规则（`resolve_or_create_broker_for_upload`）：按 `(user, account)` 命中已有券商 → 复用；未命中 → 若 `broker_name` 提供则自动新建券商（挂到指定 / 默认终端），否则整批进入 `failed`、不写入任何数据。
  - `account` 缺失或解析失败 → **整批条目进入 `failed`、不写入任何数据**（详见各接口响应说明）。
- 响应统一结构：`{ "code": 0, "message": "ok", "data": {...} }`（`ApiResponse`）。

---

## 1. 持仓上传（增量合并 + 覆盖留痕）

`POST /api/v1/holdings/import/api` — **无鉴权**

语义（按需求）：
- 增量合并（merge）：按 `code + type + account` 去重；已存在 → 覆盖更新，新增 → 插入。
- 覆盖更新前，旧行写入 `biz_holdings_history` 表留痕（满足「旧的数据存到数据表中，记录下」）。
- 新接口不删除任何历史行，仅打快照。

### 字段（每个 item）

> 顶层必传 `account`（见上方通用约定），整批统一券商；下方 `broker` 列由后端按 `account` 解析逐条回填，**无需逐条传**。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | ✅ | 证券代码 |
| `name` | string | ✅ | 证券名称 |
| `type` | string | ✅ | `stock` / `etf` / `fund_otc` / `option` / `future` / `hk_stock` |
| `quantity` | number | ✅ | 持仓数量 |
| `cost_price` | number | ✅ | 成本价 |
| `broker` | string | 否 | 券商（**由顶层 `account` 解析填充、逐条覆盖，不传或传了均忽略**） |
| `account` | string | 否 | 子账户（普通 / 两融等；**注意与顶层券商 `account` 区分**：顶层为券商资金账号，此处为子账户名） |
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
    "account": "HUAXIA-12345678",
    "broker_name": "华泰证券",
    "terminal": "主终端",
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

> 也可用 `username` 定位：`{ "username": "sos", "account": "HUAXIA-12345678", "broker_name": "华泰证券", "source": "my_bot", "items": [...] }`
> `account` 缺失或解析失败（如未提供 `broker_name` 且券商不存在）时响应为 `{ "added": 0, "updated": 0, "failed": [ { "index": 0, "code": "", "reason": "account 缺失或券商解析失败" }, ... ] }`，整批不入库。

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

> 顶层必传 `account`（见上方通用约定），整批统一券商；下方 `broker` 由后端按 `account` 解析逐条回填，**无需逐条传**。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | ✅ | 证券代码 |
| `direction` | string | ✅ | `buy` / `sell` |
| `price` | number | ✅ | 成交价（>0） |
| `quantity` | number | ✅ | 成交数量（>0） |
| `name` | string | 否 | 证券名称 |
| `type` | string | 否 | 默认 `stock` |
| `broker` / `account` | string | 否 | 券商由顶层 `account` 解析填充（逐条覆盖）；`account` 仍为逐条子账户 |
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
    "account": "HUAXIA-12345678",
    "broker_name": "华泰证券",
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

### 3.4 交易台账接口（需登录，见独立文档）
`POST /api/v1/trading/import/settlement`（券商 Excel 交割单）、`POST /api/v1/trading/import/daily`（每日成交补录）、
`GET /api/v1/trading/{settlements,daily,closed,analysis}`、`DELETE /api/v1/trading/settlements`。
完整字段、表头别名与费率口径见 [`trading_import_api.md`](./trading_import_api.md)。

> 注意：本文第 2 节 `/trades/import` 写入的 `biz_trades` 会被 `GET /api/v1/trading/daily` 与 `/analysis`
> 合并消费（交割单优先、按成交编号 / 内容指纹去重）。由于该表没有分项费用列，来自它的成交在费率统计中
> 会被排除，并在对账告警里标 `fee_estimated`。要统计真实费率，请改用交割单导入。

---

## 部署注意

- 上线走 Jenkins `doraemon-deploy`（`DEPLOY_TARGET=all / DEPLOY_ACTION=deploy / FORCE_PULL=true`），
  会重建前后端镜像并重启容器；旧的 `git bundle → scp 53 → 代推 GitHub` 手工流程已废弃。
- `biz_trades` 与 `biz_holdings_history` 表均为 `CREATE TABLE IF NOT EXISTS` 幂等建表，首次请求自动落库，无需手动迁移。
- 终端 / 券商表（`biz_terminals` / `biz_brokers`）为幂等建表；首个上传请求会自动建「默认终端」与对应券商。
- `biz_settlements`（交割单）同样幂等建表，并有 `(fk_user, trade_id)` 唯一索引保证重复导入不产生重复行；
  读取 `.xlsx` 依赖后端 `openpyxl`，新增依赖后需重建后端镜像。
