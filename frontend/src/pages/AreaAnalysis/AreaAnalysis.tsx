/**
 * 区域研判页面
 *
 * 核心功能：
 * 1. 区域事件聚集分析
 * 2. 事件关联识别
 * 3. 风险评估
 * 4. 巡逻建议生成
 */
import React, { useState, useEffect } from 'react'
import {
  Card,
  Row,
  Col,
  Input,
  Button,
  Table,
  Tag,
  Tabs,
  List,
  Statistic,
  Progress,
  Alert,
  Spin,
  Space,
  Select,
  InputNumber,
  Timeline,
  Descriptions,
  Empty,
  message,
} from 'antd'
import {
  EnvironmentOutlined,
  SearchOutlined,
  AlertOutlined,
  CarOutlined,
  ClockCircleOutlined,
  AimOutlined,
  TeamOutlined,
  LinkOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import * as eventsApi from '../../services/events'
import type {
  Event,
  AreaProfile,
  AreaAnalysisResponse,
  PatrolSuggestion,
  EventStatistics,
} from '../../types/event'
import { EVENT_TYPES, RELATION_TYPES } from '../../types/event'
import './AreaAnalysis.css'

const { TabPane } = Tabs
const { Search } = Input
const { Option } = Select

// 风险等级颜色映射
const RISK_COLORS = {
  low: '#52c41a',
  medium: '#faad14',
  high: '#ff4d4f',
  critical: '#cf1322',
}

// 风险等级标签
const RISK_LABELS = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  critical: '极高风险',
}

