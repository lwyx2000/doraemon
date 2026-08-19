// ============================================================
// ECharts registration with tree-shaking
// Only register the components we actually use to keep bundle small.
// ============================================================
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart, LineChart, CandlestickChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  DatasetComponent,
  DataZoomComponent,
  ToolboxComponent,
} from 'echarts/components'

let registered = false

export function registerECharts() {
  if (registered) return
  use([
    CanvasRenderer,
    PieChart,
    BarChart,
    LineChart,
    CandlestickChart,
    TitleComponent,
    TooltipComponent,
    LegendComponent,
    GridComponent,
    DatasetComponent,
    DataZoomComponent,
    ToolboxComponent,
  ])
  registered = true
}

registerECharts()

export { default as VChart } from 'vue-echarts'
