/**
 * 事件和区域研判 API 服务
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
} from '../types/event'

// ==================== 事件类型常量 ====================

export const getEventTypes = async () => {
  const response = await api.get('/events/types')
  return response.data
}

// ==================== 事件 CRUD ====================

export interface EventCreateData {
  event_type: string
  occurred_time: string
  location?: string
  latitude?: number
  longitude?: number
  village_name?: string
  village_distance_km?: number
  township?: string
  title?: string
  description?: string
  vehicles?: { plate?: string; type?: string; color?: string }[]
  oil_volume_liters?: number
  oil_type?: string
  equipment?: string[]
  suspects_count?: number
  suspects_description?: string
  discovery_method?: string
  handling_result?: string
  related_case_id?: number
}

export const createEvent = async (data: EventCreateData): Promise<Event> => {
  const response = await api.post('/events/', data)
  return response.data
}

export interface EventListParams {
  skip?: number
  limit?: number
  event_type?: string
  village_name?: string
  days_back?: number
}

export const listEvents = async (params?: EventListParams): Promise<Event[]> => {
  const response = await api.get('/events/', { params })
  return response.data
}

export const getEvent = async (eventId: number): Promise<Event> => {
  const response = await api.get(`/events/${eventId}`)
  return response.data
}

export interface EventUpdateData {
  location?: string
  latitude?: number
  longitude?: number
  village_name?: string
  village_distance_km?: number
  township?: string
  title?: string
  description?: string
  vehicles?: { plate?: string; type?: string; color?: string }[]
  oil_volume_liters?: number
  oil_type?: string
  equipment?: string[]
  suspects_count?: number
  suspects_description?: string
  discovery_method?: string
  handling_result?: string
  risk_level?: string
  analysis_notes?: string
  suggested_actions?: string[]
}

export const updateEvent = async (eventId: number, data: EventUpdateData): Promise<Event> => {
  const response = await api.put(`/events/${eventId}`, data)
  return response.data
}

export const deleteEvent = async (eventId: number): Promise<void> => {
  await api.delete(`/events/${eventId}`)
}

// ==================== 区域分析 ====================

export const analyzeArea = async (request: AreaAnalysisRequest): Promise<AreaAnalysisResponse> => {
  const response = await api.post('/events/area/analyze', request)
  return response.data
}

export const getAreaRiskRanking = async (limit: number = 10) => {
  const response = await api.get('/events/area/risk-ranking', { params: { limit } })
  return response.data
}

export const getHotspots = async (daysBack: number = 90, minEvents: number = 2) => {
  const response = await api.get('/events/area/hotspots', {
    params: { days_back: daysBack, min_events: minEvents },
  })
  return response.data
}

// ==================== 区域档案 ====================

export interface AreaListParams {
  skip?: number
  limit?: number
  risk_level?: string
  is_active?: boolean
}

export const listAreaProfiles = async (params?: AreaListParams): Promise<AreaProfile[]> => {
  const response = await api.get('/events/areas', { params })
  return response.data
}

export const getAreaProfile = async (areaId: number): Promise<AreaProfile> => {
  const response = await api.get(`/events/areas/${areaId}`)
  return response.data
}

export const refreshAreaProfile = async (areaName: string, radiusKm: number = 5.0) => {
  const response = await api.post(`/events/areas/${encodeURIComponent(areaName)}/refresh`, null, {
    params: { radius_km: radiusKm },
  })
  return response.data
}

// ==================== 关联分析 ====================

export const analyzeCorrelations = async (eventIds: number[]) => {
  const response = await api.post('/events/correlations/analyze', { event_ids: eventIds })
  return response.data
}

export interface CorrelationListParams {
  relation_type?: string
  is_confirmed?: boolean
  skip?: number
  limit?: number
}

export const listCorrelations = async (
  params?: CorrelationListParams
): Promise<EventRelation[]> => {
  const response = await api.get('/events/correlations', { params })
  return response.data
}

export const confirmCorrelation = async (
  relationId: number,
  confirmed: boolean,
  confirmedBy: string = 'user'
) => {
  const response = await api.post(`/events/correlations/${relationId}/confirm`, null, {
    params: { confirmed, confirmed_by: confirmedBy },
  })
  return response.data
}

// ==================== 统计和地图 ====================

export const getEventStatistics = async (daysBack: number = 30): Promise<EventStatistics> => {
  const response = await api.get('/events/statistics', { params: { days_back: daysBack } })
  return response.data
}

export interface MapDataParams {
  days_back?: number
  event_type?: string
}

export const getMapData = async (params?: MapDataParams) => {
  const response = await api.get<{ events: MapEventData[]; event_types: Record<string, string> }>(
    '/events/map-data',
    { params }
  )
  return response.data
}
