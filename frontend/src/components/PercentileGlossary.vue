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

const items: PctItem[] = [
  {
    field: '升序百分位',
    meaning: '全站所有「分位」的统一定义：当前值在历史序列中排第几（越高越贵）。',
    formula: '= 序列中「≤ 当前值」的月数 ÷ 总月数 × 100',
    group: true,
  },
  {
    field: '估值分位',
    meaning: '综合估值温度（越低越便宜）。基于股债利差，是本页的「总开关」。',
    formula: '= 100 − 股债利差的升序百分位（利差越大越便宜，故取反）；<30 便宜 / 30–70 正常 / >70 过热',
  },
  {
    field: 'PE分位',
    meaning: '当前 PE 在**全历史**月度序列中的百分位，越高越贵。',
    formula: '= 升序百分位(当前PE, 全史序列)。当前 PE 取**剔亏口径** pe_ttm_ex（仅聚 PE>0，对齐中证官方分位），缺失时回退纳亏 pe_ttm；绝对值列仍显示纳亏口径',
  },
  {
    field: 'PE分位(10Y)',
    meaning: '同上，但历史窗口只取**最近 120 个月（约10年）**，对齐万得/中证常用口径，可直接跨源对比。',
    formula: '= 升序百分位(当前PE, 全史序列末 120 点)；历史不足 120 个月时退化为全史',
  },
  {
    field: 'PB分位',
    meaning: '当前 PB（市值加权）在**全历史**月度序列中的百分位，越高越贵。',
    formula: '= 升序百分位(当前PB, 全史序列)',
  },
  {
    field: 'PB分位(10Y)',
    meaning: '当前 PB 在**最近 120 个月**窗口内的百分位。',
    formula: '= 升序百分位(当前PB, 全史序列末 120 点)',
  },
  {
    field: '等权/中位分位',
    meaning: '六列新口径（PB等权/PB中位/PE等权/PE中位/PE剔亏等权/PE剔亏中位）各自独立算分位：格子显示全史分位，鼠标悬停显示近10年分位。',
    formula: '每列各自取其历史序列算升序百分位，算法与加权列完全相同：全史 = 全部月度点；10Y = 末 120 点。因加权被大市值股主导，等权/中位分位常与加权不同，反映「成分股广度」的便宜度',
    group: true,
  },
  {
    field: '拥挤度',
    meaning: '相对冷热：该指数相对全A的估值高低，**不是绝对贵贱**——全A整体很贵时，拥挤度低也可能仍然贵。',
    formula: '= 升序百分位(当前PB ÷ 当期全A PB, 该比值的历史序列)',
  },
  {
    field: 'ERP Z分数',
    meaning: '股债利差偏离自身中枢多少倍标准差（稳健版，抗异常值）。负值=利差偏低=偏贵。',
    formula: '= (当前利差 − 近10年中位数) ÷ (1.4826 × MAD)；MAD = 绝对偏差中位数，比标准差更抗极端值',
  },
  {
    field: '历史起点',
    meaning: '全史序列的起点各指数不同（多数为指数发布日）。2026-10-28 已用 legulegu 月度序列补齐至 2005 年；个别指数（如中证1000，其数据源 2014 年起）仍从各自可得起点开始。',
    formula: '样本数见列头 tooltip；样本不足（< 最小样本数）的指数所有分位显示「—」，避免出现无统计意义的读数',
    group: true,
  },
]
</script>

<template>
  <div class="pct-panel">
    <button class="pct-toggle" @click="expanded = !expanded">
      <span class="toggle-left">
        <NIcon :component="StatsChartOutline" size="14" />
        <span class="toggle-text">分位字段说明</span>
        <span class="toggle-count">{{ items.filter((i) => !i.group).length + 1 }}</span>
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
}

@media (max-width: 768px) {
  .pct-body {
    grid-template-columns: 1fr;
  }
}
</style>
