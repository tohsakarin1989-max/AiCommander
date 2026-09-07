import api from './api'
import type { UserRole } from './auth'

export type CaseStewardState = 'disabled' | 'unavailable' | 'ready'

export interface CaseStewardPilotUser {
  id: number
  username: string
  display_name: string
  role: UserRole
}

export interface CaseStewardMetrics {
  runs_total: number
  runs_completed: number
  runs_failed: number
  reviewed_case_count: number
  evidence_coverage_percent: number
}

export interface CaseStewardStatus {
  state: CaseStewardState
  enabled: boolean
  read_only: true
  pilot_user_ids?: number[]
  eligible_users?: CaseStewardPilotUser[]
  reason?: string | null
  updated_by?: number | null
  updated_at?: string | null
  global_mode: 'shadow' | 'assist'
  environment_ready: boolean
  current_user_authorized: boolean
  can_start: boolean
  can_apply_changes: false
  max_cases_per_run: number
  metrics: CaseStewardMetrics
}

export interface CaseStewardControlPayload {
  enabled: boolean
  pilot_user_ids: number[]
  reason: string
}

export const caseStewardApi = {
  status: async () => {
    const response = await api.get<CaseStewardStatus>('/agent-case-steward/status')
    return response.data
  },
  updateControl: async (payload: CaseStewardControlPayload) => {
    const response = await api.put<CaseStewardStatus>('/agent-case-steward/control', payload)
    return response.data
  },
  suspend: async (reason: string) => {
    const response = await api.post<CaseStewardStatus>('/agent-case-steward/suspend', { reason })
    return response.data
  },
}
