import api from './api'

export interface RuntimeStatus {
  status: 'ready' | 'degraded'
  database: 'sqlite' | 'postgresql' | string
  redis: 'ok' | 'unavailable'
  active_model_count: number
  map_provider: string
  map_configured: boolean
  version: string
}

export const runtimeApi = {
  status: async () => {
    const response = await api.get<RuntimeStatus>('/runtime/status')
    return response.data
  },
}
