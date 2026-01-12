import api from './api'

export interface DeploymentReport {
  summary: {
    analysis_period: string
    key_findings: string[]
    priority_actions: string[]
  }
  temporal_analysis: any
  target_analysis: any
  patrol_routes: any
  resource_allocation: any
  prevention_measures: any
  generated_at: string
}

export const deploymentApi = {
  getReport: async (days = 90): Promise<DeploymentReport> => {
    const response = await api.get('/deployment/report', { params: { days } })
    return response.data
  },

  getTemporalPatterns: async (days = 90): Promise<any> => {
    const response = await api.get('/deployment/temporal-patterns', { params: { days } })
    return response.data
  },

  getTargetPatterns: async (): Promise<any> => {
    const response = await api.get('/deployment/target-patterns')
    return response.data
  },

  getPatrolRoutes: async (radiusKm = 2.0): Promise<any> => {
    const response = await api.get('/deployment/patrol-routes', {
      params: { radius_km: radiusKm },
    })
    return response.data
  },

  getResourceAllocation: async (): Promise<any> => {
    const response = await api.get('/deployment/resource-allocation')
    return response.data
  },

  getPreventionMeasures: async (): Promise<any> => {
    const response = await api.get('/deployment/prevention-measures')
    return response.data
  },
}

