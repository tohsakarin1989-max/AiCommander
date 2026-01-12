import api from './api'

export interface Case {
  id: number
  case_number: string
  occurred_time: string
  location?: string
  latitude?: number
  longitude?: number
  case_type?: string
  description?: string
  involved_persons?: any
  involved_items?: any
  loss_amount?: number
  // 涉油案件特征
  oil_type?: string
  oil_volume?: number
  oil_value?: number
  facility_type?: string
  facility_owner?: string
  security_level?: string
  modus_operandi?: string
  suspect_roles?: any
  vehicle_info?: any
  upstream_source?: string
  downstream_destination?: string
  // 结构化预处理结果（来自后端 features 字段）
  features?: any
  status: string
}

export interface CaseCreate {
  occurred_time: string
  location?: string
  latitude?: number
  longitude?: number
  case_type?: string
  description?: string
  involved_persons?: any
  involved_items?: any
  loss_amount?: number
  // 涉油案件特征
  oil_type?: string
  oil_volume?: number
  oil_value?: number
  facility_type?: string
  facility_owner?: string
  security_level?: string
  modus_operandi?: string
  suspect_roles?: any
  vehicle_info?: any
  upstream_source?: string
  downstream_destination?: string
}

export const caseApi = {
  getCases: async (skip = 0, limit = 100): Promise<Case[]> => {
    const response = await api.get('/cases', { params: { skip, limit } })
    return response.data
  },

  getCase: async (id: number): Promise<Case> => {
    const response = await api.get(`/cases/${id}`)
    return response.data
  },

  createCase: async (data: CaseCreate): Promise<Case> => {
    const response = await api.post('/cases', data)
    return response.data
  },

  updateCase: async (id: number, data: Partial<Case>): Promise<Case> => {
    const response = await api.put(`/cases/${id}`, data)
    return response.data
  },

  getNearbyCases: async (
    caseId: number,
    radiusKm: number = 1,
  ): Promise<Case[]> => {
    const response = await api.get(`/cases/${caseId}/nearby`, {
      params: { radius_km: radiusKm },
    })
    return response.data
  },

  getPreprocessStatus: async (): Promise<{
    pending: number
    processing: number
    success: number
    avg_duration_seconds: number | null
  }> => {
    const response = await api.get('/cases/preprocess/status')
    return response.data
  },

  preprocessCase: async (id: number): Promise<{ message: string }> => {
    const response = await api.post(`/cases/${id}/preprocess`)
    return response.data
  },

  deleteCase: async (id: number): Promise<void> => {
    await api.delete(`/cases/${id}`)
  },

  getGeographicAnalysis: async (caseIds?: number[]): Promise<any> => {
    const params = caseIds ? { case_ids: caseIds } : {}
    const response = await api.get('/cases/geo/analysis', { params })
    return response.data
  },

  getHotspots: async (radiusKm = 0.5, minCases = 3): Promise<any> => {
    const response = await api.get('/cases/geo/hotspots', {
      params: { radius_km: radiusKm, min_cases: minCases },
    })
    return response.data
  },

  getSerialCases: async (
    caseIds?: number[],
    maxDistanceKm = 2.0,
    timeWindowDays = 30,
    useSemantic = true,
    useGeo = true,
    minSemanticSimilarity = 0.6
  ): Promise<any> => {
    const params: any = {
      max_distance_km: maxDistanceKm,
      time_window_days: timeWindowDays,
      use_semantic: useSemantic,
      use_geo: useGeo,
      min_semantic_similarity: minSemanticSimilarity,
    }
    if (caseIds) {
      params.case_ids = caseIds
    }
    const response = await api.get('/cases/geo/serial-cases', { params })
    return response.data
  },

  semanticSearch: async (
    query: string,
    topK = 10,
    minSimilarity = 0.5
  ): Promise<any> => {
    const response = await api.get('/cases/semantic/search', {
      params: { query, top_k: topK, min_similarity: minSimilarity },
    })
    return response.data
  },

  getTrajectory: async (caseIds: number[]): Promise<any> => {
    const ids = caseIds.join(',')
    const response = await api.get(`/cases/trajectory/${ids}`)
    return response.data
  },

  analyzeTrajectory: async (caseIds: number[]): Promise<any> => {
    const ids = caseIds.join(',')
    const response = await api.get(`/cases/trajectory/${ids}/analysis`)
    return response.data
  },

  predictNextLocation: async (caseIds: number[], useAI = true): Promise<any> => {
    const ids = caseIds.join(',')
    const response = await api.get(`/cases/trajectory/${ids}/predict`, {
      params: { use_ai: useAI },
    })
    return response.data
  },

  getTrajectoryReplay: async (caseIds: number[], intervalSeconds = 60): Promise<any> => {
    const ids = caseIds.join(',')
    const response = await api.get(`/cases/trajectory/${ids}/replay`, {
      params: { interval_seconds: intervalSeconds },
    })
    return response.data
  },
}

