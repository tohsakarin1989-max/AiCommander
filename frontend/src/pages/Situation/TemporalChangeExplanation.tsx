import { Link } from 'react-router-dom'
import type { SituationBriefResult } from '../../services/intelligenceFlow'
import SemanticChangeExplanation from './SemanticChangeExplanation'
import './TemporalChangeExplanation.css'

type Comparison = NonNullable<SituationBriefResult['comparison_snapshot']>

function RecordLinks({ ids }: { ids: number[] }) {
  return <span>{ids.slice(0, 10).map(id => <Link key={id} to={`/cases?caseId=${id}`} className="sw-record-link">记录 {id}</Link>)}
    {ids.length > 10 && <span> 另有 {ids.length - 10} 条，完整来源保留在本期固定材料。</span>}</span>
}

const percent = (value: number | null) => value === null ? '无分母，不计算比例' : `${(value * 100).toFixed(1)}%`

export default function TemporalChangeExplanation({ comparison }: { comparison: Comparison }) {
  if (!comparison.time_basis) return <p>历史简报按原案发时间口径保留，未转换成发现／查获统计。</p>
  const { quality, change_origins: origins, snapshot_change: change } = comparison
  return <section className="sw-temporal-explanation" aria-label="变化来源与资料边界">
    <h3>哪些是新情况，哪些是资料变化？</h3>
    <p>{comparison.boundary}</p>
    <p>跨周期且无法归入单一期的时间：本期 {comparison.current.uncertain_count ?? 0} 条，对照期 {comparison.previous.uncertain_count ?? 0} 条；未并入上方确定数量，同一跨期记录可能出现在两期不确定部分。</p>
    {origins && <>
      <div className="sw-coverage-table"><table>
        <caption>本期登记变化与原始依据；各行不相加为案件总数</caption>
        <thead><tr><th>变化来源</th><th>数量</th><th>可核对的记录</th></tr></thead>
        <tbody>
          {[origins.recent_registered, origins.late_entry, origins.entry_time_uncertain].map(item => <tr key={item.label}>
            <th>{item.label}</th><td>{item.count}</td><td><RecordLinks ids={item.case_ids} /></td>
          </tr>)}
          <tr><th>{origins.corrections.label}</th><td>{origins.corrections.count}</td><td>
            <RecordLinks ids={[...new Set(origins.corrections.items.map(item => item.case_id))]} />
            {origins.corrections.items.slice(0, 3).map(item => <small key={item.change_id}> 修订 {item.revision_id}</small>)}
          </td></tr>
          <tr><th>{origins.withdrawals.label}</th><td>{origins.withdrawals.count}</td><td>仅保留当前授权区域的撤回记录，不展示已删除原文。</td></tr>
        </tbody>
      </table></div>
      <p>{origins.boundary}</p>
    </>}
    {comparison.semantic_changes && <SemanticChangeExplanation value={comparison.semantic_changes} />}
    {quality && <details><summary>资料完整性说明</summary>
      <p>分母：{quality.denominator_label}，共 {quality.denominator} 条。</p>
      <ul>
        <li>所选业务时间未知：{quality.unknown_time_count} 条（{percent(quality.unknown_time_ratio)}）。</li>
        <li>地点文字未填写：{quality.unclear_place_count} 条（{percent(quality.unclear_place_ratio)}）。</li>
        <li>结构化手法未填写：{quality.unstructured_method_count} 条（{percent(quality.unstructured_method_ratio)}）。</li>
      </ul><p>{quality.boundary}</p>
    </details>}
    {change && <details><summary>与本周期上一份材料相比</summary>
      {change.state === 'incomparable' ? <p>{change.reason}</p> : <>
        {!change.material_changed && <p>未发现原记录的实质变化，不增加待办。</p>}
        {change.items.filter(item => item.case_ids.length > 0).map(item => <p key={item.kind}>{item.label}：<RecordLinks ids={item.case_ids} /></p>)}
        <p>{change.boundary}</p>
      </>}
    </details>}
  </section>
}
