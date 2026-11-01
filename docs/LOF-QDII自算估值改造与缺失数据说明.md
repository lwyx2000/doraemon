# LOF / QDII 篮子自算估值改造 & 缺失数据说明

> 日期：2026-10-16　参考实现：`lofarb/arbcore`（篮子自算估值）
> 目标：把 doraemon（量化终端 Pro）LOF/QDII 页原本"`iopv ≈ 昨日净值`"的静态近似溢价，
> 升级为 **按底层持仓篮子实时自算的预估净值与溢价率**。

---

## 一、改了什么（已完成并验证）

### 1. 估值公式（移植 lofarb `unified_valuation.basket_valuation` 矩阵形态）

```
est_nav = nav × ( 1 + position/100 × ( Σ wᵢ · (Pᵢ_now / Pᵢ_base) · (fx_now / fx_base) − 1 ) )
est_premium_pct = (price − est_nav) / est_nav × 100
```

- `nav` / `nav_date`：53 网关 `fund_rank` 提供的真实单位净值与净值日期；
- `Pᵢ_base`：净值日期对应的**底层市场基准收盘**；
- `Pᵢ_now`：底层最新价（盘中实时，收盘后＝最新日K收盘）；
- `fx`：篮子货币兑人民币变化（美元/日元/港元）；
- `position`：基金股票仓位（%），移植 lofarb 年报口径。

lofarb 的"魔法公式"（把对冲腿 hedge 折叠进净值）是**单组件 + hedge>0** 的特例。doraemon 无 Woody 对冲数据，
统一走矩阵公式即可覆盖，二者在单成分时数学等价。

### 2. 数据源（直连外网，与 fund_service 既有"直连腾讯/东财"同一模式；53 网关美股接口不可用）

| 用途 | 源 | 关键字段（实测已验证） |
|---|---|---|
| 美股 ETF 日K（基准价/现价） | 新浪 `US_MinKService.getDailyK`（JSONP） | `d`=日期 `c`=收盘 |
| 美股 ETF 实时 | 新浪 `hq.sinajs.cn/list=gb_xxx` | 变量前缀 `hq_str_gb_`，`[1]`=现价 |
| 汇率 USD/JPY/HKD | 新浪 `fx_susdcny`/`fx_sjpycny`/`fx_shkdcny` | `[1]`现价 `[3]`昨收 `[17]`日期 |
| 港股个股 | 腾讯 `qt.gtimg.cn/q=r_hk00700` | `~`分隔 `[3]`现价 `[4]`昨收 |
| 境内期货（银/豆粕） | 新浪 `nf_AG0`/`nf_M0` | `[8]`最新 `[10]`昨结 `[17]`日期 |
| 日经225期货 | 新浪 `hf_NK` | `[0]`现价 `[7]`昨结 `[12]`日期 |
| A股 ETF 组件 | 新浪 `list=sz159560` | `[2]`昨收 `[3]`现价 `[30]`日期 |

### 3. 新增/改动文件

**后端**
- 新增 `backend/services/cross_border_valuation.py`：估值服务 + 直连取数 + 5 分钟 TTL 后台快照线程（请求路径只读快照，不阻塞，仿 `_attach_kline_metrics` 预热模式）。
- 新增 `backend/config/qdii_baskets.json`：66 只基金篮子（权重/position/币种/市场/新浪 feed 代码），移植自 lofarb `lof_config.yaml` + `fund_categories.json`。
- 改 `backend/services/fund_service.py`：基金 dict 增 `nav_date`；`get_funds_from_api` 对 etf/lof/all 调用 `attach_estimated_valuations`。
- 改 `backend/services/etf_service.py`：`_map_etf` 增 `nav`/`nav_date`；`get_etfs`/`get_etf_arbitrage_opportunities` 挂接估值。
- 改 `backend/models.py`：`FundItem` 增 `nav_date`/`est_nav`/`est_premium_pct`/`est_base_date`/`est_price_date`/`est_position`。

