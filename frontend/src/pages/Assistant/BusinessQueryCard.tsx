import { Link } from 'react-router-dom'
import type { QueryCard } from '../../services/intelligentQueries'
import type { CaseProcess } from '../../services/caseProcess'
import type { FacilityDossier, FacilityTemporalContext } from '../../services/facilityAnalysis'
import type { CaseResult } from '../../types/caseResult'
import { resultKinds, resultPath, isResultKind } from '../../services/results'
import { FacilityDossierContent } from '../../components/Facility/FacilityDossierDrawer'
import { FacilityTemporalContent } from '../../components/Facility/FacilityIdentityPanel'
import CaseProcessView from '../Cases/CaseProcessView'
import { rowsOf, textValue } from './queryPresentation'
import AttentionGrounds from '../../components/Facility/AttentionGrounds'
import type { AttentionGrounding } from '../../types/attention'
import TemporalChangeExplanation from '../Situation/TemporalChangeExplanation'
import type { SituationBriefResult } from '../../services/intelligenceFlow'

export default function BusinessQueryCard({ card }: { card: QueryCard }) {
  const data = card.data || {}
  if (card.tool === 'business_attention') {
    const value = data as unknown as AttentionGrounding
    const window = data.time_window as { start?: string; end?: string; basis?: string } | undefined
    return value.coverage && Array.isArray(value.items) && value.items.every(item => item.layers && Array.isArray(item.evidence_refs))
      ? <>{window && <p>冻结关注时段：{window.start} — {window.end}（截止不含），按{{ discovery: '发现／查获', incident: '案发', entry: '录入' }[window.basis || ''] || '已声明'}时间。</p>}
        <AttentionGrounds value={value} /></> : <p role="alert">关注依据结构不完整，不能据此判断没有问题。</p>
  }
  if (card.tool === 'business_recent_changes') {
    const value = data as unknown as NonNullable<SituationBriefResult['comparison_snapshot']>
    return value.current && value.previous && value.change_origins && value.quality
      ? <><p>本期 {value.current.case_count} 条 · 对照期 {value.previous.case_count} 条，均为冻结时点的登记数量。</p>
        <p>按{value.time_basis_label || value.time_basis}时间；本期 {value.current.start} — {value.current.end}，对照期 {value.previous.start} — {value.previous.end}（均截止不含）。</p>
        <TemporalChangeExplanation comparison={value} /></> : <p role="alert">时间比较结构不完整，未用零值代替。</p>
  }
  if (card.tool === 'read_case_process') {
    const process = data.process as CaseProcess | undefined
    return process?.coverage && Array.isArray(process.events) ? <CaseProcessView process={process} /> : <p>当前没有就绪的过程依据，未为这次读取重新处理案件。</p>
  }
  if (card.tool === 'explain_case_result') {
    const result = data.result as CaseResult | undefined
    return result?.content ? <><Link to={resultPath('case', result.id)}>查看本次引用的完整案件成果</Link>
      <p>画像第 {result.content.versions.profile_version} 版；{data.result_basis === 'specified_historical_result' ? '指定历史版本' : '本次读取的已有版本'}。</p>
      <ul>{result.content.candidates.slice(0, 3).map(item => <li key={item.id}><strong>{item.title}</strong><p>{item.claim}</p>
        <p>支持：{item.supporting_evidence.join('；') || '未提供'}</p><p>反向依据与缺口：{[...item.counter_evidence, ...item.information_gaps].join('；') || '未提供'}</p></li>)}</ul>
      <p>内容摘要：{result.content_sha256}</p></> : <p>没有可读的冻结成果，不代表已排除关联。</p>
  }
  if (card.tool === 'read_facility_dossier') {
    const dossier = data.dossier as FacilityDossier | undefined
    return dossier?.sections && dossier?.facility ? <><p>以下为本次查询时留存的档案，不是实时刷新。</p><FacilityDossierContent data={dossier} params={new URLSearchParams()} /></> : <p>档案尚不可读。</p>
  }
  if (card.tool === 'read_facility_at') return <FacilityTemporalContent temporal={data.historical as FacilityTemporalContext | undefined} />
  if (card.tool === 'compare_coverage_scenario') {
    const comparison = data.comparison as Record<string, unknown> | undefined
    if (!comparison) return <p>未取得覆盖计算，不能据此判断没有缺口。</p>
    const baseline = comparison.baseline as Record<string, unknown>, scenario = comparison.scenario as Record<string, unknown>
    const inputs = comparison.input_snapshot as Record<string, unknown>
    return <><p>{textValue(comparison.boundary)}</p><p>假设时点：{textValue(inputs?.as_of)}；未改写正式资料。</p>
      <p>情景来源：{data.scenario_origin === 'model_proposed_hypothesis' ? '模型提出的假设，未经人工确认' : '用户显式选择的计算条件，不代表真实状态'}。</p>
      <table><caption>同一批登记设施的名义覆盖对照</caption><thead><tr><th>指标</th><th>原条件</th><th>假设条件</th></tr></thead><tbody>
        {[['covered_count', '名义覆盖井点'], ['overlap_count', '重复覆盖井点'], ['unknown_count', '资料未知'], ['outside_known_count', '已知范围外井点']].map(([key, label]) => <tr key={key}><th scope="row">{label}</th><td>{textValue(baseline?.[key])}</td><td>{textValue(scenario?.[key])}</td></tr>)}
      </tbody></table><details><summary>这次计算的条件副本</summary><p>停用资源：{Array.isArray(inputs?.disabled_resource_ids) ? inputs.disabled_resource_ids.map(textValue).join('、') || '无' : '未提供'}</p>
        <p>移动位置：{JSON.stringify(inputs?.movements || {})}</p><p>算法：{textValue(comparison.algorithm_version)}；不是实际设备视场或防控效果。</p></details></>
  }
  if (card.tool === 'find_business_results') {
    const catalog = data.catalog as Record<string, unknown> | undefined
    return <ul>{rowsOf(catalog?.items).map((item, i) => isResultKind(String(item.kind)) ? <li key={i}><Link to={resultPath(item.kind as keyof typeof resultKinds, String(item.id))}>{textValue(item.title)}</Link></li> : null)}</ul>
  }
  if (card.tool === 'read_business_result') {
    const result = data.business_result as Record<string, unknown> | undefined
    return result && isResultKind(String(result.kind)) ? <Link to={resultPath(result.kind as keyof typeof resultKinds, String(result.id))}>阅读本次引用材料：{textValue(result.title)}</Link> : null
  }
  return null
}
