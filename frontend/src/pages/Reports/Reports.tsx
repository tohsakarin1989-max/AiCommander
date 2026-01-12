import React, { useState } from 'react'
import {
  Card,
  Descriptions,
  Tag,
  Button,
  Space,
  Modal,
  Typography,
  Divider,
  Alert,
  Collapse,
  List,
  message,
} from 'antd'
import {
  EyeOutlined,
  DownloadOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  BulbOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { meetingApi } from '../../services/meetings'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'

const { Title, Paragraph, Text } = Typography
const { Panel } = Collapse

const Reports: React.FC = () => {
  const navigate = useNavigate()
  const { data: meetings, isLoading } = useQuery({
    queryKey: ['meetings'],
    queryFn: () => meetingApi.getMeetings(),
  })

  const completedMeetings = meetings?.filter((m) => m.status === 'completed') || []

  const handleExportReport = (meetingId: string, report: any) => {
    try {
      const reportData = {
        meeting_id: meetingId,
        generated_at: new Date().toISOString(),
        summary: report.content?.summary || '',
        consensus_points: report.consensus_points || [],
        disagreement_points: report.disagreement_points || [],
        recommendations: report.content?.recommendations || [],
        top_ranked_insights: report.content?.top_ranked_insights || [],
        conclusions: report.content?.conclusions || '',
      }
      
      const blob = new Blob([JSON.stringify(reportData, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `报告_${meetingId}_${dayjs().format('YYYYMMDD_HHmmss')}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success('报告导出成功')
    } catch (error) {
      message.error('导出失败')
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Title level={2}>分析报告</Title>
        <Button onClick={() => navigate('/meetings')}>查看所有会议</Button>
      </div>

      {isLoading ? (
        <Card loading>加载中...</Card>
      ) : completedMeetings.length === 0 ? (
        <Alert
          message="暂无报告"
          description="请先创建并完成圆桌会议，完成后会在此显示分析报告。"
          type="info"
          showIcon
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {completedMeetings.map((meeting) => (
            <ReportCard
              key={meeting.meeting_id}
              meetingId={meeting.meeting_id}
              meeting={meeting}
              onExport={handleExportReport}
              onViewDetail={() => navigate(`/meetings?meetingId=${meeting.meeting_id}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface ReportCardProps {
  meetingId: string
  meeting?: any
  onExport: (meetingId: string, report: any) => void
  onViewDetail: () => void
}

const ReportCard: React.FC<ReportCardProps> = ({ meetingId, meeting, onExport, onViewDetail }) => {
  const [detailModalVisible, setDetailModalVisible] = useState(false)
  const { data: report, isLoading } = useQuery({
    queryKey: ['report', meetingId],
    queryFn: () => meetingApi.getReport(meetingId),
  })

  const { data: analyses } = useQuery({
    queryKey: ['analyses', meetingId],
    queryFn: () => meetingApi.getAnalyses(meetingId),
    enabled: detailModalVisible,
  })

  const { data: rankings } = useQuery({
    queryKey: ['rankings', meetingId],
    queryFn: () => meetingApi.getRankings(meetingId),
    enabled: detailModalVisible,
  })

  if (isLoading) return <Card loading>加载中...</Card>
  if (!report) return null

  const reportContent = typeof report.content === 'string' 
    ? report.content 
    : report.content

  return (
    <>
      <Card
        title={
          <Space>
            <FileTextOutlined />
            <span>报告 - {meetingId}</span>
            {meeting && (
              <Tag color="blue">
                {dayjs(meeting.completed_at || meeting.created_at).format('YYYY-MM-DD HH:mm')}
              </Tag>
            )}
          </Space>
        }
        extra={
          <Space>
            <Button
              type="primary"
              icon={<EyeOutlined />}
              onClick={() => setDetailModalVisible(true)}
            >
              查看详情
            </Button>
            <Button
              icon={<DownloadOutlined />}
              onClick={() => onExport(meetingId, report)}
            >
              导出报告
            </Button>
            <Button icon={<EyeOutlined />} onClick={onViewDetail}>
              查看会议
            </Button>
          </Space>
        }
      >
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="执行摘要">
            <Paragraph ellipsis={{ rows: 3, expandable: true }}>
              {reportContent?.summary || reportContent || '无'}
            </Paragraph>
          </Descriptions.Item>
          <Descriptions.Item label="共识点">
            {report.consensus_points && report.consensus_points.length > 0 ? (
              <List
                size="small"
                dataSource={report.consensus_points}
                renderItem={(point: string, i: number) => (
                  <List.Item>
                    <Space>
                      <CheckCircleOutlined style={{ color: '#52c41a' }} />
                      <Text>{point}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">无</Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="分歧点">
            {report.disagreement_points && report.disagreement_points.length > 0 ? (
              <List
                size="small"
                dataSource={report.disagreement_points}
                renderItem={(point: string, i: number) => (
                  <List.Item>
                    <Space>
                      <ExclamationCircleOutlined style={{ color: '#faad14' }} />
                      <Text>{point}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">无</Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="关键洞察">
            {reportContent?.top_ranked_insights && reportContent.top_ranked_insights.length > 0 ? (
              <List
                size="small"
                dataSource={reportContent.top_ranked_insights}
                renderItem={(insight: string, i: number) => (
                  <List.Item>
                    <Space>
                      <BulbOutlined style={{ color: '#1890ff' }} />
                      <Text>{insight}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">无</Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="建议">
            {reportContent?.recommendations && reportContent.recommendations.length > 0 ? (
              <List
                size="small"
                dataSource={reportContent.recommendations}
                renderItem={(rec: string, i: number) => (
                  <List.Item>
                    <Text>• {rec}</Text>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">无</Text>
            )}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Modal
        title={
          <Space>
            <FileTextOutlined />
            <span>报告详情 - {meetingId}</span>
          </Space>
        }
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            关闭
          </Button>,
          <Button
            key="export"
            type="primary"
            icon={<DownloadOutlined />}
            onClick={() => {
              onExport(meetingId, report)
              setDetailModalVisible(false)
            }}
          >
            导出报告
          </Button>,
          <Button key="view" icon={<EyeOutlined />} onClick={onViewDetail}>
            查看完整会议
          </Button>,
        ]}
        width={900}
      >
        <Collapse defaultActiveKey={['summary', 'consensus', 'recommendations']}>
          <Panel header="执行摘要" key="summary">
            <Paragraph>{reportContent?.summary || reportContent || '无'}</Paragraph>
          </Panel>
          
          {reportContent?.conclusions && (
            <Panel header="综合结论" key="conclusions">
              <Paragraph>{reportContent.conclusions}</Paragraph>
            </Panel>
          )}

          <Panel header="共识点" key="consensus">
            {report.consensus_points && report.consensus_points.length > 0 ? (
              <List
                dataSource={report.consensus_points}
                renderItem={(point: string, i: number) => (
                  <List.Item>
                    <Space>
                      <CheckCircleOutlined style={{ color: '#52c41a' }} />
                      <Text>{point}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">无共识点</Text>
            )}
          </Panel>

          <Panel header="分歧点" key="disagreement">
            {report.disagreement_points && report.disagreement_points.length > 0 ? (
              <List
                dataSource={report.disagreement_points}
                renderItem={(point: string, i: number) => (
                  <List.Item>
                    <Space>
                      <ExclamationCircleOutlined style={{ color: '#faad14' }} />
                      <Text>{point}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">无分歧点</Text>
            )}
          </Panel>

          {reportContent?.top_ranked_insights && reportContent.top_ranked_insights.length > 0 && (
            <Panel header="关键洞察（来自排名靠前的分析）" key="insights">
              <List
                dataSource={reportContent.top_ranked_insights}
                renderItem={(insight: string, i: number) => (
                  <List.Item>
                    <Space>
                      <BulbOutlined style={{ color: '#1890ff' }} />
                      <Text>{insight}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            </Panel>
          )}

          <Panel header="建议" key="recommendations">
            {reportContent?.recommendations && reportContent.recommendations.length > 0 ? (
              <List
                dataSource={reportContent.recommendations}
                renderItem={(rec: string, i: number) => (
                  <List.Item>
                    <Text>• {rec}</Text>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">无建议</Text>
            )}
          </Panel>

          {analyses && analyses.length > 0 && (
            <Panel header={`第一阶段分析（${analyses.length} 个独立回答）`} key="analyses">
              <Alert
                message="第一意见阶段"
                description="以下是所有LLM模型的独立分析结果"
                type="info"
                style={{ marginBottom: 16 }}
              />
              <Collapse>
                {analyses.map((analysis: any, index: number) => (
                  <Panel
                    header={`分析结果 ${index + 1}`}
                    key={index}
                  >
                    <pre style={{ whiteSpace: 'pre-wrap', fontSize: '12px' }}>
                      {typeof analysis.result_content === 'string'
                        ? analysis.result_content
                        : JSON.stringify(analysis.result_content, null, 2)}
                    </pre>
                  </Panel>
                ))}
              </Collapse>
            </Panel>
          )}

          {rankings && rankings.length > 0 && (
            <Panel header="第二阶段排名结果" key="rankings">
              <Alert
                message="审查和排名阶段"
                description="以下是各LLM对其他分析的排名和评价"
                type="info"
                style={{ marginBottom: 16 }}
              />
              <Collapse>
                {rankings.map((ranking: any, index: number) => (
                  <Panel
                    header={`评价者 ${index + 1} 的排名`}
                    key={index}
                  >
                    <pre style={{ whiteSpace: 'pre-wrap', fontSize: '12px' }}>
                      {JSON.stringify(ranking, null, 2)}
                    </pre>
                  </Panel>
                ))}
              </Collapse>
            </Panel>
          )}

          {reportContent?.model_contributions && Object.keys(reportContent.model_contributions).length > 0 && (
            <Panel header="各模型的独特贡献" key="contributions">
              <List
                dataSource={Object.entries(reportContent.model_contributions)}
                renderItem={([model, contribution]: [string, any]) => (
                  <List.Item>
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <Text strong>分析结果 {model}：</Text>
                      <Text>{contribution}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            </Panel>
          )}
        </Collapse>
      </Modal>
    </>
  )
}

export default Reports

