/**
 * 事件和区域研判 API 服务
 * 类型定义统一从 types/ 导入
 */
import api from './api'
import type {
  Event,
  AreaProfile,
  EventRelation,
  AreaAnalysisRequest,
  AreaAnalysisResponse,
  EventStatistics,
  MapEventData,
  EventCreateData,
  EventUpdateData,
  EventListParams,
  AreaListParams,
  CorrelationListParams,
  MapDataParams,
  AreaRiskRankingItem,
  AreaHotspot,
  RefreshAreaProfileResult,
  CorrelationAnalysisResponse,
} from '../types'

// ==================== 事件 API（命名空间风格） ====================

export const eventApi = {
  // ---------- 事件类型 ----------
  getTypes: async () => {
    const response = await api.get('/events/types')
    return response.data
  },

  // ---------- 事件 CRUD ----------
  create: async (data: EventCreateData): Promise<Event> => {
    const response = await api.post('/events/', data)
    return response.data
  },

  list: async (params?: EventListParams): Promise<Event[]> => {
    const response = await api.get('/events/', { params })
    return response.data
  },

  get: async (eventId: number): Promise<Event> => {
    const response = await api.get(`/events/${eventId}`)
    return response.data
  },

  update: async (eventId: number, data: EventUpdateData): Promise<Event> => {
    const response = await api.put(`/events/${eventId}`, data)
    return response.data
  },

  delete: async (eventId: number): Promise<void> => {
    await api.delete(`/events/${eventId}`)
  },

  convertToCase: async (eventId: number): Promise<{
    case_id: number
    event_id: number
    message: string
  }> => {
    const response = await api.post(`/events/${eventId}/convert-to-case`)
    return response.data
  },

  // ---------- 区域分析 ----------
  analyzeArea: async (request: AreaAnalysisRequest): Promise<AreaAnalysisResponse> => {
    const response = await api.post('/events/area/analyze', request)
    return response.data
  },

  getAreaRiskRanking: async (limit: number = 10): Promise<AreaRiskRankingItem[]> => {
    const response = await api.get('/events/area/risk-ranking', { params: { limit } })
    return response.data
  },

  getHotspots: async (
    daysBack: number = 90,
    minEvents: number = 2
  ): Promise<AreaHotspot[]> => {
    const response = await api.get('/events/area/hotspots', {
      params: { days_back: daysBack, min_events: minEvents },
    })
    return response.data
  },

  // ---------- 区域档案 ----------
  listAreaProfiles: async (params?: AreaListParams): Promise<AreaProfile[]> => {
    const response = await api.get('/events/areas', { params })
    return response.data
  },

  getAreaProfile: async (areaId: number): Promise<AreaProfile> => {
    const response = await api.get(`/events/areas/${areaId}`)
    return response.data
  },

  refreshAreaProfile: async (
    areaName: string,
    radiusKm: number = 5.0
  ): Promise<RefreshAreaProfileResult> => {
    const response = await api.post(`/events/areas/${encodeURIComponent(areaName)}/refresh`, null, {
      params: { radius_km: radiusKm },
    })
    return response.data
  },

  // ---------- 关联分析 ----------
  analyzeCorrelations: async (eventIds: number[]): Promise<CorrelationAnalysisResponse> => {
    const response = await api.post('/events/correlations/analyze', { event_ids: eventIds })
    return response.data
  },

  listCorrelations: async (params?: CorrelationListParams): Promise<EventRelation[]> => {
    const response = await api.get('/events/correlations', { params })
    return response.data
  },

  confirmCorrelation: async (relationId: number, confirmed: boolean, confirmedBy = 'user') => {
    const response = await api.post(`/events/correlations/${relationId}/confirm`, null, {
      params: { confirmed, confirmed_by: confirmedBy },
    })
    return response.data
  },

  // ---------- 统计和地图 ----------
  getStatistics: async (daysBack: number = 30): Promise<EventStatistics> => {
    const response = await api.get('/events/statistics', { params: { days_back: daysBack } })
    return response.data
  },

  getMapData: async (params?: MapDataParams) => {
    const response = await api.get<{ events: MapEventData[]; event_types: Record<string, string> }>(
      '/events/map-data',
      { params }
    )
    return response.data
  },
}

// ==================== 向后兼容导出（将逐步废弃） ====================

/** @deprecated 请使用 eventApi.getTypes */
export const getEventTypes = eventApi.getTypes
/** @deprecated 请使用 eventApi.create */
export const createEvent = eventApi.create
/** @deprecated 请使用 eventApi.list */
export const listEvents = eventApi.list
/** @deprecated 请使用 eventApi.get */
export const getEvent = eventApi.get
/** @deprecated 请使用 eventApi.update */
export const updateEvent = eventApi.update
/** @deprecated 请使用 eventApi.delete */
export const deleteEvent = eventApi.delete
/** @deprecated 请使用 eventApi.convertToCase */
export const convertEventToCase = eventApi.convertToCase
/** @deprecated 请使用 eventApi.analyzeArea */
export const analyzeArea = eventApi.analyzeArea
/** @deprecated 请使用 eventApi.getAreaRiskRanking */
export const getAreaRiskRanking = eventApi.getAreaRiskRanking
/** @deprecated 请使用 eventApi.getHotspots */
export const getHotspots = eventApi.getHotspots
/** @deprecated 请使用 eventApi.listAreaProfiles */
export const listAreaProfiles = eventApi.listAreaProfiles
/** @deprecated 请使用 eventApi.getAreaProfile */
export const getAreaProfile = eventApi.getAreaProfile
/** @deprecated 请使用 eventApi.refreshAreaProfile */
export const refreshAreaProfile = eventApi.refreshAreaProfile
/** @deprecated 请使用 eventApi.analyzeCorrelations */
export const analyzeCorrelations = eventApi.analyzeCorrelations
/** @deprecated 请使用 eventApi.listCorrelations */
export const listCorrelations = eventApi.listCorrelations
/** @deprecated 请使用 eventApi.confirmCorrelation */
export const confirmCorrelation = eventApi.confirmCorrelation
/** @deprecated 请使用 eventApi.getStatistics */
export const getEventStatistics = eventApi.getStatistics
/** @deprecated 请使用 eventApi.getMapData */
export const getMapData = eventApi.getMapData
