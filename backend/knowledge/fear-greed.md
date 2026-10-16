# 贪婪恐惧指数算法口径

## 算法（6 指标 min-max 加权）

过去一年 250 交易日窗口内 min-max 归一化后加权：

| 分项 | 权重 |
|---|---|
| 上涨占比 | 0.25 |
| 涨停数（剔 ST） | 0.20 |
| 指数距 52 周高点位置 | 0.15 |
| 量能比 | 0.20 |
| 融资余额 20 日变化 | 0.10 |
| (100 − 波动率) | 0.10 |

- 总分 0–100：< 10 极度恐慌，> 90 极度贪婪。
- 缺失分项按权重归一化：`components_used < 6` 即**近似日**，前端应标注。

## 数据来源

- market_stats +  legu「真实涨停」当日快照。
- 新浪 `stock_zh_index_daily(sh000001)` 算位置/量能/波动。
- `stock_margin_sse` 带日期算两融变化（**必须带 start_date/end_date**，见上游坑位）。
- 回填补涨用东财 `zt_pool_em` 剔 ST（仅近数月，非交易日为空）。

## 存储与任务

- 表 `base_fear_greed_daily`；job 每交易日 15:40 采集。
- live/backfill upsert 合并：Python 侧来源感知——live 列优先、backfill 只补 NULL、K 线列直覆（COALESCE(existing, existing) 顺序极易搞反，改动前先看清）。
- 展示：宏观看板内嵌 FearGreedPanel（总分 + 档位 + 近 90 日迷你走势 + 6 分项条），详情页 /fear-greed 下钻；展示层共用 `frontend/src/utils/fearGreedDisplay.ts`。
