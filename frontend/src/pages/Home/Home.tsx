import { useState } from 'react'
import {
  Card,
  Row,
  Col,
  Statistic,
  List,
  Tag,
  Button,
  Space,
  Typography,
  Spin,
  Empty,
  Modal,
  Alert,
  Progress,
  Descriptions,
  Collapse,
  Timeline,
} from 'antd'
import {
  DatabaseOutlined,
  TeamOutlined,
  FileTextOutlined,
  ClockCircleOutlined,
  PlusOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  ExclamationCircleOutlined,
  RobotOutlined,
  EnvironmentOutlined,
  RadarChartOutlined,
  ThunderboltOutlined,
  WarningOutlined,
  SafetyCertificateOutlined,
  FireOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { caseApi } from '../../services/cases'
import { aiApi } from '../../services/ai'
import { analysisApi, SmartAnalysisReport } from '../../services/analysis'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const { Title, Text } = Typography

// 状态标签颜色映射
const statusColors: Record<string, string> = {
  pending: 'default',
  processing: 'processing',
  completed: 'success',
  failed: 'error',
  needs_review: 'warning',
}

const statusLabels: Record<string, string> = {
  pending: '待处理',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  needs_review: '待审核',
}

const Home: React.FC = () => {
  const navigate = useNavigate()
  const [analysisModalVisible, setAnalysisModalVisible] = useState(false)
  const [analysisResult, setAnalysisResult] = useState<SmartAnalysisReport | null>(null)

  // 一键智能研判
  const smartAnalysisMutation = useMutation({
    mutationFn: () => analysisApi.smart.analyze({ time_window_days: 90, min_cases: 2 }),
    onSuccess: (data) => {
      setAnalysisResult(data)
      setAnalysisModalVisible(true)
    },
  })

  // 获取案件列表
  const { data: cases, isLoading: casesLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => caseApi.getCases(),
  })

  // 获取会议列表
  const { data: meetings, isLoading: meetingsLoading } = useQuery({
    queryKey: ['meetings'],
    queryFn: () => aiApi.meeting.list(),
  })

  // 获取结论列表
  const { data: conclusions, isLoading: conclusionsLoading } = useQuery({
    queryKey: ['conclusions'],
    queryFn: () => aiApi.conclusion.list(),
  })

  // 计算统计数据
  const stats = {
    totalCases: cases?.length || 0,
    pendingCases: cases?.filter((c) => c.status === 'pending').length || 0,
    totalMeetings: meetings?.length || 0,
    processingMeetings: meetings?.filter((m) => m.status === 'processing').length || 0,
    completedMeetings: meetings?.filter((m) => m.status === 'completed').length || 0,
    totalConclusions: conclusions?.length || 0,
    pendingReview: conclusions?.filter((c) => c.status === 'needs_review').length || 0,
  }

  // 最近案件（最新5条）
  const recentCases = cases?.slice(0, 5) || []

  // 最近会议（最新5条）
  const recentMeetings = meetings?.slice(0, 5) || []

  // 待处理任务
  const pendingTasks = [
    ...(meetings?.filter((m) => m.status === 'processing').map((m) => ({
      type: 'meeting',
      id: m.meeting_id,
      title: `会议 ${m.meeting_id} 处理中`,
      status: 'processing',
      time: m.created_at,
    })) || []),
    ...(conclusions?.filter((c) => c.status === 'needs_review').map((c) => ({
      type: 'conclusion',
      id: c.id,
      title: `案件 #${c.case_id} 结论待审核`,
      status: 'needs_review',
      time: c.created_at,
    })) || []),
  ].slice(0, 5)

  // 快捷操作
  const quickActions = [
    {
      icon: <PlusOutlined />,
      title: '新建案件',
      description: '录入新的案件信息',
      onClick: () => navigate('/cases'),
      color: '#1890ff',
    },
    {
      icon: <TeamOutlined />,
      title: '创建会议',
      description: '发起圆桌分析会议',
      onClick: () => navigate('/meetings'),
      color: '#52c41a',
    },
    {
      icon: <EnvironmentOutlined />,
      title: '地图分析',
      description: '查看案件地理分布',
      onClick: () => navigate('/cases/map'),
      color: '#722ed1',
    },
    {
      icon: <RadarChartOutlined />,
      title: '区域研判',
      description: '分析区域风险',
      onClick: () => navigate('/area-analysis'),
      color: '#fa8c16',
    },
    {
      icon: <RobotOutlined />,
      title: '智能助手',
      description: '询问AI获取洞察',
      onClick: () => navigate('/assistant'),
      color: '#13c2c2',
    },
    {
      icon: <FileTextOutlined />,
      title: '查看报告',
      description: '浏览分析报告',
      onClick: () => navigate('/reports'),
      color: '#eb2f96',
    },
  ]

  const isLoading = casesLoading || meetingsLoading || conclusionsLoading

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 400 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  return (
    <div>
      <Title level={4} style={{ marginBottom: 24 }}>系统概览</Title>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Card
            hoverable
            onClick={() => navigate('/cases')}
            style={{
              background: '#0d1117',
              border: '1px solid #1e293b',
              borderTop: '2px solid #22c55e',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            <Statistic
              title={<span style={{ color: '#94a3b8', fontSize: 12 }}>案件总数</span>}
              value={stats.totalCases}
              prefix={<DatabaseOutlined />}
              valueStyle={{ color: '#4ade80', fontSize: 22, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Card
            hoverable
            onClick={() => navigate('/cases')}
            style={{
              background: '#0d1117',
              border: '1px solid #1e293b',
              borderTop: '2px solid #f59e0b',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            <Statistic
              title={<span style={{ color: '#94a3b8', fontSize: 12 }}>待处理案件</span>}
              value={stats.pendingCases}
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: '#fcd34d', fontSize: 22, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Card
            hoverable
            onClick={() => navigate('/meetings')}
            style={{
              background: '#0d1117',
              border: '1px solid #1e293b',
              borderTop: '2px solid #a78bfa',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            <Statistic
              title={<span style={{ color: '#94a3b8', fontSize: 12 }}>会议总数</span>}
              value={stats.totalMeetings}
              prefix={<TeamOutlined />}
              valueStyle={{ color: '#c4b5fd', fontSize: 22, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Card
            hoverable
            onClick={() => navigate('/meetings')}
            style={{
              background: '#0d1117',
              border: '1px solid #1e293b',
              borderTop: '2px solid #7dd3fc',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            <Statistic
              title={<span style={{ color: '#94a3b8', fontSize: 12 }}>进行中会议</span>}
              value={stats.processingMeetings}
              prefix={<SyncOutlined spin={stats.processingMeetings > 0} />}
              valueStyle={{ color: '#7dd3fc', fontSize: 22, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Card
            hoverable
            onClick={() => navigate('/reports')}
            style={{
              background: '#0d1117',
              border: '1px solid #1e293b',
              borderTop: '2px solid #22c55e',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            <Statistic
              title={<span style={{ color: '#94a3b8', fontSize: 12 }}>已完成分析</span>}
              value={stats.completedMeetings}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#4ade80', fontSize: 22, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Card
            hoverable
            onClick={() => navigate('/conclusions')}
            style={{
              background: '#0d1117',
              border: '1px solid #1e293b',
              borderTop: '2px solid #ef4444',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            <Statistic
              title={<span style={{ color: '#94a3b8', fontSize: 12 }}>待审核结论</span>}
              value={stats.pendingReview}
              prefix={<ExclamationCircleOutlined />}
              valueStyle={{ color: '#fca5a5', fontSize: 22, fontWeight: 700 }}
            />
          </Card>
        </Col>
      </Row>

      {/* 一键智能研判 */}
      <Card
        style={{
          marginBottom: 24,
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          border: 'none',
        }}
        bodyStyle={{ padding: '24px 32px' }}
      >
        <Row align="middle" justify="space-between">
          <Col>
            <Space direction="vertical" size={4}>
              <Space>
                <ThunderboltOutlined style={{ fontSize: 28, color: '#fff' }} />
                <Title level={4} style={{ color: '#fff', margin: 0 }}>
                  一键智能研判
                </Title>
              </Space>
              <Text style={{ color: 'rgba(255,255,255,0.85)' }}>
                自动分析热点区域、识别潜在团伙、生成部署建议
              </Text>
            </Space>
          </Col>
          <Col>
            <Button
              type="primary"
              size="large"
              ghost
              icon={<ThunderboltOutlined />}
              onClick={() => smartAnalysisMutation.mutate()}
              loading={smartAnalysisMutation.isPending}
              style={{ borderColor: '#fff', color: '#fff' }}
            >
              {smartAnalysisMutation.isPending ? '分析中...' : '开始研判'}
            </Button>
          </Col>
        </Row>
      </Card>

      {/* 快捷操作 */}
      <Card title="快捷操作" style={{ marginBottom: 24 }}>
        <Row gutter={[16, 16]}>
          {quickActions.map((action, index) => (
            <Col xs={12} sm={8} md={6} lg={4} key={index}>
              <Card
                hoverable
                onClick={action.onClick}
                style={{ textAlign: 'center' }}
                bodyStyle={{ padding: 16 }}
              >
                <div
                  style={{
                    fontSize: 28,
                    color: action.color,
                    marginBottom: 8,
                  }}
                >
                  {action.icon}
                </div>
                <div style={{ fontWeight: 500, marginBottom: 4 }}>{action.title}</div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {action.description}
                </Text>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      <Row gutter={[16, 16]}>
        {/* 待处理任务 */}
        <Col xs={24} lg={8}>
          <Card
            title={
              <Space>
                <ClockCircleOutlined />
                待处理任务
                {pendingTasks.length > 0 && (
                  <Tag color="red">{pendingTasks.length}</Tag>
                )}
              </Space>
            }
            extra={
              <Button type="link" size="small" onClick={() => navigate('/meetings')}>
                查看全部 <ArrowRightOutlined />
              </Button>
            }
          >
            {pendingTasks.length === 0 ? (
              <Empty description="暂无待处理任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <List
                size="small"
                dataSource={pendingTasks}
                renderItem={(item) => (
                  <List.Item
                    style={{ cursor: 'pointer' }}
                    onClick={() => {
                      if (item.type === 'meeting') {
                        navigate(`/meetings?meetingId=${item.id}`)
                      } else {
                        navigate('/conclusions')
                      }
                    }}
                  >
                    <List.Item.Meta
                      title={
                        <Space>
                          <span>{item.title}</span>
                          <Tag color={statusColors[item.status]}>
                            {statusLabels[item.status]}
                          </Tag>
                        </Space>
                      }
                      description={dayjs(item.time).fromNow()}
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>

        {/* 最近案件 */}
        <Col xs={24} lg={8}>
          <Card
            title={
              <Space>
                <DatabaseOutlined />
                最近案件
              </Space>
            }
            extra={
              <Button type="link" size="small" onClick={() => navigate('/cases')}>
                查看全部 <ArrowRightOutlined />
              </Button>
            }
          >
            {recentCases.length === 0 ? (
              <Empty description="暂无案件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <List
                size="small"
                dataSource={recentCases}
                renderItem={(item) => (
                  <List.Item
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/cases?caseId=${item.id}`)}
                  >
                    <List.Item.Meta
                      title={
                        <Space>
                          <span>{item.case_number}</span>
                          <Tag color={statusColors[item.status]}>
                            {statusLabels[item.status] || item.status}
                          </Tag>
                        </Space>
                      }
                      description={
                        <Space split="·">
                          <span>{item.location || '未知地点'}</span>
                          <span>{dayjs(item.occurred_time).format('MM-DD HH:mm')}</span>
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>

        {/* 最近会议 */}
        <Col xs={24} lg={8}>
          <Card
            title={
              <Space>
                <TeamOutlined />
                最近会议
              </Space>
            }
            extra={
              <Button type="link" size="small" onClick={() => navigate('/meetings')}>
                查看全部 <ArrowRightOutlined />
              </Button>
            }
          >
            {recentMeetings.length === 0 ? (
              <Empty description="暂无会议" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <List
                size="small"
                dataSource={recentMeetings}
                renderItem={(item) => (
                  <List.Item
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/meetings?meetingId=${item.meeting_id}`)}
                  >
                    <List.Item.Meta
                      title={
                        <Space>
                          <span>会议 {item.meeting_id.slice(0, 8)}...</span>
                          <Tag color={statusColors[item.status]}>
                            {statusLabels[item.status] || item.status}
                          </Tag>
                        </Space>
                      }
                      description={
                        <Space split="·">
                          <span>{item.case_ids?.length || 0} 个案件</span>
                          <span>{dayjs(item.created_at).fromNow()}</span>
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
      </Row>

      {/* 智能研判结果模态框 */}
      <Modal
        title={
          <Space>
            <ThunderboltOutlined style={{ color: '#722ed1' }} />
            智能研判报告
          </Space>
        }
        open={analysisModalVisible}
        onCancel={() => {
          setAnalysisModalVisible(false)
          setAnalysisResult(null)
        }}
        footer={[
          <Button key="close" onClick={() => setAnalysisModalVisible(false)}>
            关闭
          </Button>,
          <Button
            key="deployment"
            type="primary"
            onClick={() => {
              setAnalysisModalVisible(false)
              navigate('/deployment')
            }}
          >
            查看详细部署建议
          </Button>,
        ]}
        width={900}
      >
        {analysisResult && (
          <div>
            {/* 整体风险评估 */}
            <Alert
              message={
                <Space>
                  {analysisResult.summary.overall_risk_level === 'critical' && (
                    <FireOutlined style={{ color: '#ff4d4f' }} />
                  )}
                  {analysisResult.summary.overall_risk_level === 'high' && (
                    <WarningOutlined style={{ color: '#fa8c16' }} />
                  )}
                  {analysisResult.summary.overall_risk_level === 'medium' && (
                    <ExclamationCircleOutlined style={{ color: '#faad14' }} />
                  )}
                  {analysisResult.summary.overall_risk_level === 'low' && (
                    <SafetyCertificateOutlined style={{ color: '#52c41a' }} />
                  )}
                  <span>
                    整体风险等级：
                    <Tag
                      color={
                        analysisResult.summary.overall_risk_level === 'critical'
                          ? 'red'
                          : analysisResult.summary.overall_risk_level === 'high'
                            ? 'orange'
                            : analysisResult.summary.overall_risk_level === 'medium'
                              ? 'gold'
                              : 'green'
                      }
                    >
                      {analysisResult.summary.overall_risk_level === 'critical'
                        ? '极高风险'
                        : analysisResult.summary.overall_risk_level === 'high'
                          ? '高风险'
                          : analysisResult.summary.overall_risk_level === 'medium'
                            ? '中风险'
                            : '低风险'}
                    </Tag>
                  </span>
                  <Progress
                    percent={analysisResult.summary.overall_risk_score}
                    size="small"
                    style={{ width: 100 }}
                    status={analysisResult.summary.overall_risk_score >= 70 ? 'exception' : 'active'}
                  />
                </Space>
              }
              type={
                analysisResult.summary.overall_risk_level === 'critical' ||
                analysisResult.summary.overall_risk_level === 'high'
                  ? 'error'
                  : analysisResult.summary.overall_risk_level === 'medium'
                    ? 'warning'
                    : 'success'
              }
              showIcon
              style={{ marginBottom: 16 }}
            />

            {/* 关键洞察 */}
            {analysisResult.summary.key_insights.length > 0 && (
              <Card size="small" title="关键洞察" style={{ marginBottom: 16 }}>
                <List
                  size="small"
                  dataSource={analysisResult.summary.key_insights}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            )}

            {/* 优先行动 */}
            {analysisResult.priority_actions.length > 0 && (
              <Card size="small" title="优先行动" style={{ marginBottom: 16 }}>
                <Timeline
                  items={analysisResult.priority_actions.map((action) => ({
                    color: action.priority === 1 ? 'red' : action.priority === 2 ? 'orange' : 'blue',
                    children: (
                      <div>
                        <Text strong>{action.action}</Text>
                        <br />
                        <Text type="secondary">{action.description}</Text>
                      </div>
                    ),
                  }))}
                />
              </Card>
            )}

            {/* 详细分析 */}
            <Collapse
              items={[
                {
                  key: 'hotspots',
                  label: (
                    <Space>
                      <EnvironmentOutlined />
                      热点区域分析
                      <Tag>{analysisResult.modules.hotspots?.hotspot_count || 0} 个热点</Tag>
                      {(analysisResult.modules.hotspots?.high_risk_count || 0) > 0 && (
                        <Tag color="red">
                          {analysisResult.modules.hotspots?.high_risk_count} 个高风险
                        </Tag>
                      )}
                    </Space>
                  ),
                  children: (
                    <Descriptions column={2} size="small">
                      <Descriptions.Item label="分析案件数">
                        {analysisResult.modules.hotspots?.case_count || 0}
                      </Descriptions.Item>
                      <Descriptions.Item label="识别热点数">
                        {analysisResult.modules.hotspots?.hotspot_count || 0}
                      </Descriptions.Item>
                      <Descriptions.Item label="高风险热点">
                        {analysisResult.modules.hotspots?.high_risk_count || 0}
                      </Descriptions.Item>
                    </Descriptions>
                  ),
                },
                {
                  key: 'gangs',
                  label: (
                    <Space>
                      <TeamOutlined />
                      团伙识别分析
                      <Tag>{analysisResult.modules.gangs?.gang_count || 0} 个团伙</Tag>
                      {(analysisResult.modules.gangs?.high_risk_gang_count || 0) > 0 && (
                        <Tag color="red">
                          {analysisResult.modules.gangs?.high_risk_gang_count} 个高风险
                        </Tag>
                      )}
                    </Space>
                  ),
                  children: (
                    <Descriptions column={2} size="small">
                      <Descriptions.Item label="识别团伙数">
                        {analysisResult.modules.gangs?.gang_count || 0}
                      </Descriptions.Item>
                      <Descriptions.Item label="高风险团伙">
                        {analysisResult.modules.gangs?.high_risk_gang_count || 0}
                      </Descriptions.Item>
                      <Descriptions.Item label="涉及案件总数">
                        {analysisResult.modules.gangs?.total_cases_in_gangs || 0}
                      </Descriptions.Item>
                    </Descriptions>
                  ),
                },
                {
                  key: 'patterns',
                  label: (
                    <Space>
                      <ClockCircleOutlined />
                      作案模式分析
                    </Space>
                  ),
                  children: (
                    <div>
                      {analysisResult.modules.patterns?.patterns.peak_hours && (
                        <div style={{ marginBottom: 8 }}>
                          <Text strong>高发时段：</Text>
                          {analysisResult.modules.patterns.patterns.peak_hours.map((h) => (
                            <Tag key={h.hour}>
                              {h.hour}:00 ({h.count}起)
                            </Tag>
                          ))}
                        </div>
                      )}
                      {analysisResult.modules.patterns?.patterns.peak_days && (
                        <div>
                          <Text strong>高发日期：</Text>
                          {analysisResult.modules.patterns.patterns.peak_days.map((d) => (
                            <Tag key={d.day}>
                              {d.day} ({d.count}起)
                            </Tag>
                          ))}
                        </div>
                      )}
                    </div>
                  ),
                },
                {
                  key: 'deployment',
                  label: (
                    <Space>
                      <FileTextOutlined />
                      部署建议
                      <Tag>{analysisResult.modules.deployment?.suggestion_count || 0} 条建议</Tag>
                    </Space>
                  ),
                  children: (
                    <List
                      size="small"
                      dataSource={analysisResult.modules.deployment?.suggestions || []}
                      renderItem={(item) => (
                        <List.Item>
                          <List.Item.Meta
                            title={
                              <Space>
                                <Tag color={item.priority === 'high' ? 'red' : 'orange'}>
                                  {item.priority === 'high' ? '高优先级' : '中优先级'}
                                </Tag>
                                {item.action}
                              </Space>
                            }
                            description={item.reason}
                          />
                        </List.Item>
                      )}
                    />
                  ),
                },
              ]}
            />

            {/* 综合建议 */}
            {analysisResult.recommendations.length > 0 && (
              <Card size="small" title="综合建议" style={{ marginTop: 16 }}>
                <List
                  size="small"
                  dataSource={analysisResult.recommendations}
                  renderItem={(item, index) => (
                    <List.Item>
                      <Space>
                        <Tag color="blue">{index + 1}</Tag>
                        <Text>{item}</Text>
                      </Space>
                    </List.Item>
                  )}
                />
              </Card>
            )}

            {/* 分析耗时 */}
            <div style={{ marginTop: 16, textAlign: 'right' }}>
              <Text type="secondary">
                分析耗时：{analysisResult.duration_seconds?.toFixed(2) || '-'} 秒
              </Text>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

export default Home
