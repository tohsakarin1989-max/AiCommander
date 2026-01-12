import React, { useEffect, useState } from 'react'
import {
  Table,
  Button,
  Modal,
  Form,
  Select,
  message,
  Space,
  Tag,
  Card,
  Timeline,
  Descriptions,
  Tabs,
  List,
  Typography,
  Divider,
  Badge,
  Alert,
} from 'antd'
import { PlusOutlined, EyeOutlined, TrophyOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { meetingApi, Meeting, MeetingCreate } from '../../services/meetings'
import { modelApi } from '../../services/models'
import { caseApi } from '../../services/cases'
import { systemConfigApi } from '../../services/systemConfig'
import dayjs from 'dayjs'
import { useSearchParams } from 'react-router-dom'

const { Title, Paragraph, Text } = Typography

const { Option } = Select

const Meetings: React.FC = () => {
  const [form] = Form.useForm()
  const [isModalVisible, setIsModalVisible] = useState(false)
  const [viewModalVisible, setViewModalVisible] = useState(false)
  const [selectedMeeting, setSelectedMeeting] = useState<string | null>(null)
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()

  const { data: meetings, isLoading } = useQuery({
    queryKey: ['meetings'],
    queryFn: () => meetingApi.getMeetings(),
  })

  useEffect(() => {
    const meetingId = searchParams.get('meetingId')
    if (!meetingId || !meetings) return
    const exists = meetings.some((m) => m.meeting_id === meetingId)
    if (exists) {
      setSelectedMeeting(meetingId)
      setViewModalVisible(true)
    }
  }, [searchParams, meetings])

  const { data: models } = useQuery({
    queryKey: ['models'],
    queryFn: () => modelApi.getModels(),
  })

  const { data: cases } = useQuery({
    queryKey: ['cases'],
    queryFn: () => caseApi.getCases(),
  })

  // 获取圆桌会议配置
  const { data: meetingConfig } = useQuery({
    queryKey: ['meetingConfig'],
    queryFn: () => systemConfigApi.getMeetingConfig(),
  })

  const { data: conversations } = useQuery({
    queryKey: ['conversations', selectedMeeting],
    queryFn: () => meetingApi.getConversations(selectedMeeting!),
    enabled: !!selectedMeeting,
  })

  const { data: report } = useQuery({
    queryKey: ['report', selectedMeeting],
    queryFn: () => meetingApi.getReport(selectedMeeting!),
    enabled: !!selectedMeeting,
  })

  const { data: analyses } = useQuery({
    queryKey: ['analyses', selectedMeeting],
    queryFn: () => meetingApi.getAnalyses(selectedMeeting!),
    enabled: !!selectedMeeting,
  })

  const { data: rankings } = useQuery({
    queryKey: ['rankings', selectedMeeting],
    queryFn: () => meetingApi.getRankings(selectedMeeting!),
    enabled: !!selectedMeeting,
  })

  const createMutation = useMutation({
    mutationFn: meetingApi.createMeeting,
    onSuccess: (data) => {
      message.success('会议已创建，正在后台处理中，请稍后查看结果')
      setIsModalVisible(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['meetings'] })
      
      // 如果会议正在处理中，自动轮询状态
      if (data.status === 'processing' && data.meeting_id) {
        // 每3秒轮询一次会议状态
        const pollInterval = setInterval(() => {
          queryClient.invalidateQueries({ queryKey: ['meetings'] })
          // 检查会议是否完成
          queryClient.fetchQuery({
            queryKey: ['meeting', data.meeting_id],
            queryFn: () => meetingApi.getMeeting(data.meeting_id),
          }).then((meeting: Meeting) => {
            if (meeting.status === 'completed' || meeting.status === 'failed') {
              clearInterval(pollInterval)
              message.success('会议分析完成！')
              queryClient.invalidateQueries({ queryKey: ['meetings'] })
            }
          }).catch(() => {
            // 忽略错误，继续轮询
          })
        }, 3000)
        
        // 60秒后停止轮询（避免无限轮询）
        setTimeout(() => {
          clearInterval(pollInterval)
        }, 60000)
      }
    },
    onError: (error: any) => {
      message.error(`创建失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleCreate = () => {
    form.resetFields()
    setIsModalVisible(true)
  }

  const handleView = (meeting: Meeting) => {
    setSelectedMeeting(meeting.meeting_id)
    setViewModalVisible(true)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      createMutation.mutate(values as MeetingCreate)
    } catch (error) {
      console.error('Validation failed:', error)
    }
  }

  const getStatusTag = (status: string) => {
    const statusMap: Record<string, { color: string; text: string }> = {
      pending: { color: 'default', text: '待开始' },
      processing: { color: 'processing', text: '处理中' },
      first_opinions: { color: 'processing', text: '第一阶段：第一意见' },
      reviewing: { color: 'processing', text: '第二阶段：复习排名' },
      ranking: { color: 'processing', text: '排名中' },
      finalizing: { color: 'processing', text: '第三阶段：最终回应' },
      completed: { color: 'success', text: '已完成' },
      failed: { color: 'error', text: '失败' },
    }
    const statusInfo = statusMap[status] || { color: 'default', text: status }
    return <Tag color={statusInfo.color}>{statusInfo.text}</Tag>
  }

  const columns = [
    {
      title: '会议ID',
      dataIndex: 'meeting_id',
      key: 'meeting_id',
    },
    {
      title: '案件数量',
      dataIndex: 'case_ids',
      key: 'case_ids',
      render: (ids: number[]) => ids.length,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: getStatusTag,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (time: string) => dayjs(time).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Meeting) => (
        <Button type="link" icon={<EyeOutlined />} onClick={() => handleView(record)}>
          查看
        </Button>
      ),
    },
  ]

  const moderatorModels = models?.filter((m) => m.role === 'moderator') || []
  const analystModels = models?.filter((m) => m.role === 'analyst') || []

  return (
    <div>
      <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between' }}>
        <h2>圆桌会议</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          创建会议
        </Button>
      </div>

      {meetingConfig?.provider === 'openrouter' && !meetingConfig?.api_key && (
        <Alert
          message="圆桌会议API配置缺失"
          description={
            <div>
              <p>当前选择OpenRouter模式，但未配置API密钥。</p>
              <p>
                请前往 <a href="/settings">系统设置</a> 配置OpenRouter API密钥，或切换到Direct模式。
              </p>
            </div>
          }
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {meetingConfig?.provider === 'direct' && (
        <Alert
          message="当前使用Direct模式"
          description="圆桌会议将直接使用「AI模型配置」中配置的模型API密钥，无需额外配置。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          closable
        />
      )}

      <Table
        columns={columns}
        dataSource={meetings}
        loading={isLoading}
        rowKey="meeting_id"
        pagination={{ pageSize: 10 }}
      />

      <Modal
        title="创建会议"
        open={isModalVisible}
        onOk={handleSubmit}
        onCancel={() => {
          setIsModalVisible(false)
          form.resetFields()
        }}
        width={600}
        confirmLoading={createMutation.isPending}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="case_ids"
            label="选择案件"
            rules={[{ required: true, message: '请选择至少一个案件' }]}
          >
            <Select mode="multiple" placeholder="选择案件">
              {cases?.map((c) => (
                <Option key={c.id} value={c.id}>
                  {c.case_number} - {c.location}
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="moderator_model_id"
            label="主持人模型"
            rules={[{ required: true, message: '请选择主持人模型' }]}
          >
            <Select placeholder="选择主持人模型">
              {moderatorModels.map((m) => (
                <Option key={m.id} value={m.id}>
                  {m.name} ({m.model_name})
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="analyst_model_ids"
            label="分析员模型"
            rules={[{ required: true, message: '请选择至少一个分析员模型' }]}
          >
            <Select mode="multiple" placeholder="选择分析员模型">
              {analystModels.map((m) => (
                <Option key={m.id} value={m.id}>
                  {m.name} ({m.model_name})
                </Option>
              ))}
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="会议详情 - LLM委员会三阶段流程"
        open={viewModalVisible}
        onCancel={() => {
          setViewModalVisible(false)
          setSelectedMeeting(null)
        }}
        width={1200}
        footer={null}
      >
        {selectedMeeting && (
          <Tabs
            defaultActiveKey="stage1"
            items={[
              {
                key: 'stage1',
                label: (
                  <span>
                    <Badge count={analyses?.length || 0} offset={[8, 0]}>
                      第一阶段：第一意见
                    </Badge>
                  </span>
                ),
                children: (
                  <div>
                    <Paragraph>
                      所有LLM模型独立分析案件信息，每个模型给出自己的判断（类似标签视图）。
                    </Paragraph>
                    <Tabs
                      type="card"
                      items={analyses?.map((analysis, index) => {
                        const model = models?.find((m) => m.id === analysis.analyst_model_id)
                        return {
                          key: `analysis-${index}`,
                          label: model?.name || `分析 ${index + 1}`,
                          children: (
                            <Card>
                              <pre style={{ whiteSpace: 'pre-wrap', fontSize: '12px' }}>
                                {JSON.stringify(analysis.result_content, null, 2)}
                              </pre>
                            </Card>
                          ),
                        }
                      }) || []}
                    />
                  </div>
                ),
              },
              {
                key: 'stage2',
                label: (
                  <span>
                    <TrophyOutlined /> 第二阶段：复习和排名
                  </span>
                ),
                children: (
                  <div>
                    <Paragraph>
                      每个LLM匿名审查其他LLM的回答，基于准确性和洞察力进行排名。
                    </Paragraph>
                    {rankings?.filter((r) => r.stage === 'review').map((ranking, index) => {
                      const model = models?.find((m) => m.id === ranking.evaluator_model_id)
                      return (
                        <Card
                          key={index}
                          title={`${model?.name || '模型'} 的排名结果`}
                          style={{ marginBottom: 16 }}
                        >
                          {ranking.ranking_data?.rankings?.length > 0 ? (
                            <List
                              dataSource={ranking.ranking_data.rankings}
                              renderItem={(item: any, idx: number) => (
                                <List.Item>
                                  <Space>
                                    <Badge
                                      count={item.rank}
                                      style={{ backgroundColor: idx < 3 ? '#52c41a' : '#d9d9d9' }}
                                    />
                                    <div>
                                      <Text strong>匿名ID: {item.anonymous_id}</Text>
                                      <br />
                                      <Text type="secondary">得分: {item.score}/10</Text>
                                      <br />
                                      <Text>{item.reasoning}</Text>
                                    </div>
                                  </Space>
                                </List.Item>
                              )}
                            />
                          ) : (
                            <Text type="secondary">暂无排名数据</Text>
                          )}
                          {ranking.ranking_data?.overall_comment && (
                            <>
                              <Divider />
                              <Text strong>整体评价：</Text>
                              <Paragraph>{ranking.ranking_data.overall_comment}</Paragraph>
                            </>
                          )}
                        </Card>
                      )
                    })}
                    {rankings?.find((r) => r.stage === 'final') && (
                      <Card title="综合排名统计" style={{ marginTop: 16 }}>
                        <Descriptions column={1} bordered>
                          {Object.entries(
                            rankings.find((r) => r.stage === 'final')?.aggregated_data?.rankings || {}
                          ).map(([index, data]: [string, any]) => (
                            <Descriptions.Item
                              key={index}
                              label={`分析结果 ${parseInt(index) + 1}`}
                            >
                              <Space>
                                <Text>平均得分: {data.average_score}</Text>
                                <Text type="secondary">平均排名: {data.average_rank}</Text>
                                <Text type="secondary">获得 {data.vote_count} 个评价</Text>
                              </Space>
                            </Descriptions.Item>
                          ))}
                        </Descriptions>
                      </Card>
                    )}
                  </div>
                ),
              },
              {
                key: 'stage3',
                label: '第三阶段：最终回应',
                children: (
                  <div>
                    <Paragraph>
                      主席级LLM汇总所有回答和排名，生成最终综合分析报告。
                    </Paragraph>
                    {report && (
                      <Card>
                        <Title level={4}>执行摘要</Title>
                        <Paragraph>{report.content?.summary || '无'}</Paragraph>

                        <Divider />

                        <Title level={4}>共识点</Title>
                        <List
                          dataSource={report.content?.consensus_points || []}
                          renderItem={(item) => <List.Item>{item}</List.Item>}
                        />

                        <Divider />

                        <Title level={4}>分歧点</Title>
                        <List
                          dataSource={report.content?.disagreement_points || []}
                          renderItem={(item) => <List.Item>{item}</List.Item>}
                        />

                        {report.content?.top_ranked_insights && (
                          <>
                            <Divider />
                            <Title level={4}>来自排名靠前分析的关键洞察</Title>
                            <List
                              dataSource={report.content.top_ranked_insights}
                              renderItem={(item) => <List.Item>{item}</List.Item>}
                            />
                          </>
                        )}

                        <Divider />

                        <Title level={4}>综合结论</Title>
                        <Paragraph>{report.content?.conclusions || '无'}</Paragraph>

                        <Divider />

                        <Title level={4}>建议</Title>
                        <List
                          dataSource={report.content?.recommendations || []}
                          renderItem={(item) => <List.Item>{item}</List.Item>}
                        />

                        {report.content?.model_contributions && (
                          <>
                            <Divider />
                            <Title level={4}>各模型贡献</Title>
                            <Descriptions column={1} bordered>
                              {Object.entries(report.content.model_contributions).map(
                                ([key, value]: [string, any]) => (
                                  <Descriptions.Item key={key} label={key}>
                                    {value}
                                  </Descriptions.Item>
                                )
                              )}
                            </Descriptions>
                          </>
                        )}

                        {report.content?.ranking_summary && (
                          <>
                            <Divider />
                            <Title level={4}>排名结果说明</Title>
                            <Paragraph>{report.content.ranking_summary}</Paragraph>
                          </>
                        )}
                      </Card>
                    )}
                  </div>
                ),
              },
              {
                key: 'timeline',
                label: '完整时间线',
                children: (
                  <Card>
                    <Timeline>
                      {conversations?.map((conv) => {
                        const model = models?.find((m) => m.id === conv.speaker_model_id)
                        const stageNames: Record<number, string> = {
                          0: '案件信息',
                          1: '第一阶段：第一意见',
                          2: '第二阶段：复习排名',
                          3: '第三阶段：最终回应',
                        }
                        return (
                          <Timeline.Item key={conv.id}>
                            <div>
                              <Text strong>
                                {stageNames[conv.round_number] || `轮次 ${conv.round_number}`}
                              </Text>
                              {' - '}
                              <Text type="secondary">
                                {model?.name || '未知模型'} ({conv.message_type})
                              </Text>
                              <div style={{ marginTop: 8, padding: 8, background: '#f5f5f5' }}>
                                {conv.content.length > 500 ? (
                                  <>
                                    {conv.content.substring(0, 500)}...
                                    <Button
                                      type="link"
                                      size="small"
                                      onClick={() => {
                                        Modal.info({
                                          title: '完整内容',
                                          content: <pre style={{ whiteSpace: 'pre-wrap' }}>{conv.content}</pre>,
                                          width: 800,
                                        })
                                      }}
                                    >
                                      查看完整内容
                                    </Button>
                                  </>
                                ) : (
                                  conv.content
                                )}
                              </div>
                            </div>
                          </Timeline.Item>
                        )
                      })}
                    </Timeline>
                  </Card>
                ),
              },
            ]}
          />
        )}
      </Modal>
    </div>
  )
}

export default Meetings
