import api from './api'
import type { CaseResult } from '../types/caseResult'
import type { CaseProfile, CaseProcessingCard, CaseAutomationWorkbench } from '../types'
import type { CaseSemantics } from './intelligenceFlow'

type ModuleState = 'ready' | 'updating' | 'unavailable'
export interface CaseWorkspace {
  schema_version: 'case-workspace-5.0-1' | 'case-workspace-6.0-1'
  generated_at: string
  case_id: number
  case: { id: number; case_number: string | null; status: string; operational_area_id: number }
  pipeline: { status: string; requested_at: string | null; completed_at: string | null }
  profile: { status: ModuleState; data: {
    id: string; version: number; schema_version: string; dictionary_version: string
    source_hash: string; created_at: string; payload: Record<string, unknown> & { semantics?: CaseSemantics }
  } | null }
  result: { status: ModuleState; data: CaseResult | null }
  detail_profile?: { status: ModuleState; data: CaseProfile | null }
  processing_card?: { status: ModuleState; data: CaseProcessingCard | null }
  automation_workbench?: { status: ModuleState; data: CaseAutomationWorkbench | null }
  diagram?: { status: ModuleState; data: { nodes: unknown[]; edges: unknown[] } | null }
  links: Record<'case' | 'analysis' | 'map' | 'evidence' | 'report', string>
  boundary: string
}

// Keep the existing invalidation prefix while isolating login/scope epochs.
export const caseWorkspaceKey = (caseId: number | undefined, userId: number | undefined, epoch: number) =>
  ['case-unified-result', caseId, 'workspace-v5', userId, epoch] as const

export function visibleWorkspace(query: { data?: CaseWorkspace; isError: boolean }, caseId: number | undefined) {
  return !query.isError && query.data && ['case-workspace-5.0-1', 'case-workspace-6.0-1'].includes(query.data.schema_version)
    && query.data.case_id === caseId ? query.data : undefined
}

export function workspaceRefreshInterval(workspace?: CaseWorkspace, updateCount = 0, hidden = false, failed = false): number | false {
  if (failed || hidden || updateCount >= 13) return false
  const pending = !workspace || ['pending', 'processing', 'degraded'].includes(workspace.pipeline.status)
    || workspace.result.status === 'updating' || workspace.result.data?.composition_status === 'road_not_ready'
  return pending ? 10000 : false
}

export const caseWorkspaceApi = {
  read: async (caseId: number, signal?: AbortSignal): Promise<CaseWorkspace> => {
    const { data } = await api.get<CaseWorkspace>(`/cases/${caseId}/workspace`, { signal })
    if (!['case-workspace-5.0-1', 'case-workspace-6.0-1'].includes(data.schema_version) || data.case_id !== caseId) {
      throw new Error('案件工作界面版本或案件引用不一致，请刷新后重试。')
    }
    return data
  },
}
