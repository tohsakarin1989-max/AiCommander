import LeafletMap from '../../components/Map/LeafletMap'
import type { BusinessAnswerMapContext } from '../../services/intelligentQueries'
import { businessMapValid, pointRoles } from './businessAnswerMapModel'

export default function BusinessAnswerMap({ value }: { value: BusinessAnswerMapContext }) {
  if (!businessMapValid(value)) return <p role="alert">冻结地图结构不完整，未改用当前地图。</p>
  return <section aria-label="回答同源地图"><p>{value.boundary}</p>
    <p>仅显示本回答冻结的 {value.coverage.shown} 个明确点位{value.coverage.truncated ? '（展示已限额，统计范围未截断）' : ''}。</p>
    {value.snapshots.map(snapshot => {
      const points = value.points.filter(row => row.map_snapshot_id === snapshot.id)
      if (!points.length) return null
      return <div key={snapshot.id}><p>区域 {snapshot.area_id} · 地图版本 {snapshot.version} · {snapshot.id}</p>
        <LeafletMap operationalAreaId={snapshot.area_id} snapshotRef={snapshot.id} height={320} productionAssetIds={[]}
          referencePoints={points.map((row, index) => ({ id: `${row.kind}:${row.object_id}:${row.role}:${index}`,
            latitude: row.latitude, longitude: row.longitude, title: `${row.label} · ${pointRoles[row.role]}`,
            description: row.evidence_refs.join('；') }))} />
      </div>
    })}
    <ul>{value.information_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>
  </section>
}
