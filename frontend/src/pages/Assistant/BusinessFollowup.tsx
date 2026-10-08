import { useState } from 'react'
import type { BusinessSourceContext, QueryTask } from '../../services/intelligentQueries'

export default function BusinessFollowup({ task, disabled, onRun }: { task: QueryTask; disabled: boolean; onRun: (context: BusinessSourceContext) => void }) {
  const original = task.source_context || {}
  const [basis, setBasis] = useState<BusinessSourceContext['time_basis']>(original.time_basis || 'discovery')
  const [period, setPeriod] = useState<BusinessSourceContext['period']>(original.period || 'daily')
  return <section className="query-business-questions" aria-label="沿用原问题续查">
    <h3>沿用原问题续查</h3>
    <p>保留原案件、设施和授权区域，重新核对当前来源版本；不会把旧答案当作新证据。任意文字问题仍需可信内网模型，不通过规则入口猜测。</p>
    {task.question_type === 'recent_changes' && <div className="query-actions">
      <label>时间口径<select value={basis} disabled={disabled} onChange={event => setBasis(event.target.value as BusinessSourceContext['time_basis'])}>
        <option value="discovery">发现／查获时间</option><option value="incident">有依据的案发时间</option><option value="entry">录入时间</option>
      </select></label>
      <label>比较周期<select value={period} disabled={disabled} onChange={event => setPeriod(event.target.value as BusinessSourceContext['period'])}>
        <option value="daily">最近完整30天与前30天</option><option value="weekly">最近完整自然周与前一周</option>
      </select></label>
    </div>}
    <button type="button" className="btn-primary" disabled={disabled} onClick={() => onRun({ ...original,
      ...(task.question_type === 'recent_changes' ? { time_basis: basis, period } : {}) })}>按同一问题续查</button>
  </section>
}
