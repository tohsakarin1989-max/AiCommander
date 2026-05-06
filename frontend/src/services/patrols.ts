/**
 * 巡逻服务 API
 * 类型定义统一从 types/ 导入
 */
import api from './api'
import type { PatrolRecord, PatrolCreate, PatrolComplete, AreaRisk, CaseDrivenPatrolPlan } from '../types'

export const patrolApi = {
  /**
   * 创建巡逻计划
   */
  create: async (data: PatrolCreate): Promise<PatrolRecord> => {
    const response = await api.post<PatrolRecord>('/patrols', data)
    return response.data
  },

  /**
   * 获取巡逻记录列表
   */
  list: async (params?: {
    skip?: number
    limit?: number
    status?: string
    area_name?: string
  }): Promise<PatrolRecord[]> => {
    const response = await api.get<PatrolRecord[]>('/patrols', { params })
    return response.data
  },

  /**
   * 获取单个巡逻记录
   */
  get: async (id: number): Promise<PatrolRecord> => {
    const response = await api.get<PatrolRecord>(`/patrols/${id}`)
    return response.data
  },

  /**
   * 开始巡逻
   */
  start: async (id: number): Promise<PatrolRecord> => {
    const response = await api.post<PatrolRecord>(`/patrols/${id}/start`)
    return response.data
  },

  /**
   * 完成巡逻
   */
  complete: async (id: number, data: PatrolComplete): Promise<PatrolRecord> => {
    const response = await api.post<PatrolRecord>(`/patrols/${id}/complete`, data)
    return response.data
  },

  /**
   * 取消巡逻
   */
  cancel: async (id: number): Promise<PatrolRecord> => {
    const response = await api.post<PatrolRecord>(`/patrols/${id}/cancel`)
    return response.data
  },

  /**
   * 获取区域风险列表
   */
  getAreaRisks: async (params?: {
    skip?: number
    limit?: number
    min_risk?: number
  }): Promise<AreaRisk[]> => {
    const response = await api.get<AreaRisk[]>('/patrols/areas/risks', { params })
    return response.data
  },

  /**
   * 获取指定区域风险
   */
  getAreaRisk: async (areaName: string): Promise<AreaRisk & { area_name: string }> => {
    const response = await api.get(`/patrols/areas/${encodeURIComponent(areaName)}/risk`)
    return response.data
  },

  /**
   * 刷新所有区域风险评分
   */
  refreshAreaRisks: async (): Promise<{ message: string }> => {
    const response = await api.post('/patrols/areas/refresh-risks')
    return response.data
  },

  /**
   * 获取智能巡逻时段建议（基于历史案件时间分布动态计算）
   */
  getSmartSchedule: async (days?: number): Promise<{
    recommended_windows: Array<{
      start_hour: number
      end_hour: number
      label: string
      case_count: number
      percentage: number
      risk_level: 'high' | 'medium' | 'low'
    }>
    weekday_priority: Array<{
      weekday: number
      name: string
      case_count: number
      percentage: number
    }>
    total_cases_analyzed: number
    analysis_days: number
  }> => {
    const response = await api.get('/patrols/smart-schedule', { params: { days } })
    return response.data
  },

  /**
   * 按案件信息生成区域化巡逻规划
   */
  getCaseDrivenPlan: async (params?: {
    days?: number
    limit?: number
  }): Promise<CaseDrivenPatrolPlan> => {
    const response = await api.get<CaseDrivenPatrolPlan>('/patrols/case-driven-plan', { params })
    return response.data
  },

  /**
   * 获取经过 TSP 排序优化的巡逻路线顺序
   */
  getOptimizedRoutes: async (params?: {
    radius_km?: number
    min_cases?: number
  }): Promise<{
    routes: Array<{
      visit_order: number
      center_latitude: number
      center_longitude: number
      case_count: number
      est_distance_km: number
    }>
    total_distance_km: number
    hotspot_count: number
  }> => {
    const response = await api.get('/patrols/optimized-routes', { params })
    return response.data
  },
}
