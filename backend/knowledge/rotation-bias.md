# 动量轮动与 BIAS 减仓

## 动量轮动（momentum-buy-signal）

- 在一组**低相关资产**里按回看收益排名，买最强 top-K，定期再平衡。
- 使用前先校验资产池相关性，避免互相掣肘。
- 可回测：轮动 vs 等权、按动量强度/风险平价加权。

## BIAS 乖离减仓（bias-position-strategy）

- 指数/ETF 短期（BIAS20）或中期（BIAS60）过热时**阶梯式左侧减仓**，控制回撤。
- 张翼轸 Earl 体系：BIAS 触阈即减，不猜顶；A 股基金版「赶顶改 BIAS 减仓」替代美股 Parabolic Short。
- 跨境 ETF T+0 可实现当日止损。

## 周度波段工作流（weekly-band-workflow）

每周一产出一站式决策报告：

1. momentum-buy-signal：动量排名 → 买入/轮换信号。
2. bias-position-strategy：持仓 BIAS → 减仓信号。
3. 合并为可直接执行的周度流（换仓清单 + 减仓清单）。
