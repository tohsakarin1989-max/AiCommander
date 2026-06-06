import api from './api'
import type { LlmContextPack, StructuredAiOutput } from './caseIntelligence'

export interface AutomationAlert {
  id: number
  alert_number: string
  source_system: string
  alert_type: string
  title: string
  description?: string | null
  level: string
  risk_level: string
  occurred_time: string
  location?: string | null
  latitude?: number | null
  longitude?: number | null
  facility_id?: string | null
  facility_name?: string | null
  parameter_snapshot?: Record<string, unknown> | null
  sensing_summary?: Record<string, unknown> | null
  ai_assessment?: Record<string, unknown> | null
  suggested_actions?: string[] | null
  status: string
  handling_result?: string | null
  review_notes?: string | null
  is_simulated?: boolean | null
  related_event_id?: number | null
  related_case_id?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export interface AutomationAlertTriagePack {
  alert: {
    id: number
    alert_number: string
    title: string
    status: string
    risk_level: string
    related_event_id?: number | null
    related_case_id?: number | null
  }
  facts: string[]
  triage_assessment: {
    result: string
    confidence?: number | null
    basis: string[]
  }
  information_gaps: string[]
  recommended_next_steps: string[]
  related_event?: {
    id: number
    event_number: string
    handling_result?: string | null
  } | null
  related_case_context?: LlmContextPack | null
  boundary: string[]
  ai_output?: StructuredAiOutput
}

export const automationAlertApi = {
  list: async (params?: { status?: string; limit?: number }): Promise<AutomationAlert[]> => {
    const response = await api.get('/automation-alerts/', { params })
    return response.data
  },

  seedSimulated: async (): Promise<AutomationAlert[]> => {
    const response = await api.post('/automation-alerts/simulated')
    return response.data
  },

  ensureEvent: async (alertId: number): Promise<{ alert_id: number; event_id: number; message: string }> => {
    const response = await api.post(`/automation-alerts/${alertId}/event`)
    return response.data
  },

  markFalseAlarm: async (alertId: number, note?: string): Promise<AutomationAlert> => {
    const response = await api.post(`/automation-alerts/${alertId}/false-alarm`, { note })
    return response.data
  },

  convertToCase: async (alertId: number): Promise<{
    alert_id: number
    event_id: number
    case_id: number
    message: string
  }> => {
    const response = await api.post(`/automation-alerts/${alertId}/convert-to-case`)
    return response.data
  },

  getTriagePack: async (alertId: number): Promise<AutomationAlertTriagePack> => {
    const response = await api.get(`/automation-alerts/${alertId}/triage-pack`)
    return response.data
  },
}
