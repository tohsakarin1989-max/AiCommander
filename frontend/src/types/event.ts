/**
 * 事件相关类型定义
 */

// 事件类型枚举
export const EVENT_TYPES = {
  theft_case: '盗油案件',
  vehicle_caught: '查获车辆',
  stash_found: '发现囤油点',
  equipment_found: '发现作案工具',
  suspect_activity: '可疑活动',
  damage_found: '发现设施损坏',
  illegal_station: '非法加油站',
  pipeline_tap: '管线打孔点',
} as const

export type EventType = keyof typeof EVENT_TYPES

// 关联类型
export const RELATION_TYPES = {
  spatial_cluster: { name: '空间聚集', description: '多个事件发生在同一区域' },
  supply_chain: { name: '上下游关联', description: '盗油点→运输→囤油点的链条关系' },
  temporal_pattern: { name: '时间规律', description: '同一区域周期性发案' },
  modus_match: { name: '手法相似', description: '多个事件使用相同/相似作案手法' },
  vehicle_link: { name: '车辆关联', description: '涉及相同车辆或同类型车辆' },
  route_pattern: { name: '路线关联', description: '事件分布沿特定道路/管线' },
} as const

export type RelationType = keyof typeof RELATION_TYPES

// 风险等级
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'

// 车辆信息
export interface Vehicle {
  plate?: string
  type?: string
  color?: string
}

// 事件接口
export interface Event {
  id: number
  event_number: string
  event_type: EventType
  occurred_time: string
  location?: string
  latitude?: number
  longitude?: number
  village_name?: string
  village_distance_km?: number
  township?: string
  title?: string
  description?: string
  vehicles?: Vehicle[]
  oil_volume_liters?: number
  oil_type?: string
  equipment?: string[]
  suspects_count?: number
  discovery_method?: string
  handling_result?: string
  is_analyzed: boolean
  risk_level?: RiskLevel
  analysis_notes?: string
  suggested_actions?: string[]
  related_case_id?: number
  created_at?: string
}

// 区域档案
export interface AreaProfile {
  id: number
  area_name: string
  area_type: string
  center_latitude?: number
  center_longitude?: number
  radius_km: number
  township?: string
  county?: string
  total_events: number
  events_last_30_days: number
  events_last_90_days: number
  first_event_time?: string
  last_event_time?: string
  event_types_count?: Record<string, number>
  risk_level: RiskLevel
  risk_score: number
  risk_factors?: string[]
  assessment?: string
  suggested_actions?: string[]
  patrol_suggestions?: PatrolSuggestion[]
  is_active: boolean
  created_at?: string
  updated_at?: string
}

// 事件关联
export interface EventRelation {
  id: number
  event_a_id: number
  event_b_id: number
  relation_type: RelationType
  confidence: number
  distance_km?: number
  time_gap_days?: number
  evidence?: string
  reasoning?: string
  is_confirmed: boolean
  is_rejected?: boolean
  created_at?: string
}

export interface CorrelationRelation {
  event_id: number
  event_a_id: number
  event_b_id: number
  relation_type: RelationType | string
  distance_km?: number
  time_gap_days?: number
  confidence?: number
  reasoning?: string
  chain_role?: string
  common_plates?: string[]
  related_event?: Event
}

export interface CorrelationAnalysisResponse {
  event_count: number
  relations: CorrelationRelation[]
  relation_count: number
}

// 巡逻建议
export interface PatrolSuggestion {
  location: string
  reason: string
  timing?: string
  focus_on?: string[]
  priority?: number
  method?: string
}

// 排查建议
export interface SearchSuggestion {
  target: string
  area: string
  method?: string
  rationale?: string
}

export interface AreaTimelineItem {
  id: number
  event_number: string
  event_type: EventType | string
  event_type_name: string
  occurred_time?: string
  title?: string
  location?: string
  handling_result?: string
}

export interface AreaInternalRelation {
  event_a_id: number
  event_b_id: number
  event_a_type?: EventType | string
  event_b_type?: EventType | string
  distance_km?: number
  time_gap_days?: number
  relation_types: string[]
  confidence?: number
  evidence?: string
  reasoning?: string
  supply_chain_note?: string
}

export interface AreaSuggestion {
  type: string
  priority: 'low' | 'medium' | 'high' | string
  title: string
  content: string
  action: string
}

export interface AreaPatrolSuggestions {
  area_name: string
  priority_level: 'low' | 'medium' | 'high' | string
  suggested_times: Array<{ period: string; reason: string }>
  suggested_days: Array<{ day: string; reason: string }>
  watch_targets: Array<{ type: string; description: string }>
  patrol_points: string[]
  frequency: string
}

export interface AreaRiskRankingItem {
  area_name: string
  event_count: number
  last_event?: string
  type_counts: Record<string, number>
  risk_score: number
  risk_level: RiskLevel
  days_since_last?: number
}

export interface AreaHotspot extends AreaRiskRankingItem {
  center_latitude?: number
  center_longitude?: number
}

export interface RefreshAreaProfileResult {
  message: string
  profile_id: number
  area_name: string
  risk_level: RiskLevel
  risk_score: number
  total_events: number
}

// 区域分析请求
export interface AreaAnalysisRequest {
  area_name: string
  radius_km?: number
  days_back?: number
}

// 区域分析响应
export interface AreaAnalysisResponse {
  area_name: string
  events: Event[]
  timeline: AreaTimelineItem[]
  relations: AreaInternalRelation[]
  risk_assessment: {
    level: RiskLevel
    score: number
    factors: string[]
  }
  suggestions: AreaSuggestion[]
  patrol_suggestions: AreaPatrolSuggestions
}

// 事件统计
export interface EventStatistics {
  total_events: number
  recent_events: number
  days_back: number
  by_type: Record<string, number>
  by_village: Record<string, number>
  high_risk_areas: {
    area_name: string
    risk_level: RiskLevel
    risk_score: number
    event_count: number
  }[]
}

// 地图数据
export interface MapEventData {
  id: number
  event_number: string
  event_type: EventType
  title: string
  latitude: number
  longitude: number
  occurred_time: string
  village_name?: string
  risk_level?: RiskLevel
}
