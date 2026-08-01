/**
 * Provides mock financial data for development/demo mode.
 * This data matches the UI prototypes visually.
 */

import type {
  IndexValuation,
  ConvertibleBond,
  FundItem,
  EtfFund,
  ReitItem,
  Strategy,
  AlertRule,
  MacroData,
} from '../types'

export const mockMacroData: MacroData = {
  erp: 4.82,
  erp_percentile_3y: 82,
  erp_percentile_5y: 76,
  erp_percentile_10y: 68,
  dr007: 1.85,
  gc001: 1.92,
  indices: [
    { name: 'CSI 300', level: 3654.21, change_pct: 0.42, pe: 11.4, pb: 1.22, pe_percentile: 12.4, pb_percentile: 8.1, category: 'undervalued', change_3m_pct: 2.1, win_rate: 62.4 },
    { name: 'SSE 50', level: 2412.56, change_pct: -0.15, pe: 10.2, pb: 1.15, pe_percentile: 35.6, pb_percentile: 42.2, category: 'normal', change_3m_pct: -1.4, win_rate: 54.1 },
    { name: 'CSI 500', level: 5280.12, change_pct: 1.05, pe: 18.6, pb: 1.68, pe_percentile: 5.2, pb_percentile: 11.8, category: 'opportunity', change_3m_pct: 4.2, win_rate: 68.5 },
    { name: 'CSI 1000', level: 5892.45, change_pct: 2.11, pe: 22.3, pb: 1.92, pe_percentile: 18.9, pb_percentile: 22.4, category: 'undervalued', change_3m_pct: 1.1, win_rate: 51.2 },
    { name: 'ChiNext', level: 1894.10, change_pct: -0.88, pe: 38.5, pb: 3.45, pe_percentile: 82.1, pb_percentile: 78.5, category: 'overvalued', change_3m_pct: -6.4, win_rate: 38.9 },
    { name: 'SSE Composite', level: 3124.50, change_pct: 0.12, pe: 13.1, pb: 1.35, pe_percentile: 48.2, pb_percentile: 45.1, category: 'normal', change_3m_pct: 0.0, win_rate: 50.0 },
  ],
}

