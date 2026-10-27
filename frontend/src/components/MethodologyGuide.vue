<script setup lang="ts">
/**
 * 估值方法说明面板
 *
 * 可折叠区域，默认隐藏。点击标题栏展开/收起。
 * 内容取自 doc/A股估值方案详解.md（基于「韭菜投资学」股债利差 + 拥挤度体系），
 * 把公众号的方法论说明搬上页面，与 GlossaryPanel（缩写词典）同款折叠样式。
 */
import { ref } from 'vue'
import { NIcon, NCollapseTransition, NTag } from 'naive-ui'
import { InformationCircleOutline, ChevronDownOutline, ChevronUpOutline } from '@vicons/ionicons5'

// 内容节数，用于标题栏徽标
const SECTION_COUNT = 7

const expanded = ref(false)
</script>

<template>
  <div class="guide-panel">
    <button class="guide-toggle" @click="expanded = !expanded">
      <span class="toggle-left">
        <NIcon :component="InformationCircleOutline" size="14" />
        <span class="toggle-text">估值方法说明</span>
        <span class="toggle-count">{{ SECTION_COUNT }}</span>
      </span>
      <NIcon :component="expanded ? ChevronUpOutline : ChevronDownOutline" size="16" class="toggle-arrow" />
    </button>

    <NCollapseTransition :show="expanded">
      <div class="guide-body">
        <p class="guide-lead">
          本页采用「韭菜投资学」估值体系：用 <b>股债利差</b> 判断 A 股整体贵不贵，用 <b>拥挤度</b> 判断指数之间谁更便宜。
        </p>

        <!-- 一、估值分位 -->
        <div class="guide-section">
          <h5 class="gs-title">一、估值分位（股债利差法）</h5>
          <p class="gs-text">
            股债利差 = ROE均值(近5年) ÷ PB − 10年期国债收益率 + 0.3 × CPI同比<br>
            估值分位 = 100 − 利差在历史中的升序百分位（<b>越小 = 越便宜</b>）
          </p>
          <div class="gs-tags">
            <NTag type="success" size="small" :bordered="false">&lt; 30% 便宜 · 价值机会区</NTag>
            <NTag type="warning" size="small" :bordered="false">30%–70% 正常</NTag>
            <NTag type="error" size="small" :bordered="false">&gt; 70% 过热 · 防回撤</NTag>
          </div>
          <p class="gs-note">⚠️ 分位表示「比历史上百分之多少的时候<em>更贵</em>」，等价于 1 − 利差升序百分位，方向别读反。</p>
        </div>

        <!-- 二、拥挤度 -->
        <div class="guide-section">
          <h5 class="gs-title">二、拥挤度（相对估值）</h5>
          <p class="gs-text">
            拥挤度 = (指数PB ÷ 中证全指PB) 在历史中的分位<br>
            分母用全A PB 消掉大盘涨跌，剩下纯粹的指数间比价关系，比「行业自身PE百分位」更灵敏、更适合轮动。
          </p>
          <p class="gs-note">⚠️ 铁律：<b>拥挤度低 ≠ 绝对便宜</b>。大盘整体很贵时，「最不拥挤」的指数也可能并不便宜——它只说明相对其他指数更便宜。</p>
        </div>

        <!-- 三、怎么用 -->
        <div class="guide-section">
          <h5 class="gs-title">三、怎么用</h5>
          <ul class="gs-list">
            <li>总体估值低 → 优先买<strong>拥挤度低</strong>的品种</li>
            <li>总体估值高 → 优先卖<strong>拥挤度高</strong>的品种</li>
            <li>配置建议：宽基打底 + 不拥挤行业做增强，<em>不要单押行业</em></li>
          </ul>
        </div>

        <!-- 四、局限提醒 -->
        <div class="guide-section">
          <h5 class="gs-title">四、局限提醒</h5>
          <ul class="gs-list">
            <li>分位是「相对自身历史」的位置，<b>不是收益预测</b>；低分位不代表马上涨，可能长期更低估。</li>
            <li>通胀系数 0.3、ROE 取近年均值、起点选 2005 等均为<strong>经验设定</strong>，会影响分位绝对值。</li>
            <li>风险溢价（市场情绪）未被量化，是整套体系最「软」的一环。</li>
          </ul>
        </div>

        <!-- 五、多算法对比（加权 / 等权 / 中位） -->
        <div class="guide-section">
          <h5 class="gs-title">五、多算法对比（加权 / 等权 / 中位）</h5>
          <p class="gs-text">
            主表「PB / PE(TTM)」列为<b>市值加权</b>口径（买 ETF 的真实估值：<code>Σ市值 ÷ Σ市值/指标</code>），
            被大市值成分股主导。为看清「成分股整体」的便宜程度，本页额外给出两种算法：
          </p>
          <ul class="gs-list">
            <li><b>等权</b>：成分股该指标<b>算术均值</b>——每只等权，反映指数成分股<b>广度</b>上的便宜程度，不被权重股掩盖。</li>
            <li><b>中位</b>：成分股该指标<b>中位数</b>——剔除极大/极小极值后的<b>中枢</b>，抗单只畸变样本，常与等权接近。</li>
          </ul>
          <p class="gs-text">
            三指标（PB / PE(TTM)纳亏 / PE(TTM)剔亏）各含加权 + 等权 + 中位，共 6 组绝对值；
            每组再算<b>全史分位</b>与<b>近10年分位</b>。纳亏口径含亏损股（PE&lt;0），剔亏口径仅聚 PE&gt;0（分位基准，与中证官方一致）。
          </p>
          <p class="gs-note">
            ⚠️ 口径对照：本页「加权」≈ 买 ETF 的真实估值；「等权 / 中位」与 <b>legulegu 等权 / 中位</b> 口径对齐，可直接跨源比较。
            权重股越集中的指数（如上证50），加权与等权/中位差距越大——差距本身即提示「便宜是被少数大盘股拉低还是普遍现象」。
            全史含 2007/2015 泡沫顶，全史分位通常比近10年分位低 10~30pp，跨窗口对比须同口径。
          </p>
          <p class="gs-note">
            ⚠️ 等权 <b>PE</b> 的固有缺陷（必读）：PE 算术均值对「接近盈亏平衡」的成分股极度敏感——盈利趋近 0 时 PE 趋向 ±∞，
            单只微利股（PE 数千）即可把整列均值拉高数倍；微亏股（PE 为大负数）则反向拉低。
            实测 2026-10-31：中证2000 加权 PE 127.35，<b>等权 却为 -0.36</b>（被微亏股的大负 PE 拖成负值），中位 43.66 才稳健。
            因此 <b>PE 等权列仅供跨源对照，判断贵贱请优先看「中位」或「加权」</b>；PB 等权无此问题（PB 恒为正、分布有界）。
          </p>
          <p class="gs-note">
            ℹ️ <b>历史起点（2026-10-28 补齐至 2005）</b>：上证50、沪深300、上证180/上证380、上证红利、中证500/800/100/1000、深证100、深证红利、创业板50
            共 12 个指数的历史序列已用乐咕乐股（legulegu）月度数据补齐至 <b>2005 年</b>（补到各自数据起点为止），全史分位因此包含 2007 大牛市高估值顶，
            与外部权威（legulegu / 中证参考图）收敛到 2~7pp；科创50、中证2000、中证A500、创业板指等发布较晚，自其数据起点起统计。
            补齐段仅覆盖 <b>PB 三口径与剔亏 PE（加权/中位）</b>——纳亏 PE（legulegu 无此口径）与剔亏等权 PE（其等权做了极值截断，与我们的纯算术均值不可拼接）仍自 2010 年起；
            悬停任一单元格可查看该列的实际起止月份与样本数。
          </p>
        </div>

        <p class="guide-foot">
          文中具体数值为文章发布时点快照，非当前市场状态，应以本页实时数据为准。
        </p>
      </div>
    </NCollapseTransition>
  </div>
