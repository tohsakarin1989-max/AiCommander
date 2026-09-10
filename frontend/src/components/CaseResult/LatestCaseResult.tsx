import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { caseResultsApi } from '../../services/caseResults'
import CaseResultPanel from './CaseResultPanel'
import CaseResultMap from './CaseResultMap'

/** Read-only shared result; never triggers analysis or assembles a second report. */
export default function LatestCaseResult({ caseId }: { caseId: number }) {
  const query = useQuery({
    queryKey: ['case-unified-result', caseId],
    queryFn: () => caseResultsApi.latest(caseId),
    retry: false,
    gcTime: 0,
    refetchInterval: query => !query.state.data || query.state.data.freshness === 'pending_update'
      || query.state.data.content.analysis_status === 'not_generated' ? 5000 : 30000,
  })
  return <CaseResultPanel key={caseId} caseId={caseId} result={query.data}
    loading={query.isPending} error={query.isError}
    errorStatus={(query.error as { status?: number } | null)?.status}
    map={query.data && <CaseResultMap result={query.data} />}
    footer={query.data && <Link to={`/reports?resultId=${encodeURIComponent(query.data.id)}`}>在报告中心查看此版本</Link>} />
}
