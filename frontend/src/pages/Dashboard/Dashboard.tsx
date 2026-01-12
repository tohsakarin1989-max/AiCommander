import React, { useEffect, useState, useRef } from 'react'
import { Card, Statistic, Row, Col, Table, Tag, Alert, Button, Space } from 'antd'
import {
  AlertOutlined,
  EnvironmentOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
} from '@ant-design/icons'

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

interface DashboardData {
  cases: Case[]
  statistics: {
    total_cases: number
    today_cases: number
  }
}

const Dashboard: React.FC = () => {
  const [wsConnected, setWsConnected] = useState(false)
  const [cases, setCases] = useState<Case[]>([])
  const [statistics, setStatistics] = useState({ total_cases: 0, today_cases: 0 })
  const [isPlaying, setIsPlaying] = useState(true)
  const [isInitialLoading, setIsInitialLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const isPlayingRef = useRef(isPlaying)
  const reconnectTimerRef = useRef<number | null>(null)

  useEffect(() => {
    isPlayingRef.current = isPlaying
  }, [isPlaying])

  // 初始化WebSocket连接
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host.replace(':3000', ':8000')}/api/ws/dashboard`

    const connect = () => {
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }

      setIsInitialLoading(true)
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setWsConnected(true)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          if (data.type === 'initial_data') {
            setCases(data.data.cases || [])
            setStatistics(data.data.statistics || { total_cases: 0, today_cases: 0 })
            setIsInitialLoading(false)
            setLastUpdate(new Date())
          } else if (data.type === 'update') {
            if (!isPlayingRef.current) {
              return
            }
            if (data.data?.new_cases) {
              setCases((prev) => {
                const newCases = data.data.new_cases
                const existingIds = new Set(prev.map((c) => c.id))
                const uniqueNewCases = newCases.filter((c: Case) => !existingIds.has(c.id))
                return [...uniqueNewCases, ...prev].slice(0, 50)
              })
              setLastUpdate(new Date())
            }
          } else if (data.type === 'heartbeat' || data.type === 'pong') {
            // 心跳消息，保持连接
          }
        } catch (error) {
          console.error('解析WebSocket消息失败:', error)
        }
      }

      ws.onerror = (error) => {
        console.error('WebSocket错误:', error)
        setWsConnected(false)
      }

      ws.onclose = () => {
        setWsConnected(false)
        reconnectTimerRef.current = window.setTimeout(() => {
          connect()
        }, 3000)
      }
    }

    connect()

    return () => {
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current)
      }
      wsRef.current?.close()
    }
  }, [])

  // 发送心跳
  useEffect(() => {
    if (!wsConnected) return

    const interval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30000) // 每30秒发送一次心跳

    return () => clearInterval(interval)
  }, [wsConnected])

  const columns = [
    {
      title: '案件编号',
      dataIndex: 'case_number',
      key: 'case_number',
    },
    {
      title: '案发时间',
      dataIndex: 'occurred_time',
      key: 'occurred_time',
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
      render: (location: string) => location || '-',
    },
    {
      title: '案件类型',
      dataIndex: 'case_type',
      key: 'case_type',
      render: (type: string) => type ? <Tag>{type}</Tag> : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const colorMap: Record<string, string> = {
          pending: 'default',
          processing: 'processing',
          resolved: 'success',
        }
        return <Tag color={colorMap[status] || 'default'}>{status}</Tag>
      },
    },
    {
      title: '位置',
      key: 'location',
      render: (_: any, record: Case) => (
        <Space>
          <EnvironmentOutlined />
          <span>
            {record.latitude?.toFixed(6)}, {record.longitude?.toFixed(6)}
          </span>
        </Space>
      ),
    },
  ]

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1>实时指挥大屏</h1>
        <Space>
          <Tag color={wsConnected ? 'success' : 'error'}>
            {wsConnected ? '实时连接中' : '连接断开'}
          </Tag>
          <Tag color={isPlaying ? 'processing' : 'default'}>
            {isPlaying ? '实时更新中' : '更新已暂停'}
          </Tag>
          {lastUpdate && (
            <Tag color="blue">
              最近更新：{lastUpdate.toLocaleTimeString('zh-CN')}
            </Tag>
          )}
          <Button
            icon={isPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            onClick={() => setIsPlaying(!isPlaying)}
            disabled={!wsConnected}
          >
            {isPlaying ? '暂停' : '播放'}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => window.location.reload()}>
            刷新
          </Button>
        </Space>
      </div>

      {!wsConnected && (
        <Alert
          message="WebSocket连接断开"
          description="正在尝试重新连接..."
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      {wsConnected && isInitialLoading && (
        <Alert
          message="正在加载实时数据"
          description="等待服务端推送初始数据..."
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      {wsConnected && !isPlaying && (
        <Alert
          message="实时更新已暂停"
          description="点击“播放”恢复实时刷新。"
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="案件总数"
              value={statistics.total_cases}
              prefix={<AlertOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="今日案件"
              value={statistics.today_cases}
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: '#ff4d4f' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="实时案件数"
              value={cases.length}
              prefix={<EnvironmentOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="连接状态"
              value={wsConnected ? '正常' : '断开'}
              valueStyle={{ color: wsConnected ? '#52c41a' : '#ff4d4f' }}
            />
          </Card>
        </Col>
      </Row>

      <Card title="实时案件列表" extra={<Tag>最近50条</Tag>}>
        <Table
          dataSource={cases}
          columns={columns}
          rowKey="id"
          loading={isInitialLoading && wsConnected}
          pagination={{ pageSize: 10 }}
          size="small"
          scroll={{ y: 400 }}
        />
      </Card>

      <Card title="地图视图" style={{ marginTop: 16 }}>
        <div style={{ height: 400, background: '#f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Alert
            message="地图功能开发中"
            description="实时案件位置将在地图上显示，支持轨迹回放和位置预测"
            type="info"
            showIcon
          />
        </div>
      </Card>
    </div>
  )
}

export default Dashboard
