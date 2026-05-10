/**
 * 统一类型定义
 * 所有前端类型从此文件导入，services 不再定义类型
 */

// 导出事件相关类型
export * from './event'

// ============ 案件相关类型 ============

export type CaseStatus = 'pending' | 'processing' | 'completed' | 'resolved' | 'failed'
export type OilType = '汽油' | '柴油' | '原油' | '润滑油' | '其他'
export type FacilityType = '管线' | '油库' | '加油站' | '油罐车' | '其他'
export type SecurityLevel = '高' | '中' | '低'
export type PersonRole = '内部员工' | '司机' | '加油员' | '其他'
export type CaseQualityLevel = 'high' | 'medium' | 'low'
export type CaseSourceType = '巡逻发现' | '群众举报' | '领导指派' | '公安机关线索' | '技防预警' | '红色网格上报' | '作业区反馈' | '其他'
export type OilNature = '被盗原油' | '落地原油' | '收缴油品' | '回收原油' | '其他'

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

export interface CaseQuality {
  score: number
  level: CaseQualityLevel
  category_scores: Record<string, number>
  missing_required: Array<{ field: string; label: string; reason: string }>
  warnings: Array<{ field: string; message: string }>
  recommendations: string[]
  facts: Record<string, unknown>
}

export interface CaseVehicle {
  id: number
  case_id: number
  vehicle_type?: string
  color?: string
  brand?: string
  model?: string
  plate_number?: string
  oil_volume?: number
  water_cut?: number
  custody_location?: string
  current_location?: string
  handling_status?: string
  transferred_to_police?: boolean
  transfer_time?: string
  transfer_document_no?: string
  notes?: string
  created_at?: string
  updated_at?: string
}

export interface CasePerson {
  id: number
  case_id: number
  name?: string
  gender?: string
  id_number?: string
  home_address?: string
  phone?: string
  role?: string
  handling_status?: string
  notes?: string
  created_at?: string
  updated_at?: string
}

export interface CaseEvidence {
  id: number
  case_id: number
  evidence_type?: string
  title?: string
  file_path?: string
  requirement_key?: string
  captured_at?: string
  latitude?: number
  longitude?: number
  is_sensitive?: boolean
  meta?: Record<string, unknown>
  notes?: string
  created_at?: string
  updated_at?: string
}

export interface OilRecoveryRecord {
  id: number
  case_id: number
  oil_nature?: OilNature | string
  volume_tons?: number
  water_cut?: number
  source?: string
  receiver?: string
  handled_at?: string
  handling_method?: string
  notes?: string
  created_at?: string
  updated_at?: string
}

export interface CaseStructurePreview {
  case_fields: Partial<CaseCreate>
  field_sources: Record<string, string>
  entities: {
    plate_numbers?: string[]
    person_count?: number
    material_hints?: string[]
  }
  suggested_evidence: Array<{
    requirement_key: string
    label: string
    reason: string
  }>
  warnings: string[]
  confidence: number
  boundary: string
}

export interface CaseEvidenceClassification {
  requirement_key?: string
  label: string
  evidence_type: string
  confidence: number
  matched_terms: string[]
  source: string
}

export interface BonusMaterialCheck {
  requirement_key: string
  label: string
  category: string
  required: boolean
  status: 'satisfied' | 'partial' | 'missing' | 'not_required'
  trigger_reason?: string
  note: string
  evidence_id?: number
}

export interface BonusAssessmentItem {
  key: string
  label: string
  basis: string
  quantity: number
  unit: string
  formula: string
  required_materials: string[]
  blocked_by: string[]
  status: 'calculated' | 'blocked_by_materials' | 'rules_not_configured' | 'not_applicable'
  suggested_amount: number
}

export interface BonusSquadPerformance {
  vehicle_actual: number
  vehicle_target: number
  vehicle_high: boolean
  person_actual: number
  person_target: number
  person_high: boolean
}

export interface BonusDistribution {
  squad: string
  count: number
  amount: number | null
}

export interface BonusAssessment {
  case_id: number
  case_number: string
  rules_version: string
  rules_configured: boolean
  material_gate: {
    status: 'ready' | 'blocked_by_materials' | 'rules_not_configured'
    required_count: number
    satisfied_count: number
    missing_materials: string[]
  }
  material_checks: BonusMaterialCheck[]
  bonus_items: BonusAssessmentItem[]
  total_suggested_amount: number
  primary_squad?: string | null
  bonus_counts?: Record<string, number>
  squad_performance?: Record<string, BonusSquadPerformance>
  distribution?: BonusDistribution[]
  warnings?: string[]
  ready_for_review: boolean
  manual_review_required: boolean
  boundary: string
}

export interface CaseAutomationModule {
  key: 'conclusion_layering' | 'experience_card' | 'gap_closure' | string
  label: string
  status: 'ready' | 'needs_data' | 'needs_completion' | string
  metrics: Record<string, number>
}

export interface CaseAutomationWorkbench {
  case_id: number
  case_number: string
  version: string
  modules: CaseAutomationModule[]
  conclusion_layering: {
    facts: string[]
    inferences: Array<{
      claim: string
      basis: string[]
      confidence: string
    }>
    suggestions: Array<{
      title?: string
      action?: string
      priority?: string
      basis?: string[]
      evidence?: unknown[]
      confidence?: number
    }>
    information_gaps: string[]
    evidence_index: Array<Record<string, unknown>>
    boundary: string[]
  }
  experience_card: {
    case_id: number
    case_number: string
    summary: string
    what_happened: Record<string, unknown>
    why_it_matters: string[]
    how_it_was_found: string[]
    reusable_lessons: string[]
    next_attention_points: string[]
    evidence_basis: Record<string, unknown>
  }
  gap_closure: {
    material_gaps: string[]
    information_gaps: string[]
    actions: Array<{
      source: 'material' | 'information' | string
      priority: 'high' | 'medium' | 'low' | string
      title: string
      detail: string
    }>
    bonus_ready: boolean
    review_ready?: boolean
  }
  bonus_assessment?: BonusAssessment | null
  ready_for_human_review: boolean
  boundary: string
}

