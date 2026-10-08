import { useState } from 'react'
import { Alert, Button, Input } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { openFacilityDossier } from '../../services/regionalContext'
import { mapPlacesApi, publicPlaceError } from '../../services/mapPlaces'
import FacilitySearch from '../Facility/FacilitySearch'
import { facilityPoint } from '../Facility/facilitySearchPresentation'
import type { ReferencePoint } from './referencePoint'

interface Props { areaId: number | null; snapshotId?: string; onLocate: (point: ReferencePoint) => void }
export default function MapLocationSearch(props: Props) {
  const { user, sessionEpoch } = useAuth()
  return <MapLocationSearchSession key={`${user?.id}:${sessionEpoch}:${props.areaId}:${props.snapshotId}`} {...props} />
}
function MapLocationSearchSession({ areaId, snapshotId, onLocate }: Props) {
  const { user, sessionEpoch } = useAuth()
  const [input, setInput] = useState('')
  const [term, setTerm] = useState('')
  const [error, setError] = useState('')
  const query = useQuery({ queryKey: ['public-place-search', user?.id, sessionEpoch, areaId, snapshotId, term],
    queryFn: ({ signal }) => mapPlacesApi.search(snapshotId!, areaId!, term, signal),
    enabled: Boolean(user && areaId && snapshotId && term), retry: false, gcTime: 0 })
  return <details className="cases-map-card" style={{ marginBottom: 12 }}>
    <summary style={{ padding: 12 }}>查找设施或公共地名</summary>
    <div style={{ padding: 12, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 20 }}>
      <section aria-label="生产设施查找"><h3>生产设施登记目录</h3>
        <FacilitySearch areaId={areaId} requireArea actionLabel="打开档案" onChoose={asset => openFacilityDossier(asset.id)} extraAction={asset => {
          const point = facilityPoint(asset)
          return point ? <Button size="small" onClick={() => onLocate({ id: `lookup-asset:${asset.id}`, latitude: point[0], longitude: point[1], title: `当前登记设施：${asset.name}`, description: '设施查找定位，不自动建立涉案关系；登记坐标不代表已核验入口。' })}>定位登记坐标</Button> : <span>无有效登记坐标</span>
        }} />
      </section>
      <section aria-label="公共地名参考查找"><h3>公共地名参考</h3><p>仅查询当前地图版本，不代表生产设施、已核验入口或可通行终点。</p>
        <Input.Search aria-label="公共地名" placeholder="输入至少 2 个字的地名" maxLength={120} value={input} disabled={!areaId || !snapshotId}
          onChange={event => setInput(event.target.value)} enterButton="查找地名" onSearch={value => {
            const normalized = value.trim(); setError(normalized.length < 2 ? '请输入 2 至 120 个字符的地名。' : '')
            setTerm(normalized.length >= 2 ? normalized : '')
          }} />
        {!snapshotId && <p>当前地图版本暂不可读，未切换到其他版本查询。</p>}
        {error && <p role="alert">{error}</p>}
        {query.isError ? <Alert type="warning" message={publicPlaceError(query.error)} action={<Button onClick={() => void query.refetch()}>重试地名查询</Button>} /> : query.isFetching ? <p role="status">正在查找公共地名…</p> : term && query.data && <>
          {query.data.items.length ? <ul style={{ paddingLeft: 20 }}>{query.data.items.map(place => <li key={place.id} style={{ marginBlock: 10 }}>
            <span>{place.name} · 公共参考点 </span><Button size="small" disabled={!facilityPoint(place)} onClick={() => onLocate({ id: `public-place:${place.id}`, latitude: place.latitude, longitude: place.longitude, title: `公共地名参考：${place.name}`, description: '公共地名参考点，不代表已核验入口、准确地址或可通行终点。' })}>定位参考点</Button>
          </li>)}</ul> : <p>当前地图版本中没有匹配的公共地名。</p>}
          {query.data.has_more && <p>匹配超过 50 个，请补充更具体的名称缩小范围；当前并非完整列表。</p>}
        </>}
      </section>
    </div>
  </details>
}
