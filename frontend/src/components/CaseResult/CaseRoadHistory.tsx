import { lazy, Suspense, useEffect, useState } from 'react'
import { readRoadArtifact, roadArtifactHistory, type RoadArtifact, type RoadArtifactSummary } from '../../services/roadAnalysis'
import { roadPolyline } from '../Map/roadPolyline'
import CaseResultDownload from './CaseResultDownload'
import CaseFacilityComparison from './CaseFacilityComparison'

const Map = lazy(() => import('../Map/LeafletMap'))
type Available = Extract<RoadArtifactSummary, { availability: 'available' }>

function SavedResult({ resultId, selected }: { resultId: string; selected: Available }) {
  const [view, setView] = useState<{ artifact: RoadArtifact; points?: Array<[number, number]> } | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const request = new AbortController()
    setView(null); setFailed(false)
    void readRoadArtifact(selected.id, resultId, selected.content_sha256, request.signal).then(artifact => {
      if (request.signal.aborted) return
      const points = artifact.content.schema_version === 'case-road-route-4.2.0-1'
        ? roadPolyline(artifact.content.route.shape_polyline6) : undefined
      setView({ artifact, points })
    }).catch(() => { if (!request.signal.aborted) { setView(null); setFailed(true) } })
    return () => request.abort()
  }, [resultId, selected])
  if (failed) return <p role="status">历史成果暂不可用，权限或来源版本可能已变化。未重新计算，请刷新历史列表后重试。</p>
  if (!view) return <p role="status">正在读取已保存成果…</p>
  const content = view.artifact.content
  const calculation = content.schema_version === 'case-road-route-4.2.0-1' ? content.route
    : content.schema_version === 'case-facility-comparison-5.2-1' ? content.calculation : content.matrix
  return <section aria-label="已保存道路成果">
    <p>历史留存，不重新计算；不代表当前道路仍可通行。</p>
    <p>保存时间：{view.artifact.created_at}</p>
    <CaseResultDownload key={view.artifact.id} resultId={resultId} hash={content.content_sha256} road={view.artifact} />
    {content.schema_version === 'case-facility-comparison-5.2-1' && <CaseFacilityComparison content={content} />}
    {content.schema_version === 'case-road-route-4.2.0-1' && view.points && <>
      <p>{content.target.name}附近道路参考路径，不是实际行驶轨迹。</p>
      <p>留存道路距离：{(content.route.distance_m / 1000).toFixed(2)} 公里</p>
      <Suspense fallback={<p role="status">正在加载历史地图…</p>}>
        <Map referencePath={view.points} center={view.points[0]} snapshotRef={content.map_snapshot_id} height={320} />
      </Suspense>
    </>}
    {content.schema_version === 'case-road-comparison-4.2.0-1' && <>
      <dl className="case-result__facts">{content.targets.map((target, index) => {
        const cell = content.matrix?.cells.find(item => item.source_index === 0 && item.target_index === index)
        const distance = cell?.status === 'calculated' ? cell.distance_m : null
        return <div key={target.asset_id}><dt>{target.name}</dt><dd>{typeof distance === 'number' && Number.isFinite(distance) && distance >= 0
          ? `${(distance / 1000).toFixed(2)} 公里` : '未取得参考路线，不等于现实中不可达'}</dd></div>
      })}</dl>
      <ul>{content.information_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>
    </>}
    <details><summary>历史版本与依据</summary>
      <p>计算条件时刻：{calculation?.analysis_at ?? '未记录'}</p>
      <p>路网版本：{calculation?.network_id ?? '未记录'}</p>
      <p>地图快照：{content.map_snapshot_id ?? '未记录'}</p>
      <p style={{ overflowWrap: 'anywhere' }}>成果校验：{view.artifact.content_sha256}</p>
      {content.schema_version === 'case-road-comparison-4.2.0-1' && <ul>{content.targets.map(target =>
        <li key={target.asset_id}>{target.name}：{target.evidence_ref}</li>)}</ul>}
      <p>{content.boundary}</p>
    </details>
  </section>
}

function HistoryList({ resultId }: { resultId: string }) {
  const [page, setPage] = useState<Awaited<ReturnType<typeof roadArtifactHistory>> | null>(null)
  const [cursor, setCursor] = useState<string>()
  const [attempt, setAttempt] = useState(0)
  const [failed, setFailed] = useState(false)
  const [selected, setSelected] = useState<Available | null>(null)
  useEffect(() => {
    const request = new AbortController()
    setPage(null); setSelected(null); setFailed(false)
    void roadArtifactHistory(resultId, request.signal, cursor).then(data => {
      if (!request.signal.aborted) setPage(data)
    }).catch(() => { if (!request.signal.aborted) setFailed(true) })
    return () => request.abort()
  }, [resultId, cursor, attempt])
  return <>
    {!page && !failed && <p role="status">正在读取历史列表…</p>}
    {failed && <p role="status">历史列表暂不可用，不影响其他案件成果。</p>}
    <button type="button" onClick={() => { setPage(null); setSelected(null); setCursor(undefined); setAttempt(value => value + 1) }}>刷新历史列表</button>
    {page && <>
      {page.items.length === 0 && <p>本成果尚无已保存的道路计算记录。</p>}
      <ul>{page.items.map(item => <li key={item.id}>{item.availability === 'unavailable'
        ? '此条历史成果当前不可访问或来源版本已变化。'
        : <button type="button" aria-pressed={selected?.id === item.id} onClick={() => setSelected(item)}>
          {item.created_at} · {item.operation === 'route' ? '查看留存路径' : item.operation === 'facility' ? '查看设施候选比较' : '查看留存距离比较'}
        </button>}</li>)}</ul>
      {page.next_before_id && <button type="button" onClick={() => { setPage(null); setSelected(null); setCursor(page.next_before_id!) }}>更早记录</button>}
      {selected && <SavedResult key={selected.id} resultId={resultId} selected={selected} />}
    </>}
  </>
}

export default function CaseRoadHistory({ resultId }: { resultId: string }) {
  const [open, setOpen] = useState(false)
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>历史道路成果</summary>
    {open && <HistoryList key={resultId} resultId={resultId} />}
  </details>
}
