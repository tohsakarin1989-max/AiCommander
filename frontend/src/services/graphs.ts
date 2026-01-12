import api from './api'

export interface GraphNode {
  id: number
  case_number: string
  case_type?: string
  location?: string
  latitude?: number
  longitude?: number
  modus_operandi?: string
}

export interface GraphEdge {
  source: number
  target: number
  reasons: string[]
  score: number
}

export interface SerialGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export const graphApi = {
  buildSerial: async (caseIds: number[], radiusKm = 2.0): Promise<SerialGraph> => {
    const response = await api.post('/graphs/serial', caseIds, {
      params: { radius_km: radiusKm },
    })
    return response.data
  },
}