const AreaAnalysis: React.FC = () => {
  // 状态
  const [loading, setLoading] = useState(false)
  const [areaName, setAreaName] = useState('')
  const [radiusKm, setRadiusKm] = useState(5)
  const [daysBack, setDaysBack] = useState(365)
  const [analysisResult, setAnalysisResult] = useState<AreaAnalysisResponse | null>(null)
  const [areaProfiles, setAreaProfiles] = useState<AreaProfile[]>([])
  const [statistics, setStatistics] = useState<EventStatistics | null>(null)
  const [selectedEvents, setSelectedEvents] = useState<number[]>([])

  // 加载初始数据
  useEffect(() => {
    loadInitialData()
  }, [])

  const loadInitialData = async () => {
    try {
      const [profiles, stats] = await Promise.all([
        eventsApi.listAreaProfiles({ limit: 20 }),
        eventsApi.getEventStatistics(90),
      ])
      setAreaProfiles(profiles)
      setStatistics(stats)
    } catch (error) {
      console.error('加载数据失败:', error)
    }
  }

  // 执行区域分析
  const handleAnalyze = async () => {
    if (!areaName.trim()) {
      message.warning('请输入区域名称')
      return
    }

    setLoading(true)
    try {
      const result = await eventsApi.analyzeArea({
        area_name: areaName,
        radius_km: radiusKm,
        days_back: daysBack,
      })
      setAnalysisResult(result)
      message.success(`分析完成，发现 ${result.events.length} 个相关事件`)
    } catch (error) {
      message.error('分析失败，请重试')
      console.error('区域分析失败:', error)
    } finally {
      setLoading(false)
    }
  }

  // 快速选择高风险区域
  const handleQuickSelect = (profile: AreaProfile) => {
    setAreaName(profile.area_name)
    handleAnalyze()
  }

  // 事件表格列配置
  const eventColumns = [
    {
      title: '事件编号',
      dataIndex: 'event_number',
      key: 'event_number',
      width: 140,
    },
    {
      title: '类型',
      dataIndex: 'event_type',
      key: 'event_type',
      width: 100,
      render: (type: string) => (
        <Tag color="blue">{EVENT_TYPES[type as keyof typeof EVENT_TYPES] || type}</Tag>
      ),
    },
    {
      title: '发生时间',
      dataIndex: 'occurred_time',
      key: 'occurred_time',
      width: 160,
      render: (time: string) => new Date(time).toLocaleString('zh-CN'),
    },
    {
      title: '地点',
      dataIndex: 'location',
      key: 'location',
      ellipsis: true,
    },
    {
      title: '关联村屯',
      dataIndex: 'village_name',
      key: 'village_name',
      width: 100,
    },
    {
      title: '风险',
      dataIndex: 'risk_level',
      key: 'risk_level',
      width: 80,
      render: (level: string) =>
        level ? (
          <Tag color={RISK_COLORS[level as keyof typeof RISK_COLORS]}>
            {RISK_LABELS[level as keyof typeof RISK_LABELS]}
          </Tag>
        ) : (
          '-'
        ),
    },
  ]

  // 渲染统计卡片
  const renderStatisticsCards = () => (
    <Row gutter={16} className="statistics-row">
      <Col span={6}>
        <Card>
          <Statistic
            title="近90天事件总数"
            value={statistics?.recent_events || 0}
            prefix={<AlertOutlined />}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic
            title="高风险区域"
            value={statistics?.high_risk_areas?.length || 0}
            prefix={<WarningOutlined style={{ color: '#ff4d4f' }} />}
            valueStyle={{ color: '#ff4d4f' }}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic
            title="涉及村屯数"
            value={Object.keys(statistics?.by_village || {}).length}
            prefix={<EnvironmentOutlined />}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic
            title="事件类型数"
            value={Object.keys(statistics?.by_type || {}).length}
            prefix={<TeamOutlined />}
          />
        </Card>
      </Col>
    </Row>
  )

  // 渲染高风险区域列表
  const renderHighRiskAreas = () => (
    <Card title="高风险区域" className="high-risk-card">
      {statistics?.high_risk_areas && statistics.high_risk_areas.length > 0 ? (
        <List
          dataSource={statistics.high_risk_areas}
          renderItem={(area) => (
            <List.Item
              actions={[
                <Button type="link" onClick={() => setAreaName(area.area_name)}>
                  分析
                </Button>,
              ]}
            >
              <List.Item.Meta
                avatar={
                  <AlertOutlined
                    style={{
                      fontSize: 24,
                      color: RISK_COLORS[area.risk_level as keyof typeof RISK_COLORS],
                    }}
                  />
                }
                title={
                  <Space>
                    {area.area_name}
                    <Tag color={RISK_COLORS[area.risk_level as keyof typeof RISK_COLORS]}>
                      {RISK_LABELS[area.risk_level as keyof typeof RISK_LABELS]}
                    </Tag>
                  </Space>
                }
                description={`事件数: ${area.event_count} | 风险分: ${area.risk_score.toFixed(1)}`}
              />
            </List.Item>
          )}
        />
      ) : (
        <Empty description="暂无高风险区域" />
      )}
    </Card>
  )

  // 渲染分析结果
  const renderAnalysisResult = () => {
    if (!analysisResult) return null

    return (
      <div className="analysis-result">
        {/* 风险评估 */}
        <Card title="风险评估" className="risk-assessment-card">
          <Row gutter={24}>
            <Col span={8}>
              <div className="risk-score-display">
                <Progress
                  type="dashboard"
                  percent={analysisResult.risk_assessment.score}
                  strokeColor={
                    RISK_COLORS[
                      analysisResult.risk_assessment.level as keyof typeof RISK_COLORS
                    ]
                  }
                  format={(percent) => (
                    <div>
                      <div className="score">{percent}</div>
                      <div className="label">
                        {
                          RISK_LABELS[
                            analysisResult.risk_assessment.level as keyof typeof RISK_LABELS
                          ]
                        }
                      </div>
                    </div>
                  )}
                />
              </div>
            </Col>
            <Col span={16}>
              <Descriptions title="风险因素" column={1}>
                {analysisResult.risk_assessment.factors.map((factor, idx) => (
                  <Descriptions.Item key={idx}>
                    <WarningOutlined style={{ marginRight: 8, color: '#faad14' }} />
                    {factor}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            </Col>
          </Row>
        </Card>

        {/* 事件列表和关联 */}
        <Card title={`相关事件 (${analysisResult.events.length})`} className="events-card">
          <Table
            dataSource={analysisResult.events}
            columns={eventColumns}
            rowKey="id"
            pagination={{ pageSize: 10 }}
            size="small"
            rowSelection={{
              selectedRowKeys: selectedEvents,
              onChange: (keys) => setSelectedEvents(keys as number[]),
            }}
          />
        </Card>

        {/* 关联分析 */}
        {analysisResult.relations.length > 0 && (
          <Card title="事件关联" className="relations-card">
            <List
              dataSource={analysisResult.relations}
              renderItem={(relation) => (
                <List.Item>
                  <List.Item.Meta
                    avatar={<LinkOutlined style={{ fontSize: 20, color: '#1890ff' }} />}
                    title={
                      <Space>
                        <Tag color="blue">
                          {
                            RELATION_TYPES[relation.relation_type as keyof typeof RELATION_TYPES]
                              ?.name
                          }
                        </Tag>
                        <span>置信度: {(relation.confidence * 100).toFixed(0)}%</span>
                      </Space>
                    }
                    description={
                      <div>
                        {relation.evidence && <p>{relation.evidence}</p>}
                        {relation.reasoning && (
                          <p style={{ color: '#666' }}>{relation.reasoning}</p>
                        )}
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        )}

        {/* 巡逻建议 */}
        <Card
          title="巡逻建议"
          className="patrol-suggestions-card"
          extra={<Tag color="green">可执行建议</Tag>}
        >
          <Timeline>
            {analysisResult.patrol_suggestions.map((suggestion, idx) => (
              <Timeline.Item
                key={idx}
                color={suggestion.priority === 1 ? 'red' : 'blue'}
                dot={<AimOutlined />}
              >
                <div className="patrol-item">
                  <div className="patrol-location">
                    <EnvironmentOutlined /> {suggestion.location}
                  </div>
                  <div className="patrol-reason">{suggestion.reason}</div>
                  {suggestion.timing && (
                    <div className="patrol-timing">
                      <ClockCircleOutlined /> 建议时间: {suggestion.timing}
                    </div>
                  )}
                  {suggestion.focus_on && suggestion.focus_on.length > 0 && (
                    <div className="patrol-focus">
                      关注重点:
                      {suggestion.focus_on.map((f, i) => (
                        <Tag key={i} size="small">
                          {f}
                        </Tag>
                      ))}
                    </div>
                  )}
                </div>
              </Timeline.Item>
            ))}
          </Timeline>
        </Card>

        {/* 排查建议 */}
        {analysisResult.suggestions.length > 0 && (
          <Card title="排查重点" className="search-suggestions-card">
            <List
              dataSource={analysisResult.suggestions}
              renderItem={(suggestion, idx) => (
                <List.Item>
                  <List.Item.Meta
                    avatar={<SearchOutlined style={{ fontSize: 20, color: '#722ed1' }} />}
                    title={
                      <Space>
                        <span>#{idx + 1}</span>
                        <span>{suggestion.target}</span>
                      </Space>
                    }
                    description={
                      <div>
                        <p>
                          <EnvironmentOutlined /> 排查区域: {suggestion.area}
                        </p>
                        {suggestion.method && <p>建议方法: {suggestion.method}</p>}
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        )}
      </div>
    )
  }

  return (
    <div className="area-analysis-page">
      <Card title="区域研判" className="main-card">
        <Alert
          message="区域研判说明"
          description="基于已破获案件/事件数据，分析指定区域的事件聚集特征，识别关联关系，评估风险等级，并生成巡逻防控建议。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />

        {/* 搜索区域 */}
        <Card className="search-card">
          <Row gutter={16} align="middle">
            <Col span={8}>
              <Input
                placeholder="输入村屯/区域名称"
                prefix={<EnvironmentOutlined />}
                value={areaName}
                onChange={(e) => setAreaName(e.target.value)}
                onPressEnter={handleAnalyze}
              />
            </Col>
            <Col span={4}>
              <InputNumber
                addonBefore="半径"
                addonAfter="km"
                value={radiusKm}
                onChange={(v) => setRadiusKm(v || 5)}
                min={1}
                max={50}
                style={{ width: '100%' }}
              />
            </Col>
            <Col span={4}>
              <Select value={daysBack} onChange={setDaysBack} style={{ width: '100%' }}>
                <Option value={30}>近30天</Option>
                <Option value={90}>近90天</Option>
                <Option value={180}>近半年</Option>
                <Option value={365}>近一年</Option>
                <Option value={730}>近两年</Option>
              </Select>
            </Col>
            <Col span={4}>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleAnalyze} block>
                开始分析
              </Button>
            </Col>
          </Row>
        </Card>

        <Spin spinning={loading} tip="正在分析区域数据...">
          <Tabs defaultActiveKey="overview">
            <TabPane tab="概览" key="overview">
              {renderStatisticsCards()}
              <Row gutter={16} style={{ marginTop: 16 }}>
                <Col span={12}>{renderHighRiskAreas()}</Col>
                <Col span={12}>
                  <Card title="事件类型分布">
                    {statistics?.by_type ? (
                      <List
                        size="small"
                        dataSource={Object.entries(statistics.by_type)}
                        renderItem={([type, count]) => (
                          <List.Item>
                            <Tag color="blue">
                              {EVENT_TYPES[type as keyof typeof EVENT_TYPES] || type}
                            </Tag>
                            <span>{count} 起</span>
                          </List.Item>
                        )}
                      />
                    ) : (
                      <Empty description="暂无数据" />
                    )}
                  </Card>
                </Col>
              </Row>
            </TabPane>

            <TabPane tab="分析结果" key="result">
              {analysisResult ? (
                renderAnalysisResult()
              ) : (
                <Empty description="请先选择区域并执行分析">
                  <Button type="primary" onClick={handleAnalyze} disabled={!areaName}>
                    开始分析
                  </Button>
                </Empty>
              )}
            </TabPane>

            <TabPane tab="区域档案" key="profiles">
              <Table
                dataSource={areaProfiles}
                rowKey="id"
                pagination={{ pageSize: 10 }}
                columns={[
                  {
                    title: '区域名称',
                    dataIndex: 'area_name',
                    key: 'area_name',
                  },
                  {
                    title: '事件总数',
                    dataIndex: 'total_events',
                    key: 'total_events',
                  },
                  {
                    title: '近30天',
                    dataIndex: 'events_last_30_days',
                    key: 'events_last_30_days',
                  },
                  {
                    title: '风险等级',
                    dataIndex: 'risk_level',
                    key: 'risk_level',
                    render: (level: string) => (
                      <Tag color={RISK_COLORS[level as keyof typeof RISK_COLORS]}>
                        {RISK_LABELS[level as keyof typeof RISK_LABELS]}
                      </Tag>
                    ),
                  },
                  {
                    title: '风险分数',
                    dataIndex: 'risk_score',
                    key: 'risk_score',
                    render: (score: number) => (
                      <Progress
                        percent={score}
                        size="small"
                        strokeColor={score > 60 ? '#ff4d4f' : score > 30 ? '#faad14' : '#52c41a'}
                      />
                    ),
                  },
                  {
                    title: '操作',
                    key: 'action',
                    render: (_, record: AreaProfile) => (
                      <Button type="link" onClick={() => handleQuickSelect(record)}>
                        详细分析
                      </Button>
                    ),
                  },
                ]}
              />
            </TabPane>
          </Tabs>
        </Spin>
      </Card>
    </div>
  )
}

export default AreaAnalysis
