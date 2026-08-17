/**
 * 松果投资体系 · 图表初始化脚本
 * 扫描页面中带 data-option 的 .chart 容器，用 ECharts 渲染
 * 按需引入（tree-shaking），仅加载折线图/柱状图/面积图所需模块
 */
import * as echarts from 'echarts/core';
import { LineChart, BarChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  TitleComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  TitleComponent,
  CanvasRenderer,
]);

const NAVY = '#1e2761';
const GOLD = '#c8a24b';
const GREEN = '#1a9e5c';
const RED = '#d64545';
const GRAY = '#9ca3af';

export const theme = { NAVY, GOLD, GREEN, RED, GRAY };

function initAllCharts() {
  document.querySelectorAll<HTMLElement>('.chart[data-option]').forEach((el) => {
    const raw = el.dataset.option || '';
    if (!raw) return;
    let option: Record<string, unknown>;
    try {
      option = JSON.parse(raw);
    } catch {
      console.warn('[charts] 图表数据解析失败', el.id);
      return;
    }
    const chart = echarts.init(el);
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAllCharts);
} else {
  initAllCharts();
}
