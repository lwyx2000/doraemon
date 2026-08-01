# 前端优化清单 (Frontend TODO)

> 生成时间: 2026-07-23
> 范围: `d:\workspace\doraemon\frontend`

---

## 一、组件化与样式复用

### 1.1 原生 `<table>` 未转为 NDataTable（违反项目约束）
项目约定「业务页面应使用 NDataTable 而非原生 `<table>`」，以下 7 个页面仍在使用原生表格：

| 页面 | 文件 | 行号 | 表格类名 |
|------|------|------|----------|
| IndexAnalysis | [IndexAnalysis.vue](file:///d:/workspace/doraemon/frontend/src/pages/IndexAnalysis.vue) | 79 | `.data-table` |
| AlertCenter | [AlertCenter.vue](file:///d:/workspace/doraemon/frontend/src/pages/AlertCenter.vue) | 267 | `.history-table` |
| ClosedFunds | [ClosedFunds.vue](file:///d:/workspace/doraemon/frontend/src/pages/ClosedFunds.vue) | 81 | `.fund-table` |
| Reits | [Reits.vue](file:///d:/workspace/doraemon/frontend/src/pages/Reits.vue) | 31 | `.reit-table` |
| LofFunds | [LofFunds.vue](file:///d:/workspace/doraemon/frontend/src/pages/LofFunds.vue) | 77 | `.fund-table` |
| ConvertibleBonds | [ConvertibleBonds.vue](file:///d:/workspace/doraemon/frontend/src/pages/ConvertibleBonds.vue) | 128 | `.cb-table` |
| PortfolioWatchlist | [PortfolioWatchlist.vue](file:///d:/workspace/doraemon/frontend/src/pages/PortfolioWatchlist.vue) | 120 | `.wl-table` |

> 注：Dashboard 与 AiDecisionHub 已完成 NDataTable 转换，可作为参考。

### 1.2 重复 CSS 可抽取为共享组件
以下样式在多个页面重复定义，建议抽取为共享组件或移入全局 `style.css`：

**① 标签栏 TabBar（4 个页面重复）**
- `.tab-bar` / `.tab-btn` / `.tab-btn.active`
- 涉及：[LofFunds.vue:202](file:///d:/workspace/doraemon/frontend/src/pages/LofFunds.vue#L202)、[PortfolioWatchlist.vue:210](file:///d:/workspace/doraemon/frontend/src/pages/PortfolioWatchlist.vue#L210)、[AiDecisionHub.vue:377](file:///d:/workspace/doraemon/frontend/src/pages/AiDecisionHub.vue#L377)、[StrategyCenter.vue:430](file:///d:/workspace/doraemon/frontend/src/pages/StrategyCenter.vue#L430)
- 建议：抽取 `TabBar.vue` 组件，接收 `tabs` 数组和 `v-model`

**② 百分位指示器 PercentileIndicator（3 个页面重复，命名还不一致）**
- IndexAnalysis/LofFunds: `.perc-cell` / `.perc-track` / `.perc-needle` / `.perc-label`
- Dashboard: `.percentile-cell` / `.percentile-track` / `.percentile-needle` / `.percentile-label`
- 建议：抽取 `PercentileIndicator.vue` 组件，接收 `value` (0-100)，统一命名

**③ 分类标签 CategoryTag（2 个页面重复，命名不一致）**
- IndexAnalysis: `.cat-tag` + `.cat-tag.undervalued/.overvalued/.opportunity/.normal`
- Dashboard: `.category-tag` + 内联 style
- 建议：抽取 `CategoryTag.vue` 组件，接收 `type` prop

**④ 筛选栏 FilterBar（2 个页面重复）**
- IndexAnalysis: `.filter-bar` / `.filter-label` / `.btn-group` / `.btn-opt` / `.filter-divider`
- ConvertibleBonds: `.filter-label`
- 建议：抽取 `FilterBar.vue` 或将样式移入全局 `style.css`

**⑤ 热度条 HeatTrack（Dashboard 独有但与百分位概念相似）**
- Dashboard: `.heat-track` / `.heat-needle` / `.heat-gradient` / `.heat-bar`
- 可与 PercentileIndicator 合并为通用 `ProgressBar.vue`

**⑥ 图标按钮 IconButton**
- IndexAnalysis: `.icon-btn`
- 建议抽取 `IconButton.vue`，封装 `NButton text` + `NIcon`

---

## 二、暗色模式（Dark Mode）

### 2.1 暗色模式切换无实际效果
[AppHeader.vue](file:///d:/workspace/doraemon/frontend/src/layouts/AppHeader.vue#L26) 的 `toggleDarkMode()` 仅切换 `<html>` 上的 `.dark` class，但：

- [AppLayout.vue](file:///d:/workspace/doraemon/frontend/src/layouts/AppLayout.vue) 的 `NConfigProvider` 只配置了 `themeOverrides`（亮色），**未传入 `:theme="darkTheme"`**
- 全局 [style.css](file:///d:/workspace/doraemon/frontend/src/style.css) 及所有页面均使用硬编码亮色值（`#ffffff`、`#f5f7fa`、`#181c21` 等），无 CSS 变量
- 切换后仅弹 `message.info` 提示，页面外观不变

**修复方案**：
1. AppLayout 引入 `darkTheme`，通过 `computed` 动态切换 `:theme`
2. 将硬编码颜色替换为 CSS 变量（如 `var(--bg-color)`、`var(--text-color)`）
3. 在 `themeOverrides` 中同时配置亮/暗两套

---

## 三、占位按钮未实现功能

以下按钮点击后仅 `message.info()` 占位，无实际逻辑：

| 页面 | 按钮 | 当前行为 |
|------|------|----------|
| [AppHeader.vue:53](file:///d:/workspace/doraemon/frontend/src/layouts/AppHeader.vue#L53) | 定时任务 | `message.info` |
| [AppHeader.vue:56](file:///d:/workspace/doraemon/frontend/src/layouts/AppHeader.vue#L56) | 刷新数据 | `message.info` |
| [AppHeader.vue:64](file:///d:/workspace/doraemon/frontend/src/layouts/AppHeader.vue#L64) | 设置 | `message.info` |
| [Dashboard.vue:85](file:///d:/workspace/doraemon/frontend/src/pages/Dashboard.vue#L85) | 刷新 | `message.info` |
| [LofFunds.vue:46](file:///d:/workspace/doraemon/frontend/src/pages/LofFunds.vue#L46) | 设置 | `message.info` |
| [LofFunds.vue:47](file:///d:/workspace/doraemon/frontend/src/pages/LofFunds.vue#L47) | 扫描 | `message.info` |
| [Reits.vue:17](file:///d:/workspace/doraemon/frontend/src/pages/Reits.vue#L17) | 刷新 | `message.info` |
| [ClosedFunds.vue:29](file:///d:/workspace/doraemon/frontend/src/pages/ClosedFunds.vue#L29) | 导出 | `message.info` |
| [PortfolioWatchlist.vue:46](file:///d:/workspace/doraemon/frontend/src/pages/PortfolioWatchlist.vue#L46) | 导出 | `message.info` |
| [IndexAnalysis.vue:38](file:///d:/workspace/doraemon/frontend/src/pages/IndexAnalysis.vue#L38) | 导出CSV | `message.info` |
| [IndexAnalysis.vue:39](file:///d:/workspace/doraemon/frontend/src/pages/IndexAnalysis.vue#L39) | 自定义指数 | `message.info` |
| [IndexAnalysis.vue:132](file:///d:/workspace/doraemon/frontend/src/pages/IndexAnalysis.vue#L132) | 放大 | `message.info` |
| [IndexAnalysis.vue:135](file:///d:/workspace/doraemon/frontend/src/pages/IndexAnalysis.vue#L135) | 全屏 | `message.info` |

---

## 四、PRD 功能缺口

对照 [readme.md](file:///d:/workspace/doraemon/doc/readme.md) 需求文档，以下功能未实现或部分实现：

### 4.1 AI 报告 Stream 流式输出（PRD 4.3）— 未实现
> PRD 原文：「前端'页面六'展示时需支持 Stream 流式字符输出（打字机效果），避免页面卡死」

- [AiDecisionHub.vue:94](file:///d:/workspace/doraemon/frontend/src/pages/AiDecisionHub.vue#L94) 的 `generateReport()` 使用 `setTimeout` 模拟，无真实流式输出
- 需对接后端 SSE / fetch streaming，前端逐字渲染

### 4.2 QDII 净值修正（PRD 页面二）— 未实现
> PRD 原文：「引入标的海外指数期货的盘中涨跌幅，对前一日官方净值进行实时修正」

- LofFunds 页面无海外指数期货数据展示，无净值修正逻辑

### 4.3 可转债条款触发进度（PRD 页面三）— 未实现
> PRD 原文：「强赎触发进度（如 11/15 天）、回售触发进度（如 20/30 天）、下修触发进度」

- ConvertibleBonds 页面无触发进度计数器组件

### 4.4 正股风控指标（PRD 页面三）— 未实现
> PRD 原文：「Altman Z-Score、大股东质押率、是否含 *ST 风险」

- ConvertibleBonds 页面无正股财务安全度指标

### 4.5 IOPV 延迟处理（PRD 4.1）— 未实现
> PRD 原文：「系统后台需根据持仓成分股盘中 Tick 级别走势自主模拟高频估算」

- 无高频估算逻辑，无与官方 IOPV 比对校准

### 4.6 停牌/特殊状态过滤（PRD 4.2）— 未实现
> PRD 原文：「系统需自动标记'暂停交易'」

- 无停牌标记，无申购暂停过滤

---

## 五、TypeScript 与代码质量

### 5.1 NInput 接收 Number 类型（类型校验警告）
[AiDecisionHub.vue:282](file:///d:/workspace/doraemon/frontend/src/pages/AiDecisionHub.vue#L282)：
```vue
<n-input v-model:value="aiConfig.temperature" placeholder="0.3" size="small" />
```
`aiConfig.temperature` 为 `number`（0.3），但 `NInput` 的 `value` 期望 `string`，控制台报 Vue 警告。

**修复**：改用 `NInputNumber`，或 `:value="String(aiConfig.temperature)"` + `@update:value` 转换。

### 5.2 全页面使用 Mock 数据，无真实 API 对接
- 所有页面从 [useMockData.ts](file:///d:/workspace/doraemon/frontend/src/composables/useMockData.ts) 导入静态数据
- [useApi.ts](file:///d:/workspace/doraemon/frontend/src/composables/useApi.ts) 已封装 `useAsyncData` + `api`，但无页面调用
- [api.ts](file:///d:/workspace/doraemon/frontend/src/utils/api.ts) 有 HTTP 封装但未使用

### 5.3 无加载/错误状态
- `useAsyncData` 返回 `loading` / `error`，但页面均未消费
- 无骨架屏（Skeleton）、无错误重试 UI、无空数据占位

---

## 六、响应式与可访问性

### 6.1 无响应式布局
- [AppLayout.vue:91](file:///d:/workspace/doraemon/frontend/src/layouts/AppLayout.vue#L91) 固定 `margin-left: 240px`（侧边栏宽度）
- 所有 `stat-grid` 使用固定列数（`repeat(4, 1fr)`），小屏会挤压
- 表格列使用固定 `width`，无横向滚动策略
- 无 `@media` 媒体查询

### 6.2 可访问性缺失
- 图标按钮（如 [IndexAnalysis.vue:132](file:///d:/workspace/doraemon/frontend/src/pages/IndexAnalysis.vue#L132) 的 `.icon-btn`）无 `aria-label`
- 原生 `<table>` 行无键盘导航支持（`tabindex`、`@keydown.enter`）
- 涨跌仅用颜色区分（红/绿），无文字或图标辅助标识，色觉障碍用户不友好
- 自定义 `.tab-btn` 非语义化，应考虑使用 `NTabs`

---

## 七、其他

### 7.1 硬编码日期
- [IndexAnalysis.vue:77](file:///d:/workspace/doraemon/frontend/src/pages/IndexAnalysis.vue#L77) meta 写死 `2024-05-24 15:00:00`
- [Dashboard.vue:141](file:///d:/workspace/doraemon/frontend/src/pages/Dashboard.vue#L141) meta 写死 `2026-07-22 15:00:00`
- 应来自数据源的 `updatedAt` 字段

### 7.2 图表为静态 SVG
- [IndexAnalysis.vue:158](file:///d:/workspace/doraemon/frontend/src/pages/IndexAnalysis.vue#L158) 的 PE 估值带图为写死路径的 SVG，无数据绑定
- 建议引入图表库（如 ECharts / Chart.js）实现真实数据可视化

### 7.3 全局滚动条样式可优化
- [style.css:29](file:///d:/workspace/doraemon/frontend/src/style.css#L29) 滚动条宽度仅 4px，在宽列表中难以拖拽

---

## 优先级建议

| 优先级 | 事项 | 理由 |
|--------|------|------|
| P0 | 7 个原生 table 转 NDataTable | 违反项目硬约束，且影响暗色模式适配 |
| P0 | 暗色模式修复 | 已有切换入口但无效果，用户体验割裂 |
| P1 | 抽取 TabBar / PercentileIndicator / CategoryTag 组件 | 4+2+2 个页面重复，收益大 |
| P1 | AiDecisionHub temperature 类型修复 | 控制台持续报错 |
| P1 | AI Stream 流式输出 | PRD 明确要求，核心功能 |
| P2 | 占位按钮实现真实功能 | 涉及 13 处 stub |
| P2 | 可转债条款进度 / 正股风控 | PRD 核心指标缺失 |
| P2 | 真实 API 对接 + 加载/错误态 | 当前纯 Mock |
| P3 | 响应式布局 | 当前仅适配桌面端 |
| P3 | 可访问性（aria-label / 键盘导航） | 合规性要求 |
| P3 | 图表库引入 | 当前为静态 SVG |
