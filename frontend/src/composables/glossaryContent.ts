/**
 * 英文缩写词典
 *
 * 每个页面使用到的英文缩写及其中文含义。
 * GlossaryPanel 组件根据 pageKey 自动获取对应列表。
 */

export interface GlossaryItem {
  /** 缩写 */
  abbr: string
  /** 全称（英文） */
  full: string
  /** 中文含义 */
  cn: string
}

export const glossaryByPage: Record<string, GlossaryItem[]> = {
  dashboard: [
    { abbr: 'ERP', full: 'Equity Risk Premium', cn: '股权风险溢价，股票收益率减无风险利率，衡量股债性价比' },
    { abbr: 'DR007', full: 'Depository Institutions 7-Day Repo Rate', cn: '银行间7天质押式回购利率，反映流动性松紧' },
    { abbr: 'GC001', full: 'Shanghai 1-Day Reverse Repo', cn: '上交所1天国债逆回购利率，月末季末常飙升' },
    { abbr: 'PE', full: 'Price to Earnings Ratio', cn: '市盈率，股价/每股收益，衡量估值高低' },
    { abbr: 'PB', full: 'Price to Book Ratio', cn: '市净率，股价/每股净资产，适合重资产行业' },
  ],
  indexValuation: [
    { abbr: 'PE', full: 'Price to Earnings Ratio', cn: '市盈率，股价/每股收益，衡量估值高低（越高越贵）' },
    { abbr: 'PB', full: 'Price to Book Ratio', cn: '市净率，股价/每股净资产，重资产行业更看 PB' },
    { abbr: 'TTM', full: 'Trailing Twelve Months', cn: '滚动十二个月，取最近 4 个季度财务数据' },
    { abbr: 'ROE', full: 'Return on Equity', cn: '净资产收益率，盈利能力核心指标；本系统取近5年均值' },
    { abbr: '股债利差', full: 'Equity Risk Premium', cn: '= ROE均值/PB − 10Y国债 + 0.3×CPI；利差越大=股票相对越便宜' },
    { abbr: '估值分位', full: 'Valuation Percentile', cn: '基于股债利差的百分位：<30%便宜 / 30-70%正常 / >70%过热，越小越便宜' },
    { abbr: 'PE分位', full: 'PE Percentile', cn: '当前PE在其历史中的升序百分位，越高=越贵' },
    { abbr: 'PB分位', full: 'PB Percentile', cn: '当前PB在其历史中的升序百分位，越高=越贵' },
    { abbr: '拥挤度', full: 'Crowding', cn: '指数PB / 全A PB 的历史分位，衡量相对估值高低（非绝对贵贱）' },
    { abbr: 'CPI', full: 'Consumer Price Index', cn: '居民消费价格指数同比，公式中的通胀调整项（系数0.3）' },
    { abbr: '10Y国债', full: '10-Year Treasury Yield', cn: '10年期国债收益率，无风险利率基准，股债利差公式的减项' },
  ],
  lofFunds: [
    { abbr: 'LOF', full: 'Listed Open-end Fund', cn: '上市开放式基金，可同时在场内外交易' },
    { abbr: 'QDII', full: 'Qualified Domestic Institutional Investor', cn: '合格境内机构投资者，可投资海外市场' },
    { abbr: 'IOPV', full: 'Indicative Optimized Portfolio Value', cn: '基金参考净值，盘中实时估算的净值' },
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值，每份基金代表的资产净值' },
    { abbr: 'VaR', full: 'Value at Risk', cn: '风险价值，给定置信度下的最大可能亏损' },
    { abbr: 'T+N', full: 'Trade Date plus N Days', cn: '交易日后第N日到账，T+1=次日到账，T+2=隔日到账' },
    { abbr: 'OOS', full: 'Out-of-Sample (样本外)', cn: '按时间切出后30%时段做策略验证：样本外胜率明显劣于样本内 → 过拟合警报' },
    { abbr: 'IS', full: 'In-Sample (样本内)', cn: '历史前70%时段，策略参数在此上调优；单独看IS高胜率可能是过拟合假象' },
  ],
  closedFunds: [
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值，每份基金代表的资产净值' },
    { abbr: 'LOF', full: 'Listed Open-end Fund', cn: '上市开放式基金，转LOF后可按净值赎回' },
    { abbr: 'AAA', full: 'Triple A Rating', cn: '最高信用评级，违约风险极低' },
    { abbr: 'AA+', full: 'Double A Plus Rating', cn: '次高信用评级，安全性较高' },
    { abbr: 'OOS', full: 'Out-of-Sample (样本外)', cn: '按时间切出后30%时段做策略验证：样本外胜率明显劣于样本内 → 过拟合警报' },
    { abbr: 'IS', full: 'In-Sample (样本内)', cn: '历史前70%时段，策略参数在此上调优；单独看IS高胜率可能是过拟合假象' },
  ],
  convertibleBonds: [
    { abbr: 'IV', full: 'Implied Volatility', cn: '隐含波动率，由期权价格反推的市场波动预期' },
    { abbr: 'HV', full: 'Historical Volatility', cn: '历史波动率，标的过去N日实际波动率' },
    { abbr: 'YTM', full: 'Yield to Maturity', cn: '到期收益率，持有到期的年化收益率' },
    { abbr: 'BS', full: 'Black-Scholes Model', cn: '布莱克-斯科尔斯期权定价模型' },
    { abbr: 'Delta', full: 'Delta (Hedge Ratio)', cn: '期权价格对标的价格的敏感度，用于对冲' },
    { abbr: 'Z-Score', full: 'Altman Z-Score', cn: 'Altman破产预测模型评分，<1.81为危险区' },
    { abbr: 'OOS', full: 'Out-of-Sample (样本外)', cn: '按时间切出后30%时段做策略验证：样本外胜率明显劣于样本内 → 过拟合警报' },
    { abbr: 'IS', full: 'In-Sample (样本内)', cn: '历史前70%时段，策略参数在此上调优；单独看IS高胜率可能是过拟合假象' },
  ],
  etfFunds: [
    { abbr: 'ETF', full: 'Exchange Traded Fund', cn: '交易所交易基金，可像股票一样交易的指数基金' },
    { abbr: 'IOPV', full: 'Indicative Optimized Portfolio Value', cn: '基金参考净值，盘中实时估算' },
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值' },
    { abbr: 'PE', full: 'Price to Earnings Ratio', cn: '市盈率' },
    { abbr: 'VaR', full: 'Value at Risk', cn: '风险价值，套利期间最大可能亏损' },
    { abbr: 'T+N', full: 'Trade Date plus N Days', cn: '资金到账天数' },
    { abbr: 'QDII', full: 'Qualified Domestic Institutional Investor', cn: '合格境内机构投资者，可投海外' },
    { abbr: 'BIAS', full: 'Bias Ratio (偏离度)', cn: '价格相对MA均线的偏离百分比，负值超卖、正值偏高' },
    { abbr: 'RSI', full: 'Relative Strength Index', cn: '相对强弱指标，14日口径，≤30超卖、≥70超买' },
    { abbr: 'BOLL', full: 'Bollinger Bands', cn: '布林带，20日均线±2倍标准差形成的价格通道' },
    { abbr: 'qfq', full: '前复权', cn: '历史价格按分红除息向前调整，保证技术指标连续不失真' },
    { abbr: 'Kelly', full: 'Kelly Criterion (凯利公式)', cn: 'f* = p − (1−p)/b，由胜率p与赔率b计算的最优仓位比例' },
    { abbr: '半凯利', full: 'Half Kelly', cn: '凯利值的一半，抵御历史统计误差的稳健仓位，封顶20%' },
    { abbr: 'b', full: 'Payoff Ratio (赔率)', cn: '平均单次盈利 ÷ 平均单次亏损，衡量盈亏比' },
    { abbr: 'OOS', full: 'Out-of-Sample (样本外)', cn: '按时间切出后30%时段做策略验证：样本外胜率明显劣于样本内 → 过拟合警报' },
    { abbr: 'IS', full: 'In-Sample (样本内)', cn: '历史前70%时段，策略参数在此上调优；单独看IS高胜率可能是过拟合假象' },
  ],
  reits: [
    { abbr: 'REITs', full: 'Real Estate Investment Trusts', cn: '不动产投资信托基金，投资底层资产并分红' },
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值' },
    { abbr: 'DSCR', full: 'Debt Service Coverage Ratio', cn: '偿债备付率，经营现金流/还本付息额' },
    { abbr: 'LTV', full: 'Loan to Value', cn: '贷款价值比，借款/资产价值' },
  ],
  alertCenter: [
    { abbr: 'VaR', full: 'Value at Risk', cn: '风险价值，给定置信度下最大可能亏损' },
    { abbr: 'IV', full: 'Implied Volatility', cn: '隐含波动率' },
    { abbr: 'HV', full: 'Historical Volatility', cn: '历史波动率' },
    { abbr: 'DSCR', full: 'Debt Service Coverage Ratio', cn: '偿债备付率' },
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值' },
  ],
  strategyCenter: [
    { abbr: 'LOF', full: 'Listed Open-end Fund', cn: '上市开放式基金' },
    { abbr: 'QDII', full: 'Qualified Domestic Institutional Investor', cn: '合格境内机构投资者' },
    { abbr: 'REITs', full: 'Real Estate Investment Trusts', cn: '不动产投资信托基金' },
    { abbr: 'AND/OR', full: 'Logical Operators', cn: '条件组合逻辑，AND=同时满足，OR=满足其一' },
  ],
  aiDecision: [
    { abbr: 'ERP', full: 'Equity Risk Premium', cn: '股权风险溢价' },
    { abbr: 'PE', full: 'Price to Earnings Ratio', cn: '市盈率' },
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值' },
    { abbr: 'IV', full: 'Implied Volatility', cn: '隐含波动率' },
  ],
  portfolioWatchlist: [
    { abbr: 'ETF', full: 'Exchange Traded Fund', cn: '交易所交易基金' },
    { abbr: 'LOF', full: 'Listed Open-end Fund', cn: '上市开放式基金' },
    { abbr: 'REITs', full: 'Real Estate Investment Trusts', cn: '不动产投资信托基金' },
    { abbr: 'YTM', full: 'Yield to Maturity', cn: '到期收益率' },
  ],
  holdingsAnalysis: [
    { abbr: 'PnL', full: 'Profit and Loss', cn: '盈亏，浮动盈亏 = (现价 - 成本价) × 数量' },
    { abbr: 'ETF', full: 'Exchange Traded Fund', cn: '场内基金，在交易所交易的基金' },
    { abbr: 'OTC', full: 'Over The Counter', cn: '场外，场外基金通过申赎交易，按净值计价' },
    { abbr: 'HKD', full: 'Hong Kong Dollar', cn: '港币，港股市值按港币计，不做汇率换算' },
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值，场外基金现价的来源' },
  ],
  dataSources: [
    { abbr: 'API', full: 'Application Programming Interface', cn: '应用程序接口，用于自动获取数据' },
    { abbr: 'IOPV', full: 'Indicative Optimized Portfolio Value', cn: '基金参考净值' },
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值' },
    { abbr: 'K线', full: 'Candlestick Chart', cn: '日K线，含开高低收的日行情数据' },
  ],
  preciousMetals: [
    { abbr: 'SGE', full: 'Shanghai Gold Exchange', cn: '上海黄金交易所，国内贵金属现货交易场所' },
    { abbr: 'Au99.99', full: '99.99% Purity Gold Spot', cn: '上海黄金交易所纯度99.99%黄金现货合约，报价单位元/克' },
    { abbr: 'Ag99.99', full: '99.99% Purity Silver Spot', cn: '上海黄金交易所纯度99.99%白银现货合约，原始报价元/千克' },
  ],
}
