# 分位色阶单一真源

- 唯一真源：`frontend/src/utils/percentile.ts` 的 `pctColor` / `pctColorStyle`。
- 统一覆盖：PercentileIndicator、EtfFunds、IndexValuation、IndexAnalysis、PortfolioWatchlist、LofFunds、DividendFundHub。
- Dashboard ERP 展示为**反向**（低 ERP = 便宜 = 有利），语义反转但不反转色阶函数本身，由调用方处理。
- 例外：StrategyCenter 涨跌色、dividend_service 语义色（低估·持有紫 #8b5cf6）不走分位色阶。
- 涨跌色遵循 A 股惯例：涨红跌绿（`--color-danger` / `--color-success`）。
