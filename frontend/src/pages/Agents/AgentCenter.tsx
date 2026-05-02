import { useState } from 'react'
import { Input, List, Progress, Select, Space, Tag, message } from 'antd'
import {
  PlayCircleOutlined,
  RadarChartOutlined,
  ReloadOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { aiApi } from '../../services/ai'
import { caseApi } from '../../services/cases'
import type { AgentTask } from '../../types'
import './AgentCenter.css'

const { TextArea } = Input

const AGENT_PRESETS = [
  '基于选中案件生成相似条件复盘和信息缺口清单',
  '把当前案件整理成事实依据、模式推断和防控参考',
  '提取可沉淀为案后复盘材料的经验点',
]

const ResultList = ({ title, items }: { title: string; items?: string[] }) => {
  if (!items?.length) return null
  return (
    <div className="agent-result-list">
      <div className="agent-result-label">{title}</div>
      <List
        size="small"
        dataSource={items.slice(0, 8)}
        renderItem={item => <List.Item>{item}</List.Item>}
      />
    </div>
  )
}

/** 根据状态返回对应的 CSS 修饰类名 */
function statusClass(status: string): string {
  if (status === 'running')   return 'agent-task-card--running'
  if (status === 'completed') return 'agent-task-card--completed'
  if (status === 'failed')    return 'agent-task-card--failed'
  return 'agent-task-card--pending'
}

/** 状态徽章 */
function StatusBadge({ status }: { status: string }) {
  const chipCls =
    status === 'running'   ? 'chip chip-running'   :
    status === 'completed' ? 'chip chip-completed' :
    status === 'failed'    ? 'chip chip-failed'    :
                             'chip chip-pending'

  const icon =
    status === 'running'   ? <SyncOutlined spin />   :
    status === 'completed' ? <CheckCircleOutlined /> :
    status === 'failed'    ? <CloseCircleOutlined /> :
                             <ClockCircleOutlined />

  const label =
    status === 'running'   ? '执行中' :
    status === 'completed' ? '已完成' :
    status === 'failed'    ? '失败'   :
                             '等待中'

  return (
    <span className={chipCls}>
      <span className="dot" style={{ background: 'currentColor' }} />
      {icon}
      {' '}{label}
    </span>
  )
}

const AgentCenter: React.FC = () => {
  const [query, setQuery] = useState('')
  const [selectedCaseIds, setSelectedCaseIds] = useState<number[]>([])

  const { data, refetch, isFetching } = useQuery({
    queryKey: ['agent-tasks'],
    queryFn: aiApi.agent.list,
  })

  const casesQuery = useQuery({
    queryKey: ['agent-cases'],
    queryFn: () => caseApi.getCases({ limit: 200 }),
  })

  const runMutation = useMutation({
    mutationFn: ({ q, caseIds }: { q: string; caseIds: number[] }) => aiApi.agent.run(q, caseIds),
    onSuccess: () => {
      message.success('研判辅助任务已生成')
      setQuery('')
      refetch()
    },
    onError: (error: any) => {
      message.error(error?.response?.data?.detail || '任务启动失败')
    },
  })

  const handleRun = () => {
    const trimmed = query.trim()
    if (!trimmed) {
      message.warning('请输入任务目标')
      return
    }
    runMutation.mutate({ q: trimmed, caseIds: selectedCaseIds })
  }

  const tasks: AgentTask[] = data || []
  const cases = casesQuery.data || []

  return (
    <div className="page-scrollable">

      {/* 页面标题 */}
      <div className="page-title">
        <h1>研判辅助 Agent</h1>
        <span className="sub">基于案件研判工作台输出可复核的事实、推断、建议和缺口</span>
      </div>

      {/* 新建任务卡片 */}
      <div className="card" style={{ marginBottom: 'var(--gap)' }}>
        <div className="card-head">
          <RadarChartOutlined className="ico" />
          <span className="ti">新建研判辅助任务</span>
        </div>
        <div className="card-body pad">
          <Select
            mode="multiple"
            allowClear
            showSearch
            className="agent-case-select"
            placeholder="可选：指定案件；不选则按全局研判上下文生成"
            value={selectedCaseIds}
            onChange={setSelectedCaseIds}
            optionFilterProp="label"
            loading={casesQuery.isLoading}
            options={cases.map(item => ({
              value: item.id,
              label: `${item.case_number} · ${item.location || '未知地点'}`,
            }))}
          />
          <div className="agent-preset-row">
            {AGENT_PRESETS.map(item => (
              <button key={item} className="btn-ghost-sm" onClick={() => setQuery(item)}>
                {item}
              </button>
            ))}
          </div>
          <TextArea
            className="agent-textarea"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={4}
            placeholder="描述研判目标，例如：基于选中案件形成相似条件复盘、信息缺口和可追溯依据。"
            onPressEnter={(e) => {
              if (e.ctrlKey) handleRun()
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontFamily: 'var(--mono)', fontSize: '9.5px', color: 'var(--ink-3)', letterSpacing: '0.1em' }}>
              Ctrl+Enter 快速启动 · 支持自然语言描述目标
            </span>
            <button
              className="btn-primary"
              onClick={handleRun}
              disabled={runMutation.isPending || !query.trim()}
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
            >
              <PlayCircleOutlined />
              {runMutation.isPending ? '启动中...' : '启动任务'}
            </button>
          </div>
        </div>
      </div>

      {/* 任务列表标题行 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--mono)', fontSize: '10px', letterSpacing: '0.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
          <RadarChartOutlined />
          任务记录
          {tasks.length > 0 && (
            <span className="chip" style={{ fontSize: 10 }}>{tasks.length}</span>
          )}
        </div>
        <button
          className="btn-ghost"
          onClick={() => refetch()}
          disabled={isFetching}
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
        >
          <ReloadOutlined spin={isFetching} />
          刷新
        </button>
      </div>

      {/* 任务内容 */}
      {isFetching && tasks.length === 0 ? (
        [1, 2, 3].map((i) => (
          <div key={i} className="skeleton agent-skeleton" />
        ))
      ) : tasks.length === 0 ? (
        <div className="empty-state">
          <div className="icon"><RadarChartOutlined /></div>
          <span>暂无任务记录，请在上方输入研判目标生成辅助方案</span>
        </div>
      ) : (
        <div className="agent-grid">
          {tasks.map((item: AgentTask) => (
            <div
              key={item.id}
              className={`card ${statusClass(item.status)}`}
            >
              <div className="card-head">
                <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.1em' }}>
                  TASK #{item.id}
                </span>
                <span className="spacer" />
                <StatusBadge status={item.status} />
              </div>

              <div className="card-body pad">
                <div className="agent-task-query">{item.query}</div>

                {item.result?.steps && item.result.steps.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
                    {item.result.steps.map((step, idx) => (
                      <span key={idx} className="agent-step-tag">
                        {idx + 1}. {step}
                      </span>
                    ))}
                  </div>
                )}

                {item.result?.result && (
                  <div className="agent-result-box">
                    <div className="agent-result-label">研判结果</div>
                    <pre className="agent-result-text">{item.result.result}</pre>
                    {typeof item.result.confidence === 'number' && (
                      <Space className="agent-confidence" size={8}>
                        <span>依据强度</span>
                        <Progress percent={Math.round(item.result.confidence * 100)} size="small" style={{ width: 120 }} />
                        {item.result.mode && <Tag>{item.result.mode}</Tag>}
                      </Space>
                    )}
                  </div>
                )}
                <ResultList title="事实依据" items={item.result?.facts} />
                <ResultList title="模式推断" items={item.result?.inferences} />
                <ResultList title="防控参考" items={item.result?.recommendations} />
                <ResultList title="信息缺口" items={item.result?.information_gaps} />
                <ResultList title="证据索引" items={item.result?.evidence_refs} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default AgentCenter
