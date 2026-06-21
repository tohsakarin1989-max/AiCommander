/**
 * 系统配置服务
 * 合并：AI 模型配置、系统参数配置
 * 类型定义统一从 types/ 导入
 */
import api from './api'
import type {
  AIModel,
  SystemConfig,
  ModelCreate,
  ModelUpdate,
  ModelTestResult,
} from '../types'

// ==================== API 实现 ====================

export const configApi = {
  // ---------- AI 模型 ----------
  models: {
    /** 获取模型列表 */
    list: async (role?: string) => {
      const response = await api.get<AIModel[]>('/models', { params: { role } })
      return response.data
    },

    /** 获取单个模型 */
    get: async (id: number) => {
      const response = await api.get<AIModel>(`/models/${id}`)
      return response.data
    },

    /** 创建模型 */
    create: async (data: ModelCreate) => {
      const response = await api.post<AIModel>('/models', data)
      return response.data
    },

    /** 更新模型 */
    update: async (id: number, data: ModelUpdate) => {
      const response = await api.put<AIModel>(`/models/${id}`, data)
      return response.data
    },

    /** 删除模型 */
    delete: async (id: number) => {
      await api.delete(`/models/${id}`)
    },

    /** 测试模型连接 */
    test: async (id: number) => {
      const response = await api.post<ModelTestResult>(`/models/${id}/test`)
      return response.data
    },

    /** 设为默认主持人模型 */
    setDefaultModerator: async (id: number) => {
      const response = await api.post<AIModel>(`/models/${id}/set-default`)
      return response.data
    },
  },

  // ---------- 系统参数 ----------
  system: {
    /** 获取配置列表 */
    list: async (category?: string) => {
      const response = await api.get<SystemConfig[]>('/system-config', {
        params: { category },
      })
      return response.data
    },

    /** 获取单个配置 */
    get: async (key: string) => {
      const response = await api.get<SystemConfig>(`/system-config/${key}`)
      return response.data
    },

    /** 更新配置 */
    update: async (key: string, data: { config_value: string }) => {
      const response = await api.put<SystemConfig>(`/system-config/${key}`, data)
      return response.data
    },

    /** 初始化默认配置 */
    initDefaults: async () => {
      const response = await api.post('/system-config/init-defaults')
      return response.data
    },

    /** 获取地图配置 */
    getMapConfig: async () => {
      const response = await api.get<SystemConfig[]>('/system-config/map/config')
      return response.data
    },

    /** 获取会议配置 */
    getMeetingConfig: async () => {
      const response = await api.get<SystemConfig[]>('/system-config/meeting/config')
      return response.data
    },
  },
}

// 向后兼容
export const modelApi = {
  getModels: configApi.models.list,
  getModel: configApi.models.get,
  createModel: configApi.models.create,
  updateModel: configApi.models.update,
  deleteModel: configApi.models.delete,
  testModel: configApi.models.test,
  setDefaultModerator: configApi.models.setDefaultModerator,
}

export const systemConfigApi = {
  getConfigs: configApi.system.list,
  getConfig: configApi.system.get,
  updateConfig: configApi.system.update,
  initDefaults: configApi.system.initDefaults,
}
