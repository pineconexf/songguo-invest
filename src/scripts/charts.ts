/**
 * 松果投资实验室 · 图表初始化脚本
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

const NAVY = '#5c3a21';
const GOLD = '#d9a441';
const GREEN = '#4a7c59';
const RED = '#b3543e';
const GRAY = '#9a8c7a';

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
