<script setup lang="ts">
// 登录/注册页背景装饰：细网格 + K 线 + 走势线 + 数据标签。
// 全部使用主色调（var(--color-primary)）低透明度渲染，纯装饰、不抢视觉。
const gridLines = Array.from({ length: 19 }, (_, i) => (i + 1) * 5)

const candles = [
  { x: 16, open: 172, close: 150, high: 182, low: 138 },
  { x: 54, open: 140, close: 166, high: 174, low: 130 },
  { x: 92, open: 170, close: 126, high: 178, low: 118 },
  { x: 130, open: 128, close: 154, high: 160, low: 116 },
  { x: 168, open: 152, close: 174, high: 184, low: 144 },
  { x: 206, open: 172, close: 140, high: 180, low: 132 },
  { x: 244, open: 142, close: 168, high: 174, low: 136 },
  { x: 282, open: 166, close: 180, high: 188, low: 156 },
  { x: 320, open: 178, close: 158, high: 186, low: 148 },
]
</script>

<template>
  <div class="auth-bg" aria-hidden="true">
    <!-- 细网格（中心可见、四周渐隐） -->
    <svg class="auth-layer auth-grid" viewBox="0 0 100 100" preserveAspectRatio="none">
      <g stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke" opacity="0.05">
        <line v-for="x in gridLines" :key="'v' + x" :x1="x" :x2="x" y1="0" y2="100" />
        <line v-for="y in gridLines" :key="'h' + y" x1="0" x2="100" :y1="y" :y2="y" />
      </g>
    </svg>

    <!-- 左下角 K 线 -->
    <svg class="auth-layer auth-candles" viewBox="0 0 340 240">
      <g v-for="c in candles" :key="c.x" fill="currentColor">
        <line
          :x1="c.x + 8"
          :x2="c.x + 8"
          :y1="c.high"
          :y2="c.low"
          stroke="currentColor"
          stroke-width="2"
        />
        <rect
          :x="c.x"
          :y="Math.min(c.open, c.close)"
          width="16"
          :height="Math.abs(c.open - c.close)"
          rx="1"
        />
      </g>
    </svg>

    <!-- 右上角走势线 -->
    <svg class="auth-layer auth-trend" viewBox="0 0 360 200">
      <path
        class="auth-trend-area"
        d="M0 168 C 45 150, 70 158, 100 128 S 170 92, 200 100 S 265 52, 300 44 S 345 30, 360 24 L 360 200 L 0 200 Z"
      />
      <path
        class="auth-trend-line"
        d="M0 168 C 45 150, 70 158, 100 128 S 170 92, 200 100 S 265 52, 300 44 S 345 30, 360 24"
        fill="none"
      />
      <circle cx="360" cy="24" r="4" />
    </svg>

    <!-- 浮动数据标签 -->
    <div class="auth-layer auth-chip auth-chip-1">
      <span>沪深300</span><span class="auth-chip-val">3,892.15</span><span class="auth-chip-delta">+0.42%</span>
    </div>
    <div class="auth-layer auth-chip auth-chip-2">
      <span>ERP</span><span class="auth-chip-val">4.32%</span>
    </div>
    <div class="auth-layer auth-chip auth-chip-3">
      <span>SHIBOR 7D</span><span class="auth-chip-val">1.80%</span>
    </div>
  </div>
</template>

<style scoped>
.auth-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  color: var(--color-primary);
}

.auth-layer {
  position: absolute;
}

/* 细网格：中心可见、向四周渐隐 */
.auth-grid {
  inset: 0;
  width: 100%;
  height: 100%;
  mask-image: radial-gradient(ellipse 80% 70% at 50% 45%, black 35%, transparent 80%);
  -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 45%, black 35%, transparent 80%);
}

/* K 线（左下角） */
.auth-candles {
  left: -12px;
  bottom: -28px;
  width: 340px;
  opacity: 0.1;
  transform: rotate(-4deg);
}

/* 走势线（右上角） */
.auth-trend {
  top: -18px;
  right: -14px;
  width: 360px;
  opacity: 0.14;
}
.auth-trend-area {
  fill: currentColor;
  opacity: 0.35;
}
.auth-trend-line {
  stroke: currentColor;
  stroke-width: 2;
}
.auth-trend circle {
  fill: currentColor;
}

/* 浮动数据标签 */
.auth-chip {
  display: flex;
  align-items: baseline;
  gap: 7px;
  padding: 7px 12px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: currentColor;
  opacity: 0.4;
  border: 1px solid currentColor;
  border-radius: 7px;
  background: color-mix(in srgb, var(--color-primary) 5%, transparent);
}
.auth-chip::before {
  content: '';
  align-self: center;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}
.auth-chip-val {
  font-weight: 700;
}
.auth-chip-delta {
  font-weight: 600;
  opacity: 0.75;
}

.auth-chip-1 { top: 22%; left: 7%; }
.auth-chip-2 { top: 12%; right: 11%; }
.auth-chip-3 { bottom: 18%; right: 12%; }

/* 小屏：隐藏标签、缩小图表，避免干扰 */
@media (max-width: 640px) {
  .auth-chip { display: none; }
  .auth-candles { width: 240px; opacity: 0.08; }
  .auth-trend { width: 260px; opacity: 0.1; }
}
</style>
