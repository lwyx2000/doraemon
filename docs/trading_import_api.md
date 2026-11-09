# 交易台账导入与分析接口（JWT，交割单 / 每日成交 / 费率）

> 适用版本：2026-11-09 起（`doraemon` 交易台账功能）。
> 基址：`http://<HOST>:9080`（生产入口 `http://10.100.213.248:9080`），统一前缀 `/api/v1`。
> 页面入口：持仓分析 → **交易台账**（导入 / 每日成交 / 交割单 / 已清仓）与 **交易分析**（做T / 胜率 / 费率 / 对账）。

**与无鉴权接口的区别**：[`external_upload_api.md`](./external_upload_api.md) 里的 `/holdings/import/api`、`/trades/import` 供机器程序批量上传，**无需登录**、用 `user_id` / `username` 定位用户；本文的接口是**页面内使用、全部需要 JWT**，用户归属由 token 的 `sub` 决定。两者写入同一张 `biz_trades`（每日成交），交割单单独写 `biz_settlements`。

统一响应结构：`{ "code": 0, "message": "ok", "data": {...} }`；未带或过期 token 返回 `401`。

---

## 0. 快速开始

```bash
# 1) 取 token
TOKEN=$(curl -s -X POST 'http://10.100.213.248:9080/api/v1/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username":"<用户名>","password":"<密码>"}' | python -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")

# 2) 导入券商 Excel 交割单
curl -X POST 'http://10.100.213.248:9080/api/v1/trading/import/settlement' \
  -H "Authorization: Bearer $TOKEN" \
  -F 'file=@交割单.xlsx' \
  -F 'broker=华泰证券' \
  -F 'account=普通' \
  -F 'mode=merge'

# 3) 查看分析（含分品种 / 分标的费率）
curl -s 'http://10.100.213.248:9080/api/v1/trading/analysis' \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

---

## 1. 端点总览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/trading/import/settlement` | 上传券商交割单（multipart，`.xlsx/.xlsm/.csv/.txt`） |
| POST | `/api/v1/trading/import/daily` | 导入 / 补录某交易日成交（JSON，按日全量覆盖） |
| DELETE | `/api/v1/trading/settlements?trade_date=YYYY-MM-DD` | 清空该交易日交割单，用于重导 |
| GET | `/api/v1/trading/settlements?from=&to=&code=&direction=&limit=` | 交割单明细（含资金流水），按成交日期倒序 |
| GET | `/api/v1/trading/daily?from=&to=&code=` | 每日成交（交割单 + 补充的 `biz_trades`，去重）与按日汇总 |
| GET | `/api/v1/trading/closed` | 已清仓 FIFO 回合 + 由流水重建的当前持仓 |
| GET | `/api/v1/trading/analysis?from=&to=` | 综合分析（做T / 胜率 / 费用 / **费率** / 行为 / 对账） |

`from` / `to` 为 `YYYY-MM-DD`，作用于**成交日期**；不传则取全部历史。`limit` 默认 5000，上限 50000。

---

## 2. 交割单导入 `POST /api/v1/trading/import/settlement`

### 2.1 请求（multipart/form-data）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | ✅ | `.xlsx` / `.xlsm` / `.csv` / `.txt`；读第一个 sheet；CSV 自动尝试 UTF-8-SIG / GBK / GB2312 / UTF-8 |
| `broker` | string | 否 | 券商名兜底值：文件里没有「券商名称」列时统一填充 |
| `account` | string | 否 | 账户 / 股东账号兜底值：文件里没有「股东账号」列时统一填充 |
| `mode` | string | 否 | `merge`（默认，按成交编号去重）/ `replace`（先清空文件中涉及的交易日再导入） |

> ⚠️ 老格式 `.xls` **不支持**，请先另存为 `.xlsx` 或 CSV。`.xlsx` 依赖后端 `openpyxl`（已写入 `backend/requirements.txt`）。

### 2.2 表头别名（大小写 / 空格不敏感）

解析器会**自动跳过券商标题行**：在前 25 行里寻找含「证券代码」且至少 4 列可识别的行作为表头；找不到时退而求其次找含「成交日期」且至少 3 列的行。列名先精确匹配、再按别名长度做包含匹配。

