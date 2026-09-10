import api from './api'

export type IntelligenceRuntimeOverview = {
  orchestrator: string
  business_agents: string[]
  versions: {
    algorithms: Array<{ component: string; version: string; checksum: string }>
    scope_policy: { version: string; checksum: string }
  }
  latest_evaluation?: {
    id: string
    status: string
    metrics: Record<string, number | string | null>
    completed_at?: string | null
  } | null
  formal_case_mutations_allowed: boolean
  execution_task_creation_allowed: boolean
  external_model_required: boolean
}

export const governanceApi = {
  getRuntimeOverview: async (): Promise<IntelligenceRuntimeOverview> => {
    const response = await api.get<IntelligenceRuntimeOverview>('/admin/intelligence-runtime/overview')
    return response.data
  },
}