export const mockConvertibleBonds: ConvertibleBond[] = [
  { name: 'Zhenghong CB 2', code: '113001', price: 124.52, change_pct: 1.42, conv_value: 112.40, premium_pct: 10.78, ytm: -0.45, remaining_years: 3.4, rating: 'AAA', redemption_days: 12, total_redemption_days: 15, tag: 'Double Low', tag_type: 'double_low', double_low_score: 135.2, putback_days: 8, total_putback_days: 30, revision_days: 5, total_revision_days: 15, altman_z_score: 3.85, pledge_rate: 12.4, is_st_risk: false, stock_name: '郑煤机', stock_code: '601717', iv: 28.5, hv: 32.1, is_in_conversion_period: true, stock_limit_up: false, stock_price: 8.45, stock_change_pct: 1.42 },
  { name: 'Longwell CB', code: '113002', price: 102.14, change_pct: -0.58, conv_value: 98.50, premium_pct: 3.69, ytm: 3.12, remaining_years: 1.2, rating: 'AA+', redemption_days: 2, total_redemption_days: 15, tag: 'Undervalued', tag_type: 'undervalued', double_low_score: 105.8, putback_days: 22, total_putback_days: 30, revision_days: 0, total_revision_days: 15, altman_z_score: 2.42, pledge_rate: 28.6, is_st_risk: false, stock_name: '长虹华意', stock_code: '000404', iv: 35.2, hv: 28.8, is_in_conversion_period: true, stock_limit_up: false, stock_price: 4.12, stock_change_pct: -0.58 },
  // 负溢价 -0.92%，转股期，正股涨停 → 不可行(卖不出正股)
  { name: 'TechGrowth CB', code: '113003', price: 245.80, change_pct: 4.15, conv_value: 248.10, premium_pct: -0.92, ytm: -12.4, remaining_years: 0.5, rating: 'AA', redemption_days: 15, total_redemption_days: 15, tag: 'High Risk', tag_type: 'high_risk', putback_days: 0, total_putback_days: 30, revision_days: 0, total_revision_days: 15, altman_z_score: 1.82, pledge_rate: 45.2, is_st_risk: false, stock_name: '科技成长', stock_code: '002230', iv: 55.8, hv: 48.2, is_in_conversion_period: true, stock_limit_up: true, stock_price: 18.65, stock_change_pct: 10.01 },
  { name: 'SolarEnergy CB', code: '113004', price: 112.30, change_pct: 0.22, conv_value: 105.40, premium_pct: 6.54, ytm: 1.15, remaining_years: 4.8, rating: 'AAA', redemption_days: 7, total_redemption_days: 15, tag: 'Stable Yield', tag_type: 'stable_yield', double_low_score: 112.4, putback_days: 12, total_putback_days: 30, revision_days: 3, total_revision_days: 15, altman_z_score: 4.21, pledge_rate: 8.5, is_st_risk: false, stock_name: '太阳能', stock_code: '000591', iv: 22.1, hv: 25.6, is_in_conversion_period: true, stock_limit_up: false, stock_price: 5.82, stock_change_pct: 0.22 },
  // 负溢价但未进入转股期 → 伪机会
  { name: 'AlphaLogic CB', code: '113005', price: 98.42, change_pct: -1.12, conv_value: 88.10, premium_pct: 11.7, ytm: 4.58, remaining_years: 2.1, rating: 'AA+', redemption_days: 1, total_redemption_days: 15, tag: 'Mean Reversion', tag_type: 'mean_reversion', double_low_score: 109.9, putback_days: 28, total_putback_days: 30, revision_days: 8, total_revision_days: 15, altman_z_score: 2.05, pledge_rate: 35.8, is_st_risk: false, stock_name: '阿尔法逻辑', stock_code: '300168', iv: 18.5, hv: 32.4, is_in_conversion_period: false, stock_limit_up: false, stock_suspended: false, stock_price: 12.34, stock_change_pct: -1.12 },
  { name: 'HeavyInd CB', code: '113006', price: 105.70, change_pct: 0.05, conv_value: 101.20, premium_pct: 4.44, ytm: 2.88, remaining_years: 5.9, rating: 'AAA', redemption_days: 4, total_redemption_days: 15, tag: 'Defensive', tag_type: 'defensive', putback_days: 5, total_putback_days: 30, revision_days: 1, total_revision_days: 15, altman_z_score: 3.42, pledge_rate: 15.2, is_st_risk: false, stock_name: '徐工机械', stock_code: '000425', iv: 26.3, hv: 24.1, is_in_conversion_period: true, stock_limit_up: false, stock_price: 6.78, stock_change_pct: 0.05 },
  { name: 'PetroChem CB', code: '113007', price: 108.20, change_pct: 0.35, conv_value: 102.80, premium_pct: 5.25, ytm: 2.45, remaining_years: 4.2, rating: 'AAA', redemption_days: 3, total_redemption_days: 15, tag: 'Defensive', tag_type: 'defensive', putback_days: 10, total_putback_days: 30, revision_days: 2, total_revision_days: 15, altman_z_score: 3.78, pledge_rate: 10.1, is_st_risk: false, stock_name: '中石化', stock_code: '600028', iv: 15.2, hv: 18.8, is_in_conversion_period: true, stock_limit_up: false, stock_price: 6.45, stock_change_pct: 0.35 },
  // 负溢价 -2.5%，转股期，正股未涨停，T+1敞口1.45% < 套利收益2.5% → 可行
  { name: 'MicroSys CB', code: '113008', price: 95.60, change_pct: -2.10, conv_value: 98.05, premium_pct: -2.5, ytm: 5.82, remaining_years: 1.8, rating: 'AA', redemption_days: 0, total_redemption_days: 15, tag: 'High Risk', tag_type: 'high_risk', putback_days: 30, total_putback_days: 30, revision_days: 11, total_revision_days: 15, altman_z_score: 1.45, pledge_rate: 58.9, is_st_risk: true, stock_name: 'ST微系统', stock_code: '002156', iv: 42.1, hv: 38.5, is_in_conversion_period: true, stock_limit_up: false, stock_suspended: false, stock_price: 3.21, stock_change_pct: -2.10 },
]

