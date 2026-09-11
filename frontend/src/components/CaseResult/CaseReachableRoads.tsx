import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { caseReachableRoads, roadVehicleLabel, type CaseRoadComparison, type RoadBudget } from '../../services/roadAnalysis'

const Map = lazy(() => import('../Map/LeafletMap'))
const choices: Array<{ label: string; budget: RoadBudget }> = [
  { label: '沿路 3 公里', budget: { metric: 'distance', distance_m: 3000 } },
  { label: '沿路 5 公里', budget: { metric: 'distance', distance_m: 5000 } },
  { label: '参考 10 分钟', budget: { metric: 'time', seconds: 600 } },
]

export default function CaseReachableRoads({ comparison }: { comparison: CaseRoadComparison }) {
  const [choice, setChoice] = useState(0)
  const [attempt, setAttempt] = useState(0)
  const [view, setView] = useState<Awaited<ReturnType<typeof caseReachableRoads>> | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed' | 'cancelled'>('loading')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => {
    const request = new AbortController()
    controller.current = request
    setView(null); setStatus('loading')
    void caseReachableRoads(comparison, choices[choice].budget, request.signal).then(result => {
      if (!request.signal.aborted) { setView(result); setStatus('ready') }
    }).catch(() => {
      if (!request.signal.aborted) { setView(null); setStatus('failed') }
    })
    return () => request.abort()
  }, [comparison, choice, attempt])
  const changeChoice = (index: number) => {
    controller.current?.abort(); setView(null); setStatus('loading'); setChoice(index)
  }
  return <section aria-label="案件预算道路参考" aria-busy={status === 'loading'}>
    <h4>从案件点位出发的道路参考</h4>
    <p className="case-result__note">自动沿用本成果的案件坐标、车型和路网版本。预算是查看条件，不是案发事实。</p>
    <div role="group" aria-label="道路预算">
      {choices.map((item, index) => <button key={item.label} type="button" aria-pressed={choice === index}
        disabled={choice === index} onClick={() => changeChoice(index)}>{item.label}</button>)}
    </div>
    {choice === 2 && <p className="case-result__note">时间按已知道路速度及转向条件估算，不是实时交通或准确到达时间。</p>}
    {status === 'loading' && <><p role="status">正在计算预算内道路段，其他案件内容仍可使用…</p>
      <button type="button" onClick={() => { controller.current?.abort(); setView(null); setStatus('cancelled') }}>取消道路计算</button></>}
    {(status === 'failed' || status === 'cancelled') && <><p role="status">{status === 'cancelled' ? '已取消本次计算。'
      : '预算道路暂不可用，可能是权限或版本变化、连接待核、范围超限或计算故障；未据此判断不可达。'}</p>
      <button type="button" onClick={() => setAttempt(value => value + 1)}>重新计算道路参考</button></>}
    {status === 'ready' && view && <>
      {view.data.information_gaps.length > 0 && <ul>{view.data.information_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>}
      {view.data.reachability && <p className="case-result__note">计算车型：{roadVehicleLabel(view.data.reachability.vehicle)}</p>}
      {view.segments.length > 0 ? <Suspense fallback={<p role="status">正在加载内网地图…</p>}>
        <Map referenceRoadSegments={view.segments} center={view.segments[0][0]} snapshotRef={view.data.map_snapshot_id} height={320} />
      </Suspense> : <p role="status">没有可展示的预算道路段，不等于现实中不可达。</p>}
      <p className="case-result__note">{view.data.boundary} 未显示的道路不等于不可达。</p>
    </>}
  </section>
}
