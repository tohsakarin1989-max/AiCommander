/**
 * 相似条件组分析 API
 * 类型定义统一从 types/ 导入
 */
import api from './api'
import type {
  GangProfile,
  GangAnalysisRequest,
  TimelineEntry,
  GangRelations,
  GangStatistics,
} from '../types'

export const gangApi = {
  /**
   * 识别相似条件组
   */
  identify: async (request?: GangAnalysisRequest): Promise<GangProfile[]> => {
    const response = await api.post<GangProfile[]>('/gangs/identify', request || {})
    return response.data
  },

  /**
   * 快速识别相似条件组
   */
  quickIdentify: async (params?: {
    min_similarity?: number
    min_cases?: number
    time_window_days?: number
  }): Promise<{ total_gangs: number; gangs: GangProfile[] }> => {
    const response = await api.get('/gangs/quick-identify', { params })
    return response.data
  },

  /**
   * 获取条件组关系图
   */
  getRelations: async (gangIndex: number, params?: {
    min_similarity?: number
    min_cases?: number
    time_window_days?: number
  }): Promise<GangRelations> => {
    const response = await api.get(`/gangs/${gangIndex}/relations`, { params })
    return response.data
  },

  /**
   * 获取条件组时间线
   */
  getTimeline: async (caseIds: number[]): Promise<TimelineEntry[]> => {
    const response = await api.post<TimelineEntry[]>('/gangs/timeline', caseIds)
    return response.data
  },

  /**
   * 获取条件组统计数据
   */
  getStatistics: async (timeWindowDays?: number): Promise<GangStatistics> => {
    const response = await api.get('/gangs/statistics', {
      params: { time_window_days: timeWindowDays },
    })
    return response.data
  },

  /**
   * 获取条件组案件时段热力图（7天×24小时矩阵）
   */
  getActivityHeatmap: async (
    gangIndex: number,
    request?: GangAnalysisRequest,
  ): Promise<{
    matrix: number[][]
    peak_cell: { weekday: number; hour: number; count: number }
    total_cases: number
    day_totals: number[]
    hour_totals: number[]
  }> => {
    const response = await api.post(`/gangs/${gangIndex}/activity-heatmap`, request || {})
    return response.data
  },

  /**
   * 兼容旧接口：同人同车不再推断为跨组关系
   */
  getCrossGangPersons: async (
    request?: GangAnalysisRequest,
  ): Promise<Array<{
    person_name: string
    gang_indices: number[]
    gang_count: number
    role: string
  }>> => {
    const response = await api.post('/gangs/cross-gang-persons', request || {})
    return response.data
  },
}