export const mockFunds: FundItem[] = [
  { name: 'ChinaAMC CSI 300 LOF', code: '160706', type: 'lof', price: 1.245, iopv: 1.228, premium_pct: 1.38, premium_percentile: 72, net_arbitrage_yield: 0.85, volume: 2850000 },
  { name: 'E Fund SSE 50 LOF', code: '502050', type: 'lof', price: 1.112, iopv: 1.105, premium_pct: 0.63, premium_percentile: 45, net_arbitrage_yield: 0.28, volume: 1560000 },
  // QDII — T+2到账，外汇额度受限
  // 限购1000元 → B级(资金受限)，T+2敞口4.21% > 净收益1.82% → 有风险
  { name: 'Harvest Nasdaq QDII', code: '160213', type: 'qdii', price: 2.856, iopv: 2.688, premium_pct: 6.25, premium_percentile: 88, net_arbitrage_yield: 1.82, volume: 890000, subscribe_limit: '限购 1000 元', daily_volatility: 1.8, holding_days: 2 },
  // 限购100元 → C级(不可行)，收益归零
  { name: 'Penghua Nasdaq QDII', code: '501306', type: 'qdii', price: 1.684, iopv: 1.602, premium_pct: 5.12, premium_percentile: 81, net_arbitrage_yield: 1.45, volume: 520000, subscribe_limit: '限购 100 元', daily_volatility: 1.8, holding_days: 2 },
  { name: 'Taikang Closed Opp. A', code: '501500', type: 'closed', price: 0.886, iopv: 1.012, premium_pct: -12.4, premium_percentile: 92, net_arbitrage_yield: 8.42, remaining_term: '28 Days', annualized: 8.42, est_ytm: 14.2, maturity: '2024-06-28', volume: 340000, nav: 1.012, credit_rating: 'AAA', is_lof_convertible: true, underlying_type: '混合型' },
  { name: 'GF Dynamic Select Growth', code: '162701', type: 'closed', price: 0.818, iopv: 1.0, premium_pct: -18.2, premium_percentile: 74, net_arbitrage_yield: 12.5, remaining_term: '1.4 Years', annualized: 12.5, est_ytm: 9.8, maturity: '2025-08-12', volume: 280000, nav: 1.0, credit_rating: 'AA+', is_lof_convertible: true, underlying_type: '成长股' },
  { name: 'E-Fund Blue Chip Strategic', code: '161132', type: 'closed', price: 0.909, iopv: 1.0, premium_pct: -9.1, premium_percentile: 45, net_arbitrage_yield: 5.2, remaining_term: '312 Days', annualized: 5.2, est_ytm: 6.4, maturity: '2025-02-15', volume: 195000, nav: 1.0, credit_rating: 'AA', is_lof_convertible: false, underlying_type: '蓝筹股' },
  { name: 'Huatai-PB Dividend Focus', code: '501301', type: 'closed', price: 0.785, iopv: 1.0, premium_pct: -21.5, premium_percentile: 88, net_arbitrage_yield: 10.2, remaining_term: '2.1 Years', annualized: 10.2, est_ytm: 11.1, maturity: '2026-04-30', volume: 420000, nav: 1.0, credit_rating: 'AAA', is_lof_convertible: true, underlying_type: '红利股' },
]

