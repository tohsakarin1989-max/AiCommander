/**
 * 数智自动化 —— 预留页面
 *
 * 业务场景：
 *   数字化井口参数异常 → 自动调阅附近雷达/云台 → AI 研判井口周围情况
 *   → 有异常：向指挥中心报警 / 无异常：忽略记录
 *
 * 当前状态：模拟告警可写入事件、生成核查建议、标记误报或转案件；
 * 后期替换为生产系统和雷达云台真实告警源。
 */
import { useState } from 'react'
import { Empty, List, Modal, Progress, Spin, Typography, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { automationAlertApi } from '../../services/automationAlerts'
import type { AutomationAlert, AutomationAlertTriagePack } from '../../services/automationAlerts'
import './IntelliInspect.css'

const { Text } = Typography

// ── 系统集成状态 ───────────────────────────────────────────────
const INTEGRATIONS = [
  {
    icon: '🛢️',
    name: '数字化井口监测',
    sub: 'A2 生产数据系统\n压力/流量/温度实时采集',
    status: 'reserved',
    statusText: '待对接',
  },
  {
    icon: '⚡',
    name: '异常检测引擎',
    sub: '多参数阈值 + 机器学习\n历史基线自适应',
    status: 'reserved',
    statusText: '待对接',
  },
  {
    icon: '📡',
    name: '雷达感知系统',
    sub: '毫米波雷达 / 激光雷达\n人员车辆目标检测',
    status: 'reserved',
    statusText: '待对接',
  },
  {
    icon: '🎥',
    name: '云台摄像监控',
    sub: '高清 PTZ 摄像机\n联动抓拍 / 自动跟踪',
    status: 'reserved',
    statusText: '待对接',
  },
  {
    icon: '🧠',
    name: 'AI 研判核心',
    sub: '视频画面智能分析\n人员车辆异常识别',
    status: 'pending',
    statusText: '基础就绪',
  },
  {
    icon: '📲',
    name: '指挥中心即时通',
    sub: '推送告警 + 处置工单\n与现有系统集成',
    status: 'pending',
    statusText: '基础就绪',
  },
]

// ── 业务步骤说明 ───────────────────────────────────────────────
const STEPS = [
  {
    title: '数字化井口参数采集与异常触发',
    desc: 'A2 生产管理系统持续采集各井口的压力、流量、温度、液位等运行参数，通过工业物联网网关实时上报至 AiCommander 数据总线。检测引擎融合规则引擎与 ML 模型：规则层负责明确阈值告警（压力骤降 >0.3MPa、流量波动 >±20%），ML 层识别隐性异常（盗油导致的缓慢流量下降）。告警经去重、分级（P0 紧急 / P1 高优）后触发后续流程。',
    tag: 'reserved',
    tagText: '待生产系统对接',
  },
  {
    title: '自动调阅附近雷达 / 云台',
    desc: '参数异常触发后，系统立即检索该井口 500m 范围内的所有雷达感知设备和云台摄像机。向最近的雷达下发人员/车辆扫描指令，同时驱动云台自动转向异常井口方向，开启 30 秒高清录像及智能跟踪模式。调阅过程全自动完成，响应时间 <3 秒。',
    tag: 'reserved',
    tagText: '待雷达/云台对接',
  },
  {
    title: 'AI 研判井口周围情况',
    desc: '大语言模型结合视觉识别能力，对雷达目标数据和云台视频帧进行综合研判：识别目标类型（人员/车辆/动物）、数量、活动轨迹及与井口的距离。结合时段特征（深夜/节假日/偏僻区域）综合评估异常性质。研判结论分为：无异常（自然因素或误报）→ 忽略记录；有可疑目标 → 立即升级告警。',
    tag: 'partial',
    tagText: '基础能力就绪',
  },
  {
    title: '有异常：指挥中心即时告警',
    desc: 'AI 研判发现可疑人员或车辆活动时，系统立即向指挥中心即时通推送 P0 告警，内容包括：井口编号、坐标、异常参数摘要、雷达目标数量/方位、云台实时截图、AI 研判结论。同时生成现场核查建议，供值班人员人工确认后再进入处置流程。',
    tag: 'partial',
    tagText: '基础推送已就绪',
  },
  {
    title: '无异常：记录并恢复监测',
    desc: 'AI 研判确认为设备故障、自然环境干扰或误报时，系统自动归档本次事件（含告警参数、雷达/云台核查截图、研判依据），标记为"已核查-无异常"，井口恢复正常监测状态。归档记录用于持续优化检测阈值和 AI 模型，减少后续误报。',
    tag: 'partial',
    tagText: '基础能力就绪',
  },
  {
    title: '处置反馈与闭环优化',
    desc: '保卫人员到场核查后将处置结果录入系统，形成"异常触发 → 雷达/云台调阅 → AI 研判 → 告警/忽略 → 处置"完整闭环。反馈数据用于持续优化异常检测阈值、AI 视频研判模型和雷达联动规则，逐步降低误报率，提升盗油事件识别准确率。',
    tag: 'partial',
    tagText: '反馈录入功能已有',
  },
]

const riskText = (riskLevel: string) => {
  if (riskLevel === 'critical') return '极高'
  if (riskLevel === 'high') return '高'
  if (riskLevel === 'medium') return '中'
  return '低'
}

const riskColor = (riskLevel: string) => {
  if (riskLevel === 'critical') return 'var(--err)'
  if (riskLevel === 'high') return 'oklch(0.80 0.16 75)'
  if (riskLevel === 'medium') return 'var(--warn)'
  return 'var(--ok)'
}

const IntelliInspect: React.FC = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [triagePack, setTriagePack] = useState<AutomationAlertTriagePack | null>(null)
  const alertsQuery = useQuery({
    queryKey: ['automation-alerts', 'simulated'],
    queryFn: automationAlertApi.seedSimulated,
  })

  const refreshAlerts = () => {
    queryClient.invalidateQueries({ queryKey: ['automation-alerts', 'simulated'] })
  }

  const createEventMutation = useMutation({
    mutationFn: (alert: AutomationAlert) => automationAlertApi.ensureEvent(alert.id),
    onSuccess: () => {
      message.success('告警已进入事件中心')
      refreshAlerts()
    },
    onError: (error: Error) => message.error(`生成事件失败：${error.message}`),
  })

  const verificationMutation = useMutation({
    mutationFn: (alert: AutomationAlert) => automationAlertApi.ensureEvent(alert.id),
    onSuccess: () => {
      message.success('已生成现场核查建议')
      refreshAlerts()
    },
    onError: (error: Error) => message.error(`生成核查建议失败：${error.message}`),
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

  const actionBusy =
    createEventMutation.isPending ||
    verificationMutation.isPending ||
    falseAlarmMutation.isPending ||
    convertMutation.isPending
  const alerts = alertsQuery.data || []

  return (
  <div className="ii-page">

    {/* 页面标题 */}
    <div className="page-title" style={{ marginBottom: 'var(--gap)' }}>
      <h1>数智自动化</h1>
      <div className="sub">DIGITAL-INTELLIGENCE · 参数异常触发 · 雷达/云台即时调阅 · AI 研判报警</div>
    </div>

    {/* 预留横幅 */}
    <div className="ii-reserve-banner">
      <span className="icon">◇</span>
      <div>
        <b style={{ color: 'var(--accent)' }}>当前为模拟联动模式</b>：真实 A2 生产系统、雷达和云台尚未接入，但告警可生成事件、核查建议、误报归档或转案件。
        <span style={{ marginLeft: 12, color: 'var(--ink-3)' }}>外部设备对接完成后，只需替换告警来源。</span>
      </div>
    </div>

    {/* ── 业务流程图 ── */}
    <div className="card" style={{ marginBottom: 'var(--gap)' }}>
      <div className="card-head">
        <span className="ico">⊕</span>
        <span className="ti">业务流程</span>
        <span className="spacer" />
        <span className="chip accent">自动化闭环</span>
      </div>
      <div className="card-body" style={{ padding: '20px 16px 16px' }}>
        <div className="ii-flow-wrap">
          <svg className="ii-flow-svg" viewBox="0 0 1100 200" preserveAspectRatio="xMidYMid meet">
            <defs>
              <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                <path d="M0,0 L0,6 L8,3 z" fill="oklch(0.78 0.14 45 / 0.6)" />
              </marker>
            </defs>

            {/* 连接箭头 */}
            {[0,1,2,3,4].map(i => (
              <line key={i}
                x1={85 + i * 185} y1="100"
                x2={155 + i * 185} y2="100"
                stroke="oklch(0.78 0.14 45 / 0.5)"
                strokeWidth="1.5"
                strokeDasharray="5 3"
                markerEnd="url(#arrow)"
              />
            ))}

            {/* 节点 */}
            {[
              { x: 50,  icon: '🛢️', label: '数字化井口', sub: '参数异常触发', color: 'oklch(0.78 0.11 220)' },
              { x: 235, icon: '⚡', label: '异常检测', sub: '阈值+ML触发', color: 'oklch(0.80 0.16 75)' },
              { x: 420, icon: '📡', label: '雷达/云台', sub: '自动调阅核查', color: 'oklch(0.72 0.14 285)' },
              { x: 605, icon: '🧠', label: 'AI 研判', sub: '判断周围情况', color: 'oklch(0.78 0.14 45)' },
              { x: 790, icon: '📲', label: '指挥中心', sub: '有异常即报警', color: 'oklch(0.70 0.20 25)' },
              { x: 975, icon: '✅', label: '处置反馈', sub: '闭环优化', color: 'oklch(0.78 0.14 155)' },
            ].map(({ x, icon, label, sub, color }) => (
              <g key={x} transform={`translate(${x}, 60)`}>
                {/* 背景框 */}
                <rect x="-32" y="-2" width="64" height="64" rx="0"
                  fill="var(--bg-1)" stroke={color.replace(')', ' / 0.45)')} strokeWidth="1.2" />
                {/* 图标 */}
                <text x="0" y="26" textAnchor="middle" fontSize="24">{icon}</text>
                {/* 标签 */}
                <text x="0" y="82" textAnchor="middle"
                  fontSize="11" fontFamily="IBM Plex Sans, sans-serif"
                  fill="var(--ink-0)" fontWeight="600">{label}</text>
                <text x="0" y="96" textAnchor="middle"
                  fontSize="9.5" fontFamily="JetBrains Mono, monospace"
                  fill="var(--ink-3)">{sub}</text>
                {/* 顶部色条 */}
                <rect x="-32" y="-2" width="64" height="4" fill={color.replace(')', ' / 0.8)')} />
              </g>
            ))}

            {/* 判断菱形（AI研判后分支：有异常→报警 / 无异常→忽略） */}
            <g transform="translate(605, 148)">
              <polygon points="0,-16 24,0 0,16 -24,0"
                fill="oklch(0.78 0.14 45 / 0.12)" stroke="oklch(0.78 0.14 45 / 0.45)" strokeWidth="1" />
              <text y="4" textAnchor="middle" fontSize="8.5"
                fontFamily="JetBrains Mono, monospace" fill="oklch(0.72 0.013 90)">研判</text>
            </g>
            <text x="516" y="174" fontSize="9" fontFamily="JetBrains Mono, monospace" fill="var(--ok)">无异常→忽略</text>
            <text x="630" y="174" fontSize="9" fontFamily="JetBrains Mono, monospace" fill="var(--err)">有异常→报警</text>
          </svg>
        </div>
      </div>
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 'var(--gap)' }}>

      {/* ── 左侧：步骤说明 ── */}
      <div className="card">
        <div className="card-head">
          <span className="ico">◎</span>
          <span className="ti">流程详细说明</span>
        </div>
        <div className="card-body pad" style={{ padding: '20px 24px' }}>
          <div className="ii-steps">
            {STEPS.map((s, i) => (
              <div key={i} className="ii-step">
                <div className="ii-step-num">{i + 1}</div>
                <div className="ii-step-body">
                  <div className="ii-step-title">{s.title}</div>
                  <div className="ii-step-desc">{s.desc}</div>
                  <span className={`ii-step-tag ${s.tag}`}>{s.tagText}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── 右侧：系统状态 + 告警预览 ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gap)' }}>

        {/* 集成状态 */}
        <div className="card">
          <div className="card-head">
            <span className="ico">◈</span>
            <span className="ti">系统对接状态</span>
          </div>
          <div className="card-body" style={{ padding: '12px 14px 14px' }}>
            {INTEGRATIONS.map((item, i) => (
              <div key={i} className={`ii-status-card ${item.status}`} style={{ marginBottom: 8, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 20 }}>{item.icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="ii-card-name" style={{ fontSize: 12, marginBottom: 1 }}>{item.name}</div>
                  <div className="ii-card-sub" style={{ fontSize: 10, marginBottom: 0 }}>
                    {item.sub.split('\n').join(' · ')}
                  </div>
                </div>
                <div className="ii-card-status" style={{ fontSize: 9.5, padding: '2px 7px' }}>
                  <span className="ii-status-dot" />
                  {item.statusText}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 告警预览（可联动） */}
        <div className="card">
          <div className="card-head">
            <span className="ico">⚠</span>
            <span className="ti">告警联动队列</span>
            <span className="spacer" />
            <span className="chip accent">事件 / 核查 / 案件</span>
          </div>
          <div className="card-body pad" style={{ padding: 14, position: 'relative', overflow: 'hidden' }}>
            {alertsQuery.isLoading ? (
              <div style={{ padding: 30, textAlign: 'center' }}><Spin /></div>
            ) : alerts.length ? (
              alerts.map((a) => (
                <div key={a.id} className="ii-alert-mock">
                  <div className="ii-alert-level">
                    <span className="ii-alert-badge" style={{ color: riskColor(a.risk_level), borderColor: riskColor(a.risk_level) }}>
                      {riskText(a.risk_level)}风险
                    </span>
                    {a.related_event_id && (
                      <span className="ii-alert-linked">事件 #{a.related_event_id}</span>
                    )}
                    {a.related_case_id && (
                      <span className="ii-alert-linked">案件 #{a.related_case_id}</span>
                    )}
                    <span className="ii-alert-linked">{a.status}</span>
                    <span className="ii-alert-time">{dayjs(a.occurred_time).format('HH:mm')}</span>
                  </div>
                  <div className="ii-alert-title">{a.title}</div>
                  <div className="ii-alert-desc">{a.description}</div>
                  {!!a.suggested_actions?.length && (
                    <div className="ii-card-sub" style={{ marginTop: 8 }}>
                      核查建议：{a.suggested_actions.join('；')}
                    </div>
                  )}
                  <div className="ii-alert-actions">
                    <button
                      className="btn-ghost-sm"
                      disabled={actionBusy}
                      onClick={() => createEventMutation.mutate(a)}
                    >
                      {a.related_event_id ? '已生成事件' : '生成事件'}
                    </button>
                    <button
                      className="btn-ghost-sm"
                      disabled={actionBusy}
                      onClick={() => verificationMutation.mutate(a)}
                    >
                      核查建议
                    </button>
                    <button
                      className="btn-ghost-sm"
                      disabled={actionBusy || a.status === 'false_alarm' || !!a.related_case_id}
                      onClick={() => falseAlarmMutation.mutate(a)}
                    >
                      标记误报
                    </button>
                    <button
                      className="btn-ghost-sm"
                      disabled={triageMutation.isPending}
                      onClick={() => triageMutation.mutate(a)}
                    >
                      研判包
                    </button>
                    <button
                      className="btn-primary"
                      disabled={actionBusy || a.status === 'false_alarm' || !!a.related_case_id}
                      onClick={() => convertMutation.mutate(a)}
                    >
                      转案件
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <Empty description="暂无数智自动化告警" />
            )}
            <div style={{ marginTop: 8, fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', textAlign: 'center' }}>
              模拟告警会写入事件中心；转案件会复用事件转案件接口并回写关联，不直接派发巡逻或跨部门任务。
            </div>
          </div>
        </div>

      </div>
    </div>
    <Modal
      title="数智告警研判包"
      open={!!triagePack}
      onCancel={() => setTriagePack(null)}
      width={880}
      footer={[
        triagePack?.alert.related_case_id ? (
          <button
            key="case"
            className="btn-primary"
            onClick={() => {
              navigate(`/case-intelligence?caseId=${triagePack.alert.related_case_id}`)
              setTriagePack(null)
            }}
          >
            进入案件研判
          </button>
        ) : null,
        <button key="close" className="btn-ghost" onClick={() => setTriagePack(null)}>关闭</button>,
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
  </div>
  )
}

export default IntelliInspect
