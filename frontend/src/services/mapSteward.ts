import api from './api'
import type { UserRole } from './auth'

export type MapStewardState = 'disabled' | 'suspended' | 'read_only' | 'ready'

export interface MapStewardPilotUser {
  id: number
  username: string
  display_name: string
  role: UserRole
}

export interface MapStewardMetrics {
  runs_total: number
  runs_completed: number
  runs_failed: number
  candidate_count: number
  pending_approval_count: number
  executed_approval_count: number
  rejected_approval_count: number
  adoption_rate_percent: number
  evidence_coverage_percent: number
}

export interface MapStewardStatus {
  state: MapStewardState
  enabled: boolean
  mutations_suspended: boolean
  pilot_user_ids?: number[]
  eligible_users?: MapStewardPilotUser[]
  reason?: string | null
  updated_by?: number | null
  updated_at?: string | null
  global_mode: 'shadow' | 'assist'
  environment_ready: boolean
  current_user_authorized: boolean
  can_start: boolean
  can_apply_changes: boolean
  max_assets_per_run: number
  metrics: MapStewardMetrics
}

export interface MapStewardControlPayload {
  enabled: boolean
  mutations_suspended: boolean
  pilot_user_ids: number[]
  reason: string
}

export const mapStewardApi = {
  status: async () => {
    const response = await api.get<MapStewardStatus>('/agent-map-steward/status')
    return response.data
  },
  updateControl: async (payload: MapStewardControlPayload) => {
    const response = await api.put<MapStewardStatus>('/agent-map-steward/control', payload)
    return response.data
  },
  suspend: async (reason: string) => {
    const response = await api.post<MapStewardStatus>('/agent-map-steward/suspend', { reason })
    return response.data
  },
}
