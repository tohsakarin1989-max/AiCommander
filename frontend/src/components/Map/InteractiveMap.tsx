/**
 * 交互式地图组件
 * 基于 ECharts 实现，支持：
 * - 案件散点标记
 * - 热力图层
 * - 聚类展示
 * - 轨迹动画
 */
import { useMemo, useCallback } from 'react'
import ReactECharts from 'echarts-for-react'

export interface MapCase {
  id: number
  case_number: string
  latitude: number
  longitude: number
  location?: string
  case_type?: string
  occurred_time?: string
  status?: string
}

export interface HotspotData {
  center_latitude: number
  center_longitude: number
  case_count: number
  radius_km: number
}

export interface InteractiveMapProps {
  /** 案件数据 */
  cases: MapCase[]
  /** 热点数据 */
  hotspots?: HotspotData[]
  /** 是否显示热力图 */
  showHeatmap?: boolean
  /** 是否显示聚类 */
  showCluster?: boolean
  /** 地图高度 */
  height?: number | string
  /** 主题模式 */
  theme?: 'light' | 'dark'
  /** 点击案件回调 */
  onCaseClick?: (caseData: MapCase) => void
  /** 选中的案件 ID */
  selectedCaseId?: number
  /** 是否显示轨迹连线 */
  showTrajectory?: boolean
  /** 自定义中心点 */
  center?: [number, number]
  /** 缩放级别 */
  zoom?: number
}

/**
 * 计算地图中心点和缩放级别
 */
function calculateBounds(cases: MapCase[]): {
  center: [number, number]
  zoom: number
} {
  if (cases.length === 0) {
    // 默认中国中心
    return { center: [116.4, 39.9], zoom: 5 }
  }

  const lats = cases.map((c) => c.latitude)
  const lngs = cases.map((c) => c.longitude)

  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLng = Math.min(...lngs)
  const maxLng = Math.max(...lngs)

  const centerLat = (minLat + maxLat) / 2
  const centerLng = (minLng + maxLng) / 2

  // 根据范围计算缩放级别
  const latDiff = maxLat - minLat
  const lngDiff = maxLng - minLng
  const maxDiff = Math.max(latDiff, lngDiff)

  let zoom = 12
  if (maxDiff > 10) zoom = 4
  else if (maxDiff > 5) zoom = 5
  else if (maxDiff > 2) zoom = 7
  else if (maxDiff > 1) zoom = 8
  else if (maxDiff > 0.5) zoom = 10
  else if (maxDiff > 0.1) zoom = 12
  else zoom = 14

  return { center: [centerLng, centerLat], zoom }
}

/**
 * 生成热力图数据
 */
function generateHeatmapData(cases: MapCase[]): number[][] {
  return cases.map((c) => [c.longitude, c.latitude, 1])
}

/**
 * 聚类算法：简单网格聚类
 */
function clusterCases(
  cases: MapCase[],
  gridSize: number = 0.1
): { center: [number, number]; count: number; cases: MapCase[] }[] {
  const grid: Map<string, MapCase[]> = new Map()

  cases.forEach((c) => {
    const gridX = Math.floor(c.longitude / gridSize)
    const gridY = Math.floor(c.latitude / gridSize)
    const key = `${gridX},${gridY}`

    if (!grid.has(key)) {
      grid.set(key, [])
    }
    grid.get(key)!.push(c)
  })

  const clusters: { center: [number, number]; count: number; cases: MapCase[] }[] = []

  grid.forEach((clusterCases) => {
    if (clusterCases.length === 0) return

    const avgLng = clusterCases.reduce((sum, c) => sum + c.longitude, 0) / clusterCases.length
    const avgLat = clusterCases.reduce((sum, c) => sum + c.latitude, 0) / clusterCases.length

    clusters.push({
      center: [avgLng, avgLat],
      count: clusterCases.length,
      cases: clusterCases,
    })
  })

  return clusters
}

