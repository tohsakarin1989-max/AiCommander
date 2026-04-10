/**
 * 统一类型定义
 * 所有前端类型从此文件导入，services 不再定义类型
 */

// 导出事件相关类型
export * from './event'

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

// 预处理后的案件结构化特征
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
  // 预处理扩展字段
  basic?: {
    title?: string
    summary?: string
    case_type?: string
    time?: string
    location?: string
  }
  geo?: {
    latitude?: number
    longitude?: number
    region?: string
    place_type?: string
  }
  modus?: {
    target_object?: string
    modus_operandi?: string[]
    tools?: string[]
    time_pattern?: string[]
    weather_pattern?: string[]
  }
  actors?: {
    facts?: {
      known_roles?: string[]
      known_vehicles?: {
        plate?: string
        type?: string
        suspected_fake_plate?: boolean
      }[]
    }
    clues?: {
      possible_roles?: string[]
      notes?: string
    }
    hypotheses?: {
      suspected_structure?: string
    }
  }
  oil?: {
    facts?: {
      oil_type?: string
      volume?: number
      value?: number
      facility_type?: string
      facility_owner?: string
    }
    clues?: {
      scene_observations?: string[]
    }
    hypotheses?: {
      possible_risk?: string
    }
  }
  flow?: {
    upstream_source?: string
    downstream_destination?: string[]
    economic_impact?: string
  }
  risk?: {
    level?: string
    factors?: string[]
  }
  tags?: string[]
  confidence?: number
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

export interface MeetingReportContent {
  summary?: string
  consensus_points?: string[]
  disagreement_points?: string[]
  top_ranked_insights?: string[]
  conclusions?: string
  recommendations?: string[]
  model_contributions?: Record<string, string>
  ranking_summary?: string
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
  content?: MeetingReportContent | string
  consensus_points?: string[]
  disagreement_points?: string[]
}

// 分析结果类型（第一阶段）
export interface AnalysisResult {
  id: number
  meeting_id: string
  analyst_model_id: number
  result_content: Record<string, unknown> | string
  created_at: string
}

// 排名结果类型（第二阶段）
export interface RankingData {
  rankings?: {
    anonymous_id: string
    rank: number
    score: number
    reasoning: string
  }[]
  overall_comment?: string
}

export interface AggregatedData {
  rankings?: Record<string, {
    average_score: number
    average_rank: number
    vote_count: number
  }>
}

export interface RankingResult {
  id: number
  meeting_id: string
  stage: 'review' | 'final'
  evaluator_model_id?: number
  ranking_data?: RankingData
  aggregated_data?: AggregatedData
  created_at: string
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
  description?: string
  is_active: boolean
  is_default: boolean
  created_at: string
  updated_at?: string
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
  config_key: string
  config_value: string
  category: string
  description?: string
  created_at?: string
  updated_at?: string
}

