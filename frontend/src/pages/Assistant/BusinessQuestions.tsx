import type { BusinessQuestionType, BusinessSourceContext, InitialQueryContext } from '../../services/intelligentQueries'

export const businessQuestions: Record<BusinessQuestionType, string> = {
  case_history: '这条记录有什么历史参考？', attention: '这片区域或这口井有哪些关注依据？', recent_changes: '最近发生了哪些实质变化？',
}

export function businessEntryContext(initial?: InitialQueryContext, assetId?: string): { context?: BusinessSourceContext; error?: string } {
  const filters = initial?.filters || {}
  if (assetId && (!/^[1-9]\d*$/.test(assetId) || !Number.isSafeInteger(Number(assetId)))) return { error: '设施编号无效，未退回区域查询。' }
  if (Object.keys(filters).some(key => !['operational_area_id', 'time_basis'].includes(key))) return {
    error: '本页还带有其他案件筛选条件。以下三个问题不能忽略这些条件，请使用原有带条件查询，或明确开始新查询。',
  }
  return { context: { ...(initial?.source_case_id ? { case_id: initial.source_case_id } : {}),
    ...(assetId ? { asset_id: Number(assetId) } : {}),
    ...(filters.operational_area_id ? { area_id: filters.operational_area_id } : {}),
    ...(filters.time_basis ? { time_basis: filters.time_basis } : {}) } }
}

export default function BusinessQuestions({ initial, assetId, disabled, onRun }: {
  initial?: InitialQueryContext; assetId?: string; disabled: boolean
  onRun: (type: BusinessQuestionType, title: string, context: BusinessSourceContext) => void
}) {
  const entry = businessEntryContext(initial, assetId)
  return <section className="query-business-questions" aria-label="直接回答业务问题">
    <h2>直接回答业务问题</h2>
    <p>复用当前案件、设施或区域；规则入口不依赖模型。只有缺少会改变答案的条件时，才问一个必要问题。</p>
    <div className="query-actions">{Object.entries(businessQuestions).map(([type, title]) =>
      <button key={type} type="button" className="btn-ghost" disabled={disabled || Boolean(entry.error)}
        onClick={() => entry.context && onRun(type as BusinessQuestionType, title, entry.context)}>{title}</button>)}</div>
    {entry.error && <p role="status">{entry.error}</p>}
  </section>
}
