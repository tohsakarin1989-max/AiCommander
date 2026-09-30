import type { FacilityConditionComparison, FacilityRankingChanges } from '../../services/facilityConditions'

const labels: Record<string, string> = { hard_excluded: '当前计算条件排除', different: '明确不符', unknown: '资料未知', supported: '条件支持' }
const eligibility: Record<string, string> = { retained: '保留比较', excluded: '本轮排除', unresolved: '待补依据' }
const contexts: Record<string, string> = { source: '案件来源', case_source: '案件来源', case_profile: '案件画像', map: '地图版本', network: '路网版本', algorithm: '算法', recall_set: '召回集合', analysis_time: '道路条件时刻', vehicle: '车型条件', policy: '通行规则' }

export default function FacilityConditions({ comparison, changes }: { comparison: FacilityConditionComparison; changes?: FacilityRankingChanges }) {
  return <section aria-label="设施条件对照">
    <h4>为什么保留、排除或暂不能判断</h4><p>{comparison.boundary}</p>
    {!!comparison.priority_gaps.length && <div><h5>哪些补充资料会影响判断</h5>
      <ul>{comparison.priority_gaps.map(gap => <li key={gap.key}><strong>{gap.label}</strong>：{gap.reason}
        <p>涉及 {gap.asset_ids.length} 个设施；需补：{gap.dependencies.join('、') || '尚无明确补充依赖'}。</p>
      </li>)}</ul><p>这是条件依赖提示，不是新增待办，也不承诺提高命中概率。</p></div>}
    <details><summary>全部召回设施的条件对照（{comparison.rows.length} 个）</summary>
      {comparison.rows.map(row => <article key={row.asset_id}>
        <h5>{row.name} · {eligibility[row.eligibility]}{row.rank != null ? ` · 本轮第 ${row.rank} 位` : ''}</h5>
        <dl>{row.conditions.map(condition => <div key={condition.key}>
          <dt>{condition.label} · {labels[condition.state]}</dt><dd>{condition.reason}
            {!!condition.dependencies.length && <p>依赖资料：{condition.dependencies.join('、')}</p>}
            {!!condition.evidence_refs.length && <details><summary>条件出处</summary><ul>{condition.evidence_refs.map(ref => <li key={ref}><code>{ref}</code></li>)}</ul></details>}
          </dd>
        </div>)}</dl>
        <p>生产资料适用时刻：{row.source_context.valid_at || '案发时间不足'}；资料截止：{row.source_context.known_at}；来源版本：{row.source_context.version_id ?? '未取得适用版本'}。</p>
        <small>{row.boundary}</small>
      </article>)}
    </details>
    {changes && <details><summary>与前一份可比成果的变化</summary>
      <p>{changes.state === 'no_baseline' ? '没有前版可比，不编造排名变化。' : changes.state === 'not_comparable' ? '前版范围或条件不满足比较要求。' : '以下比较两份真实冻结成果，不把同期变化归因于单一因素。'}</p>
      {changes.changes.map(change => <div key={change.asset_id}><p>{change.name}：{change.previous_rank == null ? '此前未排名' : `此前第 ${change.previous_rank} 位`} → {change.current_rank == null ? '本轮未排名' : `本轮第 ${change.current_rank} 位`}</p>
        <ul>{change.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
        <ul>{change.changed_conditions.map(condition => <li key={condition.key}>{condition.key}：{condition.previous_state == null ? '未在前版对照' : labels[condition.previous_state] || condition.previous_state} → {condition.current_state == null ? '不在本轮对照' : labels[condition.current_state] || condition.current_state}
          <details><summary>变化前后出处</summary><p>前版：{condition.previous_evidence_refs?.join('；') || '未记录'}</p><p>本版：{condition.evidence_refs.join('；') || '未记录'}</p></details>
        </li>)}</ul>
      </div>)}
      {!!changes.context_changes.length && <p>同时变化的条件：{changes.context_changes.map(key => contexts[key] || key).join('、')}</p>}
      {changes.baseline && <p>前版成果：{changes.baseline.artifact_id} · 摘要：{changes.baseline.content_sha256}</p>}<small>{changes.boundary}</small>
    </details>}
  </section>
}
