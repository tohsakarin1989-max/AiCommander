import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { resultsApi, type ResultMaterial } from '../../services/results'
import CaseResultMap from '../../components/CaseResult/CaseResultMap'
import type { CaseResult } from '../../types/caseResult'

export default function MaterialMap({ material, identity }: { material: ResultMaterial; identity: string }) {
  const [url, setUrl] = useState('')
  const map = useQuery({ queryKey: ['material-map', identity, material.kind, material.id, material.content_sha256],
    queryFn: ({ signal }) => resultsApi.mapImage(material, signal), enabled: material.map?.state === 'available', retry: false, gcTime: 0 })
  useEffect(() => {
    if (!map.data || map.error) { setUrl(''); return }
    const image = URL.createObjectURL(map.data); setUrl(image)
    return () => URL.revokeObjectURL(image)
  }, [map.data, map.error])
  if (material.kind === 'case' && material.body.content) return <CaseResultMap result={material.body as unknown as CaseResult} />
  if (!material.map) return null
  return <section aria-label="同源冻结地图"><h2>同源地图</h2>
    {material.map.state !== 'available' ? <p>{material.map.reason || '没有可用的唯一冻结地图，未使用当前地图代替。'}</p>
      : map.error ? <p role="alert">同版地图暂不可读，未换成当前地图。<button className="btn-ghost" onClick={() => void map.refetch()}>重试地图</button></p>
        : url ? <><img src={url} alt="当前材料固定版本的点位与地图，不表示实际行驶轨迹" style={{ width: '100%', height: 'auto' }} /><p>地图版本：{material.map.map_snapshot_id}；与本版导出使用相同输入。</p></>
          : <p role="status">正在读取固定地图…</p>}
  </section>
}
