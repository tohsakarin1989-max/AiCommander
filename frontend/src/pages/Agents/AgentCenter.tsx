import { useEffect, useMemo, useState } from 'react'
import { Input, List, Modal, Progress, Select, Space, Tag, message } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  RadarChartOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../../auth/AuthContext'
import { agentRunApi } from '../../services/agentRuns'
import { caseApi } from '../../services/cases'
import type { AgentRun, AgentRunApproval, AgentRunTaskType } from '../../types'
import {
  agentErrorMessage,
  agentEventLabel,
  agentResultText,
  agentStatusLabel,
  canReviewAgentRun,
  isAgentRunActive,
} from './agentPresentation'
import './AgentCenter.css'

const { TextArea } = Input

const TASK_OPTIONS: Array<{ value: AgentRunTaskType; label: string; description: string }> = [
  { value: 'case_data_quality', label: '案件数据管家', description: '检查案件完整性、一致性和研判可用性' },
  { value: 'map_data_quality', label: '地图数据管家', description: '检查重点井、坐标、几何和核验状态' },
  { value: 'dual_domain_analysis', label: '双域融合研判', description: '分析案件与重点井的时空条件和证据缺口' },
  { value: 'evidence_report', label: '综合证据报告', description: '串联三组只读工具形成可复核报告' },
]

function statusClass(status: string): string {
  if (['running', 'planning', 'verifying'].includes(status)) return 'agent-task-card--running'
  if (['completed', 'degraded'].includes(status)) return 'agent-task-card--completed'
  if (['failed', 'cancelled', 'expired'].includes(status)) return 'agent-task-card--failed'
  return 'agent-task-card--pending'
}

function StatusBadge({ status }: { status: string }) {
  const running = ['running', 'planning', 'verifying'].includes(status)
  const success = ['completed', 'degraded'].includes(status)
  const failed = ['failed', 'cancelled', 'expired'].includes(status)
  const icon = running
    ? <SyncOutlined spin />
    : success
      ? <CheckCircleOutlined />
      : failed
        ? <CloseCircleOutlined />
        : status === 'waiting_approval'
          ? <PauseCircleOutlined />
          : <ClockCircleOutlined />
  return (
    <span className={`chip ${running ? 'chip-running' : success ? 'chip-completed' : failed ? 'chip-failed' : 'chip-pending'}`}>
      {icon} {agentStatusLabel(status)}
    </span>
  )
}

function ResultList({ title, items }: { title: string; items?: unknown[] }) {
  if (!items?.length) return null
  return (
    <div className="agent-result-list">
      <div className="agent-result-label">{title}</div>
      <List
        size="small"
        dataSource={items.slice(0, 12)}
        renderItem={item => <List.Item><div className="agent-list-value">{agentResultText(item)}</div></List.Item>}
      />
    </div>
  )
}

function ApprovalCard({
  run,
  approval,
  canReview,
  onReview,
}: {
  run: AgentRun
  approval: AgentRunApproval
  canReview: boolean
  onReview: (approval: AgentRunApproval, decision: 'approve' | 'reject') => void
}) {
  return (
    <div className="agent-approval-card">
      <div className="agent-approval-title">
        <span>候选修正 · {approval.target_type} #{approval.target_id}</span>
        <Tag color={approval.status === 'pending' ? 'gold' : approval.status === 'executed' ? 'green' : 'default'}>
          {approval.status}
        </Tag>
      </div>
      <pre className="agent-patch">{JSON.stringify(approval.candidate_patch, null, 2)}</pre>
      {approval.execution_result && Object.keys(approval.execution_result).length > 0 && (
        <div className="agent-execution-note">执行结果：{JSON.stringify(approval.execution_result)}</div>
      )}
      {approval.status === 'pending' && canReview && (
        <Space>
          <button className="btn-primary" onClick={() => onReview(approval, 'approve')}>批准候选修正</button>
          <button className="btn-ghost" onClick={() => onReview(approval, 'reject')}>驳回</button>
        </Space>
      )}
      {approval.status === 'pending' && !canReview && (
        <span className="agent-muted">仅管理员可以审批；审批不代表一定写入，仍受后端写入开关约束。</span>
      )}
      {run.mode === 'shadow' && <span className="agent-muted">影子模式只记录候选，不执行正式数据写入。</span>}
    </div>
  )
}

