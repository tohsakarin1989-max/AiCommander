/**
 * 趋势图组件
 * 展示案件数量随时间的变化趋势
 */
import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'

export interface TrendDataPoint {
  date: string
  count: number
  label?: string
}

export interface TrendChartProps {
  /** 趋势数据 */
  data: TrendDataPoint[]
  /** 高度 */
  height?: number | string
  /** 主题 */
  theme?: 'light' | 'dark'
  /** 标题 */
  title?: string
  /** 是否显示面积 */
  showArea?: boolean
  /** 线条颜色 */
  color?: string
  /** 是否平滑 */
  smooth?: boolean
}

const TrendChart: React.FC<TrendChartProps> = ({
  data,
  height = 300,
  theme = 'light',
  title,
  showArea = true,
  color,
  smooth = true,
}) => {
  const colors = useMemo(
    () => ({
      bg: theme === 'dark' ? 'transparent' : 'transparent',
      text: theme === 'dark' ? '#b0b0b0' : '#666',
      line: color || (theme === 'dark' ? '#00d4ff' : '#1890ff'),
      grid: theme === 'dark' ? '#2d2d4a' : '#e8e8e8',
    }),
    [theme, color]
  )

  const option: EChartsOption = useMemo(
    () => ({
      backgroundColor: colors.bg,
      title: title
        ? {
            text: title,
            left: 'center',
            textStyle: {
              color: colors.text,
              fontSize: 14,
              fontWeight: 'normal',
            },
          }
        : undefined,
      tooltip: {
        trigger: 'axis',
        backgroundColor: theme === 'dark' ? 'rgba(30,30,50,0.95)' : 'rgba(255,255,255,0.95)',
        borderColor: theme === 'dark' ? '#444' : '#ddd',
        textStyle: { color: colors.text },
        formatter: (params: any) => {
          const p = params[0]
          return `${p.axisValue}<br/>案件数: <strong>${p.value}</strong>`
        },
      },
      grid: {
        left: 50,
        right: 20,
        top: title ? 50 : 20,
        bottom: 30,
      },
      xAxis: {
        type: 'category',
        data: data.map((d) => d.label || d.date),
        axisLine: { lineStyle: { color: colors.grid } },
        axisLabel: {
          color: colors.text,
          fontSize: 10,
          rotate: data.length > 10 ? 45 : 0,
        },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: { color: colors.text, fontSize: 10 },
        splitLine: { lineStyle: { color: colors.grid, type: 'dashed' } },
      },
      series: [
        {
          type: 'line',
          data: data.map((d) => d.count),
          smooth,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: { color: colors.line, width: 2 },
          itemStyle: { color: colors.line },
          areaStyle: showArea
            ? {
                color: {
                  type: 'linear',
                  x: 0,
                  y: 0,
                  x2: 0,
                  y2: 1,
                  colorStops: [
                    { offset: 0, color: colors.line + '40' },
                    { offset: 1, color: colors.line + '05' },
                  ],
                },
              }
            : undefined,
        },
      ],
    }),
    [data, colors, title, showArea, smooth, theme]
  )

  return <ReactECharts option={option} style={{ height, width: '100%' }} />
}

export default TrendChart
