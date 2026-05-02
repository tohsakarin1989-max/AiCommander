import { useEffect, useState } from 'react'
import {
  Button, Modal, Form, Select, Input, message,
  Space, Badge, Alert, Progress, Steps, Divider,
  Tabs, List, Typography, Descriptions, Timeline,
} from 'antd'
import {
  TrophyOutlined, LoadingOutlined,
  FileAddOutlined, SaveOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { aiApi } from '../../services/ai'
import { configApi } from '../../services/config'
import { caseApi } from '../../services/cases'
import { useMeetingProgress } from '../../services/websocket'
import type { Meeting, MeetingCreate, MeetingTemplate, AIModel } from '../../types'
import dayjs from 'dayjs'
import { useSearchParams } from 'react-router-dom'
import './Meetings.css'

const { Text, Paragraph } = Typography
const { Option } = Select

// ——— Status configuration ———
const STATUS_CFG: Record<string, { label: string; color: string; phase: number; pulse?: boolean }> = {
  pending:        { label: '待开始',   color: '#4d6a8f', phase: 0 },
  processing:     { label: '分析中',   color: '#2dd4bf', phase: 1, pulse: true },
  first_opinions: { label: '独立分析中', color: '#2dd4bf', phase: 1, pulse: true },
  reviewing:      { label: '互评中',   color: '#a78bfa', phase: 2, pulse: true },
  ranking:        { label: '排名中',   color: '#fb923c', phase: 2, pulse: true },
  finalizing:     { label: '综合报告中', color: '#fbbf24', phase: 3, pulse: true },
  completed:      { label: '已完成',   color: '#10b981', phase: 3 },
  failed:         { label: '失败',     color: '#ef4444', phase: 0 },
}

const ACTIVE_STATUSES = ['processing', 'first_opinions', 'reviewing', 'ranking', 'finalizing']

// 阶段名称
const PHASE_LABELS = ['初始化', '独立分析', '匿名互评', '综合报告']

// ——— 阶段进度指示组件（inline，用于详情头部）———
const MeetingProgressIndicator: React.FC<{ meetingId: string; initialStatus?: string }> = ({ meetingId, initialStatus }) => {
  const { progress, isConnected } = useMeetingProgress(meetingId)

  const getCurrentStep = () => {
    if (!progress) {
      if (initialStatus === 'completed') return 3
      if (initialStatus === 'failed') return -1
      return 0
    }
    return progress.stage
  }

  const getStepStatus = (step: number): 'wait' | 'process' | 'finish' | 'error' => {
    if (!progress) {
      if (initialStatus === 'completed') return step <= 3 ? 'finish' : 'wait'
      if (initialStatus === 'failed') return 'error'
      return 'wait'
    }
    if (progress.status === 'failed') return 'error'
    if (step < progress.stage) return 'finish'
    if (step === progress.stage) return progress.status === 'completed' ? 'finish' : 'process'
    return 'wait'
  }

  const currentStep = getCurrentStep()
  const spinning = currentStep >= 0 && progress?.status !== 'completed'

  return (
    <div className="rt-progress-card">
      <div className="rt-progress-label">
        <span>进行中</span>
        <span className={isConnected ? 'rt-ws-live' : 'rt-ws-off'}>
          {isConnected ? '● 实时' : '○ 离线'}
        </span>
      </div>
      <Steps current={currentStep} size="small" items={[
        { title: '准备',     status: getStepStatus(0), icon: currentStep === 0 && spinning ? <LoadingOutlined /> : undefined },
        { title: '独立分析', status: getStepStatus(1), icon: currentStep === 1 && spinning ? <LoadingOutlined /> : undefined },
        { title: '匿名互评', status: getStepStatus(2), icon: currentStep === 2 && spinning ? <LoadingOutlined /> : undefined },
        { title: '综合报告', status: getStepStatus(3), icon: currentStep === 3 && spinning ? <LoadingOutlined /> : undefined },
      ]} />
      {progress && (
        <Progress
          percent={progress.progress}
          status={progress.status === 'failed' ? 'exception' : progress.progress === 100 ? 'success' : 'active'}
          strokeColor={{ '0%': '#2dd4bf', '100%': '#10b981' }}
          style={{ marginTop: 10 }}
        />
      )}
    </div>
  )
}

// ——— Phase Rail 组件 ———
interface PhaseRailProps {
  status: string
}

const PhaseRail: React.FC<PhaseRailProps> = ({ status }) => {
  const cfg = STATUS_CFG[status] || STATUS_CFG.pending
  const currentPhase = cfg.phase
  const isDone = status === 'completed'
  const isFailed = status === 'failed'

  return (
    <div className="phase-rail">
      {PHASE_LABELS.map((label, idx) => {
        const phaseNum = idx // 0=初始化, 1=独立分析, 2=匿名互评, 3=综合报告
        const isDonePhase = isDone || phaseNum < currentPhase
        const isActivePhase = !isFailed && phaseNum === currentPhase && status !== 'pending' && !isDone

        let cls = 'phase'
        if (isDonePhase) cls += ' done'
        else if (isActivePhase) cls += ' active'

        return (
          <div key={idx} className={cls}>
            <div className="num">{isDonePhase ? '✓' : String(idx + 1).padStart(2, '0')}</div>
            <div className="nm">{label}</div>
            <div className="t">
              {isDonePhase ? '已完成' : isActivePhase ? '进行中' : '待开始'}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ——— 左侧会议卡片（用于列表）———
interface RtCardProps {
  meeting: Meeting
  selected: boolean
  onSelect: () => void
}

const RtCard: React.FC<RtCardProps> = ({ meeting, selected, onSelect }) => {
  const isLive = ACTIVE_STATUSES.includes(meeting.status)
  const isDone = meeting.status === 'completed'

  const phaseText = (() => {
    if (isDone) return `已完成 · ${meeting.analyst_model_ids.length} 路 AI`
    if (isLive) {
      const phaseNames: Record<string, string> = {
        processing: '阶段 1 · 独立分析',
        first_opinions: '阶段 1 · 独立分析',
        reviewing: '阶段 2 · 匿名互评',
        ranking: '阶段 2 · 匿名互评',
        finalizing: '阶段 3 · 综合报告',
      }
      return phaseNames[meeting.status] || '处理中'
    }
    return STATUS_CFG[meeting.status]?.label || '待开始'
  })()

  const idShort = meeting.meeting_id.length > 14
    ? meeting.meeting_id.slice(0, 12) + '…'
    : meeting.meeting_id

  let cardCls = 'rt-card'
  if (isLive) cardCls += ' live'
  if (isDone) cardCls += ' done'
  if (selected) cardCls += ' sel'

  return (
    <div className={cardCls} onClick={onSelect}>
      <div className="rt-c-head">
        <span className="rt-id">{idShort}</span>
        {isLive && <span className="live-dot">● LIVE</span>}
      </div>
      <div className="rt-c-title">
        {meeting.case_ids.length > 0
          ? `案件 #${meeting.case_ids.slice(0, 2).join(' #')}${meeting.case_ids.length > 2 ? ` +${meeting.case_ids.length - 2}` : ''} 研判`
          : '未关联案件'}
      </div>
      <div className="rt-c-phase">{phaseText}</div>
      <div className="rt-c-foot">
        <span>{dayjs(meeting.created_at).format('HH:mm · MM-DD')}</span>
        <span>{meeting.analyst_model_ids.length} 路 AI</span>
      </div>
    </div>
  )
}

// ——— 状态筛选类型 ———
type FilterType = 'all' | 'live' | 'done'

// ——— Main Component ———
const Meetings: React.FC = () => {
  const [form] = Form.useForm()
  const [templateForm] = Form.useForm()
  const [isModalVisible, setIsModalVisible] = useState(false)
  const [templateModalVisible, setTemplateModalVisible] = useState(false)
  const [selectedMeeting, setSelectedMeeting] = useState<string | null>(null)
  // 详情视图弹窗（modal）
  const [viewModalVisible, setViewModalVisible] = useState(false)
  const [_processingMeetingId, setProcessingMeetingId] = useState<string | null>(null)
  const [filterType, setFilterType] = useState<FilterType>('all')
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()

  // ——— Queries ———
  const { data: meetings, isLoading } = useQuery({
    queryKey: ['meetings'],
    queryFn: () => aiApi.meeting.list(),
  })

  useEffect(() => {
    const meetingId = searchParams.get('meetingId')
    if (!meetingId || !meetings) return
    const exists = meetings.some((m: Meeting) => m.meeting_id === meetingId)
    if (exists) {
      setSelectedMeeting(meetingId)
      setViewModalVisible(true)
    }
  }, [searchParams, meetings])

  const { data: models } = useQuery({ queryKey: ['models'], queryFn: () => configApi.models.list() })
  const { data: cases }  = useQuery({ queryKey: ['cases'],  queryFn: () => caseApi.getCases() })

  const { data: templates } = useQuery({
    queryKey: ['meetingTemplates'],
    queryFn: () => aiApi.template.list(),
  })

  const { data: meetingConfigRaw } = useQuery({
    queryKey: ['meetingConfig'],
    queryFn: () => configApi.system.getMeetingConfig(),
  })

  const meetingConfig = meetingConfigRaw as
    | { provider?: string; api_key?: string; api_base_url?: string }
    | undefined

  // 详情数据
  const { data: conversations } = useQuery({
    queryKey: ['conversations', selectedMeeting],
    queryFn: () => aiApi.meeting.getConversations(selectedMeeting!),
    enabled: !!selectedMeeting,
  })
  const { data: report } = useQuery({
    queryKey: ['report', selectedMeeting],
    queryFn: () => aiApi.meeting.getReport(selectedMeeting!),
    enabled: !!selectedMeeting,
  })
  const { data: analyses } = useQuery({
    queryKey: ['analyses', selectedMeeting],
    queryFn: () => aiApi.meeting.getAnalyses(selectedMeeting!),
    enabled: !!selectedMeeting,
  })
  const { data: rankings } = useQuery({
    queryKey: ['rankings', selectedMeeting],
    queryFn: () => aiApi.meeting.getRankings(selectedMeeting!),
    enabled: !!selectedMeeting,
  })

  // ——— Mutations ———
  const generateConclusionMutation = useMutation({
    mutationFn: (id: string) => aiApi.conclusion.generateFromMeeting(id),
    onSuccess: () => message.success('结论生成成功，可在结论工厂中查看'),
    onError: (err: any) => message.error(err?.response?.data?.detail || '结论生成失败'),
  })

  const useTemplateMutation = useMutation({
    mutationFn: (id: number) => aiApi.template.use(id),
    onSuccess: (data) => {
      form.setFieldsValue({ moderator_model_id: data.moderator_model_id, analyst_model_ids: data.analyst_model_ids })
      message.success('已应用模板配置')
    },
    onError: (err: any) => message.error(err?.response?.data?.detail || '应用模板失败'),
  })

  const saveTemplateMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; moderator_model_id: number; analyst_model_ids: number[] }) =>
      aiApi.template.create(data),
    onSuccess: () => {
      message.success('模板保存成功')
      setTemplateModalVisible(false)
      templateForm.resetFields()
      queryClient.invalidateQueries({ queryKey: ['meetingTemplates'] })
    },
    onError: (err: any) => message.error(err?.response?.data?.detail || '保存模板失败'),
  })

  const createMutation = useMutation({
    mutationFn: aiApi.meeting.create,
    onSuccess: (data) => {
      message.success('会议已创建，正在后台处理中')
      setIsModalVisible(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['meetings'] })

      if (data.status === 'processing' && data.meeting_id) {
        setProcessingMeetingId(data.meeting_id)
        // 创建后自动选中新会议
        setSelectedMeeting(data.meeting_id)

        const poll = setInterval(() => {
          queryClient.invalidateQueries({ queryKey: ['meetings'] })
          queryClient.fetchQuery({
            queryKey: ['meeting', data.meeting_id],
            queryFn: () => aiApi.meeting.get(data.meeting_id),
          }).then((m: Meeting) => {
            if (m.status === 'completed' || m.status === 'failed') {
              clearInterval(poll)
              setProcessingMeetingId(null)
              if (m.status === 'completed') message.success('会议分析完成！')
              else message.error('会议分析失败')
              queryClient.invalidateQueries({ queryKey: ['meetings'] })
            }
          }).catch(() => {})
        }, 5000)
        setTimeout(() => { clearInterval(poll); setProcessingMeetingId(null) }, 300000)
      }
    },
    onError: (err: any) => message.error(`创建失败: ${err.response?.data?.detail || err.message}`),
  })

  // ——— Helpers ———
  const handleSaveAsTemplate = async () => {
    try {
      const values = await form.validateFields(['moderator_model_id', 'analyst_model_ids'])
      templateForm.setFieldsValue(values)
      setTemplateModalVisible(true)
    } catch { message.warning('请先选择主持人和分析员模型') }
  }

  const handleTemplateSubmit = async () => {
    try { saveTemplateMutation.mutate(await templateForm.validateFields()) } catch {}
  }

  const handleCreate = async () => {
    try { createMutation.mutate(await form.validateFields() as MeetingCreate) } catch {}
  }

  const moderatorModels = models?.filter((m: AIModel) => m.role === 'moderator') || []
  const analystModels   = models?.filter((m: AIModel) => m.role === 'analyst')   || []

  const totalMeetings     = meetings?.length || 0
  const liveMeetings      = meetings?.filter((m: Meeting) => ACTIVE_STATUSES.includes(m.status)) || []
  const doneMeetings      = meetings?.filter((m: Meeting) => m.status === 'completed') || []
  const activeMeetingsCount  = liveMeetings.length
  const completedMeetingsCount = doneMeetings.length

  // 筛选后的会议列表（反转为最新在前）
  const reversedMeetings = meetings ? [...meetings].reverse() : []
  const filteredMeetings = reversedMeetings.filter((m: Meeting) => {
    if (filterType === 'live') return ACTIVE_STATUSES.includes(m.status)
    if (filterType === 'done') return m.status === 'completed'
    return true
  })

  // 当前选中会议数据
  const selectedData    = meetings?.find((m: Meeting) => m.meeting_id === selectedMeeting)
  const selectedStatus  = selectedData?.status || 'pending'
  const isSelProcessing = ACTIVE_STATUSES.includes(selectedStatus)
  const isSelDone       = selectedStatus === 'completed'

  const getModelName = (id: number) => models?.find((m: AIModel) => m.id === id)?.name || `Model-${id}`
  const moderatorName  = selectedData ? getModelName(selectedData.moderator_model_id) : '主持人'
  const analystNames   = selectedData?.analyst_model_ids.map(getModelName) || []

  // Modal 样式
  const modalStyles = {
    content: { background: 'var(--bg-1)', border: '1px solid var(--line)', padding: 0, borderRadius: 0 },
    header:  { background: 'var(--bg-1)', borderBottom: '1px solid var(--line)', padding: '14px 20px' },
    body:    { background: 'var(--bg-1)', padding: '18px 20px' },
    footer:  { background: 'var(--bg-1)', borderTop: '1px solid var(--line)', padding: '10px 20px' },
  }

  // ——— 报告内容解析 ———
  const rc = report
    ? typeof report.content === 'string' ? null : (report.content as any)
    : null

  return (
    <div className="page page-roundtable">
      <div className="rt-layout">

        {/* ===== LEFT: 会议列表 ===== */}
        <aside className="rt-list">

          {/* 列表头 */}
          <div className="rt-list-head">
            <div className="page-title" style={{ border: 0, padding: 0, margin: 0, display: 'block' }}>
              <h1>圆桌会议</h1>
              <div className="sub">MULTI-AGENT COUNCIL · 本月 {totalMeetings} 场</div>
            </div>
            <button
              className="btn-accent"
              style={{ marginTop: 12, width: '100%' }}
              onClick={() => { form.resetFields(); setIsModalVisible(true) }}
            >
              ＋ 发起新会议
            </button>
          </div>

          {/* 状态筛选 */}
          <div className="rt-filters">
            <div className="seg">
              <button
                className={filterType === 'live' ? 'on' : ''}
                onClick={() => setFilterType(filterType === 'live' ? 'all' : 'live')}
              >
                进行中 {activeMeetingsCount}
              </button>
              <button
                className={filterType === 'done' ? 'on' : ''}
                onClick={() => setFilterType(filterType === 'done' ? 'all' : 'done')}
              >
                已完成 {completedMeetingsCount}
              </button>
              <button
                className={filterType === 'all' ? 'on' : ''}
                onClick={() => setFilterType('all')}
              >
                全部 {totalMeetings}
              </button>
            </div>
          </div>

          {/* 会议卡片列表 */}
          <div className="rt-meetings">
            {isLoading ? (
              <>
                <div className="rt-card-skeleton" />
                <div className="rt-card-skeleton" />
                <div className="rt-card-skeleton" />
              </>
            ) : filteredMeetings.length > 0 ? (
              filteredMeetings.map((meeting: Meeting) => (
                <RtCard
                  key={meeting.meeting_id}
                  meeting={meeting}
                  selected={selectedMeeting === meeting.meeting_id}
                  onSelect={() => setSelectedMeeting(meeting.meeting_id)}
                />
              ))
            ) : (
              <div className="empty-state">
                <div className="icon">⚔</div>
                <div>尚无会议记录</div>
              </div>
            )}
          </div>
        </aside>

        {/* ===== RIGHT: 会议详情 ===== */}
        <section className="rt-detail">

          {selectedData ? (
            <>
              {/* 详情头部 */}
              <div className="rt-detail-head card">
                <div className="rt-title">
                  <div className="ti-row">
                    <span className="rt-id-big">
                      {selectedData.meeting_id.length > 14
                        ? selectedData.meeting_id.slice(0, 12) + '…'
                        : selectedData.meeting_id}
                    </span>
                    {isSelProcessing && <span className="live-dot">● LIVE</span>}
                    <span style={{ marginLeft: 'auto', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-3)' }}>
                      {isSelProcessing ? '处理中' : isSelDone ? '已完成' : STATUS_CFG[selectedStatus]?.label}
                      {' · '}
                      {selectedData.analyst_model_ids.length} 路 AI
                    </span>
                  </div>
                  <h2>
                    {selectedData.case_ids.length > 0
                      ? `案件 ${selectedData.case_ids.slice(0, 3).map(id => `#${id}`).join(' ')}${selectedData.case_ids.length > 3 ? ` +${selectedData.case_ids.length - 3}` : ''} · 综合研判`
                      : '未关联案件 · 综合研判'}
                  </h2>
                  <div className="rt-sub">
                    主持人 {moderatorName}
                    {' · '}
                    {dayjs(selectedData.created_at).format('MM-DD HH:mm')}
                    {analystNames.length > 0 && ` · 分析员：${analystNames.slice(0, 3).join('、')}${analystNames.length > 3 ? `…+${analystNames.length - 3}` : ''}`}
                  </div>
                </div>

                {/* 阶段进度轨道 */}
                <PhaseRail status={selectedStatus} />

                {/* 实时进度条（进行中时显示） */}
                {isSelProcessing && (
                  <div style={{ padding: '0 20px 14px' }}>
                    <MeetingProgressIndicator meetingId={selectedData.meeting_id} initialStatus={selectedStatus} />
                  </div>
                )}
              </div>

              {/* AI 分析列网格 */}
              <div className="rt-grid">
                {analyses && analyses.length > 0 ? (
                  analyses.map((analysis: any, idx: number) => {
                    const modelId = analysis.analyst_model_id
                    const modelObj = models?.find((m: AIModel) => m.id === modelId)
                    const modelName = modelObj?.name || `分析员 ${idx + 1}`
                    const initial = modelName.charAt(0).toUpperCase()
                    // 循环选色
                    const badgeColors = [
                      'oklch(0.78 0.14 155)',
                      'oklch(0.78 0.14 45)',
                      'oklch(0.78 0.11 220)',
                      'oklch(0.72 0.14 285)',
                    ]
                    const badgeColor = badgeColors[idx % badgeColors.length]
                    const contentStr = typeof analysis.result_content === 'string'
                      ? analysis.result_content
                      : JSON.stringify(analysis.result_content, null, 2)

                    // 找该分析员的互评数据
                    const myRankings = rankings?.filter((r: any) =>
                      r.stage === 'review' && r.evaluator_model_id === modelId
                    ) || []

                    // 找综合报告（主持人）
                    const isModerator = modelId === selectedData.moderator_model_id

                    return (
                      <div key={idx} className="card rt-ai-col">
                        <div className="ai-head">
                          <div className="ai-badge" style={{ '--c': badgeColor } as React.CSSProperties}>
                            {initial}
                          </div>
                          <div>
                            <div className="ai-name">{modelName}</div>
                            <div className="ai-role">
                              {isModerator ? '主持人 · 综合报告' : `分析员 ${idx + 1} · 独立研判`}
                            </div>
                          </div>
                          <span className={`ai-stat ${isSelProcessing ? 'live' : 'done'}`}>
                            {isSelProcessing ? '● 生成中' : '✓ 已提交'}
                          </span>
                        </div>
                        <div className="ai-body">
                          {/* 阶段1内容 */}
                          <div className="msg-block">
                            <div className="mb-head">
                              <span className="ph">阶段 1 · 独立分析</span>
                              <span className="t">{dayjs(selectedData.created_at).format('HH:mm')}</span>
                            </div>
                            <p style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 180, overflow: 'hidden', fontSize: 11 }}>
                              {contentStr.length > 400 ? contentStr.slice(0, 400) + '…' : contentStr}
                            </p>
                          </div>
                          {/* 互评数据（如有） */}
                          {myRankings.length > 0 && (
                            <div className="msg-block">
                              <div className="mb-head">
                                <span className="ph" style={{ color: 'var(--info)' }}>阶段 2 · 互评</span>
                                <span className="t">{myRankings[0].ranking_data?.rankings?.length || 0} 项评分</span>
                              </div>
                              <p style={{ fontSize: 11 }}>
                                {myRankings[0].ranking_data?.overall_comment || '已提交评分'}
                              </p>
                            </div>
                          )}
                          {/* 综合报告（主持人或已完成） */}
                          {isSelDone && report && isModerator && (
                            <div className="msg-block gen">
                              <div className="mb-head">
                                <span className="ph" style={{ color: 'var(--accent)' }}>阶段 3 · 综合</span>
                                <span className="t">已完成</span>
                              </div>
                              <p style={{ fontSize: 11 }}>
                                {rc?.summary || report.summary || '综合报告已生成'}
                              </p>
                            </div>
                          )}
                          {/* 正在生成中 */}
                          {isSelProcessing && STATUS_CFG[selectedStatus]?.phase === 3 && isModerator && (
                            <div className="msg-block gen">
                              <div className="mb-head">
                                <span className="ph" style={{ color: 'var(--accent)' }}>阶段 3 · 综合</span>
                                <span className="t">生成中</span>
                              </div>
                              <p className="typing" style={{ fontSize: 11 }}>
                                正在汇总各方分析，生成最终研判报告<span className="caret">▊</span>
                              </p>
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })
                ) : (
                  // 占位列（显示分析员名称）
                  selectedData.analyst_model_ids.map((modelId: number, idx: number) => {
                    const modelName = getModelName(modelId)
                    const initial = modelName.charAt(0).toUpperCase()
                    const badgeColors = [
                      'oklch(0.78 0.14 155)',
                      'oklch(0.78 0.14 45)',
                      'oklch(0.78 0.11 220)',
                      'oklch(0.72 0.14 285)',
                    ]
                    const badgeColor = badgeColors[idx % badgeColors.length]
                    return (
                      <div key={idx} className="card rt-ai-col">
                        <div className="ai-head">
                          <div className="ai-badge" style={{ '--c': badgeColor } as React.CSSProperties}>
                            {initial}
                          </div>
                          <div>
                            <div className="ai-name">{modelName}</div>
                            <div className="ai-role">分析员 · 待分析</div>
                          </div>
                          <span className="ai-stat" style={{ color: 'var(--ink-3)', borderColor: 'var(--line)' }}>
                            {isSelProcessing ? '● 等待中' : '— 待开始'}
                          </span>
                        </div>
                        <div className="ai-body">
                          <div className="empty-state" style={{ padding: '30px 10px' }}>
                            <div style={{ fontSize: 12 }}>暂无分析数据</div>
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>

              {/* 综合报告面板 */}
              <div className="card rt-synth">
                <div className="card-head">
                  <span className="ico">⌖</span>
                  <span className="ti">综合报告</span>
                  <span className="spacer" />
                  {isSelDone && (
                    <span className="chip accent">
                      {selectedData.analyst_model_ids.length} AI 协作
                    </span>
                  )}
                  {isSelProcessing && (
                    <span className="chip live">
                      <span className="dot" />
                      实时汇聚
                    </span>
                  )}
                  <button
                    className="btn-ghost-sm"
                    onClick={() => selectedData && setViewModalVisible(true)}
                  >
                    详情
                  </button>
                  {isSelDone && (
                    <button
                      className="btn-accent-sm"
                      onClick={() => selectedMeeting && generateConclusionMutation.mutate(selectedMeeting)}
                      disabled={generateConclusionMutation.isPending}
                    >
                      {generateConclusionMutation.isPending ? '生成中…' : '生成结论'}
                    </button>
                  )}
                </div>
                <div className="card-body" style={{ padding: '14px 18px' }}>
                  {isSelDone && report ? (
                    <div className="synth-grid">
                      {/* 结论 */}
                      <div className="synth-col">
                        <div className="sh">结论</div>
                        <ul>
                          {(rc?.consensus_points || report.consensus_points || []).slice(0, 4).map((pt: string, i: number) => (
                            <li key={i}>{pt}</li>
                          ))}
                          {(!rc?.consensus_points && !report.consensus_points) && (
                            <li>{rc?.summary || report.summary || '综合报告已生成'}</li>
                          )}
                        </ul>
                      </div>
                      {/* 行动建议 */}
                      <div className="synth-col">
                        <div className="sh">行动建议</div>
                        <ul>
                          {(rc?.recommendations || report.recommendations || []).slice(0, 4).map((rec: string, i: number) => (
                            <li key={i}>{rec}</li>
                          ))}
                          {!(rc?.recommendations || report.recommendations)?.length && (
                            <li>详见完整报告</li>
                          )}
                        </ul>
                      </div>
                      {/* 分歧 */}
                      <div className="synth-col">
                        <div className="sh">分歧 / 待观察</div>
                        <ul>
                          {(rc?.disagreement_points || report.disagreement_points || []).slice(0, 3).map((pt: string, i: number) => (
                            <li key={i}>{pt}</li>
                          ))}
                          {!(rc?.disagreement_points || report.disagreement_points)?.length && (
                            <li>各 AI 意见基本一致</li>
                          )}
                        </ul>
                      </div>
                    </div>
                  ) : isSelProcessing ? (
                    <div className="synth-processing">
                      <span className="caret">▊</span>
                      <span style={{ marginLeft: 10, color: 'var(--ink-3)', fontSize: 12 }}>
                        正在等待各阶段完成后生成综合报告…
                      </span>
                    </div>
                  ) : (
                    <div className="empty-state" style={{ padding: '20px 10px' }}>
                      <div>综合报告尚未生成</div>
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            /* 未选中时的空状态 */
            <div className="rt-no-selection">
              <div className="rt-no-sel-inner">
                <div className="rt-no-sel-icon">⌖</div>
                <div className="rt-no-sel-title">请从左侧选择一场会议</div>
                <div className="rt-no-sel-sub">或发起新的圆桌会议</div>
                <button
                  className="btn-accent"
                  style={{ marginTop: 20 }}
                  onClick={() => { form.resetFields(); setIsModalVisible(true) }}
                >
                  ＋ 发起新会议
                </button>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* 配置告警 */}
      {meetingConfig?.provider === 'openrouter' && !meetingConfig?.api_key && (
        <div style={{ position: 'fixed', top: 70, right: 20, zIndex: 300, maxWidth: 400 }}>
          <Alert
            message="圆桌会议 API 配置缺失"
            description={<span>当前为 OpenRouter 模式，但未配置 API 密钥。</span>}
            type="warning" showIcon closable
          />
        </div>
      )}

      {/* =================== CREATE MEETING MODAL =================== */}
      <Modal
        title={
          <div className="modal-hdr">
            <span className="modal-hdr-title">发起圆桌会议</span>
          </div>
        }
        open={isModalVisible}
        onOk={handleCreate}
        onCancel={() => { setIsModalVisible(false); form.resetFields() }}
        width={640}
        confirmLoading={createMutation.isPending}
        okText="发起"
        cancelText="取消"
        styles={modalStyles}
      >
        <Form form={form} layout="vertical">
          {templates && templates.length > 0 && (
            <Form.Item label={<span style={{ color: 'var(--ink-3)', fontSize: 11, fontFamily: 'var(--mono)', letterSpacing: '0.08em' }}>快速选择模板</span>}>
              <Space wrap>
                {templates.map((t: MeetingTemplate) => (
                  <Button key={t.id} icon={<ThunderboltOutlined />} size="small"
                    onClick={() => useTemplateMutation.mutate(t.id)}
                    loading={useTemplateMutation.isPending}
                    style={{ background: 'var(--bg-2)', borderColor: 'var(--line)', color: 'var(--ink-2)', fontFamily: 'var(--mono)', borderRadius: 0 }}
                  >
                    {t.name}
                    {t.use_count > 0 && <Badge count={t.use_count} size="small" style={{ marginLeft: 4 }} />}
                  </Button>
                ))}
              </Space>
            </Form.Item>
          )}

          <Form.Item name="case_ids"
            label={<span style={{ color: 'var(--ink-3)', fontSize: 11, fontFamily: 'var(--mono)' }}>关联案件</span>}
            rules={[{ required: true, message: '请选择至少一个案件' }]}
          >
            <Select mode="multiple" placeholder="选择参与分析的案件">
              {cases?.map((c: any) => (
                <Option key={c.id} value={c.id}>{c.case_number} — {c.location}</Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item name="moderator_model_id"
            label={<span style={{ color: 'var(--ink-3)', fontSize: 11, fontFamily: 'var(--mono)' }}>主持人模型（综合报告生成者）</span>}
            rules={[{ required: true, message: '请选择主持人模型' }]}
          >
            <Select placeholder="选择主持人">
              {moderatorModels.map((m: AIModel) => (
                <Option key={m.id} value={m.id}>{m.name} ({m.model_name})</Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item name="analyst_model_ids"
            label={<span style={{ color: 'var(--ink-3)', fontSize: 11, fontFamily: 'var(--mono)' }}>分析员模型（建议 3-5 名）</span>}
            rules={[{ required: true, message: '请选择至少一个分析员' }]}
          >
            <Select mode="multiple" placeholder="选择分析员">
              {analystModels.map((m: AIModel) => (
                <Option key={m.id} value={m.id}>{m.name} ({m.model_name})</Option>
              ))}
            </Select>
          </Form.Item>

          <Divider style={{ borderColor: 'var(--line)' }} />
          <div style={{ textAlign: 'right' }}>
            <Button icon={<SaveOutlined />} onClick={handleSaveAsTemplate}
              style={{ background: 'transparent', borderColor: 'var(--line)', color: 'var(--ink-2)', fontFamily: 'var(--mono)', borderRadius: 0 }}
            >
              保存为模板
            </Button>
          </div>
        </Form>
      </Modal>

      {/* =================== SAVE TEMPLATE MODAL =================== */}
      <Modal
        title="保存为模板"
        open={templateModalVisible}
        onOk={handleTemplateSubmit}
        onCancel={() => { setTemplateModalVisible(false); templateForm.resetFields() }}
        confirmLoading={saveTemplateMutation.isPending}
        styles={modalStyles}
      >
        <Form form={templateForm} layout="vertical">
          <Form.Item name="name" label="模板名称" rules={[{ required: true, message: '请输入模板名称' }]}>
            <Input placeholder="例如：涉油案件标准分析" />
          </Form.Item>
          <Form.Item name="description" label="模板描述">
            <Input.TextArea placeholder="描述模板的适用场景" rows={2} />
          </Form.Item>
          <Form.Item name="moderator_model_id" hidden><Input /></Form.Item>
          <Form.Item name="analyst_model_ids" hidden><Input /></Form.Item>
        </Form>
      </Modal>

      {/* =================== MEETING DETAIL MODAL =================== */}
      <Modal
        title={
          <div className="modal-hdr">
            <span className="modal-hdr-title">圆桌分析详情</span>
            {selectedMeeting && (
              <code className="modal-meeting-id" title={selectedMeeting}>
                {selectedMeeting.length > 24 ? `${selectedMeeting.slice(0, 22)}…` : selectedMeeting}
              </code>
            )}
            {selectedData && (
              <span style={{ marginLeft: 'auto', fontSize: 12, fontFamily: 'var(--mono)', color: STATUS_CFG[selectedData.status]?.color }}>
                {STATUS_CFG[selectedData.status]?.label}
              </span>
            )}
          </div>
        }
        open={viewModalVisible}
        onCancel={() => setViewModalVisible(false)}
        width={1200}
        footer={null}
        styles={{
          ...modalStyles,
          body: { background: 'var(--bg-1)', padding: '18px 20px', maxHeight: 'calc(90vh - 120px)', overflowY: 'auto' },
        }}
      >
        {selectedMeeting && selectedData && (
          <div>
            <Tabs defaultActiveKey="stage1" items={[

              // ─── 独立分析 ───
              {
                key: 'stage1',
                label: (
                  <Badge count={analyses?.length || 0} offset={[10, 0]} size="small">
                    <span>独立分析</span>
                  </Badge>
                ),
                children: (
                  <div>
                    <div className="stage-header">
                      <div className="stage-num">01</div>
                      <div>
                        <div className="stage-title">独立分析阶段</div>
                        <div className="stage-desc">各分析员相互隔离，独立对案件进行深度分析，不受他方影响</div>
                      </div>
                    </div>
                    {analyses && analyses.length > 0 ? (
                      <Tabs type="card" size="small" items={
                        analyses.map((analysis: any, idx: number) => {
                          const model = models?.find((m: AIModel) => m.id === analysis.analyst_model_id)
                          const content = typeof analysis.result_content === 'string'
                            ? analysis.result_content
                            : JSON.stringify(analysis.result_content, null, 2)
                          return {
                            key: `a-${idx}`,
                            label: model?.name || `分析员 ${idx + 1}`,
                            children: <div className="analysis-content">{content}</div>,
                          }
                        })
                      } />
                    ) : (
                      <div className="empty-state"><div>暂无分析数据</div></div>
                    )}
                  </div>
                ),
              },

              // ─── 匿名互评 ───
              {
                key: 'stage2',
                label: <span><TrophyOutlined /> 匿名互评</span>,
                children: (
                  <div>
                    <div className="stage-header">
                      <div className="stage-num">02</div>
                      <div>
                        <div className="stage-title">匿名互评阶段</div>
                        <div className="stage-desc">每位分析员匿名审阅并对其他分析结果评分排名，排除身份偏见</div>
                      </div>
                    </div>

                    {rankings?.filter((r: any) => r.stage === 'review').map((ranking: any, idx: number) => {
                      const model = models?.find((m: AIModel) => m.id === ranking.evaluator_model_id)
                      return (
                        <div key={idx} className="report-section" style={{ marginBottom: 12 }}>
                          <div className="report-section-title">{model?.name || '评审员'} 的评分</div>
                          {ranking.ranking_data?.rankings?.length > 0 ? (
                            <List size="small"
                              dataSource={ranking.ranking_data.rankings}
                              renderItem={(item: any, i: number) => (
                                <List.Item style={{ borderColor: 'var(--line-soft)', padding: '7px 0' }}>
                                  <Space>
                                    <Badge count={item.rank}
                                      style={{ backgroundColor: i === 0 ? '#e8b84b' : i === 1 ? '#94a3b8' : '#6b4c2a' }}
                                    />
                                    <div>
                                      <Text strong style={{ color: 'var(--ink-1)', fontSize: 12 }}>匿名ID: {item.anonymous_id}</Text>
                                      <br />
                                      <Text style={{ color: 'var(--ink-3)', fontSize: 11 }}>得分: {item.score}/10</Text>
                                      <br />
                                      <Text style={{ color: 'var(--ink-3)', fontSize: 11 }}>{item.reasoning}</Text>
                                    </div>
                                  </Space>
                                </List.Item>
                              )}
                            />
                          ) : (
                            <Text style={{ color: 'var(--ink-3)', fontSize: 12 }}>暂无排名数据</Text>
                          )}
                          {ranking.ranking_data?.overall_comment && (
                            <>
                              <Divider style={{ borderColor: 'var(--line-soft)', margin: '8px 0' }} />
                              <Text style={{ color: 'var(--ink-2)', fontSize: 12 }}>{ranking.ranking_data.overall_comment}</Text>
                            </>
                          )}
                        </div>
                      )
                    })}

                    {rankings?.find((r: any) => r.stage === 'final') && (
                      <div className="report-section">
                        <div className="report-section-title">综合排名统计</div>
                        <Descriptions column={1} size="small">
                          {Object.entries(
                            rankings.find((r: any) => r.stage === 'final')?.aggregated_data?.rankings || {}
                          ).map(([key, data]: [string, any]) => (
                            <Descriptions.Item key={key}
                              label={<span style={{ color: 'var(--ink-3)', fontSize: 12 }}>分析结果 {parseInt(key) + 1}</span>}
                            >
                              <Space>
                                <span style={{ color: '#e8b84b', fontSize: 12 }}>均分: {data.average_score}</span>
                                <span style={{ color: 'var(--ink-2)', fontSize: 12 }}>均名: {data.average_rank}</span>
                                <span style={{ color: 'var(--ink-3)', fontSize: 12 }}>{data.vote_count} 票</span>
                              </Space>
                            </Descriptions.Item>
                          ))}
                        </Descriptions>
                      </div>
                    )}

                    {(!rankings || rankings.length === 0) && (
                      <div className="empty-state"><div>暂无互评数据</div></div>
                    )}
                  </div>
                ),
              },

              // ─── 综合报告 ───
              {
                key: 'stage3',
                label: '综合报告',
                children: (
                  <div>
                    <div className="stage-header">
                      <div className="stage-num">03</div>
                      <div>
                        <div className="stage-title">综合报告阶段</div>
                        <div className="stage-desc">主持人汇总所有分析与排名，生成最终研判报告</div>
                      </div>
                    </div>

                    {report ? (
                      <div>
                        <div className="report-section">
                          <div className="report-section-title">执行摘要</div>
                          <Paragraph style={{ color: 'var(--ink-2)', fontSize: 13, margin: 0, lineHeight: 1.7 }}>
                            {rc?.summary || report.summary || '—'}
                          </Paragraph>
                        </div>

                        {(rc?.consensus_points || report.consensus_points || []).length > 0 && (
                          <div className="report-section">
                            <div className="report-section-title">共识点</div>
                            <List size="small"
                              dataSource={rc?.consensus_points || report.consensus_points || []}
                              renderItem={(item: string) => (
                                <List.Item style={{ borderColor: 'var(--line-soft)', padding: '5px 0', color: 'var(--ink-2)', fontSize: 13 }}>
                                  <span style={{ color: 'var(--ok)', marginRight: 10 }}>✓</span>{item}
                                </List.Item>
                              )}
                            />
                          </div>
                        )}

                        {(rc?.disagreement_points || report.disagreement_points || []).length > 0 && (
                          <div className="report-section">
                            <div className="report-section-title">分歧点</div>
                            <List size="small"
                              dataSource={rc?.disagreement_points || report.disagreement_points || []}
                              renderItem={(item: string) => (
                                <List.Item style={{ borderColor: 'var(--line-soft)', padding: '5px 0', color: 'var(--ink-2)', fontSize: 13 }}>
                                  <span style={{ color: 'var(--warn)', marginRight: 10 }}>△</span>{item}
                                </List.Item>
                              )}
                            />
                          </div>
                        )}

                        {rc?.top_ranked_insights && rc.top_ranked_insights.length > 0 && (
                          <div className="report-section">
                            <div className="report-section-title">排名靠前的关键洞察</div>
                            <List size="small"
                              dataSource={rc.top_ranked_insights}
                              renderItem={(item: string, i: number) => (
                                <List.Item style={{ borderColor: 'var(--line-soft)', padding: '5px 0', color: 'var(--ink-2)', fontSize: 13 }}>
                                  <span style={{ color: 'var(--accent)', marginRight: 10 }}>#{i + 1}</span>{item}
                                </List.Item>
                              )}
                            />
                          </div>
                        )}

                        {rc?.conclusions && (
                          <div className="report-section">
                            <div className="report-section-title">综合结论</div>
                            <Paragraph style={{ color: 'var(--ink-2)', fontSize: 13, margin: 0, whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                              {rc.conclusions}
                            </Paragraph>
                          </div>
                        )}

                        {(rc?.recommendations || report.recommendations || []).length > 0 && (
                          <div className="report-section">
                            <div className="report-section-title">建议措施</div>
                            <List size="small"
                              dataSource={rc?.recommendations || report.recommendations || []}
                              renderItem={(item: string, i: number) => (
                                <List.Item style={{ borderColor: 'var(--line-soft)', padding: '5px 0', color: 'var(--ink-2)', fontSize: 13 }}>
                                  <span style={{ color: 'var(--info)', marginRight: 10 }}>{i + 1}.</span>{item}
                                </List.Item>
                              )}
                            />
                          </div>
                        )}

                        {rc?.model_contributions && (
                          <div className="report-section">
                            <div className="report-section-title">各模型贡献</div>
                            <Descriptions column={1} size="small">
                              {Object.entries(rc.model_contributions).map(([key, val]: [string, any]) => (
                                <Descriptions.Item key={key} label={<span style={{ color: 'var(--ink-3)', fontSize: 12 }}>{key}</span>}>
                                  <span style={{ color: 'var(--ink-2)', fontSize: 12 }}>{val}</span>
                                </Descriptions.Item>
                              ))}
                            </Descriptions>
                          </div>
                        )}

                        <div style={{ textAlign: 'center', marginTop: 24, paddingTop: 18, borderTop: '1px solid var(--line)' }}>
                          <Button
                            icon={<FileAddOutlined />}
                            onClick={() => selectedMeeting && generateConclusionMutation.mutate(selectedMeeting)}
                            loading={generateConclusionMutation.isPending}
                            style={{
                              background: 'linear-gradient(135deg, #a07520, #e8b84b)',
                              border: 'none',
                              color: '#060c1a',
                              fontWeight: 600,
                              fontFamily: 'var(--mono)',
                              fontSize: 13,
                              height: 40,
                              padding: '0 28px',
                              borderRadius: 0,
                            }}
                          >
                            从此会议生成案件结论
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="empty-state"><div>综合报告尚未生成</div></div>
                    )}
                  </div>
                ),
              },

              // ─── 完整时间线 ───
              {
                key: 'timeline',
                label: '完整时间线',
                children: conversations && conversations.length > 0 ? (
                  <Timeline>
                    {conversations.map((conv: any) => {
                      const model = models?.find((m: AIModel) => m.id === conv.speaker_model_id)
                      const stageNames: Record<number, string> = {
                        0: '案件信息',
                        1: '第一阶段 · 独立分析',
                        2: '第二阶段 · 匿名互评',
                        3: '第三阶段 · 综合报告',
                      }
                      const dotColor = conv.round_number === 3 ? '#e8b84b' : conv.message_type === 'system' ? 'var(--ink-3)' : 'var(--ok)'
                      return (
                        <Timeline.Item key={conv.id} color={dotColor}>
                          <div style={{ marginBottom: 4 }}>
                            <Text strong style={{ color: 'var(--ink-1)', fontSize: 12 }}>
                              {stageNames[conv.round_number] || `轮次 ${conv.round_number}`}
                            </Text>
                            <Text style={{ color: 'var(--ink-3)', fontSize: 11, marginLeft: 10, fontFamily: 'var(--mono)' }}>
                              {model?.name || '系统'} · {conv.message_type}
                            </Text>
                          </div>
                          <div className="timeline-item-content">
                            {conv.content.length > 500 ? (
                              <>
                                <span>{conv.content.substring(0, 500)}…</span>
                                <Button type="link" size="small" style={{ padding: '0 4px' }}
                                  onClick={() => Modal.info({
                                    title: '完整内容',
                                    content: <pre style={{ whiteSpace: 'pre-wrap', color: 'var(--ink-2)', fontSize: 12 }}>{conv.content}</pre>,
                                    width: 820,
                                  })}
                                >
                                  展开
                                </Button>
                              </>
                            ) : conv.content}
                          </div>
                        </Timeline.Item>
                      )
                    })}
                  </Timeline>
                ) : (
                  <div className="empty-state"><div>暂无对话记录</div></div>
                ),
              },
            ]} />
          </div>
        )}
      </Modal>
    </div>
  )
}

export default Meetings
