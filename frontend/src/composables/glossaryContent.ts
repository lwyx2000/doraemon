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
  indexAnalysis: [
    { abbr: 'PE', full: 'Price to Earnings Ratio', cn: '市盈率，股价/每股收益，衡量估值高低' },
    { abbr: 'PB', full: 'Price to Book Ratio', cn: '市净率，股价/每股净资产，适合重资产行业' },
    { abbr: 'ERP', full: 'Equity Risk Premium', cn: '股权风险溢价，股票收益率减无风险利率' },
    { abbr: 'DR007', full: 'Depository Institutions 7-Day Repo Rate', cn: '银行间7天质押式回购利率' },
    { abbr: 'TTM', full: 'Trailing Twelve Months', cn: '滚动十二个月，指最近4个季度的财务数据' },
  ],
  lofFunds: [
    { abbr: 'LOF', full: 'Listed Open-end Fund', cn: '上市开放式基金，可同时在场内外交易' },
    { abbr: 'QDII', full: 'Qualified Domestic Institutional Investor', cn: '合格境内机构投资者，可投资海外市场' },
    { abbr: 'IOPV', full: 'Indicative Optimized Portfolio Value', cn: '基金参考净值，盘中实时估算的净值' },
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值，每份基金代表的资产净值' },
    { abbr: 'VaR', full: 'Value at Risk', cn: '风险价值，给定置信度下的最大可能亏损' },
    { abbr: 'T+N', full: 'Trade Date plus N Days', cn: '交易日后第N日到账，T+1=次日到账，T+2=隔日到账' },
  ],
  closedFunds: [
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值，每份基金代表的资产净值' },
    { abbr: 'LOF', full: 'Listed Open-end Fund', cn: '上市开放式基金，转LOF后可按净值赎回' },
    { abbr: 'AAA', full: 'Triple A Rating', cn: '最高信用评级，违约风险极低' },
    { abbr: 'AA+', full: 'Double A Plus Rating', cn: '次高信用评级，安全性较高' },
  ],
  convertibleBonds: [
    { abbr: 'IV', full: 'Implied Volatility', cn: '隐含波动率，由期权价格反推的市场波动预期' },
    { abbr: 'HV', full: 'Historical Volatility', cn: '历史波动率，标的过去N日实际波动率' },
    { abbr: 'YTM', full: 'Yield to Maturity', cn: '到期收益率，持有到期的年化收益率' },
    { abbr: 'BS', full: 'Black-Scholes Model', cn: '布莱克-斯科尔斯期权定价模型' },
    { abbr: 'Delta', full: 'Delta (Hedge Ratio)', cn: '期权价格对标的价格的敏感度，用于对冲' },
    { abbr: 'Z-Score', full: 'Altman Z-Score', cn: 'Altman破产预测模型评分，<1.81为危险区' },
  ],
  etfFunds: [
    { abbr: 'ETF', full: 'Exchange Traded Fund', cn: '交易所交易基金，可像股票一样交易的指数基金' },
    { abbr: 'IOPV', full: 'Indicative Optimized Portfolio Value', cn: '基金参考净值，盘中实时估算' },
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值' },
    { abbr: 'PE', full: 'Price to Earnings Ratio', cn: '市盈率' },
    { abbr: 'VaR', full: 'Value at Risk', cn: '风险价值，套利期间最大可能亏损' },
    { abbr: 'T+N', full: 'Trade Date plus N Days', cn: '资金到账天数' },
    { abbr: 'QDII', full: 'Qualified Domestic Institutional Investor', cn: '合格境内机构投资者，可投海外' },
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
  dataSources: [
    { abbr: 'API', full: 'Application Programming Interface', cn: '应用程序接口，用于自动获取数据' },
    { abbr: 'IOPV', full: 'Indicative Optimized Portfolio Value', cn: '基金参考净值' },
    { abbr: 'NAV', full: 'Net Asset Value', cn: '基金净值' },
    { abbr: 'K线', full: 'Candlestick Chart', cn: '日K线，含开高低收的日行情数据' },
  ],
}
