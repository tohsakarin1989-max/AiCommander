import type { CaseFacilityComparison as Comparison } from '../../services/roadAnalysis'
import { roadVehicleLabel } from '../../services/roadAnalysis'
import { lazy, Suspense, useCallback, useId, useMemo, useState } from 'react'
import { facilityComparisonMapModel } from './facilityComparisonMapModel'

const Map = lazy(() => import('../Map/LeafletMap'))

const states: Record<string, string> = {
  entrance_unknown: '入口或连接待核', permission_unknown: '许可资料不足', restricted: '通行受限',
  no_path_found: '未取得道路路径', network_missing: '缺少路网', calculation_failed: '计算失败', not_calculated: '尚未计算',
}

export default function CaseFacilityComparison({ content, onSelect }: { content: Comparison; onSelect?: (assetId: number) => void }) {
  const { coverage, candidates, unresolved } = content.result
  const map = useMemo(() => facilityComparisonMapModel(content), [content])
  const [selected, setSelected] = useState<string | null>(null)
  const prefix = useId()
  const select = useCallback((id: string) => {
    setSelected(id)
    document.getElementById(`${prefix}-${id}`)?.focus({ preventScroll: true })
  }, [prefix])
  return <section aria-label="道路前置设施候选">
    <h4>道路与生产条件比较后的来源候选</h4>
    <p>召回 {coverage.recalled} 个设施，完成 {coverage.compared} 个比较，仅展示前三项。</p>
    {!coverage.complete && <p role="status">本轮资料或计算不完整，不能据此认定全域最优候选。</p>}
    <p>计算车型：{roadVehicleLabel(content.calculation.vehicle)}。不还原案发时实际通行情况。</p>
    {!candidates.length && <p>尚无可展示的道路关联候选。入口、许可或路网资料不足，不等于没有关联设施。</p>}
    {map.available ? <div aria-label="同版本候选地图">
      <p>地图编号与下方候选一致。标记为案件记录位置及可信入口，不画直线作为道路。</p>
      <Suspense fallback={<p role="status">正在加载内网候选地图…</p>}>
        <Map referencePoints={map.referencePoints} productionAssetIds={map.productionAssetIds}
          snapshotRef={map.snapshotRef} height={340} focusedReferenceId={selected} onReferencePointClick={select} />
      </Suspense>
    </div> : candidates.length > 0 && <p role="status">本附件缺少完整冻结入口坐标，候选地图暂不可用，未用当前坐标补齐。</p>}
    <ol>{candidates.map(candidate => <li key={candidate.asset_id} id={`${prefix}-${candidate.asset_id}`} tabIndex={-1}
      aria-label={`候选 ${candidate.rank}：${candidate.name}`}>
      <strong>{candidate.name}</strong> · 稳定编号 {candidate.asset_id}
      {map.available && <button type="button" aria-pressed={selected === String(candidate.asset_id)}
        onClick={() => setSelected(String(candidate.asset_id))}>地图定位</button>}
      <p>可信入口参考道路距离 {(candidate.road_distance_m / 1000).toFixed(2)} 公里；规则支持度不是准确概率。</p>
      {onSelect && <button type="button" onClick={() => onSelect(candidate.asset_id)}>展开可信入口参考路径</button>}
      <p>相对仅按直线距离排序：{candidate.rank_change_from_distance > 0 ? `前移 ${candidate.rank_change_from_distance} 位`
        : candidate.rank_change_from_distance < 0 ? `后移 ${-candidate.rank_change_from_distance} 位` : '顺序不变'}。</p>
      <ul>{candidate.supporting_evidence.map((text, i) => <li key={i}>{text}</li>)}</ul>
      <p>反向依据：{candidate.counter_evidence.join('；')}</p>
      {!!candidate.information_gaps.length && <p>资料缺口：{candidate.information_gaps.join('；')}</p>}
      <details><summary>证据引用</summary><ul>{candidate.evidence_refs.map(ref => <li key={ref}>{ref}</li>)}</ul></details>
    </li>)}</ol>
    {!!unresolved.length && <details><summary>尚未形成比较结果的设施 {unresolved.length} 个</summary>
      <ul>{unresolved.map(item => <li key={item.asset_id}>编号 {item.asset_id}：{states[item.state] || '资料待核'}，不按零分或低风险处理。</li>)}</ul>
    </details>}
    <details><summary>范围与版本</summary><p>固定地图：{content.map_snapshot_id}；算法：{content.result.algorithm_version}</p>
      <p>路网：{content.calculation.network_id}；条件时刻：{content.calculation.analysis_at}</p>
      <p>{content.boundary}</p></details>
    <p className="case-result__note">以上为待核验候选，非案件事实。</p>
  </section>
}
