import { useMemo, useState } from 'react'
import { DatePicker, Form, Input, InputNumber, Modal, Select, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { eventApi } from '../../services/events'
import { jurisdictionApi } from '../../services/jurisdiction'
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

const OBSERVATION_EVENT_TYPES = new Set([
  'vehicle_trace',
  'oil_trace',
  'footprint_trace',
  'tool_trace',
  'facility_anomaly',
  'defense_outage',
  'suspect_activity',
  'damage_found',
])

const EventCenter: React.FC = () => {
  const [form] = Form.useForm()
  const [modalOpen, setModalOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const selectedEventType = Form.useWatch('event_type', form)
  const isWellObservation = OBSERVATION_EVENT_TYPES.has(selectedEventType)

  const { data: events, isLoading } = useQuery({
    queryKey: ['events'],
    queryFn: () => eventApi.list({ limit: 100 }),
  })

  const { data: statistics } = useQuery({
    queryKey: ['events', 'statistics'],
    queryFn: () => eventApi.getStatistics(30),
  })

  const { data: wells = [] } = useQuery({
    queryKey: ['jurisdiction-assets', 'well'],
    queryFn: () => jurisdictionApi.listAssets({ asset_type: 'well', limit: 500 }),
  })

  const createMutation = useMutation({
    mutationFn: (data: EventCreateData) => eventApi.create(data),
    onSuccess: async (created) => {
      message.success(OBSERVATION_EVENT_TYPES.has(created.event_type) ? '风险迹象已录入' : '事件已录入')
      setModalOpen(false)
      form.resetFields()
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['events'] }),
        queryClient.invalidateQueries({ queryKey: ['suggestions'] }),
      ])
      if (OBSERVATION_EVENT_TYPES.has(created.event_type)) {
        try {
          await jurisdictionApi.refreshWellAttention(30, 1)
          await queryClient.invalidateQueries({ queryKey: ['dashboard-well-attention'] })
          message.success('井点关注热力与AI研判已刷新')
        } catch (error) {
          message.warning(`迹象已保存，关注研判暂未刷新：${(error as Error).message}`)
        }
      }
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
      observation_type: isWellObservation ? values.event_type : undefined,
      occurred_time: values.occurred_time?.toISOString(),
    } as EventCreateData)
  }

  const handleWellChange = (assetId: number) => {
    const well = wells.find(item => item.id === assetId)
    if (!well) return
    form.setFieldsValue({
      related_asset_id: well.id,
      location: well.name,
      latitude: well.latitude ?? undefined,
      longitude: well.longitude ?? undefined,
    })
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
          <small>需人工核查</small>
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
            severity: 3,
            freshness: 'unknown',
            confidence_score: 0.7,
            review_status: 'pending_review',
          }}
        >
          <div className="ev-form-grid">
            <Form.Item name="event_type" label="事件类型" rules={[{ required: true }]}>
              <Select onChange={(value) => form.setFieldValue('observation_type', value)}>
                {Object.entries(EVENT_TYPES).map(([value, label]) => (
                  <Option key={value} value={value}>{label}</Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item name="occurred_time" label="发生时间" rules={[{ required: true }]}>
              <DatePicker showTime style={{ width: '100%' }} />
            </Form.Item>
            {isWellObservation && (
              <Form.Item
                name="related_asset_id"
                label="关联井点"
                rules={[{ required: true, message: '请选择本次痕迹关联的井点' }]}
              >
                <Select
                  showSearch
                  optionFilterProp="label"
                  placeholder={wells.length ? '选择井点后自动带入坐标' : '请先在辖区底座导入井点'}
                  options={wells.map(well => ({
                    value: well.id,
                    label: `${well.name}${well.address ? ` · ${well.address}` : ''}`,
                  }))}
                  onChange={handleWellChange}
                />
              </Form.Item>
            )}
            <Form.Item name="title" label={isWellObservation ? '痕迹简述' : '事件标题'}>
              <Input placeholder={isWellObservation ? '如：井口东侧发现新鲜陌生车辙' : '如：夜间异常车辆活动'} />
            </Form.Item>
            <Form.Item name="location" label="地点">
              <Input placeholder="选择井点后自动填写，也可补充具体方位" />
            </Form.Item>
            {isWellObservation ? (
              <>
                <Form.Item name="severity" label="明显程度">
                  <Select options={[
                    { value: 1, label: '轻微' },
                    { value: 2, label: '较轻' },
                    { value: 3, label: '明显' },
                    { value: 4, label: '较重' },
                    { value: 5, label: '严重' },
                  ]} />
                </Form.Item>
                <Form.Item name="freshness" label="痕迹新鲜度">
                  <Select options={[
                    { value: 'fresh', label: '新鲜' },
                    { value: 'recent', label: '近期' },
                    { value: 'unknown', label: '无法判断' },
                  ]} />
                </Form.Item>
                <Form.Item name="confidence_score" label="事实可信度">
                  <InputNumber style={{ width: '100%' }} min={0} max={1} step={0.05} />
                </Form.Item>
                <Form.Item name="review_status" label="复核状态">
                  <Select options={[
                    { value: 'pending_review', label: '待复核' },
                    { value: 'confirmed', label: '已确认事实' },
                    { value: 'rejected', label: '已排除' },
                  ]} />
                </Form.Item>
              </>
            ) : (
              <>
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
              </>
            )}
          </div>
          {isWellObservation && (
            <>
              <Form.Item name="latitude" hidden><InputNumber /></Form.Item>
              <Form.Item name="longitude" hidden><InputNumber /></Form.Item>
            </>
          )}
          <Form.Item name="description" label={isWellObservation ? '事实记录' : '事件描述'}>
            <TextArea
              rows={4}
              placeholder={isWellObservation
                ? '只记录看到的事实：痕迹位置、方向、范围、照片情况；推断交给研判模块。'
                : '记录发现过程、人员车辆、处置结果等关键信息'}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default EventCenter
