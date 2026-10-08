import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { readAutomaticRoadComparison, readRoadArtifact, roadVehicleLabel, type AutomaticRoadComparison, type FacilityComparisonProgress } from '../../services/roadAnalysis'
import { useAuth } from '../../auth/AuthContext'
import CaseResultDownload from './CaseResultDownload'
import CaseReachableRoads from './CaseReachableRoads'
import CaseRoadPath from './CaseRoadPath'
import CaseRoadHistory from './CaseRoadHistory'
import CaseFacilityComparison from './CaseFacilityComparison'
import FacilityEvaluationArchive from './FacilityEvaluationArchive'
import CaseRoadScenarios from './CaseRoadScenarios'

export function LegacyCandidateReference({ currentFacility, children }: { currentFacility: boolean; children?: ReactNode }) {
  const [open, setOpen] = useState(false)
  if (!children) return null
  return currentFacility ? <details onToggle={event => setOpen(event.currentTarget.open)}><summary>查看原空间分析与其他类型候选</summary>
    <p>以下为原冻结空间分析，未替换成道路排序，不与上方候选合并排名。</p>{open && children}</details> : <>{children}</>
}

type ComparisonProps = { resultId: string; hash: string; legacyCandidates?: ReactNode; frozen?: { id: string; content_sha256: string }; awaitingComposition?: boolean }

export function RoadComparisonProgress({ progress }: { progress: FacilityComparisonProgress }) {
  const phases = { scan: '扫描候选设施', entrances: '核验候选设施入口', roads: '分批比较道路目标' }
  return <div role="status" aria-live="polite" aria-label="道路比较处理进度">
    <p>当前阶段：{phases[progress.phase]}。后台会保存分批进度，继续处理不代表失败。</p>
    <ul>
      <li>已扫描 {progress.scanned} 个设施，{progress.scan_complete ? '当前固定范围扫描已完成' : '仍在扫描当前固定范围'}。</li>
      <li>当前候选池 {progress.candidate_pool_size} 个，上限 {progress.candidate_pool_limit} 个。</li>
      <li>入口核验已处理 {progress.entrance_facilities_checked} / {progress.entrance_facilities_total} 个候选设施，
        {progress.entrance_check_complete ? '本候选池入口核验已完成' : '尚未完成入口核验'}。</li>
      <li>道路目标已处理 {progress.road_targets_completed} 个{progress.road_targets_total === null
        ? '，总数尚未确定' : `，当前固定目标共 ${progress.road_targets_total} 个`}。
        {progress.road_complete ? '本批目标计算已完成，等待成果汇总。' : '尚未形成完整道路比较成果。'}</li>
    </ul>
    <p>授权范围或依据变化后会停止沿用本次进度。</p>
    <p>{progress.boundary}</p>
  </div>
}

export default function CaseRoadComparison(props: ComparisonProps) {
  const { user, sessionEpoch } = useAuth()
  // A new account or object never renders the former session's partial counts.
  const identity = JSON.stringify([user?.id, sessionEpoch, user?.role, props.resultId, props.hash,
    props.frozen?.id, props.frozen?.content_sha256, props.awaitingComposition])
  return <ComparisonSession key={identity} {...props} />
}

