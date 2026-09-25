import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { authApi } from './auth'
import { parseRegionalContext, writeRegionalContext, type RegionalSelection } from './regionalContext'

export function useRegionalContext() {
  const [params, setParams] = useSearchParams()
  const { user, sessionEpoch } = useAuth()
  const context = parseRegionalContext(params)
  const scopes = useQuery({ queryKey: ['my-area-scopes', user?.id, sessionEpoch], queryFn: authApi.myAreaScopes,
    staleTime: 0, refetchInterval: 30_000 })
  const available = scopes.isError ? [] : scopes.data ?? []
  const authorized = context.areaId != null && available.some(item => item.operational_area_id === context.areaId)
  const error = context.error || (scopes.isError ? '无法确认当前授权范围，请重试。'
    : scopes.isSuccess && context.areaId != null && !authorized ? '当前辖区不可访问，未切换到其他辖区。' : undefined)
  useEffect(() => {
    if (context.areaId == null && !context.error && !params.has('operational_area_id') && available.length) {
      const preferred = available.find(item => item.is_default) ?? available[0]
      setParams(previous => writeRegionalContext(previous, { operational_area_id: preferred.operational_area_id,
        assetId: context.assetId, eventId: context.eventId, caseId: context.caseId }), { replace: true })
    }
  }, [context.areaId, context.error, available, params, setParams])
  const update = (changes: RegionalSelection) => setParams(previous => writeRegionalContext(previous, changes))
  return { ...context, error, params, update, scopes: available, ready: authorized && !error,
    identity: [user?.id, sessionEpoch], user, sessionEpoch, refetchScopes: scopes.refetch }
}
