import api from './api'

export interface JurisdictionAsset {
  id: number
  external_id?: string | null
  name: string
  asset_type: string
  geometry_type?: string
  latitude?: number | null
  longitude?: number | null
  geometry?: Record<string, unknown> | null
  address?: string | null
  description?: string | null
  source?: string | null
  status?: string | null
  risk_level?: number | null
  confidence_score?: number | null
  verified?: boolean | null
  last_seen_at?: string | null
  tags?: string[] | null
  attributes?: Record<string, unknown> | null
  created_at?: string | null
  updated_at?: string | null
}

export interface JurisdictionAssetCreate {
  external_id?: string
  name: string
  asset_type: string
  geometry_type?: string
  latitude?: number
  longitude?: number
  geometry?: Record<string, unknown>
  address?: string
  description?: string
  source?: string
  status?: string
  risk_level?: number
  confidence_score?: number
  verified?: boolean
  tags?: string[]
  attributes?: Record<string, unknown>
}

export interface JurisdictionAssetSummary {
  total: number
  by_type: Record<string, number>
  by_source: Record<string, number>
  by_status: Record<string, number>
  by_layer?: Record<string, number>
  layer_labels?: Record<string, string>
}

export interface AssetTableImportResult {
  total: number
  valid: number
  created: number
  updated: number
  errors: Array<{ row: number; error: string }>
  items: Array<JurisdictionAsset | JurisdictionAssetCreate>
}

export interface PublicMapSyncRequest {
  south?: number
  west?: number
  north?: number
  east?: number
  center_lat?: number
  center_lng?: number
  radius_km?: number
  max_features?: number
}

export interface PublicMapSyncResult {
  total: number
  created: number
  updated: number
  pulled: number
  usable: number
  provider: string
  bounds: {
    south: number
    west: number
    north: number
    east: number
  }
  errors: string[]
  items: JurisdictionAsset[]
}

export interface JurisdictionDistance {
  asset: JurisdictionAsset
  distance_km: number
}

export interface CaseRiskContext {
  case_id: number
  case_number: string
  case_type?: string | null
  occurred_time?: string | null
  has_geo: boolean
  nearest: {
    road?: JurisdictionDistance | null
    village?: JurisdictionDistance | null
    production_target?: JurisdictionDistance | null
    tech?: JurisdictionDistance | null
    patrol_point?: JurisdictionDistance | null
  }
  risk_conditions: string[]
  prevention_opportunities: string[]
  risk_score: number
}

export interface SimilarTarget {
  asset: JurisdictionAsset
  similarity_score: number
  reasons: string[]
  risk_gaps: string[]
  nearest: CaseRiskContext['nearest']
}

export interface SimilarTargetsResponse {
  case_id: number
  items: SimilarTarget[]
  basis: CaseRiskContext
}

export interface CaseExperienceCard {
  case_id: number
  case_number: string
  summary: string
  time_pattern: {
    period: string
    hour?: number | null
    weekday?: number | null
    is_night?: boolean
  }
  spatial_conditions: string[]
  modus_tags: string[]
  defense_gaps: string[]
  reusable_lessons: string[]
  evidence_basis: Record<string, unknown>
}

export interface AssetRiskProfile {
  asset: JurisdictionAsset
  risk_score: number
  risk_level: string
  nearest: CaseRiskContext['nearest']
  related_cases: Array<Record<string, unknown>>
  risk_reasons: string[]
  recommendations: string[]
}

export interface PatrolPlan {
  case_id?: number | null
  control_points: Array<{ asset: JurisdictionAsset; reason: string; priority: number }>
  control_lines: Array<{ name: string; type: string; reason: string }>
  control_areas: Array<{ name: string; reason: string }>
  time_windows: Array<{ period: string; reason: string }>
  tactics: string[]
  basis: Record<string, unknown>
}

export interface MaterializedPatrolRecord {
  id: number
  patrol_number: string
  patrol_type: string
  area_name: string
  area_coordinates: Array<Record<string, unknown>>
  officer_count: number
  officer_names?: string | null
  status: string
  related_case_ids: number[]
  risk_before?: number | null
  created_by?: string | null
  created_at?: string | null
}

export interface MaterializedPatrolPlan {
  created_count: number
  skipped_count: number
  plan: PatrolPlan
  patrol_records: MaterializedPatrolRecord[]
}

export interface RoundtableBriefing {
  case_id: number
  agenda: string[]
  risk_summary: string[]
  recommended_decisions: string[]
  tasks: Array<Record<string, unknown>>
  patrol_plan: PatrolPlan
}

export interface JurisdictionFeedback {
  id: number
  case_id?: number | null
  asset_id?: number | null
  feedback_type: string
  adopted: boolean
  result?: string | null
  effectiveness_score?: number | null
  notes?: string | null
  created_at?: string | null
}

export interface EffectivenessSummary {
  total_feedback: number
  adopted_count: number
  adoption_rate: number
  average_effectiveness?: number | null
  by_type: Record<string, number>
  recent: JurisdictionFeedback[]
}

export interface DataQualitySummary {
  total_assets: number
  missing_coordinates: number
  unverified_count: number
  duplicate_candidates: number
  type_counts: Record<string, number>
  missing_required_types: string[]
  missing_public_reference_types?: string[]
  coverage_score: number
  recommendations: string[]
}

