import { useMemo, useState } from 'react'
import { DatePicker, Form, Input, InputNumber, Modal, Select, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { eventApi } from '../../services/events'
import type { Event, EventCreateData } from '../../types'
import { EVENT_TYPES } from '../../types/event'
import './EventCenter.css'

const { TextArea } = Input
const { Option } = Select

const RISK_LABELS: Record<string, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  critical: '极高风险',
}

const EventCenter: React.FC = () => {
  const [form] = Form.useForm()
  const [modalOpen, setModalOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: events, isLoading } = useQuery({
    queryKey: ['events'],
    queryFn: () => eventApi.list({ limit: 100 }),
  })

  const { data: statistics } = useQuery({
    queryKey: ['events', 'statistics'],
    queryFn: () => eventApi.getStatistics(30),
  })

  const createMutation = useMutation({
    mutationFn: (data: EventCreateData) => eventApi.create(data),
    onSuccess: async () => {
      message.success('事件已录入')
      setModalOpen(false)
      form.resetFields()
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['events'] }),
        queryClient.invalidateQueries({ queryKey: ['suggestions'] }),
      ])
    },
    onError: (error: Error) => message.error(`录入失败：${error.message}`),
  })

  const convertMutation = useMutation({
    mutationFn: (eventId: number) => eventApi.convertToCase(eventId),
    onSuccess: async (result) => {
      message.success(result.message || '事件已转案件')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['events'] }),
        queryClient.invalidateQueries({ queryKey: ['cases'] }),
        queryClient.invalidateQueries({ queryKey: ['suggestions'] }),
      ])
      navigate(`/cases?caseId=${result.case_id}`)
    },
    onError: (error: Error) => message.error(`转案件失败：${error.message}`),
  })

  const typeStats = useMemo(() => {
    const source = statistics?.by_type ?? {}
    return Object.entries(source)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
  }, [statistics])

  const handleCreate = async () => {
    const values = await form.validateFields()
    createMutation.mutate({
      ...values,
      occurred_time: values.occurred_time?.toISOString(),
    } as EventCreateData)
  }

  const rows = events ?? []

  return (
    <div className="page event-page">
      <div className="page-title">
        <h1>事件中心</h1>
        <span className="sub">事件录入 · 风险分流 · 一键转案件</span>
        <div style={{ marginLeft: 'auto' }}>
          <button className="btn-primary" onClick={() => setModalOpen(true)}>＋ 录入事件</button>
        </div>
      </div>

      <div className="ev-stats">
        <div className="ev-stat">
          <span>事件总量</span>
          <b>{statistics?.total_events ?? rows.length}</b>
          <small>全部事件</small>
        </div>
        <div className="ev-stat">
          <span>近 30 天</span>
          <b>{statistics?.recent_events ?? 0}</b>
          <small>新增事件</small>
        </div>
        <div className="ev-stat">
          <span>高风险区域</span>
          <b>{statistics?.high_risk_areas?.length ?? 0}</b>
          <small>需巡逻跟进</small>
        </div>
        <div className="ev-stat wide">
          <span>主要类型</span>
          <div className="ev-type-row">
            {typeStats.length > 0 ? typeStats.map(([type, count]) => (
              <em key={type}>{EVENT_TYPES[type as keyof typeof EVENT_TYPES] ?? type} {count}</em>
            )) : <em>暂无统计</em>}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <span className="ico">◇</span>
          <span className="ti">事件清单</span>
          <span className="spacer" />
          <span className="chip accent">未关联事件会进入建议中心</span>
        </div>
        <div className="card-body">
          {isLoading ? (
            <div className="empty-state" style={{ height: 280 }}>
              <div className="icon">⌛</div>
              <div>正在加载事件</div>
            </div>
          ) : rows.length === 0 ? (
            <div className="empty-state" style={{ height: 280 }}>
              <div className="icon">◇</div>
              <div>暂无事件</div>
              <button className="btn-primary" onClick={() => setModalOpen(true)}>录入第一条事件</button>
            </div>
          ) : (
            <table className="data ev-table">
              <thead>
                <tr>
                  <th>编号</th>
                  <th>时间</th>
                  <th>类型</th>
                  <th>地点</th>
                  <th>风险</th>
                  <th>标题/描述</th>
                  <th>动作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((event: Event) => (
                  <tr key={event.id}>
                    <td><span className="ev-no">{event.event_number}</span></td>
                    <td>{dayjs(event.occurred_time).format('MM-DD HH:mm')}</td>
                    <td>{EVENT_TYPES[event.event_type] ?? event.event_type}</td>
                    <td>{event.location || event.village_name || '—'}</td>
                    <td>
                      <span className={`tag ev-risk-${event.risk_level ?? 'low'}`}>
                        {RISK_LABELS[event.risk_level ?? 'low'] ?? '未评估'}
                      </span>
                    </td>
                    <td>
                      <div className="ev-desc">
                        <b>{event.title || '未命名事件'}</b>
                        <span>{event.description || '暂无描述'}</span>
                      </div>
                    </td>
                    <td>
                      {event.related_case_id ? (
                        <button className="btn-ghost-sm" onClick={() => navigate(`/cases?caseId=${event.related_case_id}`)}>
                          查看案件
                        </button>
                      ) : (
                        <button
                          className="btn-primary"
                          disabled={convertMutation.isPending}
                          onClick={() => convertMutation.mutate(event.id)}
                        >
                          转案件
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <Modal
        title="录入事件"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleCreate}
        okText="保存事件"
        confirmLoading={createMutation.isPending}
        width={760}
        styles={{
          content: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0 },
          header: { background: 'var(--bg-2)', borderBottom: '1px solid var(--line)' },
          footer: { background: 'var(--bg-2)', borderTop: '1px solid var(--line)' },
        }}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            event_type: 'suspect_activity',
            occurred_time: dayjs(),
          }}
        >
          <div className="ev-form-grid">
            <Form.Item name="event_type" label="事件类型" rules={[{ required: true }]}>
              <Select>
                {Object.entries(EVENT_TYPES).map(([value, label]) => (
                  <Option key={value} value={value}>{label}</Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item name="occurred_time" label="发生时间" rules={[{ required: true }]}>
              <DatePicker showTime style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="title" label="事件标题">
              <Input placeholder="如：夜间异常车辆活动" />
            </Form.Item>
            <Form.Item name="location" label="地点">
              <Input placeholder="村屯、井场、管线区段" />
            </Form.Item>
            <Form.Item name="latitude" label="纬度">
              <InputNumber style={{ width: '100%' }} precision={6} />
            </Form.Item>
            <Form.Item name="longitude" label="经度">
              <InputNumber style={{ width: '100%' }} precision={6} />
            </Form.Item>
            <Form.Item name="oil_type" label="油品">
              <Input placeholder="柴油 / 原油 / 汽油" />
            </Form.Item>
            <Form.Item name="oil_volume_liters" label="涉及油量（升）">
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
          </div>
          <Form.Item name="description" label="事件描述">
            <TextArea rows={4} placeholder="记录发现过程、人员车辆、处置结果等关键信息" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default EventCenter