**前端**
- 改 `frontend/src/types/index.ts`：`FundItem`、`EtfFund` 增 `est_*` 字段。
- 改 `frontend/src/pages/LofFunds.vue`：LOF 表溢价率后新增"篮子自算净值""自算溢价"两列（无数据显示 `-`）。
- 改 `frontend/src/pages/EtfFunds.vue`：ETF 套利表新增同两列（跨境 ETF 的实际展示位）。

### 4. 验证结果（2026-10-16 真实数据，HTTP 路由级）
- 29 只美股、3 只期货、3 只港股、1 只 A股、汇率 USD/JPY/HKD 全部命中；
- `GET /api/v1/funds?type=lof` 308 行中 1 行产出 est（161130），`type=etf` 3690 行中 17 行产出 est；
- 自算溢价能捕捉"净值滞后 + 底层隔夜涨跌"：如 161130 静态溢价 7.73% → 自算 9.97%（QQQ 10-15 收跌被正确反映）。

---

## 二、铁律（继承 lofarb，已在代码落实）

1. **position 缺失 / uncertain → 不估算**（返回 None，前端 `-`），绝不兜底造数；
2. **任一篮子成分行情缺失 → 整只不估算**（暴露缺失，不用 0 参与加权）；
3. 篮子/基准/汇率齐备才产出，数据不足静默跳过（不写 est 字段）。

---

## 三、缺失数据清单（需要你补齐的部分）

### A. 【最关键】基金池错配 —— doraemon 的基金列表基本不含 lofarb 的经典跨境套利 LOF
- 现象：53 网关 `fund_rank` 的 **LOF 池共 308 只，但 lofarb 篮子中的经典 QDII-LOF（162411 华宝油气、501018 南方原油、161125 易方达标普500、161127 标普生物、162415、160723、161129、163208、160644、501225、501312、161126、164906、164824、160216、161815、160719、161116、164701、165513）中，只有 `161130`（纳指LOF）一只在 LOF feed 命中**；其余 20 只在麦蕊 LOF 排行里查不到。
- 这些标的**大量以 ETF 形式**出现在 `fund_rank subtype=etf`（如 159501/159696/513300 等纳指、159612/513650 标普、159502/159518 油气生物），所以真正能自算的是那 17 只跨境 ETF，LOF 侧只有 1 只。
- **需要你做的**：
  1. 确认 doraemon 的跨境套利标的是否就是这批 ETF（若是，篮子配置已覆盖，无需补 LOF）；
  2. 若要覆盖 lofarb 那 20 只场外/场内 LOF-QDII，需要一个**能返回这些 LOF 代码的上游源**（当前麦蕊 fund_rank 池不含它们）——这是**上游基金池缺口**，非代码问题。

### B. 汇率"历史基准"缺失 —— 多日净值滞后时汇率增量被低估
- 现状：`fx_base` 用新浪汇率实时"昨收"近似，只捕捉**最近一个交易日**的汇率变动；`fx_now` 为现价。
- 缺口：当 `nav_date` 落后净值 2+ 个交易日（QDII 常见），需要 **nav_date 当日兑人民币历史汇率**做基准，doraemon 无此源。
  - 曾试 53 网关 `currency_boc_sina`：美元/日元可用但返回固定旧窗口、**港元报 500**，不稳定，已放弃。
- 影响量级：单日汇率波动通常 0.1–0.5%，相对资产涨跌是次要项；但**多日累计**（含净值滞后）会低估 fx 项。
- **需要你做的**：提供一个稳定的"美元/日元/港元 兑 CNY 日频历史"源（央行中间价 or 东财/新浪历史序列），服务里把 `fx_base` 从"昨收"改为"按 nav_date 查历史"。

