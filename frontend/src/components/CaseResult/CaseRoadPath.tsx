import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { expandCaseRoad, roadDetourLabel, type CaseRoadComparison, type CaseRoadRoute, type RoadDetourReference } from '../../services/roadAnalysis'
import { roadPolyline } from '../Map/roadPolyline'

const Map = lazy(() => import('../Map/LeafletMap'))

export default function CaseRoadPath({ comparison, assetId, onUnavailable }: {
  comparison: CaseRoadComparison; assetId: number; onUnavailable: () => void
}) {
  const [view, setView] = useState<{ data: CaseRoadRoute; paths: Array<{ points: Array<[number, number]>; distance: number; detour?: RoadDetourReference }> } | null>(null)
  const [selectedPath, setSelectedPath] = useState(0)
  const [status, setStatus] = useState('loading')
  const [attempt, setAttempt] = useState(0)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => {
    const request = new AbortController()
    controller.current = request
    setView(null); setSelectedPath(0); setStatus('loading')
    void expandCaseRoad(comparison, assetId, request.signal).then(data => {
      if (request.signal.aborted) return
      const alternatives = data.route.alternatives ?? []
      if (!Array.isArray(alternatives) || alternatives.length > 1) throw new Error('备选路径数量无效')
      const paths = [data.route, ...alternatives].map(path => {
        if (typeof path.distance_m !== 'number' || !Number.isFinite(path.distance_m) || path.distance_m < 0)
          throw new Error('路径距离无效')
        return { points: roadPolyline(path.shape_polyline6), distance: path.distance_m, detour: path.detour_reference }
      })
      setView({ data, paths }); setStatus('ready')
    }).catch(() => { if (!request.signal.aborted) { setView(null); setStatus('failed'); onUnavailable() } })
    return () => request.abort()
  }, [comparison, assetId, attempt, onUnavailable])
  return <div aria-label="已知道路参考路径">
    {status === 'loading' && <><p role="status">正在展开同版本参考路径…</p><button type="button" onClick={() => {
      controller.current?.abort(); setView(null); setStatus('cancelled')
    }}>取消路径计算</button></>}
    {(status === 'failed' || status === 'cancelled') && <><p role="status">{status === 'cancelled' ? '已取消路径计算。'
      : '参考路径暂不可用或引用权限、版本已变化，未据此判断不可达。'}</p>
      <button type="button" onClick={() => setAttempt(value => value + 1)}>重试路径</button></>}
    {view && status === 'ready' && <>
      <p>{view.data.target.name}附近道路参考路径，不是实际行驶轨迹。</p>
      {view.paths.length > 1 && <div role="group" aria-label="主路径与备选路径">
        {view.paths.map((path, index) => <button key={index} type="button" aria-pressed={selectedPath === index}
          onClick={() => setSelectedPath(index)}>{index === 0 ? '主路径' : '备选路径'}：{(path.distance / 1000).toFixed(2)} 公里</button>)}
      </div>}
      {view.data.route.alternatives_status === 'no_distinct_alternative_returned' &&
        <p className="case-result__note">本轮未返回独立备选，不代表现实中只有这一条道路。</p>}
      <p className="case-result__note">{roadDetourLabel(view.paths[selectedPath].detour)}</p>
      <p className="case-result__note">绕行基准采用路径实际道路端点，不计入点位到道路的偏移，也不据此认定行驶意图。</p>
      <Suspense fallback={<p role="status">正在加载内网地图…</p>}>
        <Map referencePath={view.paths[selectedPath].points} center={view.paths[selectedPath].points[0]} snapshotRef={view.data.map_snapshot_id} height={320} />
      </Suspense>
      <p className="case-result__note">实线沿已知路网绘制；底图及点位采用成果快照，通行条件采用本轮比较版本，不确认设施内部连通。</p>
    </>}
  </div>
}