export interface PreventionWorkbench {
  case_id?: number | null
  data_quality: DataQualitySummary
  effectiveness: EffectivenessSummary
  experience_card?: CaseExperienceCard
  risk_context?: CaseRiskContext
  similar_targets?: SimilarTargetsResponse
  patrol_plan: PatrolPlan
  roundtable_briefing?: RoundtableBriefing
  summary?: string
}

export const jurisdictionApi = {
  listAssets: async (params?: {
    asset_type?: string
    source?: string
    status?: string
    skip?: number
    limit?: number
  }): Promise<JurisdictionAsset[]> => {
    const response = await api.get<JurisdictionAsset[]>('/jurisdiction/assets', { params })
    return response.data
  },

  createAsset: async (data: JurisdictionAssetCreate): Promise<JurisdictionAsset> => {
    const response = await api.post<JurisdictionAsset>('/jurisdiction/assets', data)
    return response.data
  },

  updateAsset: async (id: number, data: Partial<JurisdictionAssetCreate>): Promise<JurisdictionAsset> => {
    const response = await api.put<JurisdictionAsset>(`/jurisdiction/assets/${id}`, data)
    return response.data
  },

  deactivateAsset: async (id: number): Promise<JurisdictionAsset> => {
    const response = await api.delete<JurisdictionAsset>(`/jurisdiction/assets/${id}`)
    return response.data
  },

  bulkCreateAssets: async (items: JurisdictionAssetCreate[]): Promise<{
    total: number
    created: number
    items: JurisdictionAsset[]
  }> => {
    const response = await api.post('/jurisdiction/assets/bulk', { items })
    return response.data
  },

  importGeoJson: async (geojson: Record<string, unknown>, source = 'map'): Promise<{
    total: number
    created: number
    updated: number
    errors: string[]
    items: JurisdictionAsset[]
  }> => {
    const response = await api.post('/jurisdiction/assets/import-geojson', { geojson, source })
    return response.data
  },

  syncPublicMapReferences: async (payload: PublicMapSyncRequest = {}): Promise<PublicMapSyncResult> => {
    const response = await api.post<PublicMapSyncResult>('/jurisdiction/assets/sync-public-map', payload)
    return response.data
  },

  importAssetTable: async (file: File, dryRun = false, source = 'ledger'): Promise<AssetTableImportResult> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post<AssetTableImportResult>('/jurisdiction/assets/import-table', formData, {
      params: { dry_run: dryRun, source },
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  },

  getSummary: async (): Promise<JurisdictionAssetSummary> => {
    const response = await api.get<JurisdictionAssetSummary>('/jurisdiction/assets/summary')
    return response.data
  },

  getDataQuality: async (): Promise<DataQualitySummary> => {
    const response = await api.get<DataQualitySummary>('/jurisdiction/data-quality')
    return response.data
  },

  getCaseRiskContext: async (caseId: number): Promise<CaseRiskContext> => {
    const response = await api.get<CaseRiskContext>(`/jurisdiction/cases/${caseId}/risk-context`)
    return response.data
  },

  getCaseExperienceCard: async (caseId: number): Promise<CaseExperienceCard> => {
    const response = await api.get<CaseExperienceCard>(`/jurisdiction/cases/${caseId}/experience-card`)
    return response.data
  },

  getAssetRiskProfile: async (assetId: number): Promise<AssetRiskProfile> => {
    const response = await api.get<AssetRiskProfile>(`/jurisdiction/assets/${assetId}/risk-profile`)
    return response.data
  },

  getSimilarTargets: async (caseId: number, limit = 10): Promise<SimilarTargetsResponse> => {
    const response = await api.get<SimilarTargetsResponse>('/jurisdiction/similar-targets', {
      params: { case_id: caseId, limit },
    })
    return response.data
  },

  createPatrolPlan: async (payload: {
    case_id?: number
    asset_ids?: number[]
    limit?: number
  }): Promise<PatrolPlan> => {
    const response = await api.post<PatrolPlan>('/jurisdiction/patrol-plan', payload)
    return response.data
  },

  materializePatrolPlan: async (payload: {
    case_id?: number
    asset_ids?: number[]
    limit?: number
    officer_count?: number
    officer_names?: string
    created_by?: string
  }): Promise<MaterializedPatrolPlan> => {
    const response = await api.post<MaterializedPatrolPlan>('/jurisdiction/patrol-plan/materialize', payload)
    return response.data
  },

  getRoundtableBriefing: async (caseId: number): Promise<RoundtableBriefing> => {
    const response = await api.get<RoundtableBriefing>('/jurisdiction/roundtable-briefing', {
      params: { case_id: caseId },
    })
    return response.data
  },

  createFeedback: async (payload: {
    case_id?: number
    asset_id?: number
    feedback_type: string
    adopted?: boolean
    result?: string
    effectiveness_score?: number
    notes?: string
  }): Promise<JurisdictionFeedback> => {
    const response = await api.post<JurisdictionFeedback>('/jurisdiction/feedback', payload)
    return response.data
  },

  getEffectiveness: async (): Promise<EffectivenessSummary> => {
    const response = await api.get<EffectivenessSummary>('/jurisdiction/effectiveness')
    return response.data
  },

  getPreventionWorkbench: async (caseId?: number): Promise<PreventionWorkbench> => {
    const response = await api.get<PreventionWorkbench>('/jurisdiction/prevention-workbench', {
      params: caseId ? { case_id: caseId } : undefined,
    })
    return response.data
  },
}
