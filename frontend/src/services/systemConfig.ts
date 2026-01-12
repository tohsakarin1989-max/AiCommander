import api from './api'

export interface SystemConfig {
  id: number
  config_key: string
  config_value: string
  config_type: string
  category: string
  description?: string
  extra_data?: any
  created_at: string
  updated_at?: string
}

export interface ConfigCreate {
  config_key: string
  config_value: string
  config_type?: string
  category?: string
  description?: string
  extra_data?: any
}

export interface ConfigUpdate {
  config_value?: string
  config_type?: string
  category?: string
  description?: string
  extra_data?: any
}

export const systemConfigApi = {
  getConfigs: async (category?: string): Promise<SystemConfig[]> => {
    const params = category ? { category } : {}
    const response = await api.get('/system-config', { params })
    return response.data
  },

  getConfig: async (configKey: string): Promise<SystemConfig> => {
    const response = await api.get(`/system-config/${configKey}`)
    return response.data
  },

  createConfig: async (data: ConfigCreate): Promise<SystemConfig> => {
    const response = await api.post('/system-config', data)
    return response.data
  },

  updateConfig: async (configKey: string, data: ConfigUpdate): Promise<SystemConfig> => {
    const response = await api.put(`/system-config/${configKey}`, data)
    return response.data
  },

  deleteConfig: async (configKey: string): Promise<void> => {
    await api.delete(`/system-config/${configKey}`)
  },

  initDefaults: async (): Promise<{ message: string }> => {
    const response = await api.post('/system-config/init-defaults')
    return response.data
  },

  getMapConfig: async (): Promise<{
    provider: string
    api_key: string
    api_base_url: string
  }> => {
    const response = await api.get('/system-config/map/config')
    return response.data
  },

  getMeetingConfig: async (): Promise<{
    provider: string
    api_key: string
    api_base_url: string
  }> => {
    const response = await api.get('/system-config/meeting/config')
    return response.data
  },
}

