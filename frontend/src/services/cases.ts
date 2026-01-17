import api from './api'
import type {
  Case,
  CaseCreate,
  GeoAnalysisResult,
  Hotspot,
  SerialCaseGroup,
  PreprocessStatus,
} from '../types'

// 轨迹分析结果类型
export interface TrajectoryPoint {
  case_id: number
  latitude: number
  longitude: number
  occurred_time: string
  location?: string
}

export interface TrajectoryAnalysis {
  points: TrajectoryPoint[]
  total_distance_km: number
  time_span_days: number
  average_speed_km_per_day: number
  direction_trend?: string
}

export interface TrajectoryPrediction {
  predicted_location: {
    latitude: number
    longitude: number
  }
  confidence: number
  reasoning?: string
}

export interface TrajectoryReplayFrame {
  timestamp: string
  case_id: number
  latitude: number
  longitude: number
  cumulative_distance_km: number
}

// 语义搜索结果类型
export interface SemanticSearchResult {
  case: Case
  similarity: number
  matched_features?: string[]
}

// 案件统计数据类型
export interface CaseStatistics {
  total_cases: number
  today_cases: number
  pending_cases: number
  processing_cases: number
  resolved_cases: number
  this_week_cases: number
  this_month_cases: number
  cases_with_geo: number
  case_type_distribution: Record<string, number>
  daily_trend: Array<{
    date: string
    label: string
    count: number
  }>
}

export const caseApi = {
  /**
   * 获取案件统计数据
   */
  getStatistics: async (): Promise<CaseStatistics> => {
    const response = await api.get<CaseStatistics>('/cases/statistics')
    return response.data
  },

  /**
   * 获取案件列表
   */
  getCases: async (skip = 0, limit = 100): Promise<Case[]> => {
    const response = await api.get<Case[]>('/cases', { params: { skip, limit } })
    return response.data
  },

  /**
   * 获取单个案件详情
   */
  getCase: async (id: number): Promise<Case> => {
    const response = await api.get<Case>(`/cases/${id}`)
    return response.data
  },

  /**
   * 创建案件
   */
  createCase: async (data: CaseCreate): Promise<Case> => {
    const response = await api.post<Case>('/cases', data)
    return response.data
  },

  /**
   * 更新案件
   */
  updateCase: async (id: number, data: Partial<CaseCreate>): Promise<Case> => {
    const response = await api.put<Case>(`/cases/${id}`, data)
    return response.data
  },

  /**
   * 删除案件
   */
  deleteCase: async (id: number): Promise<void> => {
    await api.delete(`/cases/${id}`)
  },

  /**
   * 获取附近案件
   */
  getNearbyCases: async (caseId: number, radiusKm = 1): Promise<Case[]> => {
    const response = await api.get<Case[]>(`/cases/${caseId}/nearby`, {
      params: { radius_km: radiusKm },
    })
    return response.data
  },

  /**
   * 获取预处理状态统计
   */
  getPreprocessStatus: async (): Promise<PreprocessStatus> => {
    const response = await api.get<PreprocessStatus>('/cases/preprocess/status')
    return response.data
  },

  /**
   * 触发案件预处理
   */
  preprocessCase: async (id: number): Promise<{ message: string }> => {
    const response = await api.post<{ message: string }>(`/cases/${id}/preprocess`)
    return response.data
  },

  /**
   * 获取地理分析结果
   */
  getGeographicAnalysis: async (caseIds?: number[]): Promise<GeoAnalysisResult> => {
    const params = caseIds ? { case_ids: caseIds } : {}
    const response = await api.get<GeoAnalysisResult>('/cases/geo/analysis', { params })
    return response.data
  },

  /**
   * 获取热点分析
   */
  getHotspots: async (radiusKm = 0.5, minCases = 3): Promise<Hotspot[]> => {
    const response = await api.get<Hotspot[]>('/cases/geo/hotspots', {
      params: { radius_km: radiusKm, min_cases: minCases },
    })
    return response.data
  },

  /**
   * 获取串案分析
   */
  getSerialCases: async (
    caseIds?: number[],
    maxDistanceKm = 2.0,
    timeWindowDays = 30,
    useSemantic = true,
    useGeo = true,
    minSemanticSimilarity = 0.6
  ): Promise<SerialCaseGroup[]> => {
    const params: Record<string, unknown> = {
      max_distance_km: maxDistanceKm,
      time_window_days: timeWindowDays,
      use_semantic: useSemantic,
      use_geo: useGeo,
      min_semantic_similarity: minSemanticSimilarity,
    }
    if (caseIds) {
      params.case_ids = caseIds
    }
    const response = await api.get<SerialCaseGroup[]>('/cases/geo/serial-cases', { params })
    return response.data
  },

  /**
   * 语义搜索
   */
  semanticSearch: async (
    query: string,
    topK = 10,
    minSimilarity = 0.5
  ): Promise<SemanticSearchResult[]> => {
    const response = await api.get<SemanticSearchResult[]>('/cases/semantic/search', {
      params: { query, top_k: topK, min_similarity: minSimilarity },
    })
    return response.data
  },

  /**
   * 获取轨迹数据
   */
  getTrajectory: async (caseIds: number[]): Promise<TrajectoryPoint[]> => {
    const ids = caseIds.join(',')
    const response = await api.get<TrajectoryPoint[]>(`/cases/trajectory/${ids}`)
    return response.data
  },

  /**
   * 分析轨迹
   */
  analyzeTrajectory: async (caseIds: number[]): Promise<TrajectoryAnalysis> => {
    const ids = caseIds.join(',')
    const response = await api.get<TrajectoryAnalysis>(`/cases/trajectory/${ids}/analysis`)
    return response.data
  },

  /**
   * 预测下一个位置
   */
  predictNextLocation: async (caseIds: number[], useAI = true): Promise<TrajectoryPrediction> => {
    const ids = caseIds.join(',')
    const response = await api.get<TrajectoryPrediction>(`/cases/trajectory/${ids}/predict`, {
      params: { use_ai: useAI },
    })
    return response.data
  },

  /**
   * 获取轨迹回放数据
   */
  getTrajectoryReplay: async (
    caseIds: number[],
    intervalSeconds = 60
  ): Promise<TrajectoryReplayFrame[]> => {
    const ids = caseIds.join(',')
    const response = await api.get<TrajectoryReplayFrame[]>(`/cases/trajectory/${ids}/replay`, {
      params: { interval_seconds: intervalSeconds },
    })
    return response.data
  },
}

// 为了向后兼容，同时导出 Case 和 CaseCreate 类型
export type { Case, CaseCreate } from '../types'
