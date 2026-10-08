import { useEffect, useRef } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { materialRequestKey, resultPath, resultsApi } from '../../services/results'
import { businessContextPath } from '../../services/businessNavigation'
import type { FacilityDossierParams } from '../../services/facilityAnalysis'

export default function FacilityMaterialActions({ assetId, allowed, filters }: {
  assetId: number; allowed: boolean; filters: FacilityDossierParams
}) {
  const navigate = useNavigate()
  const location = useLocation(), [params] = useSearchParams()
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const contextPath = (target: string) => businessContextPath(target, params, location.pathname)
  const key = useRef<string | null>(null)
  const create = useMutation({ mutationFn: () => {
    key.current ??= materialRequestKey()
    return resultsApi.freezeFacility(assetId, { ...filters, idempotency_key: key.current })
  }, onSuccess: result => { if (mounted.current) navigate(contextPath(resultPath('facility', result.id))) } })
  return <div className="material-actions">
    <Link to={contextPath(`/reports?subject=facility&subjectId=${assetId}`)}>已有设施材料</Link>
    {allowed && <><Link to={contextPath(`/topics?source=facility&sourceId=${assetId}`)}>持续关注这处设施</Link>
      <Link to={contextPath(`/assistant?assetId=${assetId}`)}>带设施询问助手</Link>
      <button className="btn-ghost" disabled={create.isPending} onClick={() => create.mutate()}>{create.isPending ? '正在重新读取并冻结' : '重新读取并保存资料'}</button>
      <p>按所选条件及当前权限重新读取。新到资料可能与目前画面不同，保存后请核对固定材料；不会改写原始资料。</p></>}
    {create.error && <p role="alert">材料保存未完成，原资料未改动。相同请求可重试，不会重复留存。</p>}
  </div>
}
