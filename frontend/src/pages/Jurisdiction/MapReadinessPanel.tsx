import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { facilityAnalysisApi, type MapReadiness } from '../../services/facilityAnalysis'
import { useRegionalContext } from '../../services/useRegionalContext'
import { openFacilityDossier } from '../../services/regionalContext'
import { ComputabilityContent } from '../../components/Facility/FacilityIdentityPanel'
import '../../components/Facility/FacilityAnalysis.css'

export function visibleReadiness(query: { data?: MapReadiness; isError: boolean }, areaId: number, page: number) {
  return !query.isError && query.data?.context.operational_area_id === areaId && query.data.page === page ? query.data : undefined
}

export function readinessDimensions(checks: MapReadiness['items'][number]['checks']) {
  const ready = (keys: string[]) => keys.every(key => checks.some(check => check.key === key && check.state === 'ready'))
  return [
    { name: '地图显示', ready: ready(['snapshot']), description: ready(['snapshot']) ? '已有发布快照；尚未验证瓦片服务和断网打开' : '没有确认的适用发布快照' },
    { name: '生产资料', ready: ready(['source', 'history']), description: ready(['source', 'history']) ? '来源与资料时点适用；不代表全部生产属性齐全' : '来源或业务有效时点待核' },
    { name: '道路计算', ready: ready(['entrance', 'connection', 'passage', 'network', 'graph_connection']), description: '核对入口、连接、许可和路网；条件齐备也不等于已实际计算可达' },
  ]
}

function MapReadinessScope({ areaId, userId, sessionEpoch }: { areaId: number; userId?: number; sessionEpoch: number }) {
  const [page, setPage] = useState(1)
  const query = useQuery({ queryKey: ['map-readiness', userId, sessionEpoch, areaId, page],
    queryFn: ({ signal }) => facilityAnalysisApi.readiness({ operational_area_id: areaId, page, page_size: 10 }, signal), retry: false, staleTime: 0, gcTime: 0 })
  const data = visibleReadiness(query, areaId, page)
  return <>
    <div className="facility-readiness-links"><a href="#map-source-management">维护来源与生产台账</a><a href="#internal-road-management">维护道路与入口</a><a href="#offline-map-management">查看离线地图版本</a></div>
    {query.isError ? <p role="alert">计算准备清单读取失败，不能据此判断资料齐全；未展示旧缓存。</p>
      : query.isPending ? <p role="status">正在核对入口、路网、许可与资料有效期…</p>
      : !data ? <p role="alert">清单范围或分页不一致，已停止展示。</p>
      : <>
        <p>当前授权范围共 {data.total} 个设施。{data.boundary}</p>
        <p>以下三类状态分别判断；当前页检查 {data.items.length} / {data.total} 个授权设施，不把本页比例当成全域覆盖。</p>
        {!data.items.length ? <p>本页没有可列出的设施，未将其解释为全域资料就绪。</p> : <ul className="map-readiness-list">{data.items.map(item => <li key={item.asset_id}>
          <div><strong>{item.name}</strong><span>设施编号 {item.asset_id}</span><button className="btn-ghost" onClick={() => openFacilityDossier(item.asset_id)}>打开设施档案</button></div>
          <dl>{readinessDimensions(item.checks).map(dimension => <div key={dimension.name}><dt>{dimension.name}：{dimension.ready ? '登记条件具备' : '条件未齐'}</dt><dd>{dimension.description}</dd></div>)}</dl>
          <details><summary>{item.state === 'ready' ? '资料就绪' : item.state === 'partial' ? '部分资料待补充' : '缺少计算资料'}，查看各项核对结果</summary>
            <ComputabilityContent data={{ state: item.state, checks: item.checks, boundary: '' }} />
          </details>
        </li>)}</ul>}
      </>}
    <div className="regional-pagination"><button className="btn-ghost" onClick={() => void query.refetch()} disabled={query.isFetching}>刷新准备清单</button>
      <button className="btn-ghost" disabled={page <= 1 || query.isFetching} onClick={() => setPage(current => current - 1)}>上一页</button>
      <span>第 {page} 页</span><button className="btn-ghost" disabled={!data || query.isFetching || page * data.page_size >= data.total} onClick={() => setPage(current => current + 1)}>下一页</button></div>
  </>
}

export default function MapReadinessPanel() {
  const context = useRegionalContext()
  if (context.user?.role !== 'admin') return null
  return <section className="map-readiness-panel" aria-label="地图计算准备清单"><h2>地图计算准备清单</h2>
    <p>按已登记设施核对资料，不以地图能显示或直线接近代替实际道路可达。</p>
    <label className="facility-readiness-area">查看辖区<select value={context.areaId ?? ''} onChange={event => context.update({ operational_area_id: Number(event.target.value) })}>
      {!context.scopes.length && <option value="">暂无可确认的辖区</option>}
      {context.scopes.map(item => <option key={item.operational_area_id} value={item.operational_area_id}>{item.area_name}</option>)}
    </select></label>
    {context.error ? <p role="alert">{context.error}</p> : context.ready && context.areaId != null
      ? <MapReadinessScope key={`${context.user?.id}:${context.areaId}:${context.sessionEpoch}`} areaId={context.areaId} userId={context.user?.id} sessionEpoch={context.sessionEpoch} />
      : <p role="status">正在确认授权范围，尚未发起资料核对。</p>}
  </section>
}
