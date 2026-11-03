<script setup lang="ts">
// 同标的跨基金溢价轮动（P4）
// 逻辑：同一底层指数/商品往往有 ETF + LOF 多只，组内溢价差可达数个百分点。
// 卖组内溢价最高的、买最低的，赚价差且不占用新的 QDII 额度。
// 关键约束：组内必须同口径比较（自算 est 优先，覆盖不足退官方并加警示），
// 净值失效（stale）的成员后端已剔除，不参与挑选。
import { ref, computed } from 'vue'
import { NButton, NIcon, NTag, NSpin } from 'naive-ui'
import { RefreshOutline, SwapHorizontalOutline } from '@vicons/ionicons5'
import { api } from '../composables/useApi'
import type { PeerRotationGroup, PeerRotationMeta, PeerRotationMember } from '../types'

const groups = ref<PeerRotationGroup[]>([])
const meta = ref<PeerRotationMeta | null>(null)
const loading = ref(false)
const loaded = ref(false)
const error = ref<string | null>(null)
const expanded = ref(true)

// 只展示「有换仓空间」和「临界」的组，没空间的组折叠成一行计数
const actionable = computed(() => groups.value.filter(g => g.action !== 'none'))
const idle = computed(() => groups.value.filter(g => g.action === 'none'))

