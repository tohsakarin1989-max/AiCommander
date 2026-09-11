import { Alert, Card, Empty, Spin, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'

import { governanceApi } from '../../services/governance'
import FixedEvaluationPanel from './FixedEvaluationPanel'
import './IntelligenceRuntimeCenter.css'


const LABELS: Record<string, { title: string; detail: string }> = {
  'geographic-foundation': { title: '地理底座智能体', detail: '生产台账治理、受控公共地图包、离线地图版本与回滚' },
  'case-governance': { title: '案件治理智能体', detail: '保存后自动形成标准画像和最多三项关键缺失' },
  'dual-domain-insight': { title: '双域线索研判智能体', detail: '案件与地图自动融合，生成带反向证据的候选推断' },
  'deployment-advisor': { title: '态势部署参谋智能体', detail: '按日、按周形成最多三项部署参考，不创建执行任务' },
}

const METRIC_LABELS: Record<string, string> = {
  case_count: '案件数',
  candidate_count: '候选数',
  evidence_coverage: '证据覆盖率',
  counter_or_gap_coverage: '反向证据或缺口覆盖率',
  top3_useful_case_rate: '人工反馈有用率',
  top3_ground_truth_hit_rate: 'Top-3 真实标注命中率',
  ground_truth_label_recall: '真实标注召回率',
  ground_truth_coverage: '真实标注覆盖率',
  high_confidence_error_rate: '高置信错误率',
  high_confidence_feedback_coverage: '高置信反馈覆盖率',
  feedback_coverage: '总体反馈覆盖率',
  metric_basis: '计算口径',
}

function metricValue(key: string, value: number | string | null) {
  if (value === null) return '不可计算（缺少真实标注）'
  if (typeof value === 'number' && (key.includes('rate') || key.includes('coverage') || key.includes('recall'))) {
    return `${(value * 100).toFixed(1)}%`
  }
  return String(value)
}

export default function IntelligenceRuntimeCenter() {
  const overviewQuery = useQuery({
    queryKey: ['intelligence-runtime-overview'],
    queryFn: governanceApi.getRuntimeOverview,
    refetchInterval: 60_000,
  })
  const overview = overviewQuery.data

  return (
    <div className="page-scrollable runtime-center">
      <section className="runtime-center__hero">
        <div>
          <span>ADMIN · DETERMINISTIC ORCHESTRATOR</span>
          <h1>智能运行运维中心</h1>
          <p>这里只查看版本、运行边界与评测结果。普通用户在案件和态势页面直接查看业务成果。</p>
        </div>
        <Tag color="blue">管理员专用</Tag>
      </section>
      <Alert
        showIcon
        type="info"
        message="四个业务智能体由确定性事件编排器触发"
        description="外部模型不是核心依赖；正式案件字段和执行任务均不允许由智能体自动改变。"
      />
      {overviewQuery.isLoading ? <Spin /> : !overview ? <Empty description="运行概览暂不可用" /> : (
        <>
          <section className="runtime-center__agents">
            {overview.business_agents.map((key, index) => (
              <Card key={key} className="runtime-center__agent">
                <b>{String(index + 1).padStart(2, '0')}</b>
                <h2>{LABELS[key]?.title || key}</h2>
                <p>{LABELS[key]?.detail || '受控业务能力'}</p>
                <Tag color="green">自动触发</Tag>
              </Card>
            ))}
          </section>
          <section className="runtime-center__grid">
            <Card title="算法与策略版本">
              <div className="runtime-center__versions">
                {overview.versions.algorithms.map(item => (
                  <div key={item.component}><span>{item.component}</span><strong>{item.version}</strong><code>{item.checksum.slice(0, 12)}</code></div>
                ))}
                <div><span>scope-policy</span><strong>{overview.versions.scope_policy.version}</strong><code>{overview.versions.scope_policy.checksum.slice(0, 12)}</code></div>
              </div>
            </Card>
            <Card title="最近一次评测摘要">
              {overview.latest_evaluation ? (
                <div className="runtime-center__evaluation">
                  <strong>{overview.latest_evaluation.status}</strong>
                  {Object.entries(overview.latest_evaluation.metrics).map(([key, value]) => (
                    <span key={key}>{METRIC_LABELS[key] || key}<b>{metricValue(key, value)}</b></span>
                  ))}
                </div>
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未运行固定评测集" />}
            </Card>
          </section>
          <FixedEvaluationPanel />
          <section className="runtime-center__boundary">
            <span>正式案件自动改写：{overview.formal_case_mutations_allowed ? '允许' : '禁止'}</span>
            <span>自动创建执行任务：{overview.execution_task_creation_allowed ? '允许' : '禁止'}</span>
            <span>外部模型必需：{overview.external_model_required ? '是' : '否'}</span>
          </section>
        </>
      )}
    </div>
  )
}
