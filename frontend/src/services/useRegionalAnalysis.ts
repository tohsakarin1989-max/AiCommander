import { useQuery } from '@tanstack/react-query'
import { facilityAnalysisApi } from './facilityAnalysis'
import { useRegionalContext } from './useRegionalContext'

export function useRegionalAnalysis(page = 1, pageSize = 20) {
  const context = useRegionalContext()
  const query = useQuery({ queryKey: ['facility-region', ...context.identity, context.areaId, context.startDate, context.endDate, page, pageSize],
    queryFn: ({ signal }) => facilityAnalysisApi.region({ operational_area_id: context.areaId!, start_date: context.startDate,
      end_date: context.endDate, page, page_size: pageSize }, signal),
    enabled: context.ready, retry: false, gcTime: 0, refetchInterval: 30_000 })
  const data = context.ready && !query.isError && query.data?.scope.operational_area_id === context.areaId ? query.data : undefined
  return { context, query, data }
}