</template>

<style scoped>
.guide-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 16px;
  box-shadow: var(--shadow-card);
}

.guide-toggle {
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
.guide-toggle:hover {
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

.guide-body {
  padding: 4px 18px 18px;
  border-top: 1px solid var(--border-default);
  color: var(--text-secondary);
}

.guide-lead {
  font-size: 13px;
  line-height: 1.7;
  margin: 12px 0 4px;
}
.guide-lead b {
  color: var(--color-primary);
}

.guide-section {
  margin-top: 14px;
}
.gs-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 6px;
  font-family: 'Work Sans', sans-serif;
}
.gs-text {
  font-size: 12.5px;
  line-height: 1.7;
  margin: 0;
  color: var(--text-secondary);
}
.gs-text b {
  color: var(--color-primary);
}
.gs-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0 4px;
}
.gs-note {
  font-size: 12px;
  line-height: 1.65;
  margin: 8px 0 0;
  color: var(--text-muted);
}
.gs-note em {
  font-style: normal;
  color: var(--text-secondary);
}
.gs-note b {
  color: var(--color-danger, #dc2626);
}
.gs-list {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--text-secondary);
}
.gs-list li {
  margin-bottom: 4px;
}
.gs-list b {
  color: var(--color-primary);
}
.gs-list em {
  font-style: normal;
  color: var(--text-muted);
}

.guide-foot {
  margin: 16px 0 0;
  padding-top: 12px;
  border-top: 1px dashed var(--border-default);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-muted);
  font-style: italic;
}

@media (max-width: 768px) {
  .guide-body {
    padding: 4px 14px 16px;
  }
}
</style>
