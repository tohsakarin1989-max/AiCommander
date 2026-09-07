import api from './api'
import type {
  AgentOperationsOverview,
  AgentRun,
  AgentRunEvent,
  AgentRunTaskType,
} from '../types'

export interface AgentRunCreatePayload {
  task_type: AgentRunTaskType
  query: string
  case_ids?: number[]
  asset_ids?: number[]
}

export const agentRunApi = {
  create: async (payload: AgentRunCreatePayload) => {
    const response = await api.post<AgentRun>('/agent-runs', payload)
    return response.data
  },
  list: async () => {
    const response = await api.get<AgentRun[]>('/agent-runs')
    return response.data
  },
  overview: async (days = 30) => {
    const response = await api.get<AgentOperationsOverview>('/agent-runs/overview', {
      params: { days },
    })
    return response.data
  },
  get: async (runId: string) => {
    const response = await api.get<AgentRun>(`/agent-runs/${runId}`)
    return response.data
  },
  events: async (runId: string, afterSequence = 0) => {
    const response = await api.get<AgentRunEvent[]>(`/agent-runs/${runId}/events`, {
      params: { after_sequence: afterSequence },
    })
    return response.data
  },
  cancel: async (runId: string) => {
    const response = await api.post<AgentRun>(`/agent-runs/${runId}/cancel`)
    return response.data
  },
  replay: async (runId: string) => {
    const response = await api.post<AgentRun>(`/agent-runs/${runId}/replay`)
    return response.data
  },
  review: async (
    runId: string,
    approvalId: string,
    decision: 'approve' | 'reject',
    comment?: string,
  ) => {
    const response = await api.post(`/agent-runs/${runId}/approvals/${approvalId}`, {
      decision,
      comment,
    })
    return response.data
  },
}