const AgentCenter: React.FC = () => {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [messageApi, messageContextHolder] = message.useMessage()
  const [modalApi, modalContextHolder] = Modal.useModal()
  const [taskType, setTaskType] = useState<AgentRunTaskType>('case_data_quality')
  const [query, setQuery] = useState('检查所选数据并形成可复核的问题清单和证据依据')
  const [selectedCaseIds, setSelectedCaseIds] = useState<number[]>([])
  const [assetIdsText, setAssetIdsText] = useState('')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  const runsQuery = useQuery({
    queryKey: ['agent-runs'],
    queryFn: agentRunApi.list,
    refetchInterval: queryState => queryState.state.data?.some(item => isAgentRunActive(item.status)) ? 2500 : false,
  })
  const detailQuery = useQuery({
    queryKey: ['agent-run', selectedRunId],
    queryFn: () => agentRunApi.get(selectedRunId as string),
    enabled: Boolean(selectedRunId),
    refetchInterval: queryState => queryState.state.data && isAgentRunActive(queryState.state.data.status) ? 2000 : false,
  })
  const casesQuery = useQuery({
    queryKey: ['agent-cases'],
    queryFn: () => caseApi.getCases({ limit: 200 }),
  })

  const runs = runsQuery.data ?? []
  useEffect(() => {
    if (!selectedRunId && runs[0]) setSelectedRunId(runs[0].id)
  }, [runs, selectedRunId])

  const selectedTask = TASK_OPTIONS.find(item => item.value === taskType)
  const assetIds = useMemo(() => Array.from(new Set(
    assetIdsText
      .split(/[,，\s]+/)
      .map(item => Number(item))
      .filter(item => Number.isInteger(item) && item > 0),
  )), [assetIdsText])

  const createMutation = useMutation({
    mutationFn: agentRunApi.create,
    onSuccess: run => {
      messageApi.success('Agent任务已进入独立队列')
      setSelectedRunId(run.id)
      void queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
    },
    onError: error => {
      messageApi.error(agentErrorMessage(error, 'Agent任务启动失败'))
    },
  })
  const cancelMutation = useMutation({
    mutationFn: agentRunApi.cancel,
    onSuccess: run => {
      messageApi.success('Agent任务已取消，核心业务不受影响')
      queryClient.setQueryData(['agent-run', run.id], run)
      void queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
    },
    onError: error => {
      messageApi.error(agentErrorMessage(error, '取消任务失败'))
    },
  })
  const replayMutation = useMutation({
    mutationFn: agentRunApi.replay,
    onSuccess: run => {
      setSelectedRunId(run.id)
      void queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
      messageApi.success('已创建可追踪的重放任务')
    },
    onError: error => {
      messageApi.error(agentErrorMessage(error, '重放任务失败'))
    },
  })
  const reviewMutation = useMutation({
    mutationFn: ({ runId, approvalId, decision }: { runId: string; approvalId: string; decision: 'approve' | 'reject' }) => (
      agentRunApi.review(runId, approvalId, decision)
    ),
    onSuccess: () => {
      messageApi.success('审批决定已记录')
      void queryClient.invalidateQueries({ queryKey: ['agent-run', selectedRunId] })
      void queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
    },
    onError: error => {
      messageApi.error(agentErrorMessage(error, '审批失败'))
    },
  })

  const handleCreate = () => {
    if (!query.trim()) {
      messageApi.warning('请输入任务目标')
      return
    }
    createMutation.mutate({
      task_type: taskType,
      query: query.trim(),
      case_ids: selectedCaseIds,
      asset_ids: assetIds,
    })
  }

  const reviewApproval = (approval: AgentRunApproval, decision: 'approve' | 'reject') => {
    const verb = decision === 'approve' ? '批准' : '驳回'
    modalApi.confirm({
      title: `${verb}候选修正？`,
      content: decision === 'approve'
        ? '后端仍会检查运行模式、写入开关、字段白名单、数据版本和点位核验状态。'
        : '驳回后不会修改正式数据，决定会进入审计轨迹。',
      okText: verb,
      cancelText: '取消',
      onOk: () => reviewMutation.mutate({
        runId: approval.run_id,
        approvalId: approval.id,
        decision,
      }),
    })
  }

  const detail = detailQuery.data
  const result = detail?.result_summary
  const canReview = canReviewAgentRun(user?.role)

  return (
    <>
      {messageContextHolder}
      {modalContextHolder}
      <div className="page-scrollable">
      <div className="page-title agent-title-row">
        <div>
          <h1>油盾 · 双域研判智能体</h1>
          <span className="sub">案件数据治理、地图数据治理与案件—重点井时空融合</span>
        </div>
        <Tag icon={<SafetyCertificateOutlined />} color="blue">受控 Agent Lab</Tag>
      </div>

      <div className="agent-safety-banner">
        原始案件、人员、井名和精确坐标留在内网；外部模型仅接收临时别名和派生特征。所有候选修正必须人工审批。
      </div>

      <div className="card agent-create-card">
        <div className="card-head"><RadarChartOutlined className="ico" /><span className="ti">新建受控任务</span></div>
        <div className="card-body pad agent-form-grid">
          <div>
            <div className="agent-result-label">能力类型</div>
            <Select
              value={taskType}
              onChange={setTaskType}
              className="agent-full-width"
              options={TASK_OPTIONS.map(item => ({ value: item.value, label: item.label }))}
            />
            <div className="agent-muted">{selectedTask?.description}</div>
          </div>
          <div>
            <div className="agent-result-label">案件范围</div>
            <Select
              mode="multiple"
              allowClear
              showSearch
              className="agent-full-width"
              placeholder="不选则分析最近案件"
              value={selectedCaseIds}
              onChange={setSelectedCaseIds}
              optionFilterProp="label"
              loading={casesQuery.isLoading}
              options={(casesQuery.data ?? []).map(item => ({
                value: item.id,
                label: `${item.case_number} · ${item.location || '未知地点'}`,
              }))}
            />
          </div>
          <div>
            <div className="agent-result-label">地图要素ID</div>
            <Input
              value={assetIdsText}
              onChange={event => setAssetIdsText(event.target.value)}
              placeholder="可选，例如：12, 18, 26"
            />
          </div>
          <div className="agent-query-field">
            <div className="agent-result-label">任务目标</div>
            <TextArea
              className="agent-textarea"
              rows={3}
              value={query}
              onChange={event => setQuery(event.target.value)}
            />
          </div>
          <div className="agent-create-actions">
            <span className="agent-muted">最多8个工具步骤 · 默认120秒 · 普通失败最多重试2次</span>
            <button className="btn-primary" onClick={handleCreate} disabled={createMutation.isPending}>
              <PlayCircleOutlined /> {createMutation.isPending ? '进入队列...' : '启动任务'}
            </button>
          </div>
        </div>
      </div>

      <div className="agent-workspace">
        <section className="agent-run-list">
          <div className="agent-section-head">
            <span>运行记录</span>
            <button className="btn-ghost" onClick={() => runsQuery.refetch()}><ReloadOutlined /> 刷新</button>
          </div>
          {runs.length === 0 ? (
            <div className="empty-state"><span>暂无 Agent 运行记录</span></div>
          ) : runs.map(run => (
            <button
              key={run.id}
              className={`agent-run-row ${statusClass(run.status)} ${selectedRunId === run.id ? 'selected' : ''}`}
              onClick={() => setSelectedRunId(run.id)}
            >
              <div className="agent-run-row-top">
                <span>{TASK_OPTIONS.find(item => item.value === run.task_type)?.label ?? run.task_type}</span>
                <StatusBadge status={run.status} />
              </div>
              <div className="agent-run-query">{run.query}</div>
              <div className="agent-run-meta">
                {run.id.slice(0, 8)} · 成果 {run.artifact_count} · 待审批 {run.pending_approval_count}
              </div>
            </button>
          ))}
        </section>

        <section className="agent-run-detail">
          {!detail ? (
            <div className="empty-state"><span>{detailQuery.isLoading ? '正在读取运行轨迹...' : '选择一条运行记录查看详情'}</span></div>
          ) : (
            <>
              <div className="agent-section-head">
                <div><strong>任务 {detail.id.slice(0, 8)}</strong> <StatusBadge status={detail.status} /></div>
                <Space>
                  {isAgentRunActive(detail.status) && (
                    <button className="btn-ghost" onClick={() => cancelMutation.mutate(detail.id)}>取消</button>
                  )}
                  {canReview && (
                    <button className="btn-ghost" onClick={() => replayMutation.mutate(detail.id)}>重放</button>
                  )}
                </Space>
              </div>

              {result?.result && <div className="agent-result-box"><div className="agent-result-label">研判结果</div><div>{result.result}</div></div>}
              {typeof result?.confidence === 'number' && (
                <Space className="agent-confidence"><span>依据强度</span><Progress percent={Math.round(result.confidence * 100)} size="small" style={{ width: 160 }} /></Space>
              )}
              <ResultList title="事实依据" items={result?.facts} />
              <ResultList title="模式推断" items={result?.inferences} />
              <ResultList title="防控参考" items={result?.recommendations} />
              <ResultList title="信息缺口" items={result?.information_gaps} />
              <ResultList title="证据索引" items={result?.evidence_refs} />
              <ResultList title="适用边界" items={result?.boundary} />

              {(detail.approvals ?? []).length > 0 && (
                <div className="agent-detail-section">
                  <div className="agent-section-head">候选修正与人工审批</div>
                  {detail.approvals?.map(approval => (
                    <ApprovalCard key={approval.id} run={detail} approval={approval} canReview={canReview} onReview={reviewApproval} />
                  ))}
                </div>
              )}

              <div className="agent-detail-section">
                <div className="agent-section-head">运行轨迹</div>
                <div className="agent-event-list">
                  {(detail.events ?? []).map(event => (
                    <div className="agent-event" key={event.id}>
                      <span className="agent-event-seq">{event.sequence}</span>
                      <div>
                        <div>{agentEventLabel(event.event_type)} {event.actor_name ? `· ${event.actor_name}` : ''}</div>
                        <div className="agent-muted">
                          {event.duration_ms != null ? `${event.duration_ms}ms · ` : ''}
                          证据 {event.evidence_refs.length} 条
                          {event.error_message ? ` · ${event.error_message}` : ''}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </section>
      </div>
      </div>
    </>
  )
}

export default AgentCenter
