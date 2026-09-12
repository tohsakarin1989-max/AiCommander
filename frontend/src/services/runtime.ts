import api from './api'

export interface RuntimeFeatures {
  legacy_operations: boolean
  bonus_accounting: boolean
  agent_lab: boolean
  showcase: boolean
}

export interface RuntimeStatus {
  status: 'ready' | 'degraded'
  database: 'sqlite' | 'postgresql' | string
  redis: 'ok' | 'unavailable'
  active_model_count: number
  map_provider: string
  map_configured: boolean
  version: string
  features: RuntimeFeatures
}

export const runtimeApi = {
  status: async () => {
    const response = await api.get<RuntimeStatus>('/runtime/status')
    return response.data
  },
}
