<script setup lang="ts">
/**
 * 分位字段说明面板
 *
 * 与「缩写词典」同款的可折叠面板（默认隐藏），逐字段解释：
 *   - 这个分位**是什么**（含义）
 *   - 它是**怎么算出来的**（计算方式 / 公式）
 *
 * 口径与后端 backend/services/valuation_service.py 严格一致，改动后端算法时
 * 必须同步本文件，否则页面解释会与实际数字脱节。
 */
import { ref } from 'vue'
import { NIcon, NCollapseTransition } from 'naive-ui'
import { StatsChartOutline, ChevronDownOutline, ChevronUpOutline } from '@vicons/ionicons5'

interface PctItem {
  /** 字段/列名 */
  field: string
  /** 一句话含义 */
  meaning: string
  /** 计算方式（公式或口径说明） */
  formula: string
  /** 是否为分组小标题 */
  group?: boolean
}

const expanded = ref(false)

// 说明结构：每个**分位列**一条独立条目；相同算法（升序百分位）只在第一条写清，
// 后续列注明「本列底层绝对值的聚合口径」+「分位算法同前」，避免冗余又满足「逐列细说」。
const items: PctItem[] = [
  // ——— ① 通用定义（所有分位共用） ———
  {
    field: '升序百分位（统一定义）',
    meaning: '全站所有「分位」的统一定义：当前值在历史月度序列中排第几（数值越大=越贵）。所有分位列都只是把不同的「当前值 + 历史序列」喂给这一个函数。',
    formula: '= 序列中「≤ 当前值」的月数 ÷ 总月数 × 100（保留两位小数）。例：64% = 当前比历史上 64% 的月份都贵。空序列返回 50。',
    group: true,
  },
  // ——— ② 估值总开关 ———
  {
    field: '估值分位',
    meaning: '综合估值温度（越低越便宜），本页排序与「总开关」依据。基于股债利差，是所有 PE/PB 分位的更高层汇总。',
    formula: '= 100 − 股债利差的升序百分位（利差越大=越便宜，故取反）。\n股债利差 = ROE均值(5Y) ÷ PB − 10Y国债 + 0.3×CPI。\n判定：<30% 便宜 / 30–70% 正常 / >70% 过热。\n⚠️ 10Y 国债处历史低位会机械抬高利差、压低本分位——读数偏低部分来自债券端而非股票变便宜。',
  },
  // ——— ③ PE 分位（2 列：全史 + 近10Y） ———
  {
    field: 'PE分位（全史，剔亏口径）',
    meaning: '当前 PE 在**全历史**月度序列中的升序百分位（高=贵），分位计算的「基准列」。',
    formula: '分子取当前 PE 的**剔亏口径** pe_ttm_ex（仅聚 PE>0 成分股），与中证官方分位口径对齐；历史序列逐点回退纳亏 pe_ttm（兼容旧行/补齐段）。\n绝对值列「PE(TTM)」仍是纳亏口径，两列不可直接互推。\n全史含 2007/2015 泡沫顶，通常比 10Y 口径高 10~30pp。',
    group: true,
  },
  {
    field: 'PE分位(10Y)',
    meaning: '同上 PE分位，但历史窗口只取**最近 120 个月（约10年）**，对齐万得/中证官方常用口径，可直接跨源对比。',
    formula: '= 升序百分位(当前PE剔亏, 全史序列末 120 点)。\n历史不足 120 个月时自动退化为全史口径（与「PE分位」列读数相同）。\n月度过采样 vs 外部日度，读数可能差 1~3pp。',
  },
  // ——— ④ PB 分位（2 列：全史 + 近10Y） ———
  {
    field: 'PB分位（全史）',
    meaning: '当前 PB（市值加权）在**全历史**月度序列中的升序百分位（高=贵）。',
    formula: '= 升序百分位(当前PB, 全史序列)。序列每月先剔除净资产为负（PB≤0）成分股再取加权 PB。\n全史含 2007/2015 泡沫顶，常比 10Y 口径高 10~30pp。\n⚠️ PB 便宜 + ROE 中枢下移时警惕价值陷阱，参考 ROE均值(5Y) 列交叉判断。',
    group: true,
  },
  {
    field: 'PB分位(10Y)',
    meaning: '当前 PB 在**最近 120 个月**窗口内的升序百分位，对齐万得/中证官方口径。',
    formula: '= 升序百分位(当前PB, 全史序列末 120 点)。\n不足 120 个月退化为全史。月度过采样 vs 外部日度差 1~3pp。',
  },
  // ——— ⑤ 等权 / 中位 六口径分位（12 列：6 指标 × 全史/10Y） ———
  {
    field: '等权 / 中位 六口径分位（共 12 列）',
    meaning: '6 个算法列（PB等权/PB中位/PE等权/PE中位/PE剔亏等权/PE剔亏中位）各自独立算分位：格子里显示全史分位条，鼠标悬停显示近10年分位。分位算法与加权列**完全相同**（同一个 _percentile 函数）。',
    formula: '每列取**自身**历史序列算升序百分位：全史 = 全部月度点；10Y = 末 120 点。\n加权被大市值股主导，等权/中位分位常与之不同，反映「成分股广度」便宜度。\n⚠️ 等权 PE 自 2010 起（2005 缺口处 legulegu 等权含极值截断，拼接会断点）；纳亏 PE 等权/中位在亏损面大的指数仍可能为负，判断贵贱优先看加权或中位。',
    group: true,
  },
  {
    field: 'PB(等权)分位',
    meaning: '「PB(等权)」列对应分位。底层绝对值 = 成分股 PB **算术均值（不按市值加权）**——不被大市值股主导，反映成分股整体便宜度。',
    formula: '= 升序百分位(当前PB等权, PB等权全史序列)；10Y 同窗挂 tooltip。\n与 PB(中位) 互校；恒为正、分布有界，无极值失真。',
  },
  {
    field: 'PB(中位)分位',
    meaning: '「PB(中位)」列对应分位。底层绝对值 = 成分股 PB **中位数**，剔除极大/极小极值后的中枢，抗单只畸变。',
    formula: '= 升序百分位(当前PB中位, 全史序列)；10Y 同窗挂 tooltip。\n常与等权接近，二者互校。',
  },
  {
    field: 'PE(等权)分位（纳亏·截尾）',
    meaning: '「PE(等权)」列对应分位。底层绝对值 = 成分股 PE 的 **95 分位截尾均值**（含亏损股 PE<0）——与「PE(TTM)」列同口径、不同加权。',
    formula: '= 升序百分位(当前PE等权, 全史序列)；10Y 同窗挂 tooltip。\n截尾：超出 5%/95% 分位的极值拉回分位值再平均，避免微利/微亏股(PE→±∞)主导整列（2026-10-28 修正；此前纯算术均值下中证2000 为 -0.36，现为 20.10）。\n⚠️ 亏损面大的指数（如科创50 现 -10.69）此列仍可能为负，判断贵贱优先看「中位」或「加权」列。',
  },
  {
    field: 'PE(中位)分位（纳亏）',
    meaning: '「PE(中位)」列对应分位。底层绝对值 = 成分股 PE **中位数**，亏损股(PE<0)仍计入排序。',
    formula: '= 升序百分位(当前PE中位, 全史序列)；10Y 同窗挂 tooltip。\n抗极值；与等权口径互校。',
  },
  {
    field: 'PE剔亏(等权)分位（剔亏·截尾）',
    meaning: '「PE剔亏(等权)」列对应分位。底层绝对值 = **仅 PE>0** 成分股的 95 分位截尾均值——分位计算基准，与中证官方分位口径一致。',
    formula: '= 升序百分位(当前PE剔亏等权, 全史序列)；10Y 同窗挂 tooltip。\n已与 legulegu「等权滚动市盈率」对齐：2026-10-27 沪深300 28.86 vs 28.33(+1.9%)、上证50 -1.2%、深证100 +1.4%；小盘残差略大（中证1000 +12.3%，财报时点差）。',
  },
  {
    field: 'PE剔亏(中位)分位（剔亏）',
    meaning: '「PE剔亏(中位)」列对应分位。底层绝对值 = **仅 PE>0** 成分股的中位数，抗极值。',
    formula: '= 升序百分位(当前PE剔亏中位, 全史序列)；10Y 同窗挂 tooltip。\n与剔亏等权互校。',
  },
  // ——— ⑥ 相对冷热 & 稳健 ———
  {
    field: '拥挤度',
    meaning: '相对冷热：该指数**相对全A**的估值高低，**不是绝对贵贱**——全A整体很贵时，拥挤度低也可能仍然贵。',
    formula: '= 升序百分位(当前PB ÷ 当期全A PB, 该比值的历史序列)。\n全A 相对自身拥挤度无意义（后端置空，全A基准行不显示）。',
  },
  {
    field: 'ERP Z分数',
    meaning: '股债利差偏离自身中枢多少倍**稳健**标准差（抗异常值）。负值=利差偏低=偏贵。与「估值分位」互补：分位看历史分布排位，Z 看离近期常态多远。',
    formula: '= (当前利差 − 近10年中位数) ÷ (1.4826 × MAD)；MAD = 绝对偏差中位数，比标准差更抗极端值。\n窗口 = 近10年利差序列（约120点）。\n判定：Z>1.5 低估(绿) / Z<-1.5 高估(红) / 之间中性。',
  },
  // ——— ⑦ 数据边界与口径 ———
  {
    field: '历史起点（2005 补齐）',
    meaning: '全史序列起点各指数不同（多数为指数发布日）。2026-10-28 用 legulegu 月度序列补齐至 2005 年，外部权威口径收敛到 2~7pp。',
    formula: '补齐范围：上证50/沪深300/上证180/上证380/上证红利/沪深系/中证500/800/1000/2000/100、深证100/深证红利、创业板50 共 12 指数，2005–2009（或各自更早缺口）补齐。\n仅含 PB(加权/等权/中位) 与剔亏 PE(加权/中位)；纳亏 PE 仍自 2010 起、等权 PE 因极值口径不补。\n各序列起止与样本数见列头 tooltip。',
    group: true,
  },
  {
    field: '样本不足（显示「—」）',
    meaning: '历史样本 < 最小样本数（24 个月）的指数，所有分位显示「—」，避免无统计意义的读数。',
    formula: '守卫逻辑：history_samples < MIN_HISTORY_SAMPLES 时 pb/pe/pe10y/pb10y/等权中位6项/估值分位/拥挤度/ERP 全部置空；前端标注「⚠」+ 样本月数提示。',
  },
  {
    field: '行业估值分位（日度快照）',
    meaning: '行业估值 Tab 的 PE/PB分位/拥挤度，与宽基**算法口径一致**（升序百分位，高=贵），但数据底座不同。',
    formula: '基于**本地每日累积的日度快照**算升序百分位（非宽基的月度序列）。\n当前为累积初期，历史越长越准，分位仅供参考；行业无「近10Y」窗口列。',
  },
]
</script>

