# 跟踪误差计算口径

## 双边取数

- 指数半边：中证指数 `stock_zh_index_hist_csindex`。
- 基金净值半边：东方财富 `fund.eastmoney.com/pingzhongdata/{code}.js` 静态 JS（容器内可用）。
- 注意：容器 IPv4 被 `api.fund.eastmoney.com` 封禁，但 CDN（静态 JS）可用——所以必须用 pingzhongdata 静态文件而非 API。

## 坑位

- csindex 网关带/不带日期参数均可能 500（疑上游反爬）：指数半边若失败，换新浪 `stock_zh_index_daily(symbol='sh000001')`（约 0.7s 全量，有 volume 无 amount）；腾讯 `_tx` 兜底有 amount 但慢约 20s。
- DuckDB TIMESTAMP 存 UTC，涉时区计算必须**真容器内验证**。
- 慢速抓取 + 落库：`ensure_fund_nav` 只补缺失区间，任务触发只走 HTTP 端点或重启 startup 回补。
