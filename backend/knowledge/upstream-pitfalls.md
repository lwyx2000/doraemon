# 上游接口坑位速查

## csindex（中证指数）

- 网关带/不带日期参数均可能 500（疑上游反爬，2026-10-12 实测）。
- 替代：新浪 `stock_zh_index_daily(symbol='sh000001')` 全量约 0.7s（有 volume 无 amount）；腾讯 `_tx` 兜底有 amount 但约 20s。

## stock_margin_sse（融资融券）

- **必须带 start_date/end_date（YYYYMMDD）**：不带只回 2000 行且止于约 2023 的陈旧窗口。
- `信用交易日期` 字段无横线，须归一化。
- szse 仅最新一日数据。

## 东方财富

- 容器 IPv4 被 `api.fund.eastmoney.com` 封禁，但 CDN 可用。
- 基金净值用 `fund.eastmoney.com/pingzhongdata/{code}.js` 静态 JS（容器内可用）。
- 涨停池 `zt_pool_em` 仅近数月，非交易日为空；回补场景须剔 ST。

## 其他

- 集思录（jisilu）数据需登录 cookie（53 已配置），不可用时相关抓取降级。
- legu「真实涨停」当日快照用于贪婪恐惧上涨占比/涨停分项。