### C. 无美股 tick 级实时行情 —— 盘中的"现价"实为最新收盘
- 现状：新浪 `gb_` 在美股休市时返回的值 ≈ 上一交易日收盘；美股盘中时段＝北京深夜。
- 因此**中国白盘时段看不到美股实时涨跌**，自算用的是"最新美股收盘 vs 净值基准日收盘"，与 lofarb **日终口径一致**（这是设计允许的信号，能捕捉净值未反映的隔夜新信息）。
- **需要你做的**（可选）：若要真正盘中实时美股价驱动估值，需接入 IB/Futu/长桥等 tick 源（lofarb 用 Woody+IB）。当前无。

### D. 无 Woody 多时段锚点价 —— 欧/日锚点已折叠为美股主板代理
- lofarb 篮子含 `^USO-EU`、`^GLD-EU`、`^INDA-EU/JP/HK` 等**多交易所锚点**（同一 ETF 在欧/日/港的分时收盘），只有 Woody 数据源认识 `^` 锚点。
- doraemon 无 Woody → 已在 `qdii_baskets.json` 把锚点成分**折叠并入其美股主板代码**（如 501018：`^USO-EU 64.93 + USO 35.07` → 全部 USO 100%），并在 `_note` 注明。
- 影响：损失"欧股时段相对美股的额外涨跌"精度，日终信号仍成立。
- **需要你做的**（可选）：接入支持欧/日 ETF 行情的源后可恢复分时锚点权重。

### E. position 为静态年报数，需季度更新
- 现状：`position` 全部来自 lofarb `lof_config.yaml`/`fund_categories.json` 的**年报/季报静态值**（如 160216=118.88% 为杠杆口径）。
- 缺口：无自动更新机制；季报换仓后 position/篮子权重会过期。
- **需要你做的**：提供季度持仓数据源（东财/天天基金持仓 or lofarb 的 DB），定期刷新 `qdii_baskets.json` 的 position 与 basket 权重。

### F. 一批基金"有 position 无篮子"，当前不估算
- **QDII 亚洲恒生系 14 只**（160322、501301~501311、160924、164705、161831、160717、161124、501025 等）：lofarb 只给了 position≈95，**没有个股篮子**（需彭博/东财持仓明细才能建篮子）。
- **德国/法国/东证 ETF**（159561、513030、513080、513800）：无 position 无篮子。
- **日经 225 ETF**（513000/513520/159866/513880）：有日经期货代理 `hf_NK` 但 **lofarb yaml 无 position** → 按铁律不估算。
- **501300 海富通美元债**：债券基金，无股票篮子口径 → 不估算。
- **需要你做的**：若要把这些也纳入自算，需要①对应指数/ETF 的 position，②恒生系的成分篮子。给 index 代理（恒指 `hkHSI`、TOPIX）也可，但需补 position。

### G. 前端 QDII tab 疑似失效（顺带发现，非本次改动引入）
- `LofFunds.vue` 的 QDII tab 过滤 `f.type === 'qdii'`，但后端把 qdii 映射到 `subtype=etf` 且写回的 `type` 恒为 `'etf'` → **该 tab 过滤后恒为空**。
- 跨境标的实际展示在 **ETF 页**（已在 `EtfFunds.vue` 加了自算两列）。
- **建议**：要么后端 QDII 列表把 `type` 规范成 `'qdii'`，要么前端 QDII tab 改为按 `category==='cross_border'` 过滤。（属既有逻辑问题，本次未动，供你决策。）

---

## 四、当前可直接自算的标的（18 只，其余为上面缺口）

LOF：`161130`
ETF：`159501 159513 159632 159659 159660 159696 159941 513100* 513110 513300 513390 513650 513870 159612 159655* 513500* 159502 159518*`（`*` 视当日 feed 是否含该代码；纳指/标普系为主）。
黄金原油、南方原油、港美互联、海外科技等经典 LOF 因 **A（基金池）** 缺口暂不在 doraemon 列表内，配置已就绪，池子补上即自动生效。

---

## 五、回滚
所有被改文件均有 `.bak_valuation` 备份；新增文件删除即恢复原状。补丁脚本：
`apply_doraemon_patch.py`（后端+LofFunds）、`apply_doraemon_patch2.py`（EtfFunds+types）。
