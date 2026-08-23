import { useEffect, useRef } from 'react';
// 按需注册：全量 `import * as echarts` 会把整包（约 1MB）打进产物
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import {
  AxisPointerComponent,
  GridComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { ECharts } from 'echarts/core';
import type { KlineItem } from '../api/types';
import { movingAverage } from '../utils/format';

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  AxisPointerComponent,
  MarkPointComponent,
  CanvasRenderer,
]);

const UP = '#16a34a'; // 涨 = 绿（以设计图为准）
const DOWN = '#dc2626'; // 跌 = 红
const BLUE = '#2563eb';
const MA20_COLOR = '#d97706';
const MA60_COLOR = '#6b7280';

interface Props {
  data: KlineItem[];
}

/** 收盘价面积图 + MA20/MA60 均线 + 底部成交量柱（红跌绿涨） */
export default function KlineChart({ data }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;

    const dates = data.map((d) => d.date);
    const closes = data.map((d) => d.close);
    const ma20 = movingAverage(closes, 20);
    const ma60 = movingAverage(closes, 60);
    const volumes = data.map((d, i) => ({
      value: d.volume,
      itemStyle: {
        color: i > 0 && d.close < data[i - 1].close ? DOWN : UP,
      },
    }));

    chart.setOption({
      animation: false,
      grid: [
        { left: 60, right: 60, top: 20, height: '58%' },
        { left: 60, right: 60, top: '76%', height: '16%' },
      ],
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        valueFormatter: (v: unknown) =>
          typeof v === 'number' ? v.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : String(v),
      },
      xAxis: [
        {
          type: 'category',
          data: dates,
          boundaryGap: false,
          axisLine: { lineStyle: { color: '#d1d5db' } },
          axisLabel: { color: '#6b7280' },
        },
        {
          type: 'category',
          gridIndex: 1,
          data: dates,
          boundaryGap: false,
          axisLabel: { show: false },
          axisLine: { lineStyle: { color: '#d1d5db' } },
          axisTick: { show: false },
        },
      ],
      yAxis: [
        {
          scale: true,
          splitLine: { lineStyle: { color: '#f3f4f6' } },
          axisLabel: {
            color: '#6b7280',
            formatter: (v: number) => v.toLocaleString('zh-CN'),
          },
        },
        {
          gridIndex: 1,
          scale: true,
          splitLine: { show: false },
          axisLabel: { show: false },
        },
      ],
      series: [
        {
          name: '收盘价',
          type: 'line',
          data: closes,
          showSymbol: false,
          lineStyle: { color: BLUE, width: 2 },
          areaStyle: {
            // 用声明式渐变，免得为 graphic.LinearGradient 再引一块 echarts
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(37,99,235,0.35)' },
                { offset: 1, color: 'rgba(37,99,235,0.03)' },
              ],
            },
          },
          markPoint: {
            symbol: 'rect',
            symbolSize: [64, 22],
            label: {
              color: '#fff',
              backgroundColor: BLUE,
              borderRadius: 3,
              padding: [3, 6],
              formatter: (p: { value: unknown }) =>
                Number(p.value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }),
            },
            data: [{ type: 'max', valueDim: 'y' }],
            silent: true,
          },
        },
        {
          name: 'MA20',
          type: 'line',
          data: ma20,
          showSymbol: false,
          lineStyle: { color: MA20_COLOR, width: 1.5 },
        },
        {
          name: 'MA60',
          type: 'line',
          data: ma60,
          showSymbol: false,
          lineStyle: { color: MA60_COLOR, width: 1.5 },
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
        },
      ],
    });

    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [data]);

  return <div ref={ref} className="kline-chart" />;
}
