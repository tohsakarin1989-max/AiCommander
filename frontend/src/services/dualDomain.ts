import api from './api'
import type { UserRole } from './auth'

export type DualDomainState = 'disabled' | 'unavailable' | 'ready'

export interface DualDomainPilotUser {
  id: number
  username: string
  display_name: string
  role: UserRole
}

export interface DualDomainMetrics {
  runs_total: number
  runs_completed: number
  runs_failed: number
  report_count: number
  analyzed_case_count: number
  analyzed_asset_count: number
  evidence_coverage_percent: number
}

export interface DualDomainStatus {
  state: DualDomainState
  enabled: boolean
  read_only: true
  pilot_user_ids?: number[]
  eligible_users?: DualDomainPilotUser[]
  reason?: string | null
  updated_by?: number | null
  updated_at?: string | null
  global_mode: 'shadow' | 'assist'
  environment_ready: boolean
  current_user_authorized: boolean
  can_start: boolean
  can_apply_changes: false
  max_cases_per_run: number
  max_assets_per_run: number
  metrics: DualDomainMetrics
}

export interface DualDomainControlPayload {
  enabled: boolean
  pilot_user_ids: number[]
  reason: string
}

export const dualDomainApi = {
  status: async () => {
    const response = await api.get<DualDomainStatus>('/agent-dual-domain/status')
    return response.data
  },
  updateControl: async (payload: DualDomainControlPayload) => {
    const response = await api.put<DualDomainStatus>('/agent-dual-domain/control', payload)
    return response.data
  },
  suspend: async (reason: string) => {
    const response = await api.post<DualDomainStatus>('/agent-dual-domain/suspend', { reason })
    return response.data
  },
}
