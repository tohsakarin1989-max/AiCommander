/**
 * 散点地图组件
 * 基于 ECharts 的简化版地图，不依赖地图 JSON
 * 适用于快速展示案件位置分布
 */
import React, { useMemo, useCallback } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'

export interface MapPoint {
  id: number
  name: string
  latitude: number
  longitude: number
  value?: number
  type?: string
  time?: string
  status?: string
  extra?: Record<string, unknown>
}

export interface ScatterMapProps {
  /** 数据点 */
  points: MapPoint[]
  /** 高度 */
  height?: number | string
  /** 主题 */
  theme?: 'light' | 'dark'
  /** 是否显示热力效果 */
  showHeatEffect?: boolean
  /** 是否显示轨迹 */
  showTrajectory?: boolean
  /** 选中的点 ID */
  selectedId?: number
  /** 点击回调 */
  onPointClick?: (point: MapPoint) => void
  /** 标题 */
  title?: string
  /** 是否显示数值标签 */
  showLabel?: boolean
}

const ScatterMap: React.FC<ScatterMapProps> = ({
  points,
  height = 400,
  theme = 'light',
  showHeatEffect = false,
  showTrajectory = false,
  selectedId,
  onPointClick,
  title,
  showLabel = false,
}) => {
  // 计算边界
  const bounds = useMemo(() => {
    if (points.length === 0) {
      return { minLng: 73, maxLng: 135, minLat: 18, maxLat: 54 } // 中国范围
    }

    const lngs = points.map((p) => p.longitude)
    const lats = points.map((p) => p.latitude)

    const minLng = Math.min(...lngs)
    const maxLng = Math.max(...lngs)
    const minLat = Math.min(...lats)
    const maxLat = Math.max(...lats)

    // 添加边距
    const lngPadding = Math.max((maxLng - minLng) * 0.1, 0.5)
    const latPadding = Math.max((maxLat - minLat) * 0.1, 0.5)

    return {
      minLng: minLng - lngPadding,
      maxLng: maxLng + lngPadding,
      minLat: minLat - latPadding,
      maxLat: maxLat + latPadding,
    }
  }, [points])

  // 轨迹数据
  const trajectoryData = useMemo(() => {
    if (!showTrajectory || points.length < 2) return []

    const sorted = [...points].sort(
      (a, b) => new Date(a.time || 0).getTime() - new Date(b.time || 0).getTime()
    )

    return sorted.map((p) => [p.longitude, p.latitude])
  }, [points, showTrajectory])

  // 颜色配置
  const colors = useMemo(
    () => ({
      bg: theme === 'dark' ? '#1a1a2e' : '#fafafa',
      grid: theme === 'dark' ? '#2d2d4a' : '#e8e8e8',
      text: theme === 'dark' ? '#b0b0b0' : '#666',
      primary: theme === 'dark' ? '#00d4ff' : '#1890ff',
      danger: theme === 'dark' ? '#ff6b6b' : '#ff4d4f',
      warning: theme === 'dark' ? '#ffd93d' : '#faad14',
      success: theme === 'dark' ? '#6bcb77' : '#52c41a',
    }),
    [theme]
  )

  // 获取点的颜色
  const getPointColor = useCallback(
    (point: MapPoint) => {
      if (point.id === selectedId) return colors.warning
      if (point.status === 'resolved') return colors.success
      if (point.status === 'processing') return colors.primary
      return colors.danger
    },
    [selectedId, colors]
  )

  // ECharts 配置
  const option: EChartsOption = useMemo(() => {
    const series: any[] = []

    // 散点图
    series.push({
      name: '案件分布',
      type: showHeatEffect ? 'effectScatter' : 'scatter',
      data: points.map((p) => ({
        name: p.name,
        value: [p.longitude, p.latitude, p.value || 1],
        itemStyle: {
          color: getPointColor(p),
        },
        point: p,
      })),
      symbolSize: (data: number[]) => {
        const baseSize = data[2] ? Math.min(20, Math.max(8, data[2] * 2)) : 10
        return baseSize
      },
      ...(showHeatEffect && {
        showEffectOn: 'render',
        rippleEffect: {
          brushType: 'stroke',
          scale: 2.5,
        },
      }),
      label: showLabel
        ? {
            show: true,
            formatter: (params: any) => params.data.name,
            position: 'top',
            color: colors.text,
            fontSize: 10,
          }
        : { show: false },
      emphasis: {
        itemStyle: {
          borderColor: '#fff',
          borderWidth: 2,
          shadowBlur: 10,
          shadowColor: 'rgba(0,0,0,0.3)',
        },
        label: {
          show: true,
          formatter: (params: any) => params.data.name,
        },
      },
    })

    // 轨迹线
    if (showTrajectory && trajectoryData.length > 1) {
      // 连接线
      series.push({
        name: '轨迹',
        type: 'line',
        data: trajectoryData,
        lineStyle: {
          color: colors.warning,
          width: 2,
          type: 'dashed',
        },
        symbol: 'none',
        smooth: true,
      })

      // 方向箭头
      series.push({
        name: '方向',
        type: 'scatter',
        data: trajectoryData.slice(1).map((coord, i) => {
          const prev = trajectoryData[i]
          return {
            value: coord,
            symbol: 'arrow',
            symbolRotate:
              (Math.atan2(coord[1] - prev[1], coord[0] - prev[0]) * 180) / Math.PI - 90,
          }
        }),
        symbolSize: 8,
        itemStyle: {
          color: colors.warning,
        },
      })
    }

    return {
      backgroundColor: colors.bg,
      title: title
        ? {
            text: title,
            left: 'center',
            textStyle: {
              color: colors.text,
              fontSize: 14,
            },
          }
        : undefined,
      tooltip: {
        trigger: 'item',
        backgroundColor: theme === 'dark' ? 'rgba(30,30,50,0.95)' : 'rgba(255,255,255,0.95)',
        borderColor: theme === 'dark' ? '#444' : '#ddd',
        textStyle: {
          color: colors.text,
        },
        formatter: (params: any) => {
          const p = params.data?.point
          if (!p) return params.name
          return `
            <div style="padding: 4px 8px;">
              <strong style="color: ${colors.primary}">${p.name}</strong><br/>
              ${p.type ? `类型: ${p.type}<br/>` : ''}
              ${p.time ? `时间: ${new Date(p.time).toLocaleDateString()}<br/>` : ''}
              坐标: ${p.latitude.toFixed(4)}, ${p.longitude.toFixed(4)}
            </div>
          `
        },
      },
      grid: {
        left: 60,
        right: 40,
        top: title ? 50 : 30,
        bottom: 50,
      },
      xAxis: {
        type: 'value',
        name: '经度',
        nameLocation: 'middle',
        nameGap: 30,
        nameTextStyle: {
          color: colors.text,
        },
        min: bounds.minLng,
        max: bounds.maxLng,
        axisLine: {
          lineStyle: { color: colors.grid },
        },
        axisTick: {
          lineStyle: { color: colors.grid },
        },
        axisLabel: {
          color: colors.text,
          formatter: (v: number) => v.toFixed(1) + '°',
        },
        splitLine: {
          lineStyle: { color: colors.grid, type: 'dashed' },
        },
      },
      yAxis: {
        type: 'value',
        name: '纬度',
        nameLocation: 'middle',
        nameGap: 40,
        nameTextStyle: {
          color: colors.text,
        },
        min: bounds.minLat,
        max: bounds.maxLat,
        axisLine: {
          lineStyle: { color: colors.grid },
        },
        axisTick: {
          lineStyle: { color: colors.grid },
        },
        axisLabel: {
          color: colors.text,
          formatter: (v: number) => v.toFixed(1) + '°',
        },
        splitLine: {
          lineStyle: { color: colors.grid, type: 'dashed' },
        },
      },
      series,
      // 数据缩放
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: 0,
          filterMode: 'none',
        },
        {
          type: 'inside',
          yAxisIndex: 0,
          filterMode: 'none',
        },
      ],
    }
  }, [
    points,
    bounds,
    trajectoryData,
    showHeatEffect,
    showTrajectory,
    showLabel,
    title,
    colors,
    getPointColor,
    theme,
  ])

  // 点击处理
  const handleClick = useCallback(
    (params: any) => {
      if (params.data?.point && onPointClick) {
        onPointClick(params.data.point)
      }
    },
    [onPointClick]
  )

  return (
    <ReactECharts
      option={option}
      style={{ height, width: '100%' }}
      onEvents={{ click: handleClick }}
      opts={{ renderer: 'canvas' }}
    />
  )
}

export default ScatterMap
