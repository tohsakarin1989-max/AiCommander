/**
 * 事件和区域研判 API 服务
 * 类型定义统一从 types/ 导入
 */
import api from './api'
import type {
  Event,
  AreaProfile,
  EventRelation,
  EventStatistics,
  MapEventData,
  EventCreateData,
  EventUpdateData,
  EventListParams,
  AreaListParams,
  CorrelationListParams,
  MapDataParams,
  CorrelationAnalysisResponse,
} from '../types'

export type EventScope = { operational_area_id?: number; start_date?: string; end_date?: string }
export type ScopedEventStatistics = EventStatistics & {
  filtered_events?: number; linked_case_count?: number; complete?: boolean; cutoff?: string;
  scope?: EventScope & { days_back?: number | null; time_field: string; end_exclusive: boolean };
  counting_rule?: string;
}

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

  list: async (params?: EventListParams & EventScope): Promise<Event[]> => {
    const response = await api.get('/events/', { params })
    return response.data
  },

  get: async (eventId: number, signal?: AbortSignal): Promise<Event> => {
    const response = await api.get(`/events/${eventId}`, { signal })
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

  // ---------- 区域档案 ----------
  listAreaProfiles: async (params?: AreaListParams): Promise<AreaProfile[]> => {
    const response = await api.get('/events/areas', { params })
    return response.data
  },

  getAreaProfile: async (areaId: number): Promise<AreaProfile> => {
    const response = await api.get(`/events/areas/${areaId}`)
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
  getStatistics: async (scope: number | (EventScope & { all_history?: boolean; days_back?: number }) = 30): Promise<ScopedEventStatistics> => {
    const response = await api.get('/events/statistics', { params: typeof scope === 'number' ? { days_back: scope } : scope })
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
/** @deprecated 请使用 eventApi.listAreaProfiles */
export const listAreaProfiles = eventApi.listAreaProfiles
/** @deprecated 请使用 eventApi.getAreaProfile */
export const getAreaProfile = eventApi.getAreaProfile
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