| 内部字段 | 可识别的列名（部分列举，完整见 `backend/services/trading_ledger_service.py::_HEADER_ALIASES`） |
|---|---|
| `code` | 证券代码、股票代码、基金代码、证券编号、代码、code、symbol |
| `name` | 证券名称、股票名称、证券简称、基金名称、名称、name |
| `trade_date` | 成交日期、交易日期、委托日期、发生日期、日期、date |
| `settle_date` | 交割日期、交收日期、结算日期 |
| `trade_id` | 成交编号、合同编号、成交序号、成交号、委托编号、流水号 |
| `direction` | 买卖标志、买卖方向、业务标志、业务名称、摘要、交易类别、方向、操作、direction |
| `price` / `quantity` / `amount` | 成交价格/成交均价/成交价；成交数量/成交股数/成交手数；成交金额/成交总额/成交额 |
| `commission` | 佣金 |
| `stamp_tax` | 印花税 |
| `transfer_fee` | 过户费、交易经手费、经手费 |
| `other_fee` | 其他费用、附加费、结算费、杂费 |
| `fee_total` | 费用合计、手续费合计、手续费、费用总额、总费用 |
| `net_amount` | 发生金额、资金变动、收付金额、清算金额、实际收付、净额 |
| `trade_time` | 成交时间、委托时间、时间 |
| `account` | 股东账号、股东代码、资金账号、账户、账号 |
| `broker` / `currency` / `type` | 券商名称/营业部/券商；币种/货币；证券类别/品种/类型 |

**最少需要**：`成交日期` + `买卖标志` + `证券代码`（交易行）+ `成交价格` + `成交数量`。`成交额` 缺失时自动按 `价格 × 数量` 计算；`发生金额` 缺失时按 `买入 = -(成交额+费用)` / `卖出 = 成交额-费用` 推算。

**费用列优先级**：`佣金 + 印花税 + 过户费 + 其他费用` 的分项合计优先；分项全为 0 时才采用「费用合计」列。只提供费用合计、不提供分项时，费率统计里的分项显示为 0，差额计入 `unallocated_fee`。

### 2.3 买卖标志取值与业务归类

| 写入 `direction` | `entry_type` | 可识别文本 |
|---|---|---|
| `buy` | `trade` | 买入、买进、证券买、申购、买、B、b、1、buy |
| `sell` | `trade` | 卖出、卖空、证券卖、赎回、卖、S、s、2、-1、sell |
| `dividend` | `cash` | 股息、红利、分红、派息 |
| `interest` | `cash` | 结息、利息 |
| `cash_in` | `cash` | 银行转存、银行转入、资金存入、转入、存入 |
| `cash_out` | `cash` | 银行转取、银行转出、资金取出、转出、取出 |
| `other` | `other` | 其它文本 → **该行进入 `failed`，不入库** |

`entry_type != trade` 的资金流水会入库并展示在交割单列表里，但**不参与**做T、已清仓、费率与盈亏计算。

### 2.4 其它解析规则

- 日期兼容 Excel `datetime` / Excel 序列号 / `20261103` / `2026-11-03` / `2026/11/03`；时间兼容 `datetime`、`09:35:01`、`2026-11-03 09:35:01`。
- 金额自动去掉千分位逗号、`¥`；`—` / `--` / 空串视为缺失。
- **证券代码补零**：Excel 把 `000001` 读成数字 `1` 时自动补成 `000001`；去除首尾引号与 `.0` 后缀。
- 空行、合计行（代码与业务名皆空）自动跳过。
- 校验失败逐行记录在 `failed` 里，不影响其它行写入。常见原因：成交日期无法解析、未识别的业务类型、成交行缺少证券代码、成交价/数量非正数、表头未识别。

### 2.5 去重与 `mode`

- 每行生成 `trade_id`：优先用「成交编号」；无编号时用 `(日期|代码|方向|价|量|时间|成交额)` 的指纹 `fp:...`。
- `biz_settlements` 上有 `(fk_user, trade_id)` 唯一索引；`merge` 模式下已存在的编号直接跳过并计入 `duplicates`，**重复上传同一份文件不会产生重复数据**。
- `replace` 会先删除本文件中**涉及交易日**的全部旧交割单，再整体写入，适合券商修改了历史数据后重导。也可以单独用 `DELETE /trading/settlements?trade_date=...` 清某一天。
- 导入结果写入导入日志（持仓分析 → 上传记录）。

### 2.6 响应

```json
{
  "code": 0, "message": "ok",
  "data": {
    "total": 7, "inserted": 7, "duplicates": 0,
    "failed": [{ "row": 12, "code": "600000", "reason": "成交日期无法解析" }],
    "date_from": "2026-11-03", "date_to": "2026-11-04",
    "brokers": ["华泰证券"]
  }
}
```

`total` = 解析成功行数 + 失败行数；`inserted` 为实际落库行数（已扣重复）；`failed[].row` 是**文件里的物理行号**（含标题行），便于对照原文件。

### 2.7 Excel 样例

