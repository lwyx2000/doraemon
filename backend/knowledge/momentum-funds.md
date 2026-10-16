# 动量策略与 A 股基金版适配

## 原始体系（Qullamaggie，美股）

- Stage 2 领头羊 + 三类 Setup：Breakout（突破）/ Episodic Pivot（事件 pivot）/ Parabolic Short（抛物线做空）。
- 关键：只做市场最强主线，止损纪律严格。

## A 股基金版适配（只做基金/ETF，不做个股）

- **资产池**：宽基、行业主题、跨境（T+0）、商品债券 ETF。
- **市场门限**：沪深300 / 中证1000 / 创业板 10SMA > 20SMA 才允许开仓（门限不过则空仓观察）。
- **EP（Episodic Pivot）适配**：题材/政策启动首日的行业 ETF 跳空——A 股语境下 EP 落在行业 ETF 而非个股。
- **不做空**：赶顶信号改用 BIAS 乖离减仓（见 rotation-bias）。
- **跨境 ETF 为 T+0**：可当日止损，是风控利器。
- 交易成本与 T+1 约束在回测中显式建模。

## 相关技能沉淀

- `qullamaggie-momentum`（美股原版 + references/ashare_funds_adaptation.md 基金版）
- `momentum-buy-signal`（动量轮动买入）
- `bias-position-strategy`（BIAS 乖离减仓）
- `weekly-band-workflow`（周度组合：周一决策报告）