<template>
  <div class="pct-panel">
    <button class="pct-toggle" @click="expanded = !expanded">
      <span class="toggle-left">
        <NIcon :component="StatsChartOutline" size="14" />
        <span class="toggle-text">分位字段说明</span>
        <span class="toggle-count">{{ items.filter((i) => !i.group).length }}</span>
      </span>
      <NIcon :component="expanded ? ChevronUpOutline : ChevronDownOutline" size="16" class="toggle-arrow" />
    </button>

    <NCollapseTransition :show="expanded">
      <div class="pct-body">
        <div v-for="item in items" :key="item.field" class="pct-item" :class="{ 'pct-group': item.group }">
          <div class="pct-head">
            <span class="p-field">{{ item.field }}</span>
            <span class="p-meaning">{{ item.meaning }}</span>
          </div>
          <div class="p-formula">{{ item.formula }}</div>
        </div>
      </div>
    </NCollapseTransition>
  </div>
</template>

<style scoped>
.pct-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 16px;
  box-shadow: var(--shadow-card);
}

.pct-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 12px 18px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background 0.15s ease, color 0.15s ease;
}
.pct-toggle:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.toggle-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toggle-text {
  font-family: 'Work Sans', sans-serif;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.03em;
}
.toggle-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: var(--bg-hover);
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}
.toggle-arrow {
  color: var(--text-muted);
  transition: transform 0.2s ease;
}

.pct-body {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 8px;
  padding: 6px 18px 16px;
  border-top: 1px solid var(--border-default);
}

.pct-item {
  padding: 9px 12px;
  border-radius: 6px;
  background: var(--bg-hover);
}
.pct-item.pct-group {
  background: transparent;
  border-left: 2px solid var(--color-primary);
  border-radius: 0 6px 6px 0;
}

.pct-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.p-field {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 700;
  color: var(--color-primary);
  flex-shrink: 0;
}
.p-meaning {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.4;
  flex: 1;
  min-width: 140px;
}
.p-formula {
  margin-top: 5px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--text-muted);
  word-break: break-word;
  white-space: pre-line;
}

@media (max-width: 768px) {
  .pct-body {
    grid-template-columns: 1fr;
  }
}
</style>