// ETF 基金（集思录策略：折溢价套利 / 网格交易 / 行业轮动 / 估值定投）
export const mockEtfFunds: EtfFund[] = [
  // 跨境 ETF — 折溢价套利（外汇额度受限导致高溢价）
  // T+2 到账: 申购T日 → 份额T+2日到账 → 二级市场卖出
  // 限购100元 → 资金容量C级(不可行)，收益归零
  { name: '华夏纳指100ETF', code: '513100.SH', category: 'cross_border', sub_category: '纳斯达克100', price: 1.856, iopv: 1.632, premium_pct: 13.73, volume: 2150000, premium_percentile: 95, net_arbitrage_yield: 3.82, subscribe_limit: '限购 100 元', daily_volatility: 1.8, holding_days: 2, grid_low: 1.65, grid_high: 1.95, grid_step: 2, grid_yield_est: 18.5, momentum_score: 88, pe: 32.5, pe_percentile: 78, val_category: 'overvalued' },
  // 限购500元 → 资金容量C级(不可行)，收益归零
  { name: '易方达中概互联ETF', code: '513050.SH', category: 'cross_border', sub_category: '中概互联', price: 1.025, iopv: 0.952, premium_pct: 7.67, volume: 4860000, premium_percentile: 90, net_arbitrage_yield: 2.15, subscribe_limit: '限购 500 元', daily_volatility: 2.5, holding_days: 2, grid_low: 0.88, grid_high: 1.10, grid_step: 2.5, grid_yield_est: 22.3, momentum_score: 72, pe: 25.8, pe_percentile: 35, val_category: 'undervalued' },
  // 无限购 → 资金容量A级，但T+2敞口5.13% > 净收益0.92% → 有风险
  { name: '华安恒生互联网ETF', code: '513770.SH', category: 'cross_border', sub_category: '恒生科技', price: 0.682, iopv: 0.658, premium_pct: 3.65, volume: 1850000, premium_percentile: 75, net_arbitrage_yield: 0.92, subscribe_limit: '无限制', daily_volatility: 2.2, holding_days: 2, grid_low: 0.58, grid_high: 0.78, grid_step: 3, grid_yield_est: 26.5, momentum_score: 68, pe: 28.2, pe_percentile: 42, val_category: 'undervalued' },
  // 无限购 + 低波动 → 资金容量A级，T+1敞口0.82% < 净收益2.5% → 可行
  { name: '国泰纳指ETF(lof)', code: '513500.SH', category: 'cross_border', sub_category: '纳斯达克100(lof)', price: 2.345, iopv: 2.210, premium_pct: 6.11, volume: 920000, premium_percentile: 85, net_arbitrage_yield: 2.5, subscribe_limit: '无限制', daily_volatility: 0.5, holding_days: 1, grid_low: 2.10, grid_high: 2.50, grid_step: 2.5, grid_yield_est: 20.2, momentum_score: 80, pe: 32.5, pe_percentile: 78, val_category: 'overvalued' },
  // 暂停申购 → 直接不可行
  { name: '广发纳指100ETF', code: '513880.SH', category: 'cross_border', sub_category: '纳斯达克100', price: 1.692, iopv: 1.498, premium_pct: 12.95, volume: 680000, premium_percentile: 92, net_arbitrage_yield: 4.12, subscribe_limit: '暂停申购', daily_volatility: 1.8, holding_days: 2, is_suspended: true, grid_low: 1.50, grid_high: 1.80, grid_step: 2, grid_yield_est: 19.0, momentum_score: 85, pe: 32.5, pe_percentile: 80, val_category: 'overvalued' },
  // 行业 ETF — 网格交易 + 轮动 (T+1到账)
  { name: '券商ETF', code: '512000.SH', category: 'industry', sub_category: '证券', price: 0.985, iopv: 0.988, premium_pct: -0.30, volume: 12800000, premium_percentile: 38, net_arbitrage_yield: 0, daily_volatility: 1.5, holding_days: 1, grid_low: 0.85, grid_high: 1.15, grid_step: 4, grid_yield_est: 32.5, momentum_score: 82, pe: 15.2, pe_percentile: 8, val_category: 'undervalued', dividend_rate: 2.1 },
  { name: '酒ETF', code: '512690.SH', category: 'industry', sub_category: '食品饮料', price: 0.625, iopv: 0.628, premium_pct: -0.48, volume: 4200000, premium_percentile: 42, net_arbitrage_yield: 0, daily_volatility: 1.3, holding_days: 1, grid_low: 0.50, grid_high: 0.70, grid_step: 4, grid_yield_est: 28.8, momentum_score: 65, pe: 18.5, pe_percentile: 8, val_category: 'undervalued', dividend_rate: 3.2 },
  { name: '地产ETF', code: '512200.SH', category: 'industry', sub_category: '房地产', price: 0.672, iopv: 0.675, premium_pct: -0.44, volume: 3800000, premium_percentile: 45, net_arbitrage_yield: 0, daily_volatility: 1.6, holding_days: 1, grid_low: 0.55, grid_high: 0.80, grid_step: 4, grid_yield_est: 35.2, momentum_score: 58, pe: 8.5, pe_percentile: 15, val_category: 'undervalued', dividend_rate: 4.0 },
  { name: '创新药ETF', code: '515120.SH', category: 'industry', sub_category: '医药生物', price: 0.512, iopv: 0.510, premium_pct: 0.39, volume: 2950000, premium_percentile: 55, net_arbitrage_yield: 0, daily_volatility: 1.8, holding_days: 1, grid_low: 0.42, grid_high: 0.62, grid_step: 3.5, grid_yield_est: 30.1, momentum_score: 75, pe: 28.6, pe_percentile: 12, val_category: 'undervalued' },
  { name: '半导体ETF', code: '512480.SH', category: 'industry', sub_category: '电子半导体', price: 1.185, iopv: 1.182, premium_pct: 0.25, volume: 8500000, premium_percentile: 60, net_arbitrage_yield: 0, daily_volatility: 2.2, holding_days: 1, grid_low: 0.95, grid_high: 1.35, grid_step: 3, grid_yield_est: 25.6, momentum_score: 91, pe: 65.2, pe_percentile: 82, val_category: 'overvalued' },
  // 宽基 ETF — 估值定投
  { name: '沪深300ETF', code: '510300.SH', category: 'broad', sub_category: '沪深300', price: 3.856, iopv: 3.858, premium_pct: -0.05, volume: 15600000, premium_percentile: 30, net_arbitrage_yield: 0, daily_volatility: 0.8, holding_days: 1, grid_low: 3.20, grid_high: 4.20, grid_step: 2.5, grid_yield_est: 15.8, momentum_score: 62, pe: 11.4, pe_percentile: 12, val_category: 'undervalued', dividend_rate: 2.8 },
  { name: '中证500ETF', code: '510500.SH', category: 'broad', sub_category: '中证500', price: 5.842, iopv: 5.840, premium_pct: 0.03, volume: 8200000, premium_percentile: 35, net_arbitrage_yield: 0, daily_volatility: 1.0, holding_days: 1, grid_low: 5.00, grid_high: 6.50, grid_step: 2.5, grid_yield_est: 16.2, momentum_score: 70, pe: 22.5, pe_percentile: 28, val_category: 'undervalued', dividend_rate: 1.5 },
  { name: '科创50ETF', code: '588000.SH', category: 'broad', sub_category: '科创50', price: 1.025, iopv: 1.022, premium_pct: 0.29, volume: 6500000, premium_percentile: 50, net_arbitrage_yield: 0, daily_volatility: 1.5, holding_days: 1, grid_low: 0.80, grid_high: 1.20, grid_step: 3, grid_yield_est: 20.5, momentum_score: 85, pe: 75.8, pe_percentile: 88, val_category: 'overvalued' },
  // 主题 ETF
  { name: '红利ETF', code: '510880.SH', category: 'theme', sub_category: '红利低波', price: 2.956, iopv: 2.958, premium_pct: -0.07, volume: 3200000, premium_percentile: 28, net_arbitrage_yield: 0, daily_volatility: 0.6, holding_days: 1, grid_low: 2.60, grid_high: 3.20, grid_step: 2, grid_yield_est: 12.5, momentum_score: 56, pe: 8.2, pe_percentile: 18, val_category: 'undervalued', dividend_rate: 5.2 },
  { name: '央企改革ETF', code: '512950.SH', category: 'theme', sub_category: '央企改革', price: 1.182, iopv: 1.180, premium_pct: 0.17, volume: 1850000, premium_percentile: 48, net_arbitrage_yield: 0, daily_volatility: 0.9, holding_days: 1, grid_low: 1.00, grid_high: 1.35, grid_step: 3, grid_yield_est: 18.8, momentum_score: 64, pe: 12.5, pe_percentile: 22, val_category: 'undervalued', dividend_rate: 3.5 },
]

