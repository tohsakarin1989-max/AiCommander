import { useRef } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { materialRequestKey, resultPath, resultsApi } from '../../services/results'

export default function FacilityMaterialActions({ assetId, allowed, filters }: {
  assetId: number; allowed: boolean; filters: { start_date?: string; end_date?: string; valid_at?: string; known_at?: string }
}) {
  const navigate = useNavigate()
  const key = useRef<string | null>(null)
  const create = useMutation({ mutationFn: () => {
    key.current ??= materialRequestKey()
    return resultsApi.freezeFacility(assetId, { ...filters, idempotency_key: key.current })
  }, onSuccess: result => navigate(resultPath('facility', result.id)) })
  return <div className="material-actions">
    <Link to={`/reports?subject=facility&subjectId=${assetId}`}>已有设施材料</Link>
    {allowed && <><Link to={`/topics?source=facility&sourceId=${assetId}`}>持续关注这处设施</Link>
      <Link to={`/assistant?assetId=${assetId}`}>带设施询问助手</Link>
      <button className="btn-ghost" disabled={create.isPending} onClick={() => create.mutate()}>{create.isPending ? '正在冻结资料' : '保存本次资料为材料'}</button></>}
    {create.error && <p role="alert">材料保存未完成，原资料未改动。相同请求可重试，不会重复留存。</p>}
  </div>
}
