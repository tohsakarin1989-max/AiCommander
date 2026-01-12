import api from './api'

export interface AgentTask {
  id: number
  query: string
  case_ids: number[]
  status: string
  result: any
  created_at: string
}

export const agentApi = {
  run: async (query: string, caseIds?: number[]): Promise<AgentTask> => {
    const response = await api.post('/agents/run', null, {
      params: { query, case_ids: caseIds },
    })
    return response.data
  },

  list: async (): Promise<AgentTask[]> => {
    const response = await api.get('/agents/tasks')
    return response.data
  },
}
