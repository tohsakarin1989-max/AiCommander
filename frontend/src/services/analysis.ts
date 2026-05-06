/**
 * 分析报告服务
 * 合并：部署建议、案件图谱
 */
import api from './api'

// ==================== 类型定义 ====================

// 部署报告
export interface DeploymentReport {
  summary: {
    analysis_period: string
    key_findings: string[]
    priority_actions: string[]
  }
  temporal_analysis: unknown
  target_analysis: unknown
  patrol_routes: unknown
  resource_allocation: unknown
  prevention_measures: unknown
}

// 智能研判报告
export interface SmartAnalysisReport {
  analysis_time: string
  time_window_days: number
  duration_seconds?: number
  modules: {
    hotspots?: {
      status: string
      case_count: number
      hotspot_count: number
      high_risk_count: number
      hotspots: Array<{
        center: { latitude: number; longitude: number }
        case_count: number
        risk_score: number
      }>
    }
    gangs?: {
      status: string
      gang_count: number
      high_risk_gang_count: number
      total_cases_in_gangs: number
      top_gangs: Array<{
        case_count: number
        risk_score: number
        modus_operandi: string[]
        known_vehicles: string[]
      }>
    }
    patterns?: {
      status: string
      case_count: number
      patterns: {
        peak_hours: Array<{ hour: number; count: number }>
        peak_days: Array<{ day: string; count: number }>
        case_types: Record<string, number>
        modus_operandi: Record<string, number>
      }
    }
    deployment?: {
      status: string
      suggestion_count: number
      suggestions: Array<{
        type: string
        priority: string
        action: string
        reason: string
        location?: string
        coordinates?: { latitude?: number | null; longitude?: number | null }
      }>
    }
    jurisdiction?: {
      status: string
      case_id?: number | null
      asset_summary?: {
        total: number
        by_type: Record<string, number>
        by_source: Record<string, number>
        by_status: Record<string, number>
      }
      data_quality?: {
        coverage_score: number
        missing_coordinates: number
        unverified_count: number
        duplicate_candidates: number
        recommendations: string[]
      }
      patrol_plan?: {
        control_points: Array<{ asset: { name: string }; reason: string; priority: number }>
      }
      similar_targets?: {
        items: Array<Record<string, unknown>>
      }
      error?: string
    }
    case_intelligence?: {
      status: string
      case_id?: number | null
      tag_count: number
      similar_case_count: number
      suggestion_count: number
      area_profile_count: number
      insights: string[]
      top_suggestions: Array<{
        title: string
        priority: string
        action: string
        reason?: string[]
      }>
      boundary?: string
      error?: string
    }
  }
  summary: {
    overall_risk_level: 'low' | 'medium' | 'high' | 'critical'
    overall_risk_score: number
    risk_factors: string[]
    case_count: number
    hotspot_count: number
    gang_count: number
    jurisdiction_coverage_score?: number | null
    case_intelligence_suggestion_count?: number
    key_insights: string[]
  }
  priority_actions: Array<{
    priority: number
    action: string
    description: string
    category: string
  }>
  recommendations: string[]
  error?: string
}

// 图谱
export interface GraphNode {
  id: number
  case_number: string
  case_type?: string | null
  location?: string | null
  latitude?: number | null
  longitude?: number | null
  modus_operandi?: string | null
  occurred_time?: string | null
  oil_type?: string | null
  oil_volume?: number | null
  facility_type?: string | null
  involved_persons_count: number
  has_vehicle: boolean
}

export interface GraphEdge {
  source: number
  target: number
  reasons: string[]
  score: number
  relation_types: string[]
  dominant_type: string
}

export interface SerialGraphStats {
  total_nodes: number
  total_edges: number
  person_links: number
  vehicle_links: number
  duplicate_anchor_links?: number
  modus_links: number
  geo_links: number
  strong_links: number
}

export interface SerialGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats?: SerialGraphStats
}

// ==================== API 实现 ====================

export const analysisApi = {
  // ---------- 智能研判（一键分析） ----------
  smart: {
    /** 一键智能研判 */
    analyze: async (params?: {
      time_window_days?: number
      min_cases?: number
      include_deployment?: boolean
    }): Promise<SmartAnalysisReport> => {
      const response = await api.post<SmartAnalysisReport>('/deployment/smart-analysis', null, {
        params: {
          time_window_days: params?.time_window_days ?? 90,
          min_cases: params?.min_cases ?? 2,
          include_deployment: params?.include_deployment ?? true,
        },
      })
      return response.data
    },
  },

  // ---------- 部署建议 ----------
  deployment: {
    /** 获取综合部署报告 */
    getReport: async (days = 90) => {
      const response = await api.get<DeploymentReport>('/deployment/report', {
        params: { days },
      })
      return response.data
    },

    /** 获取时间规律分析 */
    getTemporalPatterns: async (days = 90) => {
      const response = await api.get('/deployment/temporal-patterns', {
        params: { days },
      })
      return response.data
    },

    /** 获取目标对象分析 */
    getTargetPatterns: async () => {
      const response = await api.get('/deployment/target-patterns')
      return response.data
    },

    /** 获取巡逻路线建议 */
    getPatrolRoutes: async () => {
      const response = await api.get('/deployment/patrol-routes')
      return response.data
    },

    /** 获取资源配置建议 */
    getResourceAllocation: async () => {
      const response = await api.get('/deployment/resource-allocation')
      return response.data
    },

    /** 获取防范措施建议 */
    getPreventionMeasures: async () => {
      const response = await api.get('/deployment/prevention-measures')
      return response.data
    },
  },

  // ---------- 案件图谱 ----------
  graph: {
    /** 构建串案关系图谱 */
    buildSerial: async (caseIds: number[]) => {
      const response = await api.post<SerialGraph>('/graphs/serial', { case_ids: caseIds })
      return response.data
    },
  },
}

// 向后兼容
export const deploymentApi = analysisApi.deployment
export const graphApi = analysisApi.graph
