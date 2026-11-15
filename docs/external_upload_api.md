# 持仓 / 成交 等外部上传接口（无鉴权，机器 / 程序调用）

> 用途：供 brokerAuto 等程序把**采集到的全部业务数据**定时推送到本服务，无需 JWT 登录。
> 服务端口：后端 `:8001`（前端经 nginx `:9080` 反代到 `/api/v1`）。完整前缀 `/api/v1`。
> 页面入口：持仓分析 → 当前持仓（按资金账号切换）/ 账户数据 / 上传记录 / 交易台账。
>
> **2026-11-14 按资金账号重构**：所有数据按 `(user, broker_account, trade_date)` 隔离，
> 一次请求可传多个账号，多账号分次上传互不相删；`type` 不再是硬白名单，
> 逆回购 / 可转债 / 标准券原样保存；补齐委托、资金面板、JSON 交割单端点。
> 旧调用（只带顶层 `account`）行为完全兼容。
>
> 相关文档：页面内使用的交割单导入（Excel/CSV，需 JWT）、交易台账查询与费率统计见
> [`trading_import_api.md`](./trading_import_api.md)。

## 通用约定

- 用户定位：请求体里用 `user_id`（整数）**或** `username`（字符串）二选一。两者都缺 / 不存在 → `400`。
  ⚠️ 不要用「`user_id=1` 等价于 `username=sos`」的假设，请统一用 `username`。
- 响应结构：`{ "code": 200, "message": "success", "data": {...} }`（`ApiResponse`）。
- 留痕：`source` 标记来源程序，写入 `biz_import_log`，持仓分析 → 上传记录可按资金账号查看。
- **资金账号模型（本版核心）**：
  - `broker_account`（券商资金账号）是数据隔离主键；一个用户可有多个资金账号。
  - 顶层 `account`（或历史别名 `broker_code`）是**整批默认值**；
    逐条 `broker_account`（兼容 `fund_account` / `_broker_account`）可覆盖它。
  - 顶层 `account` 缺失但每条都带 `broker_account` 时同样合法 → **一次请求传多个账号**。
  - 逐条 `account` 仍然是「普通 / 两融」这类**子账户名**，两者不要混。
  - 每个资金账号独立解析 / 自动建券商；`terminal` 传了不存在的名称会自动回落到「默认终端」，
    不会再误报「account 缺失」。
- **dry_run**：所有上传端点支持 `dry_run: 1`，只校验不写库，返回 `would_*` 计数。
- **失败明细**：`failed[]` 每条带 `index / code / account / reason / item`（原始条目），便于重传。
- **按账号响应**：上传响应统一带 `by_account: [{account, broker, added/updated/inserted/deleted/failed}]`。

---

## 0. 推荐接入方式：统一批量端点（一次 POST 传全部数据）

`POST /api/v1/external/batch` — **无鉴权**

把多个资金账号的持仓 / 成交 / 委托 / 资金面板 / 交割单放在一个请求里。
**省略某类数据 = 不更新它；传空数组 `[]` = 清空该类（按账号按日覆盖）**。
`holdings` 默认 `mode=replace`（全量快照，本地清仓后服务端自动归档），
`trades` / `orders` / `settlements` 按 `(user, 资金账号, trade_date)` 覆盖，
`balance` 按 `(user, 资金账号, trade_date)` upsert 并保留历史。

