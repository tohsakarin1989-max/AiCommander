/** 历史告警实验页。读取已有记录；新演示仅使用隔离展示数据。 */
import { useState } from 'react'
import { Alert, Empty, List, Modal, Progress, Spin, Typography, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { automationAlertApi } from '../../services/automationAlerts'
import type { AutomationAlert, AutomationAlertTriagePack } from '../../services/automationAlerts'
import { buildAutomationAlertTriageMarkdown } from './intelliTriagePresentation'
import './IntelliInspect.css'

const { Text } = Typography

const riskText = (riskLevel: string) => {
  if (riskLevel === 'critical') return '极高'
  if (riskLevel === 'high') return '高'
  if (riskLevel === 'medium') return '中'
  if (riskLevel === 'low') return '低'
  return '未标注'
}

const riskColor = (riskLevel: string) => {
  if (riskLevel === 'critical') return 'var(--err)'
  if (riskLevel === 'high') return 'oklch(0.80 0.16 75)'
  if (riskLevel === 'medium') return 'var(--warn)'
  if (riskLevel === 'low') return 'var(--ok)'
  return 'var(--ink-3)'
}

const IntelliInspect: React.FC = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [triagePack, setTriagePack] = useState<AutomationAlertTriagePack | null>(null)
  const [copyFallbackMarkdown, setCopyFallbackMarkdown] = useState('')
  const alertsQuery = useQuery({
    queryKey: ['automation-alerts', 'history'],
    queryFn: () => automationAlertApi.list({ limit: 100 }),
  })

  const refreshAlerts = () => {
    queryClient.invalidateQueries({ queryKey: ['automation-alerts', 'history'] })
  }

  const createEventMutation = useMutation({
    mutationFn: (alert: AutomationAlert) => automationAlertApi.ensureEvent(alert.id),
    onSuccess: () => {
      message.success('告警已进入事件中心')
      refreshAlerts()
    },
    onError: (error: Error) => message.error(`生成事件失败：${error.message}`),
  })

  const falseAlarmMutation = useMutation({
    mutationFn: (alert: AutomationAlert) => automationAlertApi.markFalseAlarm(alert.id, '前端标记为误报或设备异常'),
    onSuccess: () => {
      message.success('告警已按误报/设备异常归档')
      refreshAlerts()
    },
    onError: (error: Error) => message.error(`归档失败：${error.message}`),
  })

  const convertMutation = useMutation({
    mutationFn: (alert: AutomationAlert) => automationAlertApi.convertToCase(alert.id),
    onSuccess: (result) => {
      message.success(result.message || '告警已转案件')
      refreshAlerts()
      navigate(`/cases?caseId=${result.case_id}`)
    },
    onError: (error: Error) => message.error(`转案件失败：${error.message}`),
  })

  const triageMutation = useMutation({
    mutationFn: (alert: AutomationAlert) => automationAlertApi.getTriagePack(alert.id),
    onSuccess: (data) => setTriagePack(data),
    onError: (error: Error) => message.error(`打开研判包失败：${error.message}`),
  })

  const handleCopyTriagePack = async () => {
    if (!triagePack) return
    const markdown = buildAutomationAlertTriageMarkdown(triagePack)
    try {
      await navigator.clipboard.writeText(markdown)
      setCopyFallbackMarkdown('')
      message.success('研判包 Markdown 已复制')
    } catch (error) {
      setCopyFallbackMarkdown(markdown)
      message.warning('浏览器未开放剪贴板，已打开可复制文本')
    }
  }

  const actionBusy =
    createEventMutation.isPending ||
    falseAlarmMutation.isPending ||
    convertMutation.isPending
  const alerts = alertsQuery.data || []

  return (
  <div className="ii-page">

    <div className="page-title" style={{ marginBottom: 'var(--gap)' }}>
      <h1>历史告警实验</h1>
      <div className="sub">查看已有告警、研判依据及关联记录</div>
    </div>

    <Alert
      type="info"
      showIcon
      message="旧实验流程已收起，不再生成模拟告警"
      description="本页只在打开和刷新时读取已有告警。雷达、云台及自动设备联动未接通；历史模拟记录不代表真实告警。新演示请使用隔离展示（需管理员启用）。"
      action={<button className="btn-ghost" onClick={() => navigate('/showcase')}>前往隔离展示</button>}
      style={{ marginBottom: 'var(--gap)' }}
    />

    <section className="card">
      <div className="card-head">
        <span className="ti">已有告警</span>
        <span className="chip">最近 100 条，非全量统计</span>
        <span className="spacer" />
        <button className="btn-ghost" disabled={alertsQuery.isFetching} onClick={refreshAlerts}>
          刷新已有告警
        </button>
      </div>
      <div className="card-body pad">
        {alertsQuery.isLoading ? (
          <div style={{ padding: 30, textAlign: 'center' }}><Spin /></div>
        ) : alertsQuery.isError ? (
          <Alert type="error" showIcon message="告警列表读取失败"
            description="请重试或联系管理员；读取失败不代表没有告警，不会生成模拟数据。" />
        ) : alerts.length ? (
          alerts.map((a) => (
            <article key={a.id} className="ii-alert-record">
              <div className="ii-alert-level">
                <span className="ii-alert-badge" style={{ color: riskColor(a.risk_level), borderColor: riskColor(a.risk_level) }}>
                  登记等级：{riskText(a.risk_level)}
                </span>
                <span className="ii-alert-linked">{a.is_simulated ? '历史模拟记录' : '已登记告警'}</span>
                {a.related_event_id && <span className="ii-alert-linked">事件 #{a.related_event_id}</span>}
                {a.related_case_id && <span className="ii-alert-linked">案件 #{a.related_case_id}</span>}
                <span className="ii-alert-linked">{a.status}</span>
                <time className="ii-alert-time">{dayjs(a.occurred_time).format('YYYY-MM-DD HH:mm')}</time>
              </div>
              <h2 className="ii-alert-title">{a.title}</h2>
              <div className="ii-alert-desc">{a.description}</div>
              {!!a.suggested_actions?.length && (
                <div className="ii-card-sub" style={{ marginTop: 8 }}>
                  已记录核查建议：{a.suggested_actions.join('；')}
                </div>
              )}
              <div className="ii-alert-actions">
                <button className="btn-ghost-sm" disabled={actionBusy || !!a.related_event_id}
                  onClick={() => createEventMutation.mutate(a)}>
                  {a.related_event_id ? '已生成事件' : '生成事件'}
                </button>
                <button className="btn-ghost-sm"
                  disabled={actionBusy || a.status === 'false_alarm' || !!a.related_case_id}
                  onClick={() => falseAlarmMutation.mutate(a)}>标记误报</button>
                <button className="btn-ghost-sm" disabled={triageMutation.isPending}
                  onClick={() => triageMutation.mutate(a)}>研判包</button>
                <button className="btn-primary"
                  disabled={actionBusy || a.status === 'false_alarm' || !!a.related_case_id}
                  onClick={() => convertMutation.mutate(a)}>转案件</button>
              </div>
            </article>
          ))
        ) : (
          <Empty description="暂无已有告警，不会自动生成演示记录" />
        )}
        <p className="ii-card-sub" style={{ marginTop: 12 }}>
          生成事件、误报归档或转案件仅在人工点击后执行；不自动创建外勤或跨部门任务。
        </p>
      </div>
    </section>
    <Modal
      className="ii-triage-modal"
      title="数智告警研判包"
      open={!!triagePack}
      onCancel={() => {
        setTriagePack(null)
        setCopyFallbackMarkdown('')
      }}
      style={{ top: 24 }}
      width={880}
      footer={[
        triagePack ? (
          <button
            key="copy"
            className="btn-ghost"
            onClick={handleCopyTriagePack}
          >
            复制研判包
          </button>
        ) : null,
        triagePack?.alert.related_case_id ? (
          <button
            key="case"
            className="btn-primary"
            onClick={() => {
              navigate(`/case-intelligence?caseId=${triagePack.alert.related_case_id}`)
              setTriagePack(null)
              setCopyFallbackMarkdown('')
            }}
          >
            进入案件研判
          </button>
        ) : null,
        <button
          key="close"
          className="btn-ghost"
          onClick={() => {
            setTriagePack(null)
            setCopyFallbackMarkdown('')
          }}
        >
          关闭
        </button>,
      ]}
    >
      {triagePack && (
        <div className="ii-triage-pack">
          <div className="ii-triage-head">
            <div>
              <Text strong>{triagePack.alert.alert_number}</Text>
              <div className="ii-card-sub">{triagePack.alert.title}</div>
            </div>
            {typeof triagePack.triage_assessment.confidence === 'number' && (
              <Progress
                type="circle"
                size={58}
                percent={Math.round(triagePack.triage_assessment.confidence * 100)}
              />
            )}
          </div>
          <div className="ii-triage-grid">
            <div className="ii-triage-section">
              <div className="ii-triage-title">事实依据</div>
              <List size="small" dataSource={triagePack.facts} renderItem={item => <List.Item>{item}</List.Item>} />
            </div>
            <div className="ii-triage-section">
              <div className="ii-triage-title">AI 研判依据</div>
              <List
                size="small"
                dataSource={triagePack.triage_assessment.basis}
                locale={{ emptyText: '暂无 AI 依据，需人工核查' }}
                renderItem={item => <List.Item>{item}</List.Item>}
              />
            </div>
            <div className="ii-triage-section">
              <div className="ii-triage-title">信息缺口</div>
              <List size="small" dataSource={triagePack.information_gaps} renderItem={item => <List.Item>{item}</List.Item>} />
            </div>
            <div className="ii-triage-section">
              <div className="ii-triage-title">下一步</div>
              <List size="small" dataSource={triagePack.recommended_next_steps} renderItem={item => <List.Item>{item}</List.Item>} />
            </div>
          </div>
          {triagePack.related_case_context && (
            <div className="ii-triage-section">
              <div className="ii-triage-title">已关联案件上下文</div>
              <List
                size="small"
                dataSource={triagePack.related_case_context.facts.slice(0, 6)}
                renderItem={item => <List.Item>{item}</List.Item>}
              />
            </div>
          )}
          <div className="ii-card-sub" style={{ marginTop: 10 }}>
            {triagePack.boundary.join('；')}
          </div>
        </div>
      )}
    </Modal>
    <Modal
      className="ii-triage-modal"
      title="研判包 Markdown"
      open={!!copyFallbackMarkdown}
      onCancel={() => setCopyFallbackMarkdown('')}
      style={{ top: 24 }}
      footer={[
        <button key="close" className="btn-primary" onClick={() => setCopyFallbackMarkdown('')}>关闭</button>,
      ]}
      width={760}
    >
      <textarea
        className="ii-copy-fallback"
        readOnly
        value={copyFallbackMarkdown}
        onFocus={event => event.currentTarget.select()}
      />
      <div className="ii-card-sub" style={{ marginTop: 8 }}>
        当前浏览器未开放剪贴板权限，可直接选中文本复制；内容为研判辅助材料，转案件前仍需人工确认。
      </div>
    </Modal>
  </div>
  )
}

export default IntelliInspect