export interface MapConfig {
  provider: 'openstreetmap' | 'mapbox' | 'amap' | 'google' | 'baidu'
  api_key?: string
  api_base_url?: string
  default_center?: GeoPoint
  default_zoom?: number
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

// ============ AI 助手相关类型 ============

export interface Conversation {
  id: number
  round_number: number
  speaker_model_id: number
  message_type: 'analysis' | 'ranking' | 'summary' | 'comment'
  content: string
  created_at: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
}

export interface ChatRequest {
  query: string
  case_ids?: number[]
  context?: string
  conversation_history?: ChatMessage[]
}

export interface SourceItem {
  type: 'case' | 'report'
  id?: number
  case_number?: string
  meeting_id?: string
}

export interface ChatResponse {
  response: string
  answer?: string  // 别名，兼容不同 API 返回
  sources?: SourceItem[]
  suggestions?: string[]
}

// ============ 智能体相关类型 ============

export interface AgentTaskResult {
  result?: string
  steps?: string[]
}

export interface AgentTask {
  id: number
  query: string
  case_ids: number[]
  status: string
  result: AgentTaskResult | null
  created_at: string
}

// ============ 结论相关类型 ============

export interface MeetingInfo {
  meeting_id: string
  status: string
  case_ids?: number[]
  created_at?: string
}

export interface Conclusion {
  id: number
  case_id: number
  meeting_id?: string
  meeting_info?: MeetingInfo
  status: string
  confidence: number
  risk_level: string
  summary?: string
  evidence?: {
    key_evidence?: string[]
    recommendations?: string[]
    raw?: {
      case?: { case_number?: string }
      similar_cases?: Array<{ case_id: number; similarity: number; metadata?: { case_type?: string } }>
      related_meetings?: Array<{ meeting_id: string; status: string }>
      related_reports?: Array<{ report_id: string; title?: string }>
      meeting?: { meeting_id: string; status: string; case_ids: number[] }
      report?: { content?: string; report_type?: string }
    }
  }
  created_at: string
  updated_at?: string
  reviews?: Array<{
    id: number
    action: string
    note?: string
    created_at: string
  }>
}

export interface ConclusionFilters {
  status?: string
  meeting_id?: string
  risk_level?: string
  min_confidence?: number
  max_confidence?: number
}

// ============ 地图 MCP 响应类型 ============

export interface HotspotsResponse {
  hotspots: Hotspot[]
  total: number
}

export interface SerialCasesResponse {
  serial_cases: SerialCaseGroup[]
  total: number
}

export interface LocationInfoResponse {
  success: boolean
  location: {
    latitude: number
    longitude: number
    address?: string
    province?: string
    city?: string
    district?: string
    street?: string
    adcode?: string
  }
  mcp_available?: boolean
  note?: string
  error?: string
}

export interface POI {
  name: string
  type: string
  address: string
  location: string
  distance: number
  tel?: string
}

export interface NearbyPOIsResponse {
  success: boolean
  pois: POI[]
  count: number
  center: GeoPoint
  radius: number
  keywords: string
}

export interface AIAnalysisResponse {
  success: boolean
  location_info: LocationInfoResponse
  comprehensive_data: unknown
  approach_analysis: unknown
  weather_info: unknown
  ai_analysis: {
    geographic_features?: string
    villages_analysis?: string
    gas_stations_analysis?: string
    refineries_analysis?: string
    approach_routes?: string[]
    risk_assessment?: string
    prevention_suggestions?: string[]
    analysis?: string
    parse_error?: boolean
  }
  error?: string
}

// ============ 会议模板相关类型 ============

export interface MeetingTemplate {
  id: number
  name: string
  description?: string
  moderator_model_id: number
  analyst_model_ids: number[]
  config?: Record<string, unknown>
  is_system: boolean
  use_count: number
  created_at: string
}

export interface MeetingTemplateCreate {
  name: string
  description?: string
  moderator_model_id: number
  analyst_model_ids: number[]
  config?: Record<string, unknown>
}

export interface MeetingTemplateUpdate {
  name?: string
  description?: string
  moderator_model_id?: number
  analyst_model_ids?: number[]
  config?: Record<string, unknown>
}

// ============ 轨迹分析类型（从 cases.ts 迁移） ============

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

export interface SemanticSearchResult {
  case: Case
  similarity: number
  matched_features?: string[]
}

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

// ============ 模型配置类型（从 config.ts 迁移，替换原有） ============

export interface ModelCreate {
  name: string
  provider: ModelProvider
  model_name: string
  api_key: string
  role: ModelRole
  config?: AIModelConfig
  description?: string
}

export interface ModelUpdate {
  name?: string
  provider?: ModelProvider
  model_name?: string
  api_key?: string
  role?: ModelRole
  config?: AIModelConfig
  description?: string
  is_active?: boolean
}

export interface ModelTestResult {
  success: boolean
  message: string
  latency_ms?: number
}

// ============ 事件操作类型（从 events.ts 迁移） ============

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

export interface EventListParams {
  skip?: number
  limit?: number
  event_type?: string
  village_name?: string
  days_back?: number
}

export interface AreaListParams {
  skip?: number
  limit?: number
  risk_level?: string
  is_active?: boolean
}

export interface CorrelationListParams {
  relation_type?: string
  is_confirmed?: boolean
  skip?: number
  limit?: number
}

export interface MapDataParams {
  days_back?: number
  event_type?: string
}

// ============ 巡逻相关类型（从 patrols.ts 迁移） ============

export interface PatrolRecord {
  id: number
  patrol_number: string
  patrol_type: string
  area_name: string
  area_coordinates?: Array<{ lat: number; lng: number }>
  start_time?: string
  end_time?: string
  officer_count: number
  officer_names?: string
  status: string
  findings?: string
  issues_found: number
  actions_taken?: string
  evidence_photos?: string[]
  related_case_ids?: number[]
  related_deployment_id?: number
  risk_before?: number
  risk_after?: number
  effectiveness_score?: number
  feedback_notes?: string
  created_at: string
  updated_at: string
  created_by?: string
}

export interface PatrolCreate {
  area_name: string
  patrol_type?: string
  area_coordinates?: Array<{ lat: number; lng: number }>
  officer_count?: number
  officer_names?: string
  related_case_ids?: number[]
  related_deployment_id?: number
  created_by?: string
}

export interface PatrolComplete {
  findings?: string
  issues_found?: number
  actions_taken?: string
  patrol_route?: Array<{ lat: number; lng: number; time?: string }>
  evidence_photos?: string[]
  effectiveness_score?: number
  feedback_notes?: string
}

export interface AreaRisk {
  id: number
  area_name: string
  area_coordinates?: Array<{ lat: number; lng: number }>
  risk_score: number
  risk_level: string
  case_count_30d: number
  case_count_7d: number
  patrol_count_30d: number
  last_patrol_date?: string
  days_since_patrol?: number
  risk_history?: Array<{ date: string; score: number; reason: string }>
  created_at: string
  updated_at: string
}

// ============ 团伙分析类型（从 gangs.ts 迁移） ============

export interface GangProfile {
  case_ids: number[]
  case_count: number
  active_hours: number[]
  active_days: number[]
  preferred_locations: string[]
  modus_operandi: string[]
  target_facilities: string[]
  known_persons: string[]
  known_vehicles: string[]
  oil_types: string[]
  geographic_center?: { latitude: number; longitude: number }
  time_span_days: number
  risk_score: number
}

export interface GangAnalysisRequest {
  case_ids?: number[]
  min_similarity?: number
  min_cases?: number
  time_window_days?: number
}

export interface TimelineEntry {
  case_id: number
  case_number: string
  occurred_time?: string
  location?: string
  case_type?: string
  modus_operandi?: string
}

export interface GangRelations {
  gang_profile: GangProfile
  relations: {
    nodes: Array<{ id: string; type: string; label: string }>
    edges: Array<{ source: string; target: string; label?: string }>
  }
}

export interface GangStatistics {
  total_gangs: number
  total_cases_in_gangs: number
  high_risk_gangs: number
  average_gang_size: number
  top_gangs: GangProfile[]
}

// ============ 地图标记相关类型 ============

export interface CaseMarker {
  id: number
  lat: number
  lng: number
  title: string
  caseNumber: string
  caseType?: string
  riskLevel?: 'high' | 'medium' | 'low'
  occurredTime?: string
  modus?: string
}

export interface SerialGroup {
  caseIds: number[]
  color?: string
}
