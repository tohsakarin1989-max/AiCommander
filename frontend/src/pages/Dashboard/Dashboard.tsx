/**
 * 智慧大屏 - 实时指挥中心
 * 功能：
 * - 实时案件数据展示
 * - 多维度统计图表
 * - 交互式地图
 * - 暗色/亮色主题切换
 */
import React, { useEffect, useState, useRef, useMemo, useCallback } from 'react'
import { Card, Table, Tag, Alert, Button, Space, Switch, Row, Col, Tooltip } from 'antd'
import {
  AlertOutlined,
  EnvironmentOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  FullscreenOutlined,
  FullscreenExitOutlined,
  BulbOutlined,
  BulbFilled,
  FireOutlined,
  RiseOutlined,
} from '@ant-design/icons'

import { ScatterMap } from '../../components/Map'
import { TrendChart, PieChart, BarChart, StatisticCard } from '../../components/Charts'
import type { MapPoint } from '../../components/Map'
import './Dashboard.css'

interface Case {
  id: number
  case_number: string
  occurred_time: string
  latitude: number
  longitude: number
  location?: string
  case_type?: string
  status: string
}

interface DashboardStatistics {
  total_cases: number
  today_cases: number
  pending_cases: number
  resolved_cases: number
  this_week_cases: number
  this_month_cases: number
}

interface TrendData {
  date: string
  count: number
  label: string
}

interface TypeDistribution {
  name: string
  value: number
}