```bash
curl -X POST 'http://192.168.3.53:9080/api/v1/external/batch' \
  -H 'Content-Type: application/json' \
  -d '{
    "username": "sos", "source": "brokerAuto", "trade_date": "2026-11-14", "dry_run": 0,
    "accounts": [
      {
        "account": "666622117166", "broker_name": "华泰证券",
        "holdings": [
          {"code":"600519","name":"贵州茅台","type":"stock","quantity":100,"cost_price":1680,
           "avail_qty":100,"last_price":1700,"client_market_value":170000,"client_profit":2000},
          {"code":"204001","name":"GC001","type":"repo","quantity":1000,"cost_price":1.2,
           "client_market_value":85000},
          {"code":"127119","name":"中鼎转03","type":"bond_cb","quantity":10,"cost_price":140.16}
        ],
        "trades": [
          {"code":"204001","name":"GC001","type":"repo","direction":"sell","price":1.2,
           "quantity":850,"amount":85000,"trade_id":"T1","biz":"通用回购逆回购",
           "trade_time":"2026-11-14 09:35:01"},
          {"code":"204001","type":"repo","direction":"repo_buy","price":1.2,
           "quantity":-790,"amount":79000,"trade_id":"T2","biz":"通用回购逆回购购回"}
        ],
        "orders": [
          {"order_no":"O1","code":"600519","name":"贵州茅台","side":"买入",
           "price":1680,"quantity":100,"filled_qty":100,"order_time":"09:40:00","status":"已成"}
        ],
        "balance": {"total_asset":256504.88,"available":78967.99,"withdrawable":965.71,
                    "market_value":177287.30,"position_profit":57122.81,
                    "today_profit":737.70,"today_profit_pct":0.29,"frozen":200,"buy_unfilled":0},
        "settlements": [
          {"trade_date":"2026-11-14","code":"600519","name":"贵州茅台","direction":"买入",
           "price":1680,"quantity":100,"amount":168000,"commission":25,"stamp_tax":0,
           "transfer_fee":1,"trade_id":"S1"}
        ]
      },
      {"account": "262700008483", "broker_name": "银河证券",
       "holdings": [], "trades": [], "balance": {"total_asset":50000,"available":10800}}
    ]
  }'
```

不带 `accounts` 时退化为单账号：直接读顶层 `holdings / trades / orders / balance / settlements` +
`account`。响应：

```json
{
  "code": 200, "message": "success",
  "data": {
    "ok": true, "dry_run": false, "trade_date": "2026-11-14", "account_count": 2,
    "results": [{"account":"666622117166","broker":"华泰证券","parts":{"holdings":{...},"trades":{...}}, "failed":0}],
    "totals": {"added":3,"updated":0,"removed":0,"deleted":0,"inserted":9,"failed":0}
  }
}
```

> 也可以用 `holdings_mode=merge` / `trades_mode=merge` 覆盖默认的 `replace`。
> `merge` 的成交按 `trade_id` 幂等 upsert，适合断点重传。

---

## 1. 持仓上传

`POST /api/v1/holdings/import/api` — **无鉴权**

语义：按 `broker_account + code + type + broker + 子账户` **增量合并**；
覆盖前旧行写入 `biz_holdings_history` 留痕。`mode=replace` 时按账号全量快照，
本次未出现的行自动归档（清仓不再残留）。

| 字段（每个 item） | 类型 | 必填 | 说明 |
|---|---|---|---|
| `code` / `name` | string | ✅ | 代码 / 名称 |
| `type` | string | ✅ | **自由字符串**：`stock / etf / fund_otc / option / future / hk_stock / repo / bond_cb / standard_bond / bond / other`，未知值原样保存并单独归类 |
| `quantity` / `cost_price` | number | ✅ | 数量 / 成本价（数量可为负，不可为 0） |
| `broker_account` | string | 否 | 资金账号，覆盖顶层 `account` |
| `account` | string | 否 | 子账户（普通 / 两融） |
| `avail_qty` | number | 否 | 可用数量 |
| `last_price` | number | 否 | 客户端上报现价（行情取不到时兜底） |
| `client_market_value` / `market_value` | number | 否 | 客户端上报市值（进入总市值汇总） |
| `client_profit` / `profit` / `profit_pct` | number | 否 | 客户端上报盈亏 |
| `snapshot_date` / `trade_date` | string | 否 | 快照日期 |
| `open_date` / `currency` / `biz` / `raw` | any | 否 | 建仓日 / 币种 / 业务名 / 券商原始行 |
| 其它任意字段 | any | 否 | `extra="allow"`：全部保留，不再静默丢弃 |