const InteractiveMap: React.FC<InteractiveMapProps> = ({
  cases,
  hotspots = [],
  showHeatmap = false,
  showCluster = false,
  height = 600,
  theme = 'light',
  onCaseClick,
  selectedCaseId,
  showTrajectory = false,
  center: customCenter,
  zoom: customZoom,
}) => {
  const { center, zoom } = useMemo(() => {
    if (customCenter && customZoom) {
      return { center: customCenter, zoom: customZoom }
    }
    return calculateBounds(cases)
  }, [cases, customCenter, customZoom])

  // 聚类数据
  const clusters = useMemo(() => {
    if (!showCluster || cases.length < 10) return []
    return clusterCases(cases, zoom > 10 ? 0.01 : zoom > 7 ? 0.05 : 0.1)
  }, [cases, showCluster, zoom])

  // 热力图数据
  const heatmapData = useMemo(() => {
    if (!showHeatmap) return []
    return generateHeatmapData(cases)
  }, [cases, showHeatmap])

  // 轨迹数据（按时间排序）
  const trajectoryData = useMemo(() => {
    if (!showTrajectory || cases.length < 2) return []
    const sorted = [...cases].sort(
      (a, b) =>
        new Date(a.occurred_time || 0).getTime() - new Date(b.occurred_time || 0).getTime()
    )
    return sorted.map((c) => [c.longitude, c.latitude])
  }, [cases, showTrajectory])

  // 主题配置
  const themeConfig = useMemo(
    () => ({
      backgroundColor: theme === 'dark' ? '#1a1a2e' : '#f5f5f5',
      textColor: theme === 'dark' ? '#e0e0e0' : '#333',
      primaryColor: theme === 'dark' ? '#00d4ff' : '#1890ff',
      dangerColor: theme === 'dark' ? '#ff6b6b' : '#ff4d4f',
      warningColor: theme === 'dark' ? '#ffd93d' : '#faad14',
      successColor: theme === 'dark' ? '#6bcb77' : '#52c41a',
    }),
    [theme]
  )

  // ECharts 配置
  const option = useMemo(() => {
    const series: any[] = []

    // 1. 案件散点图（如果不使用聚类）
    if (!showCluster || cases.length < 10) {
      series.push({
        name: '案件位置',
        type: 'scatter',
        coordinateSystem: 'geo',
        data: cases.map((c) => ({
          name: c.case_number,
          value: [c.longitude, c.latitude, c.id],
          itemStyle: {
            color:
              c.id === selectedCaseId
                ? themeConfig.warningColor
                : c.status === 'resolved'
                ? themeConfig.successColor
                : themeConfig.primaryColor,
          },
          caseData: c,
        })),
        symbolSize: (val: number[]) => (val[2] === selectedCaseId ? 16 : 10),
        emphasis: {
          itemStyle: {
            borderColor: '#fff',
            borderWidth: 2,
          },
        },
        tooltip: {
          formatter: (params: any) => {
            const c = params.data.caseData
            return `
              <div style="padding: 8px;">
                <strong>${c.case_number}</strong><br/>
                地点: ${c.location || '-'}<br/>
                类型: ${c.case_type || '-'}<br/>
                时间: ${c.occurred_time ? new Date(c.occurred_time).toLocaleDateString() : '-'}<br/>
                坐标: ${c.latitude.toFixed(6)}, ${c.longitude.toFixed(6)}
              </div>
            `
          },
        },
      })
    }

    // 2. 聚类散点图
    if (showCluster && clusters.length > 0) {
      series.push({
        name: '案件聚类',
        type: 'scatter',
        coordinateSystem: 'geo',
        data: clusters.map((cluster) => ({
          name: `${cluster.count} 个案件`,
          value: [...cluster.center, cluster.count],
          cluster,
        })),
        symbolSize: (val: number[]) => Math.min(50, Math.max(20, val[2] * 5)),
        itemStyle: {
          color: themeConfig.dangerColor,
          opacity: 0.7,
        },
        label: {
          show: true,
          formatter: (params: any) => params.data.value[2],
          color: '#fff',
          fontWeight: 'bold',
        },
        tooltip: {
          formatter: (params: any) => {
            const cluster = params.data.cluster
            return `
              <div style="padding: 8px;">
                <strong>${cluster.count} 个案件</strong><br/>
                点击查看详情
              </div>
            `
          },
        },
      })
    }

    // 3. 热点区域（来自后端分析）
    if (hotspots.length > 0) {
      series.push({
        name: '热点区域',
        type: 'effectScatter',
        coordinateSystem: 'geo',
        data: hotspots.map((h) => ({
          name: `热点 (${h.case_count} 个案件)`,
          value: [h.center_longitude, h.center_latitude, h.case_count],
        })),
        symbolSize: (val: number[]) => Math.min(60, Math.max(25, val[2] * 8)),
        showEffectOn: 'render',
        rippleEffect: {
          brushType: 'stroke',
          scale: 3,
        },
        itemStyle: {
          color: themeConfig.dangerColor,
          shadowBlur: 10,
          shadowColor: themeConfig.dangerColor,
        },
        tooltip: {
          formatter: (params: any) => `热点区域: ${params.data.value[2]} 个案件`,
        },
      })
    }

    // 4. 热力图层
    if (showHeatmap && heatmapData.length > 0) {
      series.push({
        name: '热力分布',
        type: 'heatmap',
        coordinateSystem: 'geo',
        data: heatmapData,
        pointSize: 15,
        blurSize: 20,
      })
    }

    // 5. 轨迹连线
    if (showTrajectory && trajectoryData.length > 1) {
      series.push({
        name: '案件轨迹',
        type: 'lines',
        coordinateSystem: 'geo',
        polyline: true,
        data: [
          {
            coords: trajectoryData,
          },
        ],
        lineStyle: {
          color: themeConfig.warningColor,
          width: 2,
          opacity: 0.8,
          curveness: 0.1,
        },
        effect: {
          show: true,
          period: 6,
          trailLength: 0.3,
          symbol: 'arrow',
          symbolSize: 8,
          color: themeConfig.warningColor,
        },
      })
    }

    return {
      backgroundColor: themeConfig.backgroundColor,
      tooltip: {
        trigger: 'item',
        backgroundColor: theme === 'dark' ? 'rgba(30,30,50,0.9)' : 'rgba(255,255,255,0.9)',
        textStyle: {
          color: themeConfig.textColor,
        },
        borderColor: theme === 'dark' ? '#444' : '#ddd',
      },
      legend: {
        show: true,
        top: 10,
        right: 10,
        textStyle: {
          color: themeConfig.textColor,
        },
        data: series.map((s) => s.name),
      },
      geo: {
        map: 'china',
        roam: true,
        zoom: zoom,
        center: center,
        scaleLimit: {
          min: 1,
          max: 20,
        },
        itemStyle: {
          areaColor: theme === 'dark' ? '#2a2a4a' : '#e8e8e8',
          borderColor: theme === 'dark' ? '#404060' : '#ccc',
        },
        emphasis: {
          itemStyle: {
            areaColor: theme === 'dark' ? '#3a3a5a' : '#ddd',
          },
        },
        regions: [],
        // 使用经纬度坐标系
        // 注意：如果没有中国地图JSON，可以设置 show: false 使用纯坐标
        show: false,
      },
      // 使用 grid + xAxis + yAxis 模拟经纬度坐标系（无地图JSON时的备选方案）
      grid: {
        left: 50,
        right: 50,
        top: 60,
        bottom: 50,
      },
      xAxis: {
        type: 'value',
        min: center[0] - 180 / zoom,
        max: center[0] + 180 / zoom,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: {
          show: true,
          lineStyle: {
            color: theme === 'dark' ? '#333' : '#eee',
          },
        },
      },
      yAxis: {
        type: 'value',
        min: center[1] - 90 / zoom,
        max: center[1] + 90 / zoom,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: {
          show: true,
          lineStyle: {
            color: theme === 'dark' ? '#333' : '#eee',
          },
        },
      },
      // 重新定义 series，使用笛卡尔坐标系
      series: series.map((s) => ({
        ...s,
        coordinateSystem: 'cartesian2d',
        data: s.data?.map((d: any) => ({
          ...d,
          value: d.value ? [d.value[0], d.value[1], ...(d.value.slice(2) || [])] : d,
        })),
      })),
      // 视觉映射（用于热力图）
      visualMap: showHeatmap
        ? {
            show: false,
            min: 0,
            max: 10,
            inRange: {
              color: ['#50a3ba', '#eac736', '#d94e5d'],
            },
          }
        : undefined,
    }
  }, [
    cases,
    clusters,
    hotspots,
    heatmapData,
    trajectoryData,
    showHeatmap,
    showCluster,
    showTrajectory,
    selectedCaseId,
    center,
    zoom,
    theme,
    themeConfig,
  ])

  // 点击事件处理
  const handleChartClick = useCallback(
    (params: any) => {
      if (params.data?.caseData && onCaseClick) {
        onCaseClick(params.data.caseData)
      } else if (params.data?.cluster && onCaseClick && params.data.cluster.cases.length === 1) {
        onCaseClick(params.data.cluster.cases[0])
      }
    },
    [onCaseClick]
  )

  return (
    <ReactECharts
      option={option}
      style={{ height, width: '100%' }}
      onEvents={{
        click: handleChartClick,
      }}
      opts={{ renderer: 'canvas' }}
    />
  )
}

export default InteractiveMap