export interface CaseTip {
  id: number
  case_id?: number
  reporter_name?: string
  reporter_contact?: string
  reported_at?: string
  location?: string
  content?: string
  source_type?: CaseSourceType | string
  verification_status?: string
  resolution?: string
  prevention_actions?: Array<Record<string, unknown>>
  created_at?: string
  updated_at?: string
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
  management?: {
    report_quality_score?: number
    report_quality_level?: CaseQualityLevel | string
    missing_fields?: string[]
    timeliness?: {
      reported_within_1h?: boolean
      entered_within_48h?: boolean
    }
    recommended_completion_actions?: string[]
  }
  analysis_readiness?: {
    spacetime?: string
    gang?: string
    patrol?: string
    roundtable?: string
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
  report_time?: string
  report_unit?: string
  source_type?: CaseSourceType | string
  source_detail?: string
  police_reported?: boolean
  case_filed?: boolean
  police_officer?: string
  police_phone?: string
  security_officers?: string[]
  oil_nature?: OilNature | string
  water_cut?: number
  vehicle_handling?: string
  person_handling?: string
  oil_handling?: string
  operation_role?: string
  current_stage?: string
  quality_score?: number
  quality_level?: CaseQualityLevel
  quality_issues?: CaseQuality
  quality_updated_at?: string
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
  report_time?: string
  report_unit?: string
  source_type?: CaseSourceType | string
  source_detail?: string
  police_reported?: boolean
  case_filed?: boolean
  police_officer?: string
  police_phone?: string
  security_officers?: string[]
  oil_nature?: OilNature | string
  water_cut?: number
  vehicle_handling?: string
  person_handling?: string
  oil_handling?: string
  operation_role?: string
  current_stage?: string
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
  confidence?: number
  facts?: string[]
  inferences?: string[]
  recommendations?: string[]
  information_gaps?: string[]
  evidence_refs?: string[]
  boundary?: string[]
  mode?: string
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

// ============ 犯罪链条相关类型 ============

export type ChainPosition = 'upstream' | 'midstream' | 'downstream' | 'unknown'
export type ChainLinkStatus = 'inferred' | 'confirmed' | 'rejected'
export type ChainLinkType = 'upstream_transport' | 'transport_storage' | string

export interface ChainCaseBrief {
  id: number
  case_number: string
  case_type?: string
  facility_type?: string
  chain_position: ChainPosition
  chain_label: string
  occurred_time?: string
  location?: string
  latitude?: number
  longitude?: number
}

export interface ChainLink {
  id: number
  case_id_a: number
  case_id_b: number
  link_type: ChainLinkType
  status: ChainLinkStatus
  confidence: number
  distance_km: number
  time_diff_days: number
  reasoning?: string
  created_at?: string
  confirmed_by?: string
  confirmed_at?: string
  from_case?: ChainCaseBrief
  to_case?: ChainCaseBrief
}

export interface ChainLinkLine {
  id: number
  status: Exclude<ChainLinkStatus, 'rejected'>
  confidence: number
  distanceKm: number
  timeDiffDays: number
  reasoning?: string
  from: {
    id: number
    lat: number
    lng: number
    caseNumber: string
    chainPosition: ChainPosition
  }
  to: {
    id: number
    lat: number
    lng: number
    caseNumber: string
    chainPosition: ChainPosition
  }
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

export interface CaseDrivenPatrolPlan {
  generated_at: string
  analysis_days: number
  area_count: number
  areas: Array<{
    area_name: string
    case_count: number
    case_ids: number[]
    center: {
      latitude?: number | null
      longitude?: number | null
    }
    priority_score: number
    risk_level: string
    average_quality_score: number
    source_types: string[]
    oil_natures: string[]
    recommended_windows: Array<{
      start_hour: number
      end_hour: number
      label: string
      case_count: number
      risk_level: string
    }>
    patrol_focus: string[]
    completion_actions: string[]
  }>
  data_quality: {
    total_cases: number
    missing_geo_case_count: number
    low_quality_case_count: number
    note: string
  }
}

// ============ 相似条件组分析类型（兼容旧 gangs API 命名） ============

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
  chainPosition?: ChainPosition
  occurredTime?: string
  modus?: string
}

export interface SerialGroup {
  caseIds: number[]
  color?: string
}

// ── 保卫人员 ─────────────────────────────────────────────────────────────────
export interface SecurityPersonnel {
  id: number
  name: string
  badge_number?: string
  department?: string
  position?: string
  phone?: string
  status: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface SecurityPersonnelCreate {
  name: string
  badge_number?: string
  department?: string
  position?: string
  phone?: string
  status?: string
  notes?: string
}

// ── 重要部位 ─────────────────────────────────────────────────────────────────
export interface KeyLocation {
  id: number
  name: string
  location_type: string
  latitude?: number
  longitude?: number
  address?: string
  description?: string
  risk_level: number
  status: string
  created_at: string
  updated_at: string
}

export interface KeyLocationCreate {
  name: string
  location_type: string
  latitude?: number
  longitude?: number
  address?: string
  description?: string
  risk_level?: number
  status?: string
}
