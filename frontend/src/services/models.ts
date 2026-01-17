import api from './api'
import type { ModelProvider, ModelRole } from '../types'

export interface AIModelConfig {
  temperature?: number
  max_tokens?: number
  api_base?: string
  specialty?: string
  [key: string]: unknown
}

export interface AIModel {
  id: number
  name: string
  provider: ModelProvider
  model_name: string
  role: ModelRole
  is_active: boolean
  is_default: boolean
  config?: AIModelConfig
  description?: string
  created_at?: string
}

export interface ModelCreate {
  name: string
  provider: ModelProvider
  model_name: string
  api_key: string
  role?: ModelRole
  config?: AIModelConfig
  description?: string
}

export interface ModelUpdate {
  name?: string
  provider?: ModelProvider
  model_name?: string
  api_key?: string
  role?: ModelRole
  is_active?: boolean
  config?: AIModelConfig
  description?: string
}

export interface ModelTestResult {
  success: boolean
  message: string
  latency_ms?: number
}

export const modelApi = {
  /**
   * 获取模型列表
   */
  getModels: async (role?: ModelRole): Promise<AIModel[]> => {
    const params = role ? { role } : {}
    const response = await api.get<AIModel[]>('/models', { params })
    return response.data
  },

  /**
   * 获取模型详情
   */
  getModel: async (id: number): Promise<AIModel> => {
    const response = await api.get<AIModel>(`/models/${id}`)
    return response.data
  },

  /**
   * 创建模型
   */
  createModel: async (data: ModelCreate): Promise<AIModel> => {
    const response = await api.post<AIModel>('/models', data)
    return response.data
  },

  /**
   * 更新模型
   */
  updateModel: async (id: number, data: ModelUpdate): Promise<AIModel> => {
    const response = await api.put<AIModel>(`/models/${id}`, data)
    return response.data
  },

  /**
   * 删除模型
   */
  deleteModel: async (id: number): Promise<void> => {
    await api.delete(`/models/${id}`)
  },

  /**
   * 设置为默认主持人模型
   */
  setDefaultModerator: async (id: number): Promise<void> => {
    await api.post(`/models/${id}/set-default`)
  },

  /**
   * 测试模型连接
   */
  testModel: async (id: number): Promise<ModelTestResult> => {
    const response = await api.post<ModelTestResult>(`/models/${id}/test`)
    return response.data
  },
}
