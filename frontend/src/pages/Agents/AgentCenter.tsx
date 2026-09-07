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
import { caseStewardApi } from '../../services/caseSteward'
import { jurisdictionApi } from '../../services/jurisdiction'
import { mapStewardApi } from '../../services/mapSteward'
import type { AgentRun, AgentRunApproval, AgentRunTaskType } from '../../types'
import {
  agentErrorMessage,
  agentEventLabel,
  agentExecutionModeLabel,
  agentResultText,
  agentStatusLabel,
  canReviewAgentRun,
  isAgentRunActive,
} from './agentPresentation'
import {
  canStartCaseSteward,
  canSubmitCaseStewardRun,
  caseStewardControlReason,
  caseStewardControlHint,
  caseStewardStateLabel,
} from './caseStewardPresentation'
import {
  canSubmitMapStewardRun,
  canStartMapSteward,
  mapStewardControlHint,
  mapStewardControlReason,
  mapStewardStateLabel,
} from './mapStewardPresentation'
import './AgentCenter.css'

const { TextArea } = Input

const TASK_OPTIONS: Array<{
  value: AgentRunTaskType
  label: string
  description: string
  defaultQuery: string
}> = [
  {
    value: 'case_data_quality',
    label: '案件数据管家',
    description: '检查案件完整性、一致性和研判可用性',
    defaultQuery: '检查所选案件并形成可复核的问题清单和证据索引',
  },
  {
    value: 'map_data_quality',
    label: '地图数据管家',
    description: '检查重点井、坐标、几何和核验状态',
    defaultQuery: '检查所选地图资源并形成可复核的问题清单和证据依据',
  },
  {
    value: 'dual_domain_analysis',
    label: '双域融合研判',
    description: '分析案件与重点井的时空条件和证据缺口',
    defaultQuery: '分析所选案件与地图资源的时空条件并说明证据边界',
  },
  {
    value: 'evidence_report',
    label: '综合证据报告',
    description: '串联三组只读工具形成可复核报告',
    defaultQuery: '基于所选数据生成事实、推断、建议、缺口和证据索引报告',
  },
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
  canApprove,
  onReview,
}: {
  run: AgentRun
  approval: AgentRunApproval
  canReview: boolean
  canApprove: boolean
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
        <div>
          <Space>
            {canApprove && (
              <button className="btn-primary" onClick={() => onReview(approval, 'approve')}>批准候选修正</button>
            )}
            <button className="btn-ghost" onClick={() => onReview(approval, 'reject')}>驳回</button>
          </Space>
          {!canApprove && <span className="agent-muted">当前只允许检查和驳回，不允许应用候选修正。</span>}
        </div>
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
  const [taskType, setTaskType] = useState<AgentRunTaskType>('map_data_quality')
  const [query, setQuery] = useState(TASK_OPTIONS[1].defaultQuery)
  const [selectedCaseIds, setSelectedCaseIds] = useState<number[]>([])
  const [selectedAssetIds, setSelectedAssetIds] = useState<number[]>([])
  const [pilotUserIds, setPilotUserIds] = useState<number[]>([])
  const [controlReason, setControlReason] = useState('启动地图数据管家受控试用')
  const [casePilotUserIds, setCasePilotUserIds] = useState<number[]>([])
  const [caseControlReason, setCaseControlReason] = useState('启动案件数据管家只读试用')
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
  const mapStatusQuery = useQuery({
    queryKey: ['agent-map-steward-status'],
    queryFn: mapStewardApi.status,
    refetchInterval: 10000,
  })
  const caseStatusQuery = useQuery({
    queryKey: ['agent-case-steward-status'],
    queryFn: caseStewardApi.status,
    refetchInterval: 10000,
  })
  const casesQuery = useQuery({
    queryKey: ['agent-cases'],
    queryFn: () => caseApi.getCases({ limit: 200 }),
    enabled: Boolean(mapStatusQuery.data)
      && (mapStatusQuery.data?.global_mode !== 'assist' || Boolean(caseStatusQuery.data)),
  })
  const assetsQuery = useQuery({
    queryKey: ['agent-map-assets'],
    queryFn: () => jurisdictionApi.listAssets({ status: 'active', limit: 500 }),
  })

  const runs = runsQuery.data ?? []
  const pilotUserIdsKey = mapStatusQuery.data?.pilot_user_ids?.join(',') ?? ''
  const casePilotUserIdsKey = caseStatusQuery.data?.pilot_user_ids?.join(',') ?? ''
  useEffect(() => {
    if (!selectedRunId && runs[0]) setSelectedRunId(runs[0].id)
  }, [runs, selectedRunId])
  useEffect(() => {
    if (mapStatusQuery.data?.pilot_user_ids) {
      setPilotUserIds(mapStatusQuery.data.pilot_user_ids)
    }
  }, [pilotUserIdsKey])
  useEffect(() => {
    if (
      mapStatusQuery.data?.global_mode === 'assist'
      && !['map_data_quality', 'case_data_quality'].includes(taskType)
    ) {
      setTaskType('map_data_quality')
      setSelectedCaseIds([])
    }
  }, [mapStatusQuery.data?.global_mode, taskType])
  useEffect(() => {
    if (caseStatusQuery.data?.pilot_user_ids) {
      setCasePilotUserIds(caseStatusQuery.data.pilot_user_ids)
    }
  }, [casePilotUserIdsKey])

  const selectedTask = TASK_OPTIONS.find(item => item.value === taskType)
  const mapStatus = mapStatusQuery.data
  const caseStatus = caseStatusQuery.data
  const isAssistMode = mapStatus?.global_mode === 'assist'
  const visibleTaskOptions = useMemo(
    () => isAssistMode
      ? TASK_OPTIONS.filter(item => ['map_data_quality', 'case_data_quality'].includes(item.value))
      : TASK_OPTIONS,
    [isAssistMode],
  )

  const createMutation = useMutation({
    mutationFn: agentRunApi.create,
    onSuccess: run => {
      messageApi.success('Agent任务已进入独立队列')
      setSelectedRunId(run.id)
      void queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
      void queryClient.invalidateQueries({ queryKey: ['agent-map-steward-status'] })
      void queryClient.invalidateQueries({ queryKey: ['agent-case-steward-status'] })
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
      void queryClient.invalidateQueries({ queryKey: ['agent-map-steward-status'] })
      void queryClient.invalidateQueries({ queryKey: ['agent-case-steward-status'] })
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
      void queryClient.invalidateQueries({ queryKey: ['agent-map-steward-status'] })
      void queryClient.invalidateQueries({ queryKey: ['agent-case-steward-status'] })
    },
    onError: error => {
      messageApi.error(agentErrorMessage(error, '审批失败'))
    },
  })
  const controlMutation = useMutation({
    mutationFn: mapStewardApi.updateControl,
    onSuccess: status => {
      queryClient.setQueryData(['agent-map-steward-status'], status)
      messageApi.success(status.mutations_suspended ? '地图数据管家已切换为安全暂停' : '地图数据管家受控试用已开启')
      void queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
    },
    onError: error => messageApi.error(agentErrorMessage(error, '试用设置更新失败')),
  })
  const suspendMutation = useMutation({
    mutationFn: mapStewardApi.suspend,
    onSuccess: status => {
      queryClient.setQueryData(['agent-map-steward-status'], status)
      void queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
      if (selectedRunId) void queryClient.invalidateQueries({ queryKey: ['agent-run', selectedRunId] })
      messageApi.success('试用已停用，活动任务和待审批候选已安全终止')
    },
    onError: error => messageApi.error(agentErrorMessage(error, '停用地图数据管家失败')),
  })
  const caseControlMutation = useMutation({
    mutationFn: caseStewardApi.updateControl,
    onSuccess: status => {
      queryClient.setQueryData(['agent-case-steward-status'], status)
      messageApi.success(status.enabled ? '案件数据管家只读试用已开启' : '案件数据管家试用已关闭')
      void queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
    },
    onError: error => messageApi.error(agentErrorMessage(error, '案件试用设置更新失败')),
  })
  const caseSuspendMutation = useMutation({
    mutationFn: caseStewardApi.suspend,
    onSuccess: status => {
      queryClient.setQueryData(['agent-case-steward-status'], status)
      void queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
      if (selectedRunId) void queryClient.invalidateQueries({ queryKey: ['agent-run', selectedRunId] })
      messageApi.success('案件数据管家试用已停用，正式案件数据未发生变化')
    },
    onError: error => messageApi.error(agentErrorMessage(error, '停用案件数据管家失败')),
  })

  const handleCreate = () => {
    if (!query.trim()) {
      messageApi.warning('请输入任务目标')
      return
    }
    if (isAssistMode && taskType === 'map_data_quality') {
      if (!canStartMapSteward(mapStatus)) {
        messageApi.warning('当前账号暂不能发起地图数据管家试用任务')
        return
      }
      if (!selectedAssetIds.length) {
        messageApi.warning('请先选择需要检查的地图资源')
        return
      }
    }
    if (isAssistMode && taskType === 'case_data_quality') {
      if (!canStartCaseSteward(caseStatus)) {
        messageApi.warning('当前账号暂不能发起案件数据管家试用任务')
        return
      }
      if (!selectedCaseIds.length) {
        messageApi.warning('请先选择需要检查的案件')
        return
      }
    }
    createMutation.mutate({
      task_type: taskType,
      query: query.trim(),
      case_ids: isAssistMode && taskType === 'map_data_quality' ? [] : selectedCaseIds,
      asset_ids: isAssistMode && taskType === 'case_data_quality' ? [] : selectedAssetIds,
    })
  }

  const updatePilotControl = (mutationsSuspended: boolean) => {
    if (!pilotUserIds.length) {
      messageApi.warning('请至少选择一名试用人员')
      return
    }
    if (controlReason.trim() && controlReason.trim().length < 2) {
      messageApi.warning('请填写至少2个字的调整原因')
      return
    }
    const action = mutationsSuspended ? 'pause' : 'enable'
    const reason = mapStewardControlReason(controlReason, action)
    controlMutation.mutate({
      enabled: true,
      mutations_suspended: mutationsSuspended,
      pilot_user_ids: pilotUserIds,
      reason,
    })
  }

  const confirmSuspendPilot = () => {
    modalApi.confirm({
      title: '停用地图数据管家试用？',
      content: '活动中的地图质检任务将取消，待审批候选将失效；正式地图数据不会被修改，核心系统继续运行。',
      okText: '确认停用',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: () => suspendMutation.mutate(mapStewardControlReason(controlReason, 'disable')),
    })
  }

  const updateCasePilotControl = () => {
    if (!casePilotUserIds.length) {
      messageApi.warning('请至少选择一名案件数据管家试用人员')
      return
    }
    if (caseControlReason.trim().length < 2) {
      messageApi.warning('请填写至少2个字的调整原因')
      return
    }
    caseControlMutation.mutate({
      enabled: true,
      pilot_user_ids: casePilotUserIds,
      reason: caseStewardControlReason(caseControlReason, 'enable'),
    })
  }

  const confirmSuspendCasePilot = () => {
    modalApi.confirm({
      title: '停用案件数据管家试用？',
      content: '活动中的案件只读质检任务将取消；正式案件、人员和车辆数据不会被修改。',
      okText: '确认停用',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: () => caseSuspendMutation.mutate(caseStewardControlReason(caseControlReason, 'disable')),
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
        默认由内网规则引擎完成分析，不需要模型密钥、也不会向外部发送数据；如经安全评审启用外部模型，模型也只能接收临时别名和派生特征。所有候选修正必须人工审批。
      </div>

      {mapStatus && (
        <div className="card agent-pilot-card">
          <div className="card-head agent-pilot-head">
            <div>
              <RadarChartOutlined className="ico" />
              <span className="ti">地图数据管家 · 指定人员试用</span>
            </div>
            <Tag color={mapStatus.state === 'ready' ? 'green' : mapStatus.state === 'suspended' ? 'gold' : 'default'}>
              {mapStewardStateLabel(mapStatus.state)}
            </Tag>
          </div>
          <div className="card-body pad">
            <div className="agent-pilot-summary">
              <span>{mapStewardControlHint(mapStatus)}</span>
              {mapStatus.reason && <span className="agent-muted">最近调整：{mapStatus.reason}</span>}
            </div>
            <div className="agent-metric-grid">
              <div><strong>{mapStatus.metrics.runs_total}</strong><span>试用任务</span></div>
              <div><strong>{mapStatus.metrics.candidate_count}</strong><span>候选修正</span></div>
              <div><strong>{mapStatus.metrics.adoption_rate_percent}%</strong><span>人工采纳率</span></div>
              <div><strong>{mapStatus.metrics.evidence_coverage_percent}%</strong><span>证据覆盖率</span></div>
            </div>
            {user?.role === 'admin' && (
              <div className="agent-pilot-controls">
                <div>
                  <div className="agent-result-label">指定试用人员</div>
                  <Select
                    mode="multiple"
                    allowClear
                    showSearch
                    optionFilterProp="label"
                    className="agent-full-width"
                    placeholder="选择管理员或分析员"
                    value={pilotUserIds}
                    onChange={setPilotUserIds}
                    options={(mapStatus.eligible_users ?? []).map(item => ({
                      value: item.id,
                      label: `${item.display_name || item.username} · ${item.role === 'admin' ? '管理员' : '分析员'}`,
                    }))}
                  />
                </div>
                <div>
                  <div className="agent-result-label">调整原因</div>
                  <Input
                    value={controlReason}
                    onChange={event => setControlReason(event.target.value)}
                    maxLength={500}
                    placeholder="说明开启、暂停或停用原因"
                  />
                </div>
                <div className="agent-pilot-actions">
                  <button
                    className="btn-primary"
                    disabled={controlMutation.isPending}
                    onClick={() => updatePilotControl(false)}
                  >开启受控辅助</button>
                  <button
                    className="btn-ghost"
                    disabled={controlMutation.isPending}
                    onClick={() => updatePilotControl(true)}
                  >暂停候选写入</button>
                  <button
                    className="btn-ghost agent-danger-action"
                    disabled={suspendMutation.isPending}
                    onClick={confirmSuspendPilot}
                  >一键停用试用</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {caseStatus && (
        <div className="card agent-pilot-card">
          <div className="card-head agent-pilot-head">
            <div>
              <SafetyCertificateOutlined className="ico" />
              <span className="ti">案件数据管家 · 指定人员只读试用</span>
            </div>
            <Tag color={caseStatus.state === 'ready' ? 'green' : 'default'}>
              {caseStewardStateLabel(caseStatus.state)}
            </Tag>
          </div>
          <div className="card-body pad">
            <div className="agent-pilot-summary">
              <span>{caseStewardControlHint(caseStatus)}</span>
              {caseStatus.reason && <span className="agent-muted">最近调整：{caseStatus.reason}</span>}
            </div>
            <div className="agent-metric-grid">
              <div><strong>{caseStatus.metrics.runs_total}</strong><span>质检任务</span></div>
              <div><strong>{caseStatus.metrics.reviewed_case_count}</strong><span>复核案件</span></div>
              <div><strong>{caseStatus.metrics.runs_failed}</strong><span>失败任务</span></div>
              <div><strong>{caseStatus.metrics.evidence_coverage_percent}%</strong><span>证据覆盖率</span></div>
            </div>
            {user?.role === 'admin' && (
              <div className="agent-pilot-controls">
                <div>
                  <div className="agent-result-label">指定试用人员</div>
                  <Select
                    mode="multiple"
                    allowClear
                    showSearch
                    optionFilterProp="label"
                    className="agent-full-width"
                    placeholder="选择管理员或分析员"
                    value={casePilotUserIds}
                    onChange={setCasePilotUserIds}
                    options={(caseStatus.eligible_users ?? []).map(item => ({
                      value: item.id,
                      label: `${item.display_name || item.username} · ${item.role === 'admin' ? '管理员' : '分析员'}`,
                    }))}
                  />
                </div>
                <div>
                  <div className="agent-result-label">调整原因</div>
                  <Input
                    value={caseControlReason}
                    onChange={event => setCaseControlReason(event.target.value)}
                    maxLength={500}
                    placeholder="说明开启或停用原因"
                  />
                </div>
                <div className="agent-pilot-actions">
                  <button
                    className="btn-primary"
                    disabled={caseControlMutation.isPending}
                    onClick={updateCasePilotControl}
                  >开启只读试用</button>
                  <button
                    className="btn-ghost agent-danger-action"
                    disabled={caseSuspendMutation.isPending}
                    onClick={confirmSuspendCasePilot}
                  >一键停用试用</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="card agent-create-card">
        <div className="card-head"><RadarChartOutlined className="ico" /><span className="ti">新建受控任务</span></div>
        <div className="card-body pad agent-form-grid">
          <div>
            <div className="agent-result-label">能力类型</div>
            <Select
              value={taskType}
              onChange={value => {
                setTaskType(value)
                setQuery(TASK_OPTIONS.find(item => item.value === value)?.defaultQuery ?? '')
                if (isAssistMode && value === 'map_data_quality') setSelectedCaseIds([])
                if (isAssistMode && value === 'case_data_quality') setSelectedAssetIds([])
              }}
              className="agent-full-width"
              options={visibleTaskOptions.map(item => ({ value: item.value, label: item.label }))}
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
              placeholder={isAssistMode && taskType === 'map_data_quality' ? '地图数据管家试用不读取案件' : '选择需要质检的案件'}
              value={isAssistMode && taskType === 'map_data_quality' ? [] : selectedCaseIds}
              onChange={values => {
                const maxCases = caseStatus?.max_cases_per_run ?? 30
                if (isAssistMode && taskType === 'case_data_quality' && values.length > maxCases) {
                  messageApi.warning(`单次最多选择 ${maxCases} 起案件`)
                  return
                }
                setSelectedCaseIds(values)
              }}
              disabled={isAssistMode && taskType === 'map_data_quality'}
              optionFilterProp="label"
              loading={casesQuery.isLoading}
              options={(casesQuery.data ?? []).map(item => ({
                value: item.id,
                label: `${item.case_number} · ${item.location || '未知地点'}`,
              }))}
            />
          </div>
          <div>
            <div className="agent-result-label">地图资源范围</div>
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              className="agent-full-width"
              placeholder={isAssistMode && taskType === 'case_data_quality' ? '案件数据管家试用不读取地图资源' : '选择需要检查的地图资源'}
              value={isAssistMode && taskType === 'case_data_quality' ? [] : selectedAssetIds}
              onChange={values => {
                const maxAssets = mapStatus?.max_assets_per_run ?? 500
                if (isAssistMode && values.length > maxAssets) {
                  messageApi.warning(`单次最多选择 ${maxAssets} 项地图资源`)
                  return
                }
                setSelectedAssetIds(values)
              }}
              maxTagCount="responsive"
              disabled={isAssistMode && taskType === 'case_data_quality'}
              loading={assetsQuery.isLoading}
              options={(assetsQuery.data ?? []).map(item => ({
                value: item.id,
                label: `${item.name} · ${item.asset_type} · #${item.id}`,
              }))}
            />
            {isAssistMode && taskType === 'map_data_quality' && mapStatus && (
              <div className="agent-muted">单次最多选择 {mapStatus.max_assets_per_run} 项地图资源。</div>
            )}
            {isAssistMode && taskType === 'case_data_quality' && caseStatus && (
              <div className="agent-muted">单次最多选择 {caseStatus.max_cases_per_run} 起案件，只生成证据化质检结果。</div>
            )}
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
            <button
              className="btn-primary"
              onClick={handleCreate}
              disabled={createMutation.isPending || (
                isAssistMode && taskType === 'map_data_quality'
                  ? !canSubmitMapStewardRun(mapStatus, selectedAssetIds.length)
                  : isAssistMode && taskType === 'case_data_quality'
                    ? !canSubmitCaseStewardRun(caseStatus, selectedCaseIds.length)
                    : false
              )}
            >
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
                <div>
                  <strong>任务 {detail.id.slice(0, 8)}</strong>{' '}
                  <StatusBadge status={detail.status} />{' '}
                  <Tag color="cyan">{agentExecutionModeLabel(result?.mode)}</Tag>
                </div>
                <Space>
                  {isAgentRunActive(detail.status) && (
                    <button className="btn-ghost" onClick={() => cancelMutation.mutate(detail.id)}>取消</button>
                  )}
                  {canReview && (
                    detail.mode !== 'assist'
                    || (detail.task_type === 'map_data_quality' && mapStatus?.current_user_authorized)
                    || (detail.task_type === 'case_data_quality' && caseStatus?.current_user_authorized)
                  ) && (
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
                    <ApprovalCard
                      key={approval.id}
                      run={detail}
                      approval={approval}
                      canReview={canReview}
                      canApprove={Boolean(
                        canReview
                        && detail.mode === 'assist'
                        && detail.task_type === 'map_data_quality'
                        && mapStatus?.can_apply_changes
                      )}
                      onReview={reviewApproval}
                    />
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
