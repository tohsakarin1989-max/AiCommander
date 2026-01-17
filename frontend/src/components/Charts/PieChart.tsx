/**
 * 饼图/环形图组件
 * 展示案件类型分布等比例数据
 */
import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'

export interface PieDataItem {
  name: string
  value: number
  color?: string
}

export interface PieChartProps {
  /** 数据 */
  data: PieDataItem[]
  /** 高度 */
  height?: number | string
  /** 主题 */
  theme?: 'light' | 'dark'
  /** 标题 */
  title?: string
  /** 是否为环形图 */
  donut?: boolean
  /** 是否显示图例 */
  showLegend?: boolean
  /** 是否显示标签 */
  showLabel?: boolean
  /** 颜色列表 */
  colors?: string[]
}

const PieChart: React.FC<PieChartProps> = ({
  data,
  height = 300,
  theme = 'light',
  title,
  donut = true,
  showLegend = true,
  showLabel = true,
  colors: customColors,
}) => {
  const defaultColors =
    theme === 'dark'
      ? ['#00d4ff', '#ff6b6b', '#ffd93d', '#6bcb77', '#9b59b6', '#3498db', '#e74c3c']
      : ['#1890ff', '#ff4d4f', '#faad14', '#52c41a', '#722ed1', '#13c2c2', '#eb2f96']

  const colors = customColors || defaultColors
  const textColor = theme === 'dark' ? '#b0b0b0' : '#666'

  const option: EChartsOption = useMemo(
    () => ({
      backgroundColor: 'transparent',
      title: title
        ? {
            text: title,
            left: 'center',
            textStyle: {
              color: textColor,
              fontSize: 14,
              fontWeight: 'normal',
            },
          }
        : undefined,
      tooltip: {
        trigger: 'item',
        backgroundColor: theme === 'dark' ? 'rgba(30,30,50,0.95)' : 'rgba(255,255,255,0.95)',
        borderColor: theme === 'dark' ? '#444' : '#ddd',
        textStyle: { color: textColor },
        formatter: (params: any) => {
          return `${params.name}<br/>数量: <strong>${params.value}</strong> (${params.percent}%)`
        },
      },
      legend: showLegend
        ? {
            orient: 'vertical',
            right: 10,
            top: 'center',
            textStyle: { color: textColor, fontSize: 12 },
            itemWidth: 10,
            itemHeight: 10,
          }
        : undefined,
      series: [
        {
          type: 'pie',
          radius: donut ? ['45%', '70%'] : '70%',
          center: showLegend ? ['40%', '50%'] : ['50%', '50%'],
          avoidLabelOverlap: true,
          itemStyle: {
            borderRadius: donut ? 4 : 0,
            borderColor: theme === 'dark' ? '#1a1a2e' : '#fff',
            borderWidth: 2,
          },
          label: showLabel
            ? {
                show: true,
                formatter: '{b}: {c}',
                color: textColor,
                fontSize: 11,
              }
            : { show: false },
          emphasis: {
            label: {
              show: true,
              fontSize: 14,
              fontWeight: 'bold',
            },
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: 'rgba(0, 0, 0, 0.3)',
            },
          },
          labelLine: {
            show: showLabel,
            lineStyle: { color: textColor },
          },
          data: data.map((item, index) => ({
            ...item,
            itemStyle: {
              color: item.color || colors[index % colors.length],
            },
          })),
        },
      ],
    }),
    [data, title, donut, showLegend, showLabel, colors, textColor, theme]
  )

  return <ReactECharts option={option} style={{ height, width: '100%' }} />
}

export default PieChart
