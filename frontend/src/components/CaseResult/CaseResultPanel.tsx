import type { ReactNode } from 'react'
import type { CaseResult } from '../../types/caseResult'
import CaseSemanticProfile from '../../pages/Cases/CaseSemanticProfile'
import CaseResultDownload from './CaseResultDownload'
import CaseRoadComparison from './CaseRoadComparison'
import './CaseResultPanel.css'

const labels: Record<string, string> = {
  occurred_time: '案发时间（存储值）', location: '地点', case_type: '案件类型', oil_type: '油品',
  oil_nature: '油品性质', facility_type: '设施类型', modus_operandi: '作案手法', report_unit: '报案单位', source_type: '案件来源',
  upstream_source: '来源线索', downstream_destination: '去向线索', water_cut: '含水率（记录值）',
  oil_volume: '涉油数量（记录值）', oil_value: '涉油价值（记录值）',
  evidence_count: '证据记录数', vehicle_count: '车辆记录数', person_count: '人员记录数',
}

function Facts({ values }: { values: Record<string, unknown> }) {
  return <dl className="case-result__facts">{Object.entries(values).filter(([key]) => key in labels).map(([key, value]) =>
    <div key={key}><dt>{labels[key]}</dt><dd>{value == null || value === '' ? '未记录' :
      typeof value === 'string' || typeof value === 'number' ? String(value) : JSON.stringify(value)}
      {key === 'occurred_time' && typeof value === 'string' && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
        && <small>（存储值未注明时区，不与原文时刻直接比较）</small>}
    </dd></div>,
  )}</dl>
}

export default function CaseResultPanel({ result, caseId, loading, error, errorStatus, map, footer }: {
  result?: CaseResult; caseId: number; loading?: boolean; error?: boolean; errorStatus?: number; map?: ReactNode; footer?: ReactNode
}) {
  // A failed refresh must hide cached content, including its map and source text.
  const usable = !error && result?.content.case_id === caseId
    && result.content.schema_version === 'case-result-4.1.0-1'
  if (!usable) return <section className="detail-section case-result" aria-label="统一研判成果">
    <h3>统一研判成果</h3>
    <p role="status">{error && errorStatus !== 404 ? '成果暂时无法读取，已隐藏上次内容。案件保存不受影响。'
      : loading ? '正在读取后台成果…'
        : '成果尚未生成、引用已失效或当前不可访问。后台完成后自动显示，无需手动运行智能体。'}</p>
  </section>
  const { content } = result
  return <section className="detail-section case-result" aria-label="统一研判成果">
    <header className="case-result__header"><h3>统一研判成果</h3><span>画像第 {content.versions.profile_version} 版</span></header>
    <p className="case-result__note">事实记录、候选解释和信息缺口分开呈现，供人工判断，不自动形成正式结论或执行任务。</p>
    <CaseResultDownload key={`${result.id}:${result.content_sha256}`} resultId={result.id} hash={result.content_sha256} />
    {result.freshness === 'pending_update' && <p role="status" className="case-result__warning">等待更新：案件内容或规则已变化，以下为上一次处理结果。</p>}
    <details><summary>原始记录摘要与关联条件</summary>
      <p>{content.facts_summary.label}</p><Facts values={content.facts_summary.recorded_fields} />
      <Facts values={content.related_conditions} />
    </details>
    {content.information_gaps.profile.length > 0 && <div className="case-result__gaps">
      <h4>关键缺项</h4><ul>{content.information_gaps.profile.map((gap, index) => <li key={index}>
        {gap.label}{gap.reason ? `：${gap.reason}` : ''}</li>)}</ul>
    </div>}
    <h4>待核验候选</h4>
    {content.candidates.length ? <ol className="case-result__candidates">{content.candidates.slice(0, 3).map(item =>
      <li key={item.id}><h4>{item.rank}. {item.title}</h4><p>{item.claim}</p>
        <small>规则支持度：{Number.isFinite(item.score) ? item.score : '未提供'}，不是准确概率。</small>
        <h5>支持证据</h5><ul>{item.supporting_evidence.map((text, index) => <li key={index}>{text}</li>)}</ul>
        <h5>反向证据与信息缺口</h5>
        <ul>{[...item.counter_evidence, ...item.information_gaps].map((text, index) => <li key={index}>{text}</li>)}</ul>
        <details><summary>证据引用与适用边界</summary>
          <ul>{item.evidence_refs.map(ref => <li key={ref}><code>{ref}</code></li>)}</ul><p>{item.boundary}</p>
        </details>
      </li>,
    )}</ol> : <p>尚无可展示候选，不代表不存在相关线索。</p>}
    {!!content.information_gaps.analysis.length && <ul className="case-result__gaps">{content.information_gaps.analysis.map((text, index) => <li key={index}>{text}</li>)}</ul>}
    {map}
    {result.freshness !== 'pending_update' && <CaseRoadComparison key={`${result.id}:${result.content_sha256}`} resultId={result.id} hash={result.content_sha256} />}
    <CaseSemanticProfile key={result.id} semantics={content.semantics ?? undefined} updating={result.freshness === 'pending_update'} />
    <details><summary>成果版本与边界</summary>
      <dl className="case-result__facts">
        <div><dt>成果编号</dt><dd>{result.id}</dd></div>
        <div><dt>生成时间</dt><dd>{result.created_at}</dd></div>
        <div><dt>地图版本</dt><dd>{content.versions.map_snapshot_id || '尚未结合地图'}</dd></div>
        <div><dt>算法版本</dt><dd>{content.versions.algorithm_version || '仅画像整理'}</dd></div>
        <div><dt>字典版本</dt><dd>{content.versions.dictionary_version}</dd></div>
        <div><dt>内容摘要</dt><dd><code>{result.content_sha256}</code></dd></div>
      </dl><ul>{content.boundary.map(text => <li key={text}>{text}</li>)}</ul>
    </details>
    {footer}
  </section>
}
