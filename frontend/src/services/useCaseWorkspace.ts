import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { caseWorkspaceApi, caseWorkspaceKey, visibleWorkspace, workspaceRefreshInterval } from './caseWorkspace'

export function useCaseWorkspace(caseId?: number) {
  const { user, sessionEpoch } = useAuth()
  const query = useQuery({
    queryKey: caseWorkspaceKey(caseId, user?.id, sessionEpoch),
    queryFn: ({ signal }) => caseWorkspaceApi.read(caseId!, signal),
    enabled: !!caseId && !!user,
    retry: false,
    gcTime: 0,
    refetchInterval: current => workspaceRefreshInterval(current.state.data),
  })
  return { ...query, workspace: visibleWorkspace(query, caseId) }
}

/** Independently loaded legacy sections retain their own availability and auth epoch. */
export function useCaseWorkspaceSection<T>(name: string, caseId: number | undefined,
  read: () => Promise<T>, enabled = true) {
  const { user, sessionEpoch } = useAuth()
  const query = useQuery({
    queryKey: [name, caseId, user?.id, sessionEpoch], queryFn: read,
    enabled: !!caseId && !!user && enabled, retry: false, gcTime: 0,
  })
  return { ...query, data: query.isError ? undefined : query.data }
}