| 成交日期 | 证券代码 | 证券名称 | 买卖标志 | 成交价格 | 成交数量 | 成交金额 | 佣金 | 印花税 | 过户费 | 成交编号 | 成交时间 | 发生金额 | 股东账号 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-03 | 600000 | 浦发银行 | 证券买入 | 10.00 | 10000 | 100000 | 25 | 0 | 1 | T001 | 09:40:00 | -100026 | A1 |
| 2026-11-03 | 600000 | 浦发银行 | 证券卖出 | 10.10 | 10000 | 101000 | 25.25 | 101 | 1.01 | T002 | 14:30:00 | 100872.74 | A1 |
| 2026-11-04 | 510300 | 沪深300ETF | 买 | 4.00 | 12500 | 50000 | 12.5 | 0 | 0 | T003 | 10:00:00 | -50012.5 | A1 |

---

## 3. 每日成交导入 `POST /api/v1/trading/import/daily`

页面内粘贴 / 手工补录用；与无鉴权 `/trades/import` 写同一张 `biz_trades`，按 `(用户, 交易日)` **先删后插全量覆盖**。

```json
{
  "trade_date": "2026-11-03",
  "source": "web",
  "items": [
    {
      "code": "510300", "name": "沪深300ETF", "type": "etf",
      "direction": "buy", "price": 3.92, "quantity": 5000,
      "amount": 19600, "fee": 5, "trade_time": "2026-11-03 09:45:12",
      "account": "普通", "broker": "华泰证券"
    }
  ]
}
```

必填：`trade_date`（`YYYY-MM-DD`）、`items[].code`、`direction`（`buy`/`sell`）、`price > 0`、`quantity > 0`。响应：`{ "deleted": 0, "inserted": 1, "failed": [] }`。

> ⚠️ **每日成交缺少费用明细**时，净收益与费率都不含这部分费用；这些记录会被标 `fee_estimated`，在 `analysis.fees.estimated_fee_rows` 与对账 `warnings` 里提示。要算准费用，请以交割单为准。

交割单与每日成交合并时**交割单优先**：按成交编号或内容指纹去重，每日成交只作补充。

---

## 4. 分品种 / 分标的费率统计（`/trading/analysis` → `data.fee_rates`）

### 4.1 口径

```
费率(bp) = 费用 / 成交额 × 10000      1 bp = 0.01% = 万分之一
```

- 买入、卖出**分开计算**（`buy_fee_rate_bps` / `sell_fee_rate_bps`）；`stamp_tax_bps` 的分母是**卖出额**（印花税只对卖出收取）。
- 只统计 `entry_type = trade` 且 `direction ∈ {buy, sell}` 的**交割单成交行**；每日成交无费用明细，不进费率。
- **费用列全空的行不进分母**（记为 `fee_missing_rows`），避免把「未披露」当成 0 费率；对账 `warnings` 会提示。
- `nominal_commission_bps`：优先取组内成交额 ≥ 5 万的大单佣金率中位数反推名义佣金率；大单不足 3 笔时退化为排除最低佣金小单后的中位数；无样本为 `null`。
- `min_commission_count`：佣金恰为 5 元且成交额 < 2 万的笔数；`min_commission_extra` = 这些小单实际佣金 − 按名义佣金率应收佣金（估算多付，仅供参考）。
- `unallocated_fee`：`fee_total` 与四个分项之和的差额（券商只给费用合计、不拆分时出现）。

### 4.2 品种分组规则（`by_asset_type[].key`）

| key | 含义 | 代码段 / 兜底 |
|---|---|---|
| `stock_a` | 沪深A股 | `60 / 68 / 00 / 30` 开头 |
| `stock_bj` | 北交所 | `43 / 83 / 87 / 92 / 8 / 4` 开头 |
| `cb` | 可转债 | `110 / 111 / 113 / 118 / 120 / 121 / 123 / 127 / 128` 开头 |
| `fund` | 基金(ETF/LOF) | `15 / 16 / 50 / 51 / 52 / 56 / 58` 开头 |
| `bond` | 债券 | 其它 `12` 开头、`01 / 02 / 10 / 19` 开头 |
| `hk` | 港股通 | 5 位数字代码 |
| `other` | 其它/未识别 | 代码无法识别；再用名称（含「转债」/「ETF」/「基金」/「债」）与券商「证券类别」列兜底 |

`by_code` 为单只标的（按成交额降序），每组附带 `asset_type` / `asset_label`。

### 4.3 响应结构（片段）