export const mockReits: ReitItem[] = [
  { name: '招商蛇口产业园REIT', code: '180101', market_price: 3.285, annual_distribution: 0.185, dividend_rate: 5.63, irr: 6.12, occupancy_rate: 92.5, project_name: '深圳蛇口网谷', nav: 3.182, volume: 1850000, dscr: 1.42, occupancy_trend: -1.2, asset_type: '产业园', leverage_ratio: 32.5 },
  { name: '中金普洛斯仓储REIT', code: '508056', market_price: 3.856, annual_distribution: 0.212, dividend_rate: 5.50, irr: 5.88, occupancy_rate: 95.2, project_name: '北京/上海仓储', nav: 3.712, volume: 2200000, dscr: 1.68, occupancy_trend: 2.5, asset_type: '仓储物流', leverage_ratio: 28.2 },
  { name: '华安张江光大REIT', code: '508000', market_price: 2.956, annual_distribution: 0.168, dividend_rate: 5.68, irr: 6.35, occupancy_rate: 88.6, project_name: '上海张江产业园', nav: 3.082, volume: 890000, dscr: 1.15, occupancy_trend: -5.8, asset_type: '产业园', leverage_ratio: 38.6 },
  { name: '富国首创水务REIT', code: '508006', market_price: 3.452, annual_distribution: 0.195, dividend_rate: 5.65, irr: 7.82, occupancy_rate: 100, project_name: '深圳/合肥水务', nav: 3.358, volume: 1250000, dscr: 2.15, occupancy_trend: 0, asset_type: '水务', leverage_ratio: 22.4 },
  { name: '浙商沪杭甬REIT', code: '508001', market_price: 7.856, annual_distribution: 0.412, dividend_rate: 5.24, irr: 4.95, occupancy_rate: 100, project_name: '沪杭甬高速', nav: 7.642, volume: 3100000, dscr: 1.88, occupancy_trend: 0, asset_type: '高速公路', leverage_ratio: 35.8 },
]

