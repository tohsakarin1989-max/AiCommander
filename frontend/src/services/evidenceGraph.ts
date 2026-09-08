import api from './api'


export type EvidenceGraphLayer = 'subject' | 'source' | 'context' | 'analysis' | 'conclusion' | 'gap'
export type EvidenceGraphStatus =
  | 'recorded'
  | 'verified'
  | 'confirmed'
  | 'draft'
  | 'inferred'
  | 'contextual'
  | 'missing'
  | 'derived'
  | 'degraded'
  | 'archived'
  | 'rejected'

export interface EvidenceGraphNode {
  id: string
  type: 'case' | 'case_fact' | 'case_evidence' | 'knowledge_asset' | 'related_case' | 'well' | 'map_asset' | 'agent_artifact' | 'gap'
  layer: EvidenceGraphLayer
  label: string
  subtitle: string
  status: EvidenceGraphStatus
  confidence: number
  source_ref: string
  is_human_confirmed: boolean
  detail: Record<string, unknown>
}

export interface EvidenceGraphEdge {
  id: string
  source: string
  target: string
  relation: string
  label: string
  status: 'recorded' | 'verified' | 'confirmed' | 'inferred' | 'contextual' | 'rejected'
  confidence: number
  evidence_refs: string[]
  boundary: string
}

export interface EvidenceReviewItem {
  id: string
  code: string
  severity: 'high' | 'medium' | 'low'
  title: string
  detail: string
  related_node_ids: string[]
  next_action: string
}

export interface EvidenceGraphPayload {
  case_id: number
  case_number: string
  generated_at: string
  source_snapshot: {
    algorithm: 'sha256'
    data_version: string
    scope: string
  }
  summary: {
    total_nodes: number
    total_edges: number
    source_nodes: number
    confirmed_nodes: number
    inferred_nodes: number
    gap_nodes: number
    traceability_rate: number
    graph_health: 'complete' | 'review_needed' | 'insufficient'
  }
  nodes: EvidenceGraphNode[]
  edges: EvidenceGraphEdge[]
  review_queue: EvidenceReviewItem[]
  boundary: {
    read_only: true
    statements: string[]
  }
}

export const evidenceGraphApi = {
  getCaseGraph: async (
    caseId: number,
    options: { wellRadiusKm?: number; maxContextNodes?: number } = {},
  ): Promise<EvidenceGraphPayload> => {
    const response = await api.get<EvidenceGraphPayload>(`/graphs/evidence/${caseId}`, {
      params: {
        well_radius_km: options.wellRadiusKm ?? 5,
        max_context_nodes: options.maxContextNodes ?? 20,
      },
    })
    return response.data
  },
}