```json
{
  "fee_rates": {
    "summary": {
      "overall_fee_rate_bps": 5.915, "buy_fee_rate_bps": 2.931,
      "sell_fee_rate_bps": 8.976, "commission_bps": 2.763,
      "stamp_tax_bps": 6.26, "total_amount": 326850.0, "total_fee": 193.32,
      "trade_count": 7, "rated_count": 7, "fee_missing_rows": 0,
      "asset_type_count": 3, "code_count": 4,
      "min_commission_count": 3, "min_commission_extra": 8.6,
      "nominal_commission_bps": 2.5,
      "highest_fee_group": "沪深A股", "highest_fee_rate_bps": 7.664,
      "highest_fee_code": "浦发银行", "highest_fee_code_bps": 7.625
    },
    "by_asset_type": [
      {
        "key": "stock_a", "label": "沪深A股", "trade_count": 3, "rated_count": 3,
        "fee_missing_rows": 0, "buy_amount": 105500.0, "sell_amount": 101000.0,
        "total_amount": 206500.0, "total_fee": 158.26,
        "commission": 55.25, "stamp_tax": 101.0, "transfer_fee": 2.01, "other_fee": 0.0,
        "unallocated_fee": 0.0,
        "fee_rate_bps": 7.664, "buy_fee_rate_bps": 2.938, "sell_fee_rate_bps": 12.6,
        "commission_bps": 2.676, "stamp_tax_bps": 10.0, "transfer_fee_bps": 0.097,
        "avg_fee_per_trade": 52.75, "min_commission_count": 1,
        "min_commission_extra": 3.61, "nominal_commission_bps": 2.5
      }
    ],
    "by_code": [
      { "key": "600000", "label": "浦发银行", "asset_type": "stock_a", "asset_label": "沪深A股",
        "fee_rate_bps": 7.625, "total_amount": 201000.0, "total_fee": 153.26 }
    ],
    "note": "费率 = 费用 / 成交额 × 10000（bp，1bp=万分之一）；..."
  }
}
```

> 上例为节选：`by_code[]` 每项字段与 `by_asset_type[]` 完全相同，额外带 `asset_type` / `asset_label`；`note` 为口径说明原文。

`highest_fee_code` 只在成交额 ≥ 1 万的标的里提名，避免最低佣金小单误占榜首。

### 4.4 参考值与异常诊断

| 检查项 | 参考 | 前端提示 |
|---|---|---|
| 沪深A股卖出印花税 | ≈ 10 bp（千一） | 偏离 8~12 bp 时提示核对 |
| ETF / 可转债 / 债券印花税 | 0 bp | 出现 > 0.5 bp 时提示核对分类或计费口径 |
| 佣金 | 常见 2.5~3 bp | 小单命中最低 5 元佣金时费率显著升高，单列 `min_commission_*` |
| 费用列全空 | 不计入费率 | `fee_missing_rows` + 对账告警 |

费率统计是**实测值**，不根据用户设置的佣金费率反推，也不估算印花税。

---

## 5. 其它查询端点要点

- `GET /trading/settlements` → `data = { items, total, date_from, date_to }`；`items[]` 含 `commission / stamp_tax / transfer_fee / other_fee / fee_total / net_amount / trade_id / account / broker / source`。
- `GET /trading/daily` → `data = { dates, days, items, settlement_rows, daily_rows }`；`days[]` 为按交易日汇总（含 `t_net_pnl` 做T净收益）。
- `GET /trading/closed` → `data = { items, open_positions, summary }`；回合按 `(account, code)` FIFO 配对，费用摊入买卖两侧，`open_positions` 可与导入的当前持仓对账。
- `GET /trading/analysis` 除 `fee_rates` 外还有 `meta / t_trades / rounds / fees / behavior / reconciliation`，口径见 `backend/services/trading_ledger_service.py` 模块说明。

---

## 6. 已知边界

1. 不支持 `.xls`；`openpyxl` 只读第一个 sheet，合并单元格 / 多表头文件需先整理为单表头。
2. 无成交编号时按内容指纹去重：同一天同标的同价同量同时间的**两笔真实成交**会被判重复，建议导出时保留「成交编号」列。
3. 每日成交缺费用 → 净收益不含该部分费用；费率统计完全不纳入每日成交。
4. 品种按代码段推断，港股通 / B股 / 特殊品种若代码规则不同会落到 `other`，可用「证券类别」列或名称辅助识别。
5. 费率的分母是**已导入区间内的成交额**，跨券商 / 跨账户合并统计；要分账户对比请用 `GET /trading/settlements` 自行按 `account` 聚合。
6. 导入是**按用户隔离**的（`fk_user` 取 JWT `sub`）；`DELETE` 只清当前用户的该交易日数据。

---

## 7. 部署与建表

- `biz_settlements` 由 `backend/database/init_sqlite.py` 的 `BIZ_TABLES` 与 `trading_ledger_service._ensure_tables()` 双重幂等建表，首次请求自动落库，无需手工迁移；含 `(fk_user, trade_date)`、`(fk_user, code)` 索引与 `(fk_user, trade_id)` 唯一索引。
- 后端依赖新增 `openpyxl`（`backend/requirements.txt`），部署需重建后端镜像。
- 上线走 Jenkins `doraemon-deploy`（`DEPLOY_TARGET=all / DEPLOY_ACTION=deploy / FORCE_PULL=true`），会重建前后端镜像并重启容器；旧的 `git bundle → scp 53` 流程已废弃。