export const mockStrategies: Strategy[] = [
  {
    id: '1', name: '双低可转债轮动策略', target_asset: 'cb', active: true,
    rules: [
      { id: 'r1', field: '价格', operator: '<', value: '120', logic: 'AND' },
      { id: 'r2', field: '转股溢价率', operator: '<', value: '20', logic: 'AND' },
      { id: 'r3', field: '信用评级', operator: '属于', value: 'AA, AA+, AAA', logic: 'AND' },
    ],
    createdAt: '2026-06-01',
  },
  {
    id: '2', name: 'QDII 溢价套利策略', target_asset: 'lof', active: true,
    rules: [
      { id: 'r4', field: '实时折溢价率', operator: '>', value: '3', logic: 'AND' },
      { id: 'r5', field: '净套利收益率', operator: '>', value: '1.5', logic: 'AND' },
    ],
    createdAt: '2026-06-10',
  },
  {
    id: '3', name: '高分红REITs筛选', target_asset: 'reit', active: false,
    rules: [
      { id: 'r6', field: '分红率', operator: '>', value: '5', logic: 'AND' },
      { id: 'r7', field: '出租率', operator: '>', value: '85', logic: 'AND' },
    ],
    createdAt: '2026-07-01',
  },
]

export const mockAlertRules: AlertRule[] = [
  { id: 'a1', name: '溢价率异动预警', type: 'premium', target: 'LOF基金', condition: 'above', value: 5, channels: ['popup', 'dingtalk'], active: true },
  { id: 'a2', name: '折价率收敛提醒', type: 'discount', target: '封闭基金', condition: 'below', value: -5, channels: ['popup'], active: true },
  { id: 'a3', name: '强赎风险监控', type: 'price', target: 'TechGrowth CB', condition: 'above', value: 130, channels: ['popup', 'wechat'], active: true },
  { id: 'a4', name: 'YTM超阈值预警', type: 'ytm', target: '可转债', condition: 'below', value: 0, channels: ['email'], active: false },
]
