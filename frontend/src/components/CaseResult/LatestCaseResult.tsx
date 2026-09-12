import { Link } from 'react-router-dom'
import { useCaseWorkspace } from '../../services/useCaseWorkspace'
import CaseResultPanel from './CaseResultPanel'
import CaseResultMap from './CaseResultMap'
import CaseEvaluationArchive from './CaseEvaluationArchive'
import { useAuth } from '../../auth/AuthContext'
import { agentLabEnabled } from '../../config/features'

/** Read-only shared result; never triggers analysis or assembles a second report. */
export default function LatestCaseResult({ caseId }: { caseId: number }) {
  const { user } = useAuth()
  const query = useCaseWorkspace(caseId)
  const result = query.workspace?.result.data ?? undefined
  return <CaseResultPanel key={caseId} caseId={caseId} result={result}
    loading={query.isPending} error={query.isError}
    errorStatus={(query.error as { status?: number } | null)?.status}
    map={result && <CaseResultMap result={result} />}
    footer={result && <>
      <Link to={`/reports?resultId=${encodeURIComponent(result.id)}`}>在报告中心查看此版本</Link>
      {user?.role === 'admin' && agentLabEnabled && !query.isError
        && result.freshness !== 'pending_update' && result.content.versions.map_snapshot_id
        && <CaseEvaluationArchive key={result.id} result={result} refreshing={query.isFetching} />}
    </>} />
}