async function load(force = false) {
  if (loading.value) return
  loading.value = true
  error.value = null
  try {
    const res = await api.getFundRotationGroups(force)
    groups.value = res.data ?? []
    // 后端 meta 结构与 SectionSourceMeta 不同（轮动组统计），走 unknown 中转避免类型冲突
    meta.value = (res.meta as unknown as PeerRotationMeta) ?? null
    loaded.value = true
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function actionLabel(a: string): string {
  return a === 'switch' ? '可换' : a === 'marginal' ? '临界' : '无空间'
}

function actionType(a: string): 'success' | 'warning' | 'default' {
  return a === 'switch' ? 'success' : a === 'marginal' ? 'warning' : 'default'
}

function premColor(v: number): string {
  return v >= 0 ? 'var(--color-danger)' : 'var(--color-success)'
}

function fmtPrem(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

function memberTip(m: PeerRotationMember): string {
  const parts: string[] = []
  if (m.nav_date) parts.push(`净值日 ${m.nav_date}`)
  if (m.nav_lag_days != null) parts.push(`落后 ${m.nav_lag_days} 个交易日`)
  if (m.volume != null) parts.push(`成交额 ${(m.volume / 1e4).toFixed(0)} 万`)
  if (m.premium_gap != null && Math.abs(m.premium_gap) > 0.5) {
    parts.push(`口径差 ${m.premium_gap > 0 ? '+' : ''}${m.premium_gap}pp`)
  }
  return parts.join('；')
}

defineExpose({ load })
</script>

<template>
  <div class="rot-panel">
    <div class="rot-header">
      <div class="rot-title-wrap">
        <n-icon :component="SwapHorizontalOutline" size="18" class="rot-icon" />
        <h2 class="rot-title">同标的溢价轮动</h2>
        <span class="rot-sub">组内卖高溢价、买低溢价，赚价差且不占新额度</span>
      </div>
      <div class="rot-actions">
        <span v-if="meta?.updateTime" class="rot-meta">{{ meta.updateTime }}</span>
        <n-button v-if="!loaded" size="small" type="primary" :loading="loading" @click="load(false)">
          分析
        </n-button>
        <template v-else>
          <n-button size="small" text @click="expanded = !expanded">
            {{ expanded ? '收起' : '展开' }}
          </n-button>
          <n-button size="small" :loading="loading" @click="load(true)">
            <template #icon><n-icon :component="RefreshOutline" /></template>
            刷新
          </n-button>
        </template>
      </div>
    </div>

    <div v-if="!loaded && !loading" class="rot-hint">
      点击「分析」按同标的把 ETF/LOF 归组，比较组内溢价极差并扣除双边换仓成本
      （{{ meta?.costPct ?? 0.5 }}%），给出换仓候选。首次分析需拉全市场基金，约 10~30 秒。
    </div>

    <div v-if="loading && !loaded" class="rot-loading">
      <n-spin size="small" /> <span>正在归组并计算价差…</span>
    </div>

    <div v-if="error" class="rot-error">{{ error }}</div>

    <template v-if="loaded && expanded">
      <div v-if="meta?.warning" class="rot-warn-bar">{{ meta.warning }}</div>

      <div v-if="actionable.length === 0" class="rot-hint">
        当前没有扣成本后仍为正的换仓空间（阈值 {{ meta?.thresholds?.switch ?? 1.5 }}pp）。
        共归入 {{ meta?.groups ?? groups.length }} 组 / {{ meta?.funds ?? 0 }} 只基金。
      </div>

      <div v-for="g in actionable" :key="g.group" class="rot-group">
        <div class="rot-group-head">
          <span class="rot-group-name">{{ g.group_name }}</span>
          <n-tag :type="actionType(g.action)" size="small" :bordered="false">{{ actionLabel(g.action) }}</n-tag>
          <span class="rot-group-stat">
            {{ g.count }} 只 · 极差 <b>{{ g.spread.toFixed(2) }}pp</b> · 净空间
            <b :style="{ color: g.net_edge > 0 ? 'var(--color-success)' : 'var(--text-muted)' }">
              {{ g.net_edge > 0 ? '+' : '' }}{{ g.net_edge.toFixed(2) }}pp
            </b>
            · {{ g.premium_basis === 'est' ? '自算口径' : '官方口径' }}
          </span>
        </div>

        <div class="rot-pair">
          <div class="rot-leg sell">
            <span class="rot-leg-tag">卖</span>
            <span class="rot-leg-code">{{ g.sell.code }}</span>
            <span class="rot-leg-name" :title="memberTip(g.sell)">{{ g.sell.name }}</span>
            <span class="rot-leg-prem" :style="{ color: premColor(g.sell.premium_pct) }">
              {{ fmtPrem(g.sell.premium_pct) }}
            </span>
          </div>
          <div class="rot-leg buy">
            <span class="rot-leg-tag">买</span>
            <span class="rot-leg-code">{{ g.buy.code }}</span>
            <span class="rot-leg-name" :title="memberTip(g.buy)">{{ g.buy.name }}</span>
            <span class="rot-leg-prem" :style="{ color: premColor(g.buy.premium_pct) }">
              {{ fmtPrem(g.buy.premium_pct) }}
            </span>
          </div>
        </div>

        <div v-if="g.members.length > 2" class="rot-members">
          <span
            v-for="m in g.members"
            :key="m.code"
            class="rot-member"
            :title="memberTip(m)"
            :class="{ hi: m.code === g.sell.code, lo: m.code === g.buy.code }"
          >
            {{ m.code }} {{ fmtPrem(m.premium_pct) }}
          </span>
        </div>

        <div v-for="(w, i) in g.warnings" :key="i" class="rot-warn">⚠ {{ w }}</div>
        <div v-if="g.excluded.length" class="rot-excluded">
          已剔除 {{ g.excluded.length }} 只：{{ g.excluded.map(e => `${e.code}(${e.reason})`).join('、') }}
        </div>
      </div>

      <div v-if="idle.length" class="rot-idle">
        另有 {{ idle.length }} 组价差不覆盖成本：{{ idle.map(g => g.group_name).join('、') }}
      </div>

      <div class="rot-foot">
        <b>怎么读：</b>只看组内<b>相对差</b>。官方口径的溢价 = 价格 ÷ 前一交易日净值 − 1，
        里面含着当日涨跌（科创50 一组今天全在 −4% 附近，是板块跌了，不是全场折价），
        同一指数的成员这部分会互相抵消，所以极差可用、绝对值不可用。
        <template v-if="meta?.staleFilter === false">
          <br /><b>注意：</b>交易日历未就绪，本轮未做净值陈旧度过滤，个别品种的净值锚可能已过期。
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.rot-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.rot-header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-default);
}
.rot-title-wrap { display: flex; align-items: center; gap: 8px; min-width: 0; }
.rot-icon { color: var(--color-primary); }
.rot-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: 'Work Sans', sans-serif;
}
.rot-sub { font-size: 12px; color: var(--text-muted); }
.rot-actions { display: flex; align-items: center; gap: 8px; }
.rot-meta { font-size: 12px; color: var(--text-muted); }
.rot-hint, .rot-loading, .rot-error {
  padding: 14px 18px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.rot-loading { display: flex; align-items: center; gap: 8px; }
.rot-error { color: var(--color-danger); }
.rot-warn-bar {
  margin: 12px 18px 0;
  padding: 8px 12px;
  border-radius: 6px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.3);
  font-size: 12px;
  color: var(--text-secondary);
}
.rot-group {
  padding: 12px 18px;
  border-bottom: 1px dashed var(--border-default);
}
.rot-group:last-of-type { border-bottom: none; }
.rot-group-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.rot-group-name { font-size: 13.5px; font-weight: 700; color: var(--text-primary); }
.rot-group-stat { font-size: 12px; color: var(--text-muted); }
.rot-group-stat b { color: var(--text-primary); }
.rot-pair { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; }
.rot-leg {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12.5px;
  border: 1px solid var(--border-default);
  background: var(--bg-page);
  min-width: 0;
}
.rot-leg.sell { border-left: 3px solid var(--color-danger); }
.rot-leg.buy { border-left: 3px solid var(--color-success); }
.rot-leg-tag { font-weight: 700; color: var(--text-muted); }
.rot-leg-code { font-family: 'JetBrains Mono', monospace; color: var(--text-secondary); }
.rot-leg-name {
  color: var(--text-primary);
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rot-leg-prem { font-family: 'JetBrains Mono', monospace; font-weight: 700; }
.rot-members { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.rot-member {
  font-size: 11.5px;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-muted);
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-page);
  border: 1px solid var(--border-default);
}
.rot-member.hi { color: var(--color-danger); border-color: rgba(239, 68, 68, 0.35); }
.rot-member.lo { color: var(--color-success); border-color: rgba(16, 185, 129, 0.35); }
.rot-warn { margin-top: 6px; font-size: 11.5px; color: var(--color-warning); line-height: 1.6; }
.rot-excluded { margin-top: 6px; font-size: 11.5px; color: var(--text-muted); line-height: 1.6; }
.rot-idle {
  padding: 10px 18px 14px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
}
.rot-foot {
  padding: 10px 18px 14px;
  font-size: 11.5px;
  line-height: 1.75;
  color: var(--text-muted);
  border-top: 1px solid var(--border-default);
  background: var(--bg-page);
}
.rot-foot b { color: var(--text-secondary); }
</style>