function ComparisonSession({ resultId, hash, legacyCandidates, frozen, awaitingComposition = false }: ComparisonProps) {
  const [artifact, setArtifact] = useState<AutomaticRoadComparison['artifact']>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed' | 'paused' | 'processing' | 'waiting_network' | 'information_missing' | 'not_available' | 'composition_pending'>('loading')
  const [attempt, setAttempt] = useState(0)
  const [controller, setController] = useState<AbortController | null>(null)
  const [pathTarget, setPathTarget] = useState<number | null>(null)
  const [dependencies, setDependencies] = useState<string[]>([])
  const [progress, setProgress] = useState<FacilityComparisonProgress | null>(null)
  const [unavailableReason, setUnavailableReason] = useState<AutomaticRoadComparison['reason']>()
  const invalidateComparison = useCallback(() => { setArtifact(null); setPathTarget(null); setProgress(null); setStatus('failed') }, [])
  useEffect(() => {
    const request = new AbortController()
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    let polls = 0
    setController(request)
    setArtifact(null)
    setPathTarget(null)
    setDependencies([])
    setProgress(null)
    setUnavailableReason(undefined)
    setStatus('loading')
    const load = async () => {
      if (!active || request.signal.aborted) return
      if (document.hidden) { timer = setTimeout(() => void load(), 10000); return }
      try {
        if (frozen) {
          const item = await readRoadArtifact(frozen.id, resultId, frozen.content_sha256, request.signal)
          if (!active || request.signal.aborted) return
          if (item.content.schema_version !== 'case-facility-comparison-5.2-1' || item.content.content_sha256 !== hash)
            throw new Error('组合道路附件不一致')
          setArtifact({ ...item, content: item.content })
          setStatus('ready')
          return
        }
        const result = await readAutomaticRoadComparison(resultId, hash, request.signal)
        if (!active || request.signal.aborted) return
        setDependencies(result.information_dependencies || [])
        setProgress(result.status === 'processing' ? result.progress || null : null)
        setUnavailableReason(result.status === 'unavailable' ? result.reason : undefined)
        polls += 1
        if (result.status === 'completed' && result.artifact) {
          if (awaitingComposition) {
            setStatus('composition_pending')
            return
          }
          setArtifact(result.artifact)
          setStatus('ready')
        } else if (result.status === 'processing' || result.status === 'waiting_network') {
          setStatus(polls < 12 ? result.status : 'paused')
          if (polls < 12) timer = setTimeout(() => void load(), result.status === 'waiting_network' ? 60000 : 10000)
        } else {
          setStatus(result.status === 'unavailable' ? 'failed' : result.status === 'completed' ? 'failed' : result.status)
        }
      } catch {
        if (!active || request.signal.aborted) return
        setArtifact(null)
        setProgress(null)
        setDependencies([])
        setUnavailableReason(undefined)
        setStatus('failed')
      }
    }
    const expire = () => {
      active = false; request.abort(); clearTimeout(timer)
      setArtifact(null); setProgress(null); setDependencies([]); setPathTarget(null)
      setUnavailableReason(undefined); setStatus('failed')
    }
    window.addEventListener('aic:auth-expired', expire)
    void load()
    return () => { active = false; request.abort(); clearTimeout(timer); window.removeEventListener('aic:auth-expired', expire) }
  }, [resultId, hash, attempt, frozen?.id, frozen?.content_sha256, awaitingComposition])
  const data = artifact?.content
  const usable = data?.schema_version === 'case-road-comparison-4.2.0-1' && data.result_id === resultId && data.content_sha256 === hash ? data : null
  const facility = data?.schema_version === 'case-facility-comparison-5.2-1' && data.result_id === resultId && data.content_sha256 === hash ? data : null
  return <section className="case-result__roads" aria-label="道路参考比较" aria-busy={status === 'loading'}>
    {!(status === 'ready' && facility) && !(frozen && status === 'failed') && <LegacyCandidateReference currentFacility={false}>{legacyCandidates}</LegacyCandidateReference>}
    <h4>设施道路与条件研判</h4>
    <p className="case-result__note">新结果先比较设施池的道路条件再排序；旧版点位附近道路比较继续保留。车型未明确时使用标明的小客车参考假设，不确认案发时路线。</p>
    <p className="case-result__note">{frozen ? '本页与顶部报告下载使用同一冻结组合，不用后来生成的附件替换当前内容。' : '道路参考与原冻结成果分开保存；比较完成后可直接下载含道路附件的报告，历史版本仍可追溯。'}</p>
    {status === 'loading' && <p role="status">正在读取后台道路成果…</p>}
    {status === 'composition_pending' && <p role="status">道路附件已形成，等待统一成果刷新后再展示；不将新附件混入旧成果。若范围或条件已变化，需等待对应新结果。</p>}
    {status === 'processing' && <><p role="status">后台正在处理，完成后自动显示；可以继续查看案件。</p>
      {progress && <RoadComparisonProgress progress={progress} />}
      <button type="button" onClick={() => { controller?.abort(); setStatus('paused') }}>暂停刷新</button></>}
    {status === 'waiting_network' && <><p role="status">路网或通行授权尚未就绪，系统会在可用后继续。案件录入和原研判内容不受影响。</p>
      <button type="button" onClick={() => { controller?.abort(); setStatus('paused') }}>暂停刷新</button></>}
    {status === 'failed' && <p role="status">{unavailableReason === 'frozen_inputs_changed'
      ? '本次比较依据已变化，已隐藏旧进度；旧附件不能作为当前比较，请刷新核对。'
      : unavailableReason === 'frozen_inputs_unavailable'
        ? '本次冻结资料或当前授权已不可用，已隐藏旧进度，请刷新核对。'
        : '道路比较暂不可用，可能缺少授权路网或点位连接尚待核验。没有据此判断不可达，其他成果仍可查看。'}</p>}
    {status === 'paused' && <p role="status">已暂停页面刷新，后台任务仍会继续。</p>}
    {status === 'information_missing' && <p role="status">案件点位、设施点位或车辆通行条件不足，暂未形成道路比较。未推定设施入口或不可达结论。</p>}
    {status === 'information_missing' && !!dependencies.length && <ul>{dependencies.map(item => <li key={item}>{item}</li>)}</ul>}
    {status === 'not_available' && <p role="status">暂无可读取的后台道路成果。历史案件或尚未配置路网的案件可继续查看原研判内容。</p>}
    {(status === 'failed' || status === 'paused' || status === 'not_available') && <button type="button" onClick={() => setAttempt(value => value + 1)}>刷新结果</button>}
    {status === 'ready' && facility && artifact && <>
      <CaseFacilityComparison content={facility} onSelect={setPathTarget} />
      <CaseRoadScenarios artifactId={artifact.id} artifactHash={artifact.content_sha256} resultId={resultId} resultHash={hash} />
      {pathTarget !== null && <CaseRoadPath key={`${facility.result_id}:${artifact.id}:${pathTarget}`}
        comparison={facility} artifact={artifact} assetId={pathTarget} onUnavailable={invalidateComparison} />}
      {!frozen && <CaseResultDownload resultId={resultId} hash={hash} road={{ id: artifact.id, content_sha256: artifact.content_sha256 }} />}
      <FacilityEvaluationArchive artifactId={artifact.id}
        available={Array.isArray(facility.result.scoring_evidence) && !!facility.result.scorer_checksum} />
      {!frozen && <LegacyCandidateReference currentFacility>{legacyCandidates}</LegacyCandidateReference>}
    </>}
    {status === 'ready' && usable && <>
      {usable.matrix && <p className="case-result__note">计算车型：{roadVehicleLabel(usable.matrix.vehicle)}。未提供的其他车型属性采用引擎默认参考值。</p>}
      {usable.matrix && <dl className="case-result__facts">{usable.targets.map((target, index) => {
        const cell = usable.matrix?.cells.find(item => item.source_index === 0 && item.target_index === index)
        const valid = cell?.status === 'calculated' && typeof cell.distance_m === 'number' && Number.isFinite(cell.distance_m) && cell.distance_m >= 0
        return <div key={target.asset_id}><dt>{target.name}</dt><dd>{valid ? `${(cell!.distance_m! / 1000).toFixed(2)} 公里`
          : '未取得参考路线，不等于现实中不可达'} {valid && <button type="button" aria-pressed={pathTarget === target.asset_id}
            onClick={() => setPathTarget(target.asset_id)}>查看参考路径</button>}</dd></div>
      })}</dl>}
      {usable.information_gaps.length > 0 && <ul>{usable.information_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>}
      {pathTarget !== null && <CaseRoadPath key={`${usable.result_id}:${pathTarget}`} comparison={usable} assetId={pathTarget} onUnavailable={invalidateComparison} />}
      {usable.matrix && <details><summary>计算版本与依据</summary><p>计算条件时刻：{usable.matrix.analysis_at}</p>
        <p>路网版本：{usable.matrix.network_id}；通行规则版本：{usable.matrix.policy_revision}</p>
        <p>点位地图快照：{usable.map_snapshot_id}</p><ul>{usable.targets.map(item => <li key={item.asset_id}>{item.name}：{item.evidence_ref}</li>)}</ul>
        <p>{usable.boundary}</p></details>}
      {artifact && <CaseResultDownload key={`${resultId}:${hash}:${artifact.id}:${artifact.content_sha256}`}
        resultId={resultId} hash={hash} road={{ id: artifact.id, content_sha256: artifact.content_sha256 }} />}
      {usable.matrix && usable.map_snapshot_id && <CaseReachableRoads
        key={`${resultId}:${hash}:${artifact?.id}`} comparison={usable} />}
    </>}
    {!frozen && <CaseRoadHistory key={resultId} resultId={resultId} />}
  </section>
}
