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
