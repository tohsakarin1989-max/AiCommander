import api from './api'
import type { CaseResult } from '../types/caseResult'

type ModuleState = 'ready' | 'updating' | 'unavailable'
export interface CaseWorkspace {
  schema_version: 'case-workspace-5.0-1'
  generated_at: string
  case_id: number
  case: { id: number; case_number: string | null; status: string; operational_area_id: number }
  pipeline: { status: string; requested_at: string | null; completed_at: string | null }
  profile: { status: ModuleState; data: {
    id: string; version: number; schema_version: string; dictionary_version: string
    source_hash: string; created_at: string; payload: Record<string, unknown>
  } | null }
  result: { status: ModuleState; data: CaseResult | null }
  links: Record<'case' | 'analysis' | 'map' | 'evidence' | 'report', string>
  boundary: string
}

// Keep the existing invalidation prefix while isolating login/scope epochs.
export const caseWorkspaceKey = (caseId: number | undefined, userId: number | undefined, epoch: number) =>
  ['case-unified-result', caseId, 'workspace-v5', userId, epoch] as const

export function visibleWorkspace(query: { data?: CaseWorkspace; isError: boolean }, caseId: number | undefined) {
  return !query.isError && query.data?.schema_version === 'case-workspace-5.0-1'
    && query.data.case_id === caseId ? query.data : undefined
}

export function workspaceRefreshInterval(workspace?: CaseWorkspace) {
  return !workspace || ['pending', 'processing', 'degraded'].includes(workspace.pipeline.status)
    || workspace.result.status === 'updating' ? 5000 : 30000
}

export const caseWorkspaceApi = {
  read: async (caseId: number, signal?: AbortSignal): Promise<CaseWorkspace> => {
    const { data } = await api.get<CaseWorkspace>(`/cases/${caseId}/workspace`, { signal })
    if (data.schema_version !== 'case-workspace-5.0-1' || data.case_id !== caseId) {
      throw new Error('案件工作界面版本或案件引用不一致，请刷新后重试。')
    }
    return data
  },
}
