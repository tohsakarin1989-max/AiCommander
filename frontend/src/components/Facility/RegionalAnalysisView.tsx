import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useRegionalAnalysis } from '../../services/useRegionalAnalysis'
import { openFacilityDossier, regionalContextPath } from '../../services/regionalContext'
import RegionalControls from './RegionalControls'
import { evidenceStateLabels } from './FacilityDossierDrawer'

export default function RegionalAnalysisView() {
  const [page, setPage] = useState(1)
  const { context, query, data } = useRegionalAnalysis(page)
  useEffect(() => setPage(1), [context.areaId, context.startDate, context.endDate])
  const timeline = data ? [
    ...data.cases.items.map(item => ({ key: `case:${item.id}`, id: item.id, kind: 'case' as const, title: item.case_number, date: item.occurred_time })),
    ...data.events.items.map(item => ({ key: `event:${item.id}`, id: item.id, kind: 'event' as const, title: item.title || item.event_number, date: item.occurred_time })),
  ].sort((left, right) => (right.date ?? '').localeCompare(left.date ?? '')) : []
  return <div className="regional-analysis">
    <RegionalControls context={context} />
    {query.isError && <p role="alert">区域资料读取失败，未展示缓存或推断为空。<button onClick={() => void query.refetch()}>重试</button></p>}
    {query.isFetching && !data && <p role="status">正在读取授权区域资料…</p>}
    {data && <>
      <p>{data.boundary}</p>
      <p>当前范围：{data.scope.area_name}；设施 {data.facilities.total} 个，案件 {data.cases.total} 起，事件 {data.events.total} 条。
        其中独立事件 {data.events.independent_count} 条、已关联案件事件 {data.events.linked_case_count} 条；事件与案件不简单相加。</p>
      {!!data.events.linked_case_outside_window_count && <p>其中 {data.events.linked_case_outside_window_count} 条事件关联了时间窗外案件；不把这些案件计入本期总量。</p>}
      <h2>生产设施条件对照</h2><p>依照已有历史资料逐项对照，不预测发案、不按邻近数量排名。</p>
      <div className="regional-facilities">{data.facilities.items.map(facility => <article key={facility.id}>
        <h3>{facility.name}</h3><p>稳定编号 {facility.id} · {facility.asset_type}</p>
        <button className="btn-ghost" onClick={() => openFacilityDossier(facility.id)}>查看设施档案</button>
        {facility.condition_comparison.state === 'restricted' ? <p>条件资料受限，无法展示内容和数量。</p> : <>
          <p>{evidenceStateLabels[facility.condition_comparison.state] || '资料待核'}</p>
          <p>{facility.condition_comparison.boundary}</p>
          {(facility.condition_comparison.reference_cases ?? []).map(reference => <details key={reference.case_id}>
            <summary>{reference.title}</summary><Link to={regionalContextPath(`/cases?caseId=${reference.case_id}`, context.params)}>查看原案件</Link>
            <p>相似条件：{reference.similar.join('；') || '未记录'}</p><p>不同条件：{reference.different.join('；') || '未记录，不能据此认为相同'}</p>
            {!!reference.historical_conditions?.length && <p>历史手法与地点参考（非当前设施事实）：{reference.historical_conditions.join('；')}</p>}
            <p>信息缺口：{reference.gaps.join('；') || '未列出，不代表资料完整'}</p>
            {!!reference.evidence_refs.length && <p>依据：{reference.evidence_refs.join('；')}</p>}
          </details>)}
          {!!facility.condition_comparison.gaps.length && <p>资料缺口：{facility.condition_comparison.gaps.join('；')}</p>}
        </>}
      </article>)}</div>
      {!data.facilities.total && <p>当前授权条件下没有生产设施记录。</p>}
      <div className="regional-pagination"><button disabled={page <= 1} onClick={() => setPage(v => v - 1)}>上一页设施</button>
        <span>第 {page} 页</span><button disabled={page * data.facilities.page_size >= data.facilities.total} onClick={() => setPage(v => v + 1)}>下一页设施</button></div>
      <h2>案件与事件时间线</h2>
      <p>当前展示案件 {data.cases.items.length} 起、事件 {data.events.items.length} 条；无有效坐标案件 {data.cases.missing_coordinates} 起仍计入总数。</p>
      {(data.coverage.cases_truncated || data.coverage.events_truncated) && <p role="status">时间线和地图展示数量有限，以上总量来自全部授权匹配记录。</p>}
      <ol>{timeline.map(item => <li key={item.key}>
        <button className="btn-ghost" aria-pressed={item.kind === 'case' ? context.caseId === item.id : context.eventId === item.id}
          onClick={() => context.update(item.kind === 'case' ? { caseId: item.id } : { eventId: item.id })}>选择</button>
        {item.date || '时间未记录'} · {item.kind === 'case' ? '案件' : '事件'} · <Link to={regionalContextPath(item.kind === 'case' ? `/cases?caseId=${item.id}` : `/events?eventId=${item.id}`, context.params)}>{item.title}</Link>
      </li>)}</ol>
      {!timeline.length && <p>当前条件下没有可展示的时间记录。</p>}
      <p>地图与设施入口位于上方“案件与设施地图”，继续使用同一辖区和时间条件。</p>
    </>}
  </div>
}
