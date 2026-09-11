import { Alert, Button, Space, Spin, Table, Tag } from 'antd'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { governanceApi } from '../../services/governance'

const LABELS: Record<string, string> = { execution_failed: '运行失败', positive_empty: '阳性样本无候选',
  positive_top3_miss: '阳性目标未命中', negative_with_candidates: '阴性样本出现候选', unlabeled_cases: '未标注案件' }
const CALIBRATION_STATES: Record<string, string> = {
  insufficient_labels: '核验样本不足，不能形成校准结果', algorithm_version_not_unique: '算法版本不唯一或缺少代码摘要',
  validation_type_not_in_training: '验证集存在训练未覆盖的目标类型', incomplete_label_coverage: '标注或运行覆盖不完整，仅保留试验结果',
  heldout_improved_requires_review: '本次留出验证有改善，仍需复核，未应用于生产', no_heldout_improvement: '留出验证未改善，不采用校准结果',
}

export default function EvaluationDiagnosticsPanel({ runId }: { runId: string }) {
  const [requested, setRequested] = useState(false)
  const query = useQuery({ queryKey: ['evaluation-diagnostics', runId], queryFn: () => governanceApi.getDiagnostics(runId), retry: false })
  const calibration = useQuery({ queryKey: ['score-calibration', runId], queryFn: () => governanceApi.getCalibration(runId), enabled: requested && !query.isError, retry: false })
  if (query.isError) return <Alert type="warning" message="诊断结果无法读取，请检查来源权限或运行版本。旧内容已隐藏。" />
  if (!query.data || query.isFetching) return <Spin />
  const data = query.data
  return <section className="fixed-evaluations__comparison" aria-label="评测错误诊断">
    <h3>错误诊断与校准准备</h3>
    <Alert type="info" showIcon message={data.calibration_status === 'no_verified_labels' ? '缺少已核验候选，不能校准' : '仅为已核验样本诊断，尚未完成概率校准'} description={data.boundary} />
    <p>固定案件 {data.case_count} 起；已核验候选 {data.judged_candidates} 项，未核验 {data.unjudged_candidates} 项。</p>
    <Space wrap>{Object.entries(data.problems).map(([key, count]) => <Tag key={key}>{LABELS[key] || key}：{count}</Tag>)}</Space>
    <Table size="small" pagination={false} rowKey={row => String(row.lower)} scroll={{ x: 480 }} dataSource={data.buckets} columns={[
      { title: '规则支持度区间', render: (_, row) => row.lower === null ? '小于0' : row.upper_exclusive === null ? `${row.lower}及以上` : `${row.lower}至${row.upper_exclusive}（不含上限）` },
      { title: '核验正确', dataIndex: 'verified_correct' }, { title: '核验错误', dataIndex: 'verified_incorrect' },
      { title: '尚未核验', dataIndex: 'unjudged' },
    ]} />
    {data.legacy_cases_without_observations > 0 && <p>有 {data.legacy_cases_without_observations} 起旧运行未保存候选级观测，不补造历史分数。</p>}
    <Button onClick={() => { if (requested) void calibration.refetch(); else setRequested(true) }} loading={calibration.isFetching}>验证校准可用性</Button>
    {calibration.isError && <Alert type="warning" message="校准来源当前不可读取或完整性校验失败，旧结果已隐藏。" />}
    {calibration.data && !calibration.isError && !calibration.isFetching && <div aria-live="polite">
      <h4>{CALIBRATION_STATES[calibration.data.status] || '校准状态待确认'}</h4>
      <p>训练 {calibration.data.split.train_case_ids.length} 起案件、{calibration.data.split.train_observations} 项候选；
        留出验证 {calibration.data.split.validation_case_ids.length} 起案件、{calibration.data.split.validation_observations} 项候选。</p>
      {calibration.data.validation && <p>验证误差（越低越好）：简单基线 {calibration.data.validation.baseline.toFixed(4)}，
        校准后 {calibration.data.validation.calibrated.toFixed(4)}。此数值不是准确率。</p>}
      <p>{calibration.data.boundary}</p>
    </div>}
  </section>
}
