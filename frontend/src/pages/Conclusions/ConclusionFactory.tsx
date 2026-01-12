import React, { useState } from 'react'
import {
  Card,
  InputNumber,
  Button,
  Space,
  Table,
  Tag,
  message,
  Select,
  Drawer,
  Descriptions,
  List,
  Collapse,
  Spin,
} from 'antd'
import { useMutation, useQuery } from '@tanstack/react-query'
import { conclusionApi, Conclusion, ConclusionFilters } from '../../services/conclusions'
import { useNavigate } from 'react-router-dom'

const ConclusionFactory: React.FC = () => {
  const [caseId, setCaseId] = useState<number | null>(null)
  const [filters, setFilters] = useState<ConclusionFilters>({})
  const [detailId, setDetailId] = useState<number | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const navigate = useNavigate()

  const { data, refetch, isFetching } = useQuery({
    queryKey: ['conclusions', filters],
    queryFn: () => conclusionApi.list(filters),
  })

  const generateMutation = useMutation({
    mutationFn: (id: number) => conclusionApi.generate(id),
    onSuccess: () => {
      message.success('结论生成完成')
      refetch()
    },
    onError: (error: any) => {
      message.error(error?.response?.data?.detail || '结论生成失败')
    },
  })

  const reviewMutation = useMutation({
    mutationFn: (payload: { id: number; action: 'approve' | 'reject' | 'flag' }) =>
      conclusionApi.review(payload.id, payload.action),
    onSuccess: () => {
      message.success('已更新结论状态')
      refetch()
    },
    onError: (error: any) => {
      message.error(error?.response?.data?.detail || '操作失败')
    },
  })

  const { data: detail, isFetching: isDetailLoading } = useQuery({
    queryKey: ['conclusion-detail', detailId],
    queryFn: () => conclusionApi.get(detailId as number),
    enabled: detailOpen && !!detailId,
  })

  const columns = [
    { title: '结论ID', dataIndex: 'id', key: 'id' },
    { title: '案件ID', dataIndex: 'case_id', key: 'case_id' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (value: string) => {
        const color = value === 'published' ? 'green' : value === 'needs_review' ? 'orange' : 'red'
        return <Tag color={color}>{value}</Tag>
      },
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      key: 'confidence',
      render: (value: number) => value?.toFixed(2),
    },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      key: 'risk_level',
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: '异常原因',
      dataIndex: 'review_reason',
      key: 'review_reason',
      render: (value: string) => (value ? <Tag color="orange">{value}</Tag> : '-'),
    },
    {
      title: '摘要',
      dataIndex: 'summary',
      key: 'summary',
      ellipsis: true,
    },
    {
      title: '证据链',
      key: 'evidence',
      render: (_: any, record: Conclusion) => (
        <Button
          size="small"
          onClick={() => {
            setDetailId(record.id)
            setDetailOpen(true)
          }}
        >
          查看
        </Button>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: Conclusion) => (
        <Space>
          <Button
            size="small"
            onClick={() => reviewMutation.mutate({ id: record.id, action: 'approve' })}
          >
            通过
          </Button>
          <Button
            size="small"
            danger
            onClick={() => reviewMutation.mutate({ id: record.id, action: 'reject' })}
          >
            退回
          </Button>
          <Button
            size="small"
            onClick={() => reviewMutation.mutate({ id: record.id, action: 'flag' })}
          >
            标记风险
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Card title="结论工厂（低人力模式）">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Space wrap>
            <InputNumber
              placeholder="输入案件ID"
              value={caseId ?? undefined}
              onChange={(value) => setCaseId(value as number)}
            />
            <Button
              type="primary"
              onClick={() => {
                if (!caseId) {
                  message.warning('请先输入案件ID')
                  return
                }
                generateMutation.mutate(caseId)
              }}
              loading={generateMutation.isLoading}
            >
              一键生成结论
            </Button>
          </Space>
          <Space wrap>
            <Select
              placeholder="状态"
              allowClear
              style={{ width: 160 }}
              onChange={(value) => setFilters((prev) => ({ ...prev, status: value }))}
              options={[
                { value: 'draft', label: 'draft' },
                { value: 'needs_review', label: 'needs_review' },
                { value: 'published', label: 'published' },
                { value: 'flagged', label: 'flagged' },
                { value: 'rejected', label: 'rejected' },
              ]}
            />
            <Select
              placeholder="风险等级"
              allowClear
              style={{ width: 160 }}
              onChange={(value) => setFilters((prev) => ({ ...prev, risk_level: value }))}
              options={[
                { value: 'low', label: 'low' },
                { value: 'medium', label: 'medium' },
                { value: 'high', label: 'high' },
                { value: 'unknown', label: 'unknown' },
              ]}
            />
            <InputNumber
              placeholder="最低置信度"
              min={0}
              max={1}
              step={0.05}
              onChange={(value) => setFilters((prev) => ({ ...prev, min_confidence: value as number }))}
            />
            <InputNumber
              placeholder="最高置信度"
              min={0}
              max={1}
              step={0.05}
              onChange={(value) => setFilters((prev) => ({ ...prev, max_confidence: value as number }))}
            />
            <Button onClick={() => refetch()} loading={isFetching}>
              应用筛选
            </Button>
            <Button
              onClick={() => {
                const next = { status: 'needs_review' }
                setFilters(next)
              }}
            >
              异常队列
            </Button>
            <Button
              onClick={() => {
                setFilters({})
              }}
            >
              清空筛选
            </Button>
          </Space>
        </Space>
      </Card>

      <Card title="结论列表" loading={isFetching}>
        <Table
          rowKey="id"
          dataSource={data || []}
          columns={columns}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      <Drawer
        title="证据链详情"
        open={detailOpen}
        width={640}
        onClose={() => setDetailOpen(false)}
      >
        {isDetailLoading ? (
          <Spin />
        ) : detail ? (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="结论ID">{detail.id}</Descriptions.Item>
              <Descriptions.Item label="案件ID">{detail.case_id}</Descriptions.Item>
              <Descriptions.Item label="状态">{detail.status}</Descriptions.Item>
              <Descriptions.Item label="置信度">{detail.confidence?.toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="风险等级">{detail.risk_level}</Descriptions.Item>
              <Descriptions.Item label="摘要">{detail.summary}</Descriptions.Item>
            </Descriptions>

            <Collapse
              items={[
                {
                  key: 'key',
                  label: '关键证据',
                  children: (
                    <List
                      dataSource={detail.evidence?.key_evidence || []}
                      renderItem={(item: string) => <List.Item>{item}</List.Item>}
                    />
                  ),
                },
                {
                  key: 'case',
                  label: '案件详情',
                  children: (
                    <Space>
                      <span>案件编号：{detail.evidence?.raw?.case?.case_number || '-'}</span>
                      <Button
                        size="small"
                        onClick={() => navigate(`/cases?caseId=${detail.case_id}`)}
                      >
                        查看案件
                      </Button>
                    </Space>
                  ),
                },
                {
                  key: 'similar',
                  label: '相似案件',
                  children: (
                    <List
                      dataSource={detail.evidence?.raw?.similar_cases || []}
                      renderItem={(item: any) => (
                        <List.Item>
                          <Space>
                            <Tag>案件 {item.case_id}</Tag>
                            <span>相似度 {item.similarity}</span>
                            <span>{item.metadata?.case_type || ''}</span>
                            <Button
                              size="small"
                              onClick={() => navigate(`/cases?caseId=${item.case_id}`)}
                            >
                              查看案件
                            </Button>
                          </Space>
                        </List.Item>
                      )}
                    />
                  ),
                },
                {
                  key: 'meetings',
                  label: '关联会议',
                  children: (
                    <List
                      dataSource={detail.evidence?.raw?.related_meetings || []}
                      renderItem={(item: any) => (
                        <List.Item>
                          <Space>
                            <Tag>{item.meeting_id}</Tag>
                            <span>{item.status}</span>
                            <Button
                              size="small"
                              onClick={() => navigate(`/meetings?meetingId=${item.meeting_id}`)}
                            >
                              查看会议
                            </Button>
                          </Space>
                        </List.Item>
                      )}
                    />
                  ),
                },
                {
                  key: 'reports',
                  label: '关联报告',
                  children: (
                    <List
                      dataSource={detail.evidence?.raw?.related_reports || []}
                      renderItem={(item: any) => (
                        <List.Item>
                          <Space>
                            <Tag>报告 {item.report_id}</Tag>
                            <span>{item.report_type}</span>
                            <Button
                              size="small"
                              onClick={() => navigate(`/meetings?meetingId=${item.meeting_id}`)}
                            >
                              查看报告
                            </Button>
                          </Space>
                        </List.Item>
                      )}
                    />
                  ),
                },
                {
                  key: 'raw',
                  label: '原始证据',
                  children: (
                    <pre style={{ whiteSpace: 'pre-wrap' }}>
                      {JSON.stringify(detail.evidence?.raw || {}, null, 2)}
                    </pre>
                  ),
                },
              ]}
            />
          </Space>
        ) : (
          <div>暂无证据数据</div>
        )}
      </Drawer>
    </Space>
  )
}

export default ConclusionFactory