顶层：`username/user_id`、`source`、`account`、`broker_name`、`remark`、`terminal`、
`mode`(`merge`/`replace`)、`dry_run`、`snapshot_date`。

响应：

```json
{"added":3,"updated":0,"removed":0,"failed":[],
 "by_account":[{"account":"666622117166","broker":"华泰证券","added":3,"updated":0,"removed":0,"failed":0}],
 "dry_run":false}
```

---

## 2. 成交上传

`POST /api/v1/trades/import` — **无鉴权**

语义：**按 `(user, broker_account, trade_date)` 覆盖**（不再是按用户按日全删）。
本批涉及的账号当日旧行 + 历史遗留的无账号行会被删除后重插；其它账号当日数据不受影响。
`mode=merge` 改为按 `trade_id` 幂等 upsert。

| 字段（每个 item） | 类型 | 必填 | 说明 |
|---|---|---|---|
| `code` | string | ✅ | 证券代码 |
| `direction` | string | ✅ | `buy / sell / repo_sell / repo_buy / new_issue / dividend / interest / cash_in / cash_out / other`，也接受中文业务名（「通用回购逆回购购回」→ `repo_buy`） |
| `price` / `quantity` | number | ✅ | 价格（逆回购为**年化利率**）/ 数量（**允许负数**，购回 -790） |
| `amount` | number | 否 | **显式成交额优先**；不给才按 `price*quantity` 算 |
| `type` | string | 否 | 自由字符串：`repo / bond_cb / standard_bond` 等，默认 `stock` |
| `trade_id` / `order_no` | string | 否 | 成交编号 / 委托编号（对账、幂等） |
| `biz` / `entry_type` | string | 否 | 业务名 / `trade`/`cash`/`other` |
| `fee` / `commission` / `stamp_tax` / `transfer_fee` / `other_fee` / `fee_total` / `net_amount` | number | 否 | 手续费与分项费用 |
| `trade_time` / `settle_date` / `currency` / `raw` | any | 否 | 成交时间 / 交割日 / 币种 / 原始行 |
| `broker_account` / `account` | string | 否 | 资金账号 / 子账户 |

> `direction` 非 `buy/sell` 的流水（购回、新股入帐、分红、出入金）**只入库展示**，
> 不参与做T / 已清仓 / 胜率 / 费率统计，避免污染盈亏口径。

响应：`{"deleted":0,"inserted":2,"failed":[],"by_account":[...],"dry_run":false}`。

---

## 3. 新增端点（把剩下的数据也收进来）

全部**无鉴权**，都支持逐条 `broker_account`、多账号、按账号覆盖、`dry_run`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/orders/import` | 当日委托：`order_no/code/name/side/price/quantity/filled_qty/filled_price/order_time/status/raw`，按 `(user,资金账号,trade_date)` 覆盖 |
| POST | `/api/v1/account/balance/import` | 资金面板：`balance` 扁平对象或 `items[]` 多账号，按 `(user,资金账号,trade_date)` upsert，保留历史快照 |
| POST | `/api/v1/settlements/import` | **无鉴权 JSON 交割单**：分项费用 / 成交编号 / 业务名 / 净额 / 原始行，写入 `biz_settlements`，现有费率、已清仓、做T分析直接消费 |
| POST | `/api/v1/brokers/import` | 预注册券商：`brokers:[{account,broker_name,terminal,remark}]`，避免首次上传静默失败 |
| GET | `/api/v1/external/overview` | 账号总览：每账号持仓/成交/委托/资金/上传次数与最后同步时间 + 全局合计 |
| GET | `/api/v1/external/accounts` | 只返回账号列表 |
| GET | `/api/v1/external/trades?broker_account=&trade_date=&limit=` | 成交明细（含新字段） |
| GET | `/api/v1/external/orders?broker_account=&trade_date=` | 委托明细 |
| GET | `/api/v1/external/balances?broker_account=&limit=` | 资金面板历史 |
| GET | `/api/v1/external/settlements?broker_account=&date_from=&date_to=` | 交割单明细 |

> 查询端点同时接受浏览器 JWT 与 `?username=...` / `?user_id=...`（外部预检）。

### 3.1 资金面板示例

```bash
curl -X POST 'http://192.168.3.53:9080/api/v1/account/balance/import' \
  -H 'Content-Type: application/json' \
  -d '{
    "username":"sos","source":"brokerAuto","trade_date":"2026-11-14",
    "account":"666622117166","broker_name":"华泰证券",
    "balance":{"total_asset":256504.88,"available":78967.99,"withdrawable":965.71,
               "market_value":177287.30,"position_profit":57122.81,
               "today_profit":737.70,"today_profit_pct":0.29,"frozen":200,"buy_unfilled":0}
  }'
