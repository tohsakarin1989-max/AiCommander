export interface AnalysisApplicability {
  version: string
  entries: Array<{ kind: string; status: string; reason: string; evidence_refs: unknown[] }>
  boundary: string
}

const kinds: Record<string, string> = {
  base: '基础整理', history: '历史参考', statistics: '适用统计', spatial_background: '周边背景',
  source_inference: '来源与去向分析', road_analysis: '道路条件分析',
}
const statuses: Record<string, string> = { applicable: '资料可支持', insufficient_data: '现有资料不足', not_applicable: '本次不适用' }

export default function CaseAnalysisApplicability({ value, loading, error, updating }: {
  value?: AnalysisApplicability | null; loading?: boolean; error?: boolean; updating?: boolean
}) {
  return <section className="detail-section" aria-label="后台分析适用情况">
    <div className="ds-head">后台分析适用情况</div>
    <p>这里只说明已有资料支持哪些分析，不代表本单位处置进展，也不要求补齐公安侦查信息。</p>
    {error ? <p role="alert">适用情况暂不可读，不等于资料不足或案件未完成。</p>
      : loading ? <p role="status">正在读取本版分析适用情况…</p>
        : updating ? <p role="status">资料已变化，正在更新适用情况，未用旧版结果表示当前条件。</p>
          : !value ? <p>当前画像尚无适用性记录，未将其解释为分析失败。</p>
            : <><dl className="case-analysis-applicability">{value.entries.map(entry => <div key={entry.kind}>
              <dt>{kinds[entry.kind] || '其他分析'} · {statuses[entry.status] || '状态待核'}</dt>
              <dd>{entry.reason}</dd>
            </div>)}</dl><p className="narr">{value.boundary}</p></>}
  </section>
}
