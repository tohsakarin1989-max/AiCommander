/**
 * 案件数据 API 服务
 * 类型定义统一从 types/ 导入
 */
import api from './api'
import type {
  BonusAssessment,
  Case,
  CaseAutomationWorkbench,
  CaseCreate,
  CaseUpdatePayload,
  CaseEvidence,
  CaseEvidenceClassification,
  ChainLink,
  CasePerson,
  CaseQuality,
  CaseStructurePreview,
  CaseTip,
  CaseVehicle,
  GeoAnalysisResult,
  Hotspot,
  OilRecoveryRecord,
  SerialCaseGroup,
  PreprocessStatus,
  TrajectoryPoint,
  TrajectoryAnalysis,
  TrajectoryPrediction,
  TrajectoryReplayFrame,
  SemanticSearchResult,
  CaseStatistics,
} from '../types'

export interface CaseImportError {
  row: number
  error: string
}

export interface CaseImportResult {
  total: number
  created: number
  updated: number
  valid?: number
  dry_run?: boolean
  preview?: Array<Record<string, unknown>>
  errors: CaseImportError[]
}

export const caseApi = {
  /**
   * 从案情文本中预提取案件字段
   */
  structureCaseText: async (text: string): Promise<CaseStructurePreview> => {
    const response = await api.post<CaseStructurePreview>('/cases/structure-preview', { text })
    return response.data
  },

  /**
   * 识别佐证材料类型
   */
  classifyEvidence: async (data: Partial<CaseEvidence>): Promise<CaseEvidenceClassification> => {
    const response = await api.post<CaseEvidenceClassification>('/cases/evidence/classify', data)
    return response.data
  },

  /**
   * 获取案件统计数据
   */
  getStatistics: async (): Promise<CaseStatistics> => {
    const response = await api.get<CaseStatistics>('/cases/statistics')
    return response.data
  },

  /**
   * 获取案件列表（支持筛选）
   */
  getCases: async (params?: {
    skip?: number
    limit?: number
    keyword?: string
    status?: string
    case_type?: string
    oil_type?: string
    source_type?: string
    report_unit?: string
    current_stage?: string
    quality_level?: string
    min_quality_score?: number
    max_quality_score?: number
    start_date?: string
    end_date?: string
    has_geo?: boolean
    missing_location?: boolean
  }): Promise<Case[]> => {
    const response = await api.get<Case[]>('/cases', {
      params: {
        skip: params?.skip ?? 0,
        limit: params?.limit ?? 100,
        ...params,
      },
    })
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
  updateCase: async (id: number, data: CaseUpdatePayload): Promise<Case> => {
    const response = await api.put<Case>(`/cases/${id}`, data)
    return response.data
  },

  /**
   * 仅补录案件坐标
   */
  updateCaseLocation: async (id: number, data: { latitude: number; longitude: number }): Promise<Case> => {
    const response = await api.patch<Case>(`/cases/${id}/location`, data)
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
   * 获取案件信息质量评分
   */
  getCaseQuality: async (caseId: number): Promise<CaseQuality> => {
    const response = await api.get<CaseQuality>(`/cases/${caseId}/quality`)
    return response.data
  },

  /**
   * 重新计算案件信息质量评分
   */
  recalculateCaseQuality: async (caseId: number): Promise<CaseQuality> => {
    const response = await api.post<CaseQuality>(`/cases/${caseId}/quality/recalculate`)
    return response.data
  },

  /**
   * 获取案件统一画像
   */
  getFeatureProfile: async (caseId: number): Promise<Record<string, unknown>> => {
    const response = await api.get<Record<string, unknown>>(`/cases/${caseId}/feature-profile`)
    return response.data
  },

  getCaseVehicles: async (caseId: number): Promise<CaseVehicle[]> => {
    const response = await api.get<CaseVehicle[]>(`/cases/${caseId}/vehicles`)
    return response.data
  },

  createCaseVehicle: async (caseId: number, data: Partial<CaseVehicle>): Promise<CaseVehicle> => {
    const response = await api.post<CaseVehicle>(`/cases/${caseId}/vehicles`, data)
    return response.data
  },

  getCasePersons: async (caseId: number): Promise<CasePerson[]> => {
    const response = await api.get<CasePerson[]>(`/cases/${caseId}/persons`)
    return response.data
  },

  createCasePerson: async (caseId: number, data: Partial<CasePerson>): Promise<CasePerson> => {
    const response = await api.post<CasePerson>(`/cases/${caseId}/persons`, data)
    return response.data
  },

  getCaseEvidence: async (caseId: number): Promise<CaseEvidence[]> => {
    const response = await api.get<CaseEvidence[]>(`/cases/${caseId}/evidence`)
    return response.data
  },

  createCaseEvidence: async (caseId: number, data: Partial<CaseEvidence>): Promise<CaseEvidence> => {
    const response = await api.post<CaseEvidence>(`/cases/${caseId}/evidence`, data)
    return response.data
  },

  getBonusAssessment: async (caseId: number): Promise<BonusAssessment> => {
    const response = await api.get<BonusAssessment>(`/cases/${caseId}/bonus-assessment`)
    return response.data
  },

  getAutomationWorkbench: async (caseId: number): Promise<CaseAutomationWorkbench> => {
    const response = await api.get<CaseAutomationWorkbench>(`/cases/${caseId}/automation-workbench`)
    return response.data
  },

  getChainLinks: async (caseId: number, includeRejected = false): Promise<ChainLink[]> => {
    const response = await api.get<ChainLink[]>('/chain-links', {
      params: { case_id: caseId, include_rejected: includeRejected },
    })
    return response.data
  },

  confirmChainLink: async (linkId: number, operator = '人工确认'): Promise<ChainLink> => {
    const response = await api.post<ChainLink>(`/chain-links/${linkId}/confirm`, { operator })
    return response.data
  },

  rejectChainLink: async (linkId: number): Promise<ChainLink> => {
    const response = await api.post<ChainLink>(`/chain-links/${linkId}/reject`)
    return response.data
  },

  getChainMapData: async (params?: { case_id?: number; min_confidence?: number }): Promise<{ chain_links: ChainLink[]; total: number }> => {
    const response = await api.get<{ chain_links: ChainLink[]; total: number }>('/chain-links/map-data', { params })
    return response.data
  },

  calculateBonusAssessment: async (
    caseId: number,
    rules?: Record<string, unknown>
  ): Promise<BonusAssessment> => {
    const response = await api.post<BonusAssessment>(`/cases/${caseId}/bonus-assessment/calculate`, { rules })
    return response.data
  },

  getOilRecoveryRecords: async (caseId: number): Promise<OilRecoveryRecord[]> => {
    const response = await api.get<OilRecoveryRecord[]>(`/cases/${caseId}/oil-recovery`)
    return response.data
  },

  createOilRecoveryRecord: async (caseId: number, data: Partial<OilRecoveryRecord>): Promise<OilRecoveryRecord> => {
    const response = await api.post<OilRecoveryRecord>(`/cases/${caseId}/oil-recovery`, data)
    return response.data
  },

  getCaseTips: async (params?: { case_id?: number; verification_status?: string }): Promise<CaseTip[]> => {
    const response = await api.get<CaseTip[]>('/cases/tips', { params })
    return response.data
  },

  createCaseTip: async (data: Partial<CaseTip>): Promise<CaseTip> => {
    const response = await api.post<CaseTip>('/cases/tips', data)
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
    const response = await api.get<{ hotspots: unknown[] }>('/cases/geo/hotspots', {
      params: { radius_km: radiusKm, min_cases: minCases },
    })
    // 后端返回 center_latitude/center_longitude 扁平字段，统一转换为 center: GeoPoint
    return (response.data.hotspots ?? []).map((h: unknown) => {
      const raw = h as Record<string, unknown>
      return {
        center: {
          latitude: (raw.center_latitude ?? (raw.center as Record<string, number>)?.latitude ?? 0) as number,
          longitude: (raw.center_longitude ?? (raw.center as Record<string, number>)?.longitude ?? 0) as number,
        },
        radius_km: raw.radius_km as number,
        case_count: raw.case_count as number,
        case_ids: (raw.case_ids ?? []) as number[],
        risk_score: (raw.risk_score ?? (raw.case_count as number) * 0.1) as number,
        cases: raw.cases,
      } as Hotspot & { cases?: unknown }
    })
  },

  /**
   * 获取串案分析
   */
  getSerialCases: async (
    caseIds?: number[],
    maxDistanceKm = 2.0,
    timeWindowDays = 30,
    useSemantic = false,
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
    const response = await api.get<{ serial_cases: unknown[] }>('/cases/geo/serial-cases', { params })
    // 后端返回 cases 数组+case_count，前端类型期望 case_ids[]，在此统一转换
    return (response.data.serial_cases ?? []).map((g: unknown) => {
      const raw = g as Record<string, unknown>
      const casesArr = (raw.cases ?? []) as Array<Record<string, unknown>>
      const caseIds = casesArr.map(c => c.id as number)
      return {
        group_id: String(raw.group_id ?? ''),
        case_ids: caseIds,
        similarity_score: (raw.similarity_score ?? 0) as number,
        common_features: raw.common_case_type ? [raw.common_case_type as string] : [],
        time_span_days: (raw.time_span_days ?? 0) as number,
        geographic_spread_km: (raw.geographic_spread_km ?? 0) as number,
        // 透传额外字段供其他组件使用
        case_count: (raw.case_count ?? caseIds.length) as number,
        center_latitude: (raw.center_latitude ?? 0) as number,
        center_longitude: (raw.center_longitude ?? 0) as number,
        cases: casesArr,
      } as SerialCaseGroup
    })
  },

  /**
   * 语义搜索
   */
  semanticSearch: async (
    query: string,
    topK = 10,
    minSimilarity = 0.5
  ): Promise<SemanticSearchResult[]> => {
    const response = await api.get<{ results: SemanticSearchResult[] }>('/cases/semantic/search', {
      params: { query, top_k: topK, min_similarity: minSimilarity },
    })
    return response.data.results ?? []
  },

  /**
   * 获取轨迹数据
   */
  getTrajectory: async (caseIds: number[]): Promise<TrajectoryPoint[]> => {
    const ids = caseIds.join(',')
    const response = await api.get<{ trajectory: TrajectoryPoint[] }>(`/cases/trajectory/${ids}`)
    return response.data.trajectory ?? []
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

  /**
   * 获取热点时间演化数据（按月分段）
   */
  getHotspotEvolution: async (params?: {
    months?: number
    radius_km?: number
    min_cases?: number
  }): Promise<{
    periods: Array<{
      period: string          // "2024-11"
      start_date: string
      end_date: string
      hotspots: Array<{
        center_latitude: number
        center_longitude: number
        case_count: number
        radius_km: number
        hotspot_key: string
      }>
      total_cases: number
    }>
    trend_summary: {
      heating_up: number
      cooling_down: number
      stable: number
      new_hotspots: number
    }
    months_analyzed: number
  }> => {
    const response = await api.get('/cases/hotspot-evolution', { params })
    return response.data
  },

  /**
   * 导入案件（Excel/CSV文件）
   */
  importCases: async (file: File, dryRun = false): Promise<CaseImportResult> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post<CaseImportResult>('/cases/import', formData, {
      params: { dry_run: dryRun },
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  /**
   * 导入前预览，校验文件但不写入数据库
   */
  previewImportCases: async (file: File): Promise<CaseImportResult> => {
    return caseApi.importCases(file, true)
  },
}
