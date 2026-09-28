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
const SECTION_COUNT = 6

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