```

### 3.2 旧端点（兼容，不 recommend 新接入）

- `GET /api/v1/trades?user_id=1&trade_date=...` 仍可用，新增 `broker_account` / `limit` 过滤。
- `GET /api/v1/trades/dates?username=sos` 列出交易日。
- `GET /api/v1/holdings/history/archive?hold_id=`（需 JWT）查看持仓覆盖快照。
- `GET /api/v1/holdings?type=&broker=&account=&broker_account=`（需 JWT）新增资金账号过滤。

---

## 4. 中间交互怎么设计（为什么这样改）

| 风险 | 旧行为 | 现在 |
|---|---|---|
| 多账号同日成交互相删 | 按 `(user, trade_date)` 先删后插 | 按 `(user, broker_account, trade_date)` 删；一次 POST 多账号也只删涉及账号 |
| 不同账号同标的持仓互相覆盖 | `code+type+account` | `broker_account+code+type+broker+子账户`；旧库无账号行会被本次「认领」补上账号，不产生重复 |
| 一次只能传一个账号 | 顶层 `account` 整批统一 | 逐条 `broker_account` 覆盖；`external/batch` 用 `accounts[]` 一次传全部 |
| 逆回购/可转债被拒 | 持仓 `type` 硬白名单 | 自由字符串 + 单独归类；成交 `amount` 显式优先（price 是年化利率） |
| 购回 / 新股入帐丢失 | `direction` 只允许 buy/sell、数量须正 | 方向扩展 + 中文业务名归一化 + 负数量，非买卖流水只入库不进盈亏统计 |
| 缺成交编号 / 费用 / 原始行 | 静默忽略 | 全部落库，`raw` 最长 4000 字符 |
| 写脏数据难排查 | 无预演 | `dry_run=1` + `failed[].item` + 按账号 `by_account` + 上传记录留痕 |
| 本地清仓后服务端残留 | 增量合并 | `mode=replace` 按账号全量快照，自动归档已清仓行 |
| 首次上传报「account 缺失」 | 传了不存在的 `terminal` 就整批失败 | `terminal` 无效自动回落默认终端；也可先调 `/brokers/import` 预注册 |

**单人局域网使用**：只传一个账号，和以前一样简单；`external/batch` 里 `accounts` 只有一项即可。
**预留多账号**：数据模型、去重键、覆盖维度、页面筛选都按账号设计，新增账号不需要改代码，
持仓分析页会自动出现新账号的卡片、切换器与「账户数据」明细。

---

## 5. 部署注意

- 上线走 Jenkins `doraemon-deploy`（`DEPLOY_TARGET=all / DEPLOY_ACTION=deploy / FORCE_PULL=true`）。
- `biz_holdings` / `biz_trades` / `biz_settlements` 的新列由 `init_biz_database()` 与
  service 层 `_ensure_tables()` 双重幂等 `ALTER` 补齐；`biz_orders` / `biz_account_balances` /
  `biz_import_log` 静态 DDL 建表，无需手工迁移。
- 契约回归测试：`python backend/scripts/test_external_upload.py`（用独立临时 SQLite，不碰线上数据）。
- 安全：无鉴权端点默认只在局域网使用；若暴露到外网，建议加 `X-Upload-Token` 或对 `source` 白名单。
