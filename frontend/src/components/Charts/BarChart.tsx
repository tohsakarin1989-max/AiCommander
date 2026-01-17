/**
 * 柱状图组件
 * 展示区域分布、热点排名等数据
 */
import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'

export interface BarDataItem {
  name: string
  value: number
  color?: string
}

export interface BarChartProps {
  /** 数据 */
  data: BarDataItem[]
  /** 高度 */
  height?: number | string
  /** 主题 */
  theme?: 'light' | 'dark'
  /** 标题 */
  title?: string
  /** 是否水平显示 */
  horizontal?: boolean
  /** 是否显示数值标签 */
  showLabel?: boolean
  /** 是否使用渐变色 */
  gradient?: boolean
  /** 基础颜色 */
  color?: string
  /** 最大显示数量 */
  maxItems?: number
}

const BarChart: React.FC<BarChartProps> = ({
  data,
  height = 300,
  theme = 'light',
  title,
  horizontal = false,
  showLabel = true,
  gradient = true,
  color,
  maxItems = 10,
}) => {
  const displayData = useMemo(() => {
    const sorted = [...data].sort((a, b) => b.value - a.value)
    return sorted.slice(0, maxItems)
  }, [data, maxItems])

  const colors = useMemo(
    () => ({
      text: theme === 'dark' ? '#b0b0b0' : '#666',
      grid: theme === 'dark' ? '#2d2d4a' : '#e8e8e8',
      primary: color || (theme === 'dark' ? '#00d4ff' : '#1890ff'),
      secondary: theme === 'dark' ? '#6366f1' : '#722ed1',
    }),
    [theme, color]
  )

  const option: EChartsOption = useMemo(() => {
    const categories = displayData.map((d) => d.name)
    const values = displayData.map((d) => d.value)

    const barStyle = gradient
      ? {
          color: {
            type: 'linear',
            x: horizontal ? 0 : 0,
            y: horizontal ? 0 : 1,
            x2: horizontal ? 1 : 0,
            y2: horizontal ? 0 : 0,
            colorStops: [
              { offset: 0, color: colors.primary },
              { offset: 1, color: colors.secondary },
            ],
          },
          borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
        }
      : {
          color: colors.primary,
          borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
        }

    return {
      backgroundColor: 'transparent',
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
        axisPointer: { type: 'shadow' },
        backgroundColor: theme === 'dark' ? 'rgba(30,30,50,0.95)' : 'rgba(255,255,255,0.95)',
        borderColor: theme === 'dark' ? '#444' : '#ddd',
        textStyle: { color: colors.text },
      },
      grid: {
        left: horizontal ? 100 : 40,
        right: 20,
        top: title ? 50 : 20,
        bottom: horizontal ? 30 : 60,
        containLabel: !horizontal,
      },
      xAxis: horizontal
        ? {
            type: 'value',
            axisLine: { show: false },
            axisLabel: { color: colors.text, fontSize: 10 },
            splitLine: { lineStyle: { color: colors.grid, type: 'dashed' } },
          }
        : {
            type: 'category',
            data: categories,
            axisLine: { lineStyle: { color: colors.grid } },
            axisLabel: {
              color: colors.text,
              fontSize: 10,
              rotate: categories.length > 6 ? 45 : 0,
              interval: 0,
            },
            axisTick: { show: false },
          },
      yAxis: horizontal
        ? {
            type: 'category',
            data: categories,
            axisLine: { show: false },
            axisLabel: {
              color: colors.text,
              fontSize: 11,
              width: 80,
              overflow: 'truncate',
            },
            axisTick: { show: false },
          }
        : {
            type: 'value',
            axisLine: { show: false },
            axisLabel: { color: colors.text, fontSize: 10 },
            splitLine: { lineStyle: { color: colors.grid, type: 'dashed' } },
          },
      series: [
        {
          type: 'bar',
          data: values.map((v, i) => ({
            value: v,
            itemStyle: displayData[i].color ? { color: displayData[i].color } : barStyle,
          })),
          barMaxWidth: 40,
          label: showLabel
            ? {
                show: true,
                position: horizontal ? 'right' : 'top',
                color: colors.text,
                fontSize: 10,
              }
            : { show: false },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowColor: 'rgba(0,0,0,0.2)',
            },
          },
        },
      ],
    }
  }, [displayData, colors, title, horizontal, showLabel, gradient, theme])

  return <ReactECharts option={option} style={{ height, width: '100%' }} />
}

export default BarChart