const Dashboard: React.FC = () => {
  // 状态管理
  const [wsConnected, setWsConnected] = useState(false)
  const [cases, setCases] = useState<Case[]>([])
  const [statistics, setStatistics] = useState<DashboardStatistics>({
    total_cases: 0,
    today_cases: 0,
    pending_cases: 0,
    resolved_cases: 0,
    this_week_cases: 0,
    this_month_cases: 0,
  })
  const [isPlaying, setIsPlaying] = useState(true)
  const [isDarkMode, setIsDarkMode] = useState(true)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [selectedCaseId, setSelectedCaseId] = useState<number | undefined>()

  const wsRef = useRef<WebSocket | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // 计算趋势数据（最近7天）
  const trendData = useMemo<TrendData[]>(() => {
    const days = 7
    const result: TrendData[] = []
    const now = new Date()

    for (let i = days - 1; i >= 0; i--) {
      const date = new Date(now)
      date.setDate(date.getDate() - i)
      const dateStr = date.toISOString().split('T')[0]

      const count = cases.filter((c) => {
        const caseDate = new Date(c.occurred_time).toISOString().split('T')[0]
        return caseDate === dateStr
      }).length

      result.push({
        date: dateStr,
        count,
        label: `${date.getMonth() + 1}/${date.getDate()}`,
      })
    }

    return result
  }, [cases])

  // 计算类型分布
  const typeDistribution = useMemo<TypeDistribution[]>(() => {
    const typeCount: Record<string, number> = {}

    cases.forEach((c) => {
      const type = c.case_type || '未分类'
      typeCount[type] = (typeCount[type] || 0) + 1
    })

    return Object.entries(typeCount)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
  }, [cases])

  // 计算区域分布（按状态）
  const statusDistribution = useMemo(() => {
    const pending = cases.filter((c) => c.status === 'pending').length
    const processing = cases.filter((c) => c.status === 'processing').length
    const resolved = cases.filter((c) => c.status === 'resolved').length

    return [
      { name: '待处理', value: pending },
      { name: '处理中', value: processing },
      { name: '已解决', value: resolved },
    ]
  }, [cases])

  // 地图数据
  const mapPoints = useMemo<MapPoint[]>(() => {
    return cases
      .filter((c) => c.latitude != null && c.longitude != null)
      .map((c) => ({
        id: c.id,
        name: c.case_number,
        latitude: c.latitude,
        longitude: c.longitude,
        type: c.case_type,
        time: c.occurred_time,
        status: c.status,
      }))
  }, [cases])

  // WebSocket 连接
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host.replace(':3000', ':8000')}/api/ws/dashboard`

    const connectWebSocket = () => {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('WebSocket 连接已建立')
        setWsConnected(true)
      }

      ws.onmessage = (event) => {
        if (!isPlaying) return

        try {
          const data = JSON.parse(event.data)

          if (data.type === 'initial_data') {
            setCases(data.data.cases || [])
            if (data.data.statistics) {
              setStatistics((prev) => ({ ...prev, ...data.data.statistics }))
            }
          } else if (data.type === 'update') {
            if (data.data?.new_cases) {
              setCases((prev) => {
                const newCases = data.data.new_cases
                const existingIds = new Set(prev.map((c) => c.id))
                const uniqueNewCases = newCases.filter((c: Case) => !existingIds.has(c.id))
                return [...uniqueNewCases, ...prev].slice(0, 100)
              })
            }
            if (data.data?.statistics) {
              setStatistics((prev) => ({ ...prev, ...data.data.statistics }))
            }
          }
        } catch (error) {
          console.error('解析 WebSocket 消息失败:', error)
        }
      }

      ws.onerror = () => {
        setWsConnected(false)
      }

      ws.onclose = () => {
        setWsConnected(false)
        // 自动重连
        setTimeout(() => {
          if (wsRef.current?.readyState === WebSocket.CLOSED) {
            connectWebSocket()
          }
        }, 3000)
      }
    }

    connectWebSocket()

    return () => {
      wsRef.current?.close()
    }
  }, [isPlaying])

  // 心跳保活
  useEffect(() => {
    if (!wsConnected) return

    const interval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30000)

    return () => clearInterval(interval)
  }, [wsConnected])

  // 全屏切换
  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen()
      setIsFullscreen(true)
    } else {
      document.exitFullscreen()
      setIsFullscreen(false)
    }
  }, [])

  // 监听全屏变化
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement)
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  // 地图点击处理
  const handleMapPointClick = useCallback((point: MapPoint) => {
    setSelectedCaseId(point.id)
  }, [])

  // 表格列定义
  const columns = [
    {
      title: '案件编号',
      dataIndex: 'case_number',
      key: 'case_number',
      width: 140,
      render: (text: string, record: Case) => (
        <span
          style={{
            color: record.id === selectedCaseId ? '#faad14' : isDarkMode ? '#00d4ff' : '#1890ff',
            cursor: 'pointer',
          }}
          onClick={() => setSelectedCaseId(record.id)}
        >
          {text}
        </span>
      ),
    },
    {
      title: '案发时间',
      dataIndex: 'occurred_time',
      key: 'occurred_time',
      width: 160,
      render: (time: string) => {
        if (!time) return '-'
        const date = new Date(time)
        return date.toLocaleString('zh-CN')
      },
    },
    {
      title: '案发地点',
      dataIndex: 'location',
      key: 'location',
      ellipsis: true,
      render: (location: string) => location || '-',
    },
    {
      title: '类型',
      dataIndex: 'case_type',
      key: 'case_type',
      width: 100,
      render: (type: string) =>
        type ? <Tag color={isDarkMode ? 'cyan' : 'blue'}>{type}</Tag> : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (status: string) => {
        const config: Record<string, { color: string; text: string }> = {
          pending: { color: 'gold', text: '待处理' },
          processing: { color: 'processing', text: '处理中' },
          resolved: { color: 'success', text: '已解决' },
        }
        const { color, text } = config[status] || { color: 'default', text: status }
        return <Tag color={color}>{text}</Tag>
      },
    },
  ]

  const theme = isDarkMode ? 'dark' : 'light'

  return (
    <div
      ref={containerRef}
      className={`dashboard-container dashboard-container--${theme}`}
    >
      {/* 顶部标题栏 */}
      <div className="dashboard-header">
        <div className="dashboard-header__left">
          <h1 className="dashboard-title">
            <FireOutlined style={{ marginRight: 12 }} />
            智慧指挥大屏
          </h1>
          <Tag color={wsConnected ? 'success' : 'error'} className="connection-tag">
            {wsConnected ? '● 实时连接' : '○ 连接断开'}
          </Tag>
        </div>

        <div className="dashboard-header__right">
          <Space size="middle">
            <Tooltip title={isDarkMode ? '切换亮色主题' : '切换暗色主题'}>
              <Button
                type="text"
                icon={isDarkMode ? <BulbOutlined /> : <BulbFilled />}
                onClick={() => setIsDarkMode(!isDarkMode)}
                className="header-btn"
              />
            </Tooltip>
            <Tooltip title={isPlaying ? '暂停数据更新' : '继续数据更新'}>
              <Button
                type="text"
                icon={isPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                onClick={() => setIsPlaying(!isPlaying)}
                className="header-btn"
              />
            </Tooltip>
            <Tooltip title={isFullscreen ? '退出全屏' : '全屏显示'}>
              <Button
                type="text"
                icon={isFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
                onClick={toggleFullscreen}
                className="header-btn"
              />
            </Tooltip>
            <Button
              type="text"
              icon={<ReloadOutlined />}
              onClick={() => window.location.reload()}
              className="header-btn"
            />
          </Space>
        </div>
      </div>

      {/* 连接断开警告 */}
      {!wsConnected && (
        <Alert
          message="WebSocket 连接断开"
          description="正在尝试重新连接..."
          type="warning"
          showIcon
          className="connection-alert"
        />
      )}

      {/* 主内容区域 */}
      <div className="dashboard-content">
        {/* 左侧统计区 */}
        <div className="dashboard-left">
          {/* 统计卡片 */}
          <Row gutter={[12, 12]} className="stat-cards">
            <Col span={12}>
              <StatisticCard
                title="案件总数"
                value={statistics.total_cases}
                icon={<AlertOutlined />}
                theme={theme}
                type="primary"
                animated
              />
            </Col>
            <Col span={12}>
              <StatisticCard
                title="今日新增"
                value={statistics.today_cases}
                icon={<ClockCircleOutlined />}
                theme={theme}
                type="danger"
                trend={statistics.today_cases > 0 ? 12 : 0}
                animated
              />
            </Col>
            <Col span={12}>
              <StatisticCard
                title="待处理"
                value={statistics.pending_cases || statusDistribution[0]?.value || 0}
                icon={<RiseOutlined />}
                theme={theme}
                type="warning"
                animated
              />
            </Col>
            <Col span={12}>
              <StatisticCard
                title="已解决"
                value={statistics.resolved_cases || statusDistribution[2]?.value || 0}
                icon={<EnvironmentOutlined />}
                theme={theme}
                type="success"
                animated
              />
            </Col>
          </Row>

          {/* 趋势图 */}
          <Card
            className="chart-card"
            title={<span className="card-title">案件趋势（近7天）</span>}
            bordered={false}
          >
            <TrendChart data={trendData} height={180} theme={theme} showArea smooth />
          </Card>

          {/* 类型分布 */}
          <Card
            className="chart-card"
            title={<span className="card-title">案件类型分布</span>}
            bordered={false}
          >
            <PieChart
              data={typeDistribution}
              height={200}
              theme={theme}
              donut
              showLegend
              showLabel={false}
            />
          </Card>
        </div>

        {/* 中间地图区 */}
        <div className="dashboard-center">
          <Card
            className="map-card"
            title={
              <span className="card-title">
                <EnvironmentOutlined style={{ marginRight: 8 }} />
                案件分布地图
                <Tag color="cyan" style={{ marginLeft: 12 }}>
                  {mapPoints.length} 个案件
                </Tag>
              </span>
            }
            bordered={false}
          >
            <ScatterMap
              points={mapPoints}
              height={isFullscreen ? 'calc(100vh - 280px)' : 480}
              theme={theme}
              showHeatEffect
              selectedId={selectedCaseId}
              onPointClick={handleMapPointClick}
            />
          </Card>
        </div>

        {/* 右侧列表区 */}
        <div className="dashboard-right">
          {/* 状态分布 */}
          <Card
            className="chart-card"
            title={<span className="card-title">处理状态</span>}
            bordered={false}
          >
            <BarChart
              data={statusDistribution}
              height={160}
              theme={theme}
              horizontal
              showLabel
              gradient
            />
          </Card>

          {/* 实时案件列表 */}
          <Card
            className="table-card"
            title={
              <span className="card-title">
                实时案件
                <Tag color="processing" style={{ marginLeft: 8 }}>
                  最近 {Math.min(cases.length, 100)} 条
                </Tag>
              </span>
            }
            bordered={false}
          >
            <Table
              dataSource={cases.slice(0, 50)}
              columns={columns}
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ y: isFullscreen ? 'calc(100vh - 480px)' : 320 }}
              className={`dashboard-table dashboard-table--${theme}`}
              rowClassName={(record) =>
                record.id === selectedCaseId ? 'selected-row' : ''
              }
              onRow={(record) => ({
                onClick: () => setSelectedCaseId(record.id),
              })}
            />
          </Card>
        </div>
      </div>

      {/* 底部状态栏 */}
      <div className="dashboard-footer">
        <span>
          数据更新时间：{new Date().toLocaleString('zh-CN')}
        </span>
        <span>
          系统状态：{wsConnected ? '正常运行' : '连接中断'}
        </span>
      </div>
    </div>
  )
}

export default Dashboard
