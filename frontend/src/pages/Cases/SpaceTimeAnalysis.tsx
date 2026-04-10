import React, { useState, useMemo } from 'react'
import { Card, DatePicker, Button, Spin, Typography, Space, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { PlayCircleOutlined, PauseCircleOutlined, StepBackwardOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs, { Dayjs } from 'dayjs'
import { caseApi } from '../../services/cases'
import LeafletMap from '../../components/Map/LeafletMap'
import type { CaseMarker } from '../../types'

const { RangePicker } = DatePicker
const { Text } = Typography

const cardStyle = {
  background: '#0d1117',
  border: '1px solid #1e293b',
  borderRadius: 6,
}

const SpaceTimeAnalysis: React.FC = () => {
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(180, 'day'),
    dayjs(),
  ])
  const [isPlaying, setIsPlaying] = useState(false)
  const [playIndex, setPlayIndex] = useState(0)
  const [playSpeed] = useState(1000) // ms/步

  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => caseApi.getCases(),
  })

  // 按日期范围筛选有坐标的案件，按时间排序
  const filteredCases = useMemo(() => {
    const [start, end] = dateRange
    return (cases || [])
      .filter(
        (c) =>
          c.latitude != null &&
          c.longitude != null &&
          c.occurred_time &&
          dayjs(c.occurred_time).isAfter(start) &&
          dayjs(c.occurred_time).isBefore(end)
      )
      .sort((a, b) => dayjs(a.occurred_time).valueOf() - dayjs(b.occurred_time).valueOf())
  }, [cases, dateRange])

  // 回放：显示到 playIndex 为止的案件
  const visibleMarkers: CaseMarker[] = useMemo(() => {
    const slice = isPlaying ? filteredCases.slice(0, playIndex + 1) : filteredCases
    return slice.map((c) => ({
      id: c.id,
      lat: c.latitude!,
      lng: c.longitude!,
      title: c.case_number,
      caseNumber: c.case_number,
      caseType: c.case_type,
      occurredTime: c.occurred_time,
      modus: c.modus_operandi,
    }))
  }, [filteredCases, isPlaying, playIndex])

  // 24 小时发案分布
  const hourlyData = useMemo(() => {
    const counts = new Array(24).fill(0)
    filteredCases.forEach((c) => {
      if (c.occurred_time) counts[dayjs(c.occurred_time).hour()]++
    })
    return counts
  }, [filteredCases])

  // 周发案分布
  const weeklyData = useMemo(() => {
    const labels = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
    const counts = new Array(7).fill(0)
    filteredCases.forEach((c) => {
      if (c.occurred_time) counts[dayjs(c.occurred_time).day()]++
    })
    return { labels, counts }
  }, [filteredCases])

  // 月度趋势
  const monthlyData = useMemo(() => {
    const monthMap: Record<string, number> = {}
    filteredCases.forEach((c) => {
      if (c.occurred_time) {
        const month = dayjs(c.occurred_time).format('YYYY-MM')
        monthMap[month] = (monthMap[month] || 0) + 1
      }
    })
    const sorted = Object.entries(monthMap).sort(([a], [b]) => a.localeCompare(b))
    return { months: sorted.map(([m]) => m), counts: sorted.map(([, c]) => c) }
  }, [filteredCases])

  // 回放控制
  const handlePlay = () => {
    if (filteredCases.length === 0) return
    setPlayIndex(0)
    setIsPlaying(true)
    const interval = setInterval(() => {
      setPlayIndex((prev) => {
        if (prev >= filteredCases.length - 1) {
          clearInterval(interval)
          setIsPlaying(false)
          return prev
        }
        return prev + 1
      })
    }, playSpeed)
  }

  const handleReset = () => {
    setIsPlaying(false)
    setPlayIndex(0)
  }

  const echartsBase = {
    backgroundColor: 'transparent',
    grid: { top: 20, bottom: 30, left: 30, right: 10 },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: '#0d1117',
      borderColor: '#1e293b',
      textStyle: { color: '#e2e8f0' },
    },
  }

  const xAxisBase = {
    axisLine: { lineStyle: { color: '#1e293b' } },
    axisLabel: { color: '#64748b', fontSize: 9 },
  }

  const yAxisBase = {
    type: 'value' as const,
    axisLine: { lineStyle: { color: '#1e293b' } },
    splitLine: { lineStyle: { color: '#1e293b' } },
    axisLabel: { color: '#64748b', fontSize: 9 },
  }

  const hourlyOption = {
    ...echartsBase,
    xAxis: { type: 'category' as const, data: Array.from({ length: 24 }, (_, i) => `${i}时`), ...xAxisBase },
    yAxis: yAxisBase,
    series: [{
      type: 'bar' as const,
      data: hourlyData,
      itemStyle: {
        color: (params: { dataIndex: number }) =>
          hourlyData[params.dataIndex] === Math.max(...hourlyData) ? '#ef4444' : '#7dd3fc',
        borderRadius: [2, 2, 0, 0],
      },
    }],
  }

  const weeklyOption = {
    ...echartsBase,
    xAxis: { type: 'category' as const, data: weeklyData.labels, ...xAxisBase },
    yAxis: yAxisBase,
    series: [{
      type: 'bar' as const,
      data: weeklyData.counts,
      itemStyle: { color: '#f59e0b', borderRadius: [2, 2, 0, 0] },
    }],
  }

  const monthlyOption = {
    ...echartsBase,
    xAxis: { type: 'category' as const, data: monthlyData.months, ...xAxisBase },
    yAxis: yAxisBase,
    series: [{
      type: 'line' as const,
      data: monthlyData.counts,
      smooth: true,
      lineStyle: { color: '#22c55e', width: 2 },
      itemStyle: { color: '#22c55e' },
      areaStyle: { color: 'rgba(34,197,94,0.1)' },
    }],
  }

  const peakHour = hourlyData.indexOf(Math.max(...hourlyData))
  const peakDay = weeklyData.counts.indexOf(Math.max(...weeklyData.counts))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: 'calc(100vh - 80px)' }}>
      {/* 顶部时间轴筛选器 */}
      <Card size="small" style={cardStyle} styles={{ body: { padding: '10px 14px' } }}>
        <Space size={16} wrap>
          <Text style={{ color: '#94a3b8', fontSize: 12 }}>时间范围：</Text>
          <RangePicker
            value={dateRange}
            onChange={(vals) => {
              if (vals && vals[0] && vals[1]) setDateRange([vals[0], vals[1]])
            }}
            style={{ background: '#1e293b', border: '1px solid #334155' }}
          />
          <Tag style={{ background: 'rgba(125,211,252,0.1)', border: '1px solid #7dd3fc', color: '#7dd3fc' }}>
            {filteredCases.length} 起案件
          </Tag>
          <Space>
            <Button
              size="small"
              icon={isPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
              onClick={isPlaying ? () => setIsPlaying(false) : handlePlay}
              disabled={filteredCases.length === 0}
              style={{ background: 'rgba(125,211,252,0.1)', border: '1px solid #7dd3fc', color: '#7dd3fc' }}
            >
              {isPlaying ? '暂停' : '时间回放'}
            </Button>
            <Button
              size="small"
              icon={<StepBackwardOutlined />}
              onClick={handleReset}
              style={{ border: '1px solid #334155', color: '#94a3b8' }}
            >
              重置
            </Button>
          </Space>
          {isPlaying && filteredCases.length > 0 && (
            <Text style={{ color: '#fcd34d', fontSize: 12 }}>
              ▶ {filteredCases[playIndex]?.occurred_time?.slice(0, 10)} —— {filteredCases[playIndex]?.case_number}
            </Text>
          )}
        </Space>
      </Card>

      {/* 主体：地图 + 统计 */}
      <div style={{ flex: 1, display: 'flex', gap: 12, minHeight: 0 }}>
        {/* 地图（60%） */}
        <div style={{ flex: 3 }}>
          {isLoading ? (
            <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Spin tip="加载数据..." />
            </div>
          ) : (
            <LeafletMap markers={visibleMarkers} height="100%" />
          )}
        </div>

        {/* 统计面板（40%） */}
        <div style={{ flex: 2, display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto' }}>
          <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
            <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>24小时发案分布</Text>
            <ReactECharts option={hourlyOption} style={{ height: 120 }} />
          </Card>

          <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
            <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>周发案规律</Text>
            <ReactECharts option={weeklyOption} style={{ height: 120 }} />
          </Card>

          <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
            <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>月度趋势</Text>
            <ReactECharts option={monthlyOption} style={{ height: 120 }} />
          </Card>

          {/* 规律摘要（有数据时显示） */}
          {filteredCases.length > 0 && (
            <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
              <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>规律摘要</Text>
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 5 }}>
                <div style={{ color: '#cbd5e1', fontSize: 11 }}>
                  发案高峰时段：<span style={{ color: '#fcd34d' }}>{peakHour}:00 — {(peakHour + 1) % 24}:00</span>
                </div>
                <div style={{ color: '#cbd5e1', fontSize: 11 }}>
                  高发星期：<span style={{ color: '#fcd34d' }}>{weeklyData.labels[peakDay]}</span>
                </div>
                <div style={{ color: '#cbd5e1', fontSize: 11 }}>
                  有坐标案件：<span style={{ color: '#7dd3fc' }}>{filteredCases.length} 起</span>
                </div>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

export default SpaceTimeAnalysis
