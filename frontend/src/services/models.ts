import api from './api'

export interface AIModel {
  id: number
  name: string
  provider: string
  model_name: string
  role: 'moderator' | 'analyst'
  is_active: boolean
  is_default: boolean
  config: {
    temperature?: number
    max_tokens?: number
    api_base?: string
    [key: string]: any
  }
  description?: string
}

export interface ModelCreate {
  name: string
  provider: string
  model_name: string
  api_key: string
  role: string
  config?: {
    temperature?: number
    max_tokens?: number
    api_base?: string
    [key: string]: any
  }
  description?: string
}

export const modelApi = {
  getModels: async (role?: string): Promise<AIModel[]> => {
    const params = role ? { role } : {}
    const response = await api.get('/models', { params })
    return response.data
  },

  getModel: async (id: number): Promise<AIModel> => {
    const response = await api.get(`/models/${id}`)
    return response.data
  },

  createModel: async (data: ModelCreate): Promise<AIModel> => {
    const response = await api.post('/models', data)
    return response.data
  },

  updateModel: async (id: number, data: Partial<AIModel>): Promise<AIModel> => {
    const response = await api.put(`/models/${id}`, data)
    return response.data
  },

  deleteModel: async (id: number): Promise<void> => {
    await api.delete(`/models/${id}`)
  },

  setDefaultModerator: async (id: number): Promise<void> => {
    await api.post(`/models/${id}/set-default`)
  },

  testModel: async (id: number): Promise<{ success: boolean; message: string }> => {
    const response = await api.post(`/models/${id}/test`)
    return response.data
  },
}

