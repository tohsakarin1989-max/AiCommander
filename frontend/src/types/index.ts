/**
 * 统一类型定义
 */

// ============ 案件相关类型 ============

export type CaseStatus = 'pending' | 'processing' | 'completed' | 'failed'
export type OilType = '汽油' | '柴油' | '原油' | '润滑油' | '其他'
export type FacilityType = '管线' | '油库' | '加油站' | '油罐车' | '其他'
export type SecurityLevel = '高' | '中' | '低'
export type PersonRole = '内部员工' | '司机' | '加油员' | '其他'

export interface Person {
  name?: string
  role?: PersonRole
  id_number?: string
  phone?: string
  description?: string
}

export interface Item {
  name: string
  category?: string
  quantity?: number
  value?: number
  description?: string
}

export interface VehicleInfo {
  plate_number?: string
  vehicle_type?: string
  color?: string
  owner?: string
}

export interface CaseFeatures {
  keywords?: string[]
  entities?: {
    persons?: string[]
    locations?: string[]
    organizations?: string[]
    items?: string[]
  }
  summary?: string
  risk_level?: string
}

export interface Case {
  id: number
  case_number: string
  occurred_time: string
  location?: string
  latitude?: number
  longitude?: number
  case_type?: string
  description?: string
  involved_persons?: Person[]
  involved_items?: Item[]
  loss_amount?: number
  // 涉油案件特征
  oil_type?: OilType
  oil_volume?: number
  oil_value?: number
  facility_type?: FacilityType
  facility_owner?: string
  security_level?: SecurityLevel
  modus_operandi?: string
  suspect_roles?: PersonRole[]
  vehicle_info?: VehicleInfo
  upstream_source?: string
  downstream_destination?: string
  // 结构化预处理结果
  features?: CaseFeatures
  status: CaseStatus
}

export interface CaseCreate {
  occurred_time: string
  location?: string
  latitude?: number
  longitude?: number
  case_type?: string
  description?: string
  involved_persons?: Person[]
  involved_items?: Item[]
  loss_amount?: number
  oil_type?: OilType
  oil_volume?: number
  oil_value?: number
  facility_type?: FacilityType
  facility_owner?: string
  security_level?: SecurityLevel
  modus_operandi?: string
  suspect_roles?: PersonRole[]
  vehicle_info?: VehicleInfo
  upstream_source?: string
  downstream_destination?: string
}

// ============ 会议相关类型 ============

export type MeetingStatus = 'pending' | 'processing' | 'completed' | 'failed'

export interface MeetingStageResult {
  stage: number
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  data?: Record<string, unknown>
  error?: string
}

export interface Meeting {
  id: number
  meeting_id: string
  case_ids: number[]
  moderator_model_id: number
  analyst_model_ids: number[]
  status: MeetingStatus
  stage_results?: MeetingStageResult[]
  final_report?: MeetingReport
  created_at: string
  updated_at?: string
}

export interface MeetingCreate {
  case_ids: number[]
  moderator_model_id: number
  analyst_model_ids: number[]
}

export interface MeetingReport {
  meeting_id: string
  summary: string
  key_findings: string[]
  risk_assessment?: string
  recommendations?: string[]
  analyst_contributions: {
    model_name: string
    contribution_summary: string
    ranking?: number
  }[]
  generated_at: string
}

// ============ AI 模型相关类型 ============

export type ModelProvider = 'openai' | 'anthropic' | 'openai-compatible' | 'azure-openai'
export type ModelRole = 'moderator' | 'analyst' | 'both'

export interface AIModelConfig {
  specialty?: string
  temperature?: number
  max_tokens?: number
  api_base?: string
  [key: string]: unknown
}

export interface AIModel {
  id: number
  name: string
  provider: ModelProvider
  model_name: string
  role: ModelRole
  config?: AIModelConfig
  is_active: boolean
  created_at: string
}

export interface AIModelCreate {
  name: string
  provider: ModelProvider
  model_name: string
  api_key: string
  role?: ModelRole
  config?: AIModelConfig
}

// ============ 地理分析相关类型 ============

export interface GeoPoint {
  latitude: number
  longitude: number
}

export interface Hotspot {
  center: GeoPoint
  radius_km: number
  case_count: number
  case_ids: number[]
  risk_score: number
}

export interface SerialCaseGroup {
  group_id: string
  case_ids: number[]
  similarity_score: number
  common_features: string[]
  time_span_days: number
  geographic_spread_km: number
}

export interface GeoAnalysisResult {
  total_cases: number
  cases_with_geo: number
  coverage_rate: number
  center_point?: GeoPoint
  bounding_box?: {
    min_lat: number
    max_lat: number
    min_lng: number
    max_lng: number
  }
}

// ============ 系统配置相关类型 ============

export interface SystemConfig {
  id: number
  key: string
  value: string
  description?: string
  category: string
}

export interface MapConfig {
  provider: 'amap' | 'google' | 'baidu'
  api_key?: string
  default_center: GeoPoint
  default_zoom: number
}

// ============ API 响应相关类型 ============

export interface ApiResponse<T> {
  data: T
  message?: string
  code?: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export interface PreprocessStatus {
  pending: number
  processing: number
  success: number
  failed: number
  avg_duration_seconds: number | null
}
