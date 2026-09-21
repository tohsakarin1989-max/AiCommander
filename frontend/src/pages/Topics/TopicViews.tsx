import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router-dom'
import type { TopicViews as Views } from '../../services/analysisTopics'
import { categoryNames, kindNames } from './topicPresentation'
import { CaseHistoryContent } from '../Cases/CaseHistoryReferences'
import { isCaseHistoryResult } from '../../services/caseHistory'
const LeafletMap = lazy(() => import('../../components/Map/LeafletMap'))

const labels: Record<string, string> = {
  title: '标题', summary: '摘要', claim: '候选推断', status: '状态', hypothesis_type: '候选类型',
  supporting_evidence: '支持依据', counter_evidence: '反向依据', information_gaps: '信息缺口',
  evidence_refs: '来源引用', boundary: '适用边界', rule_support: '规则支持度（不是概率）',
  case_id: '案件 ID', operational_area_id: '辖区 ID', distance_m: '道路距离（米）', duration_seconds: '参考耗时（秒）',
  candidates: '候选', facilities: '设施', selected: '入选', ranking: '排序', coverage: '计算覆盖',
  reason: '原因', reasons: '依据', name: '名称', count: '数量', total: '合计', current_count: '本期案件数',
  previous_count: '上期案件数', change: '数量变化', versions: '版本', network_id: '路网版本', policy_revision: '通行版本',
}
function Entries({ value }: { value: unknown }) {
  if (value == null) return <>未提供</>
  if (typeof value !== 'object') return <>{String(value)}</>
  if (Array.isArray(value)) return value.length ? <ul>{value.map((item, i) => <li key={i}><Entries value={item} /></li>)}</ul> : <>未记录</>
  return <dl className="topic-data">{Object.entries(value).map(([key, item]) =>
    <div key={key}><dt>{labels[key] || key}</dt><dd><Entries value={item} /></dd></div>)}</dl>
}

export function TopicLinkedViews({ views, tab }: { views: Views; tab: string }) {
  const [area, setArea] = useState<number | null>(null)
  const [groupPage, setGroupPage] = useState(0)
  const mapVersion = views.map.versions.find(item => item.operational_area_id === area) || views.map.versions[0]
  const points = views.map.points.filter(item => item.operational_area_id === mapVersion?.operational_area_id)
  const groups = views.graph.groups.slice(groupPage * 10, (groupPage + 1) * 10)
  if (tab === 'map') return <section aria-label="专题地图与时间线">
    <p>{views.boundary}</p>
    {views.map.versions.length > 1 && <label>地图辖区<select value={mapVersion.operational_area_id}
      onChange={e => setArea(Number(e.target.value))}>{views.map.versions.map(item =>
        <option key={item.id} value={item.operational_area_id}>辖区 {item.operational_area_id} · {item.version}</option>)}</select></label>}
    {mapVersion ? <><p>地图版本：{mapVersion.version}；本页当前辖区 {points.length} 个案件位置。</p>
      <Suspense fallback={<p role="status">正在加载离线地图…</p>}>
        <LeafletMap key={mapVersion.id} snapshotRef={mapVersion.id} operationalAreaId={mapVersion.operational_area_id}
          productionAssetIds={[]} height="480px" referencePoints={points.map(item => ({
            id: String(item.case_id), latitude: item.latitude, longitude: item.longitude,
            title: `案件 #${item.case_id}`, description: '该版画像记录位置，不是推断轨迹',
          }))} />
      </Suspense></> : <p role="status">该版没有可引用的地图快照，未使用当前底图代替历史版本。可继续查看时间线与原文依据。</p>}
    <p>本页无可用坐标：{views.map.unmapped_in_page} 起，仍计入总体统计。</p>
    <h3>本页时间线</h3><ol>{views.timeline.map(item => <li key={item.case_id}>
      {item.occurred_time || '时间未提供'} · <Link to={`/cases?caseId=${item.case_id}`}>案件 #{item.case_id}</Link> · 画像版本 {item.profile_version}
    </li>)}</ol>
  </section>
  if (tab === 'groups') return <section aria-label="条件案组图谱">
    <p>{views.graph.boundary} 图中只展示本页案件；各条件旁的计数为完整匹配案组计数。</p>
    {!views.graph.groups.length && <p>本页没有可组成案组的有效表述，不能据此认定案件没有关联。</p>}
    {groups.map(group => <div className="topic-group" key={`${group.category}:${group.kind}:${group.value}`}>
      <strong>{categoryNames[group.category]} · {group.value}（{kindNames[group.kind]}）<br />全组 {group.case_count} 起</strong>
      <span aria-hidden="true">→</span><div className="topic-actions">{group.case_ids.map(id =>
        <Link key={id} to={`/cases?caseId=${id}`}>案件 #{id}</Link>)}</div>
    </div>)}
    {views.graph.groups.length > 10 && <div className="topic-actions">
      <button className="btn-ghost" disabled={!groupPage} onClick={() => setGroupPage(v => v - 1)}>上一组条件</button>
      <span>条件 {groupPage * 10 + 1} 至 {Math.min((groupPage + 1) * 10, views.graph.groups.length)}</span>
      <button className="btn-ghost" disabled={(groupPage + 1) * 10 >= views.graph.groups.length} onClick={() => setGroupPage(v => v + 1)}>下一组条件</button>
    </div>}
  </section>
  return <section aria-label="已有成果和周期材料">
    <p>{views.boundary}</p>
    <h3>历史案件与已确认经验</h3>
    {!views.history ? <p>该版没有历史参考记录，不代表没有相关历史资料。</p> : <>
      <p>{views.history.boundary}</p>
      {views.history.state === 'insufficient_conditions' ? <p>缺少可靠的检索条件，未自动编造历史查询。</p> : <>
        <p>历史参考使用以下代表条件（不计入本期统计）：{views.history.selection.conditions.map(item =>
          `${categoryNames[item.category] || item.category}·${item.value}（${kindNames[item.kind] || item.kind}）`).join('、') || '保存的关键词'}。</p>
        {isCaseHistoryResult(views.history.result) ? <CaseHistoryContent result={views.history.result} />
          : <p role="alert">历史参考结构不完整，不能据此判断没有匹配资料。</p>}
      </>}
    </>}
    <h3>本页案件已有候选与道路依据</h3>
    {!views.case_results.length && <p>未找到可复用且版本一致的案件成果，未重新生成或补造候选。</p>}
    {views.case_results.map(result => <details key={result.id}><summary>案件 #{result.case_id} · 已有候选与信息缺口</summary>
      <Entries value={{ candidates: result.candidates, information_gaps: result.information_gaps }} /></details>)}
    {!views.roads.length && <p>本页未引用可用道路成果；这不表示不可达。</p>}
    {views.roads.map(road => <details key={road.id}><summary>案件 #{road.case_id} · 道路依据</summary><Entries value={road.content} /></details>)}
    <h3>同辖区既有日/周材料</h3>
    {!views.period_materials.length && <p>没有可引用的日/周材料，未用专题统计冒充周期态势。</p>}
    {views.period_materials.map(brief => <details key={brief.id}><summary>{brief.period_type === 'daily' ? '日报' : '周报'}：{brief.period_start} 至 {brief.period_end}</summary>
      <p>材料编号：{brief.id}</p><Entries value={{ summary: brief.summary, information_gaps: brief.information_gaps }} />
      <details><summary>原周期比较依据</summary><Entries value={brief.comparison_snapshot} /></details>
    </details>)}
  </section>
}
