import type {
  EvidenceGraphEdge,
  EvidenceGraphLayer,
  EvidenceGraphNode,
  EvidenceGraphPayload,
  EvidenceGraphStatus,
} from '../../services/evidenceGraph'


export interface EvidenceGraphFilters {
  showContext: boolean
  showInferred: boolean
  showGaps: boolean
}

export const LAYER_PRESENTATION: Record<EvidenceGraphLayer, { label: string; color: string }> = {
  subject: { label: '案件主体', color: '#53d7ff' },
  source: { label: '原始来源', color: '#74e6b1' },
  context: { label: '双域背景', color: '#6fa8ff' },
  analysis: { label: '派生分析', color: '#e7ad5a' },
  conclusion: { label: '复核成果', color: '#b6eb76' },
  gap: { label: '断链缺口', color: '#ff6b66' },
}

const LAYER_ORDER: EvidenceGraphLayer[] = [
  'subject',
  'source',
  'context',
  'analysis',
  'conclusion',
  'gap',
]

const NODE_SYMBOL: Record<EvidenceGraphNode['type'], string> = {
  case: 'path://M512 64L900 288V736L512 960L124 736V288Z',
  case_fact: 'roundRect',
  case_evidence: 'diamond',
  knowledge_asset: 'rect',
  related_case: 'path://M512 64L900 288V736L512 960L124 736V288Z',
  well: 'pin',
  map_asset: 'circle',
  agent_artifact: 'triangle',
  gap: 'emptyCircle',
}

export function getStatusPresentation(status: EvidenceGraphStatus | EvidenceGraphEdge['status']) {
  const values: Record<string, { label: string; tone: string }> = {
    recorded: { label: '原始记录', tone: 'source' },
    verified: { label: '已核验来源', tone: 'source' },
    confirmed: { label: '人工确认', tone: 'ok' },
    draft: { label: '待人工复核', tone: 'warn' },
    inferred: { label: '待人工确认', tone: 'warn' },
    contextual: { label: '仅作参考', tone: 'context' },
    missing: { label: '证据缺口', tone: 'danger' },
    derived: { label: '规则派生', tone: 'analysis' },
    degraded: { label: '降级结果', tone: 'warn' },
    archived: { label: '已归档', tone: 'muted' },
    rejected: { label: '人工排除', tone: 'danger' },
  }
  return values[status] ?? { label: status, tone: 'muted' }
}

export function getGraphHealthPresentation(status: EvidenceGraphPayload['summary']['graph_health']) {
  return {
    complete: { label: '证据路径完整', tone: 'ok' },
    review_needed: { label: '存在待复核断链', tone: 'warn' },
    insufficient: { label: '关键证据不足', tone: 'danger' },
  }[status]
}

export function filterEvidenceGraph(
  payload: Pick<EvidenceGraphPayload, 'nodes' | 'edges'>,
  filters: EvidenceGraphFilters,
) {
  const hiddenByStatus = new Set<EvidenceGraphStatus>([
    'draft',
    'inferred',
    'derived',
    'degraded',
  ])
  const nodes = payload.nodes.filter((item) => {
    if (!filters.showContext && item.layer === 'context') return false
    if (!filters.showGaps && item.layer === 'gap') return false
    if (!filters.showInferred && hiddenByStatus.has(item.status)) return false
    return true
  })
  const nodeIds = new Set(nodes.map(item => item.id))
  const edges = payload.edges.filter((item) => (
    nodeIds.has(item.source)
    && nodeIds.has(item.target)
    && (filters.showInferred || item.status !== 'inferred')
    && (filters.showContext || item.status !== 'contextual')
  ))
  return { nodes, edges }
}

export function buildEvidenceGraphOption(
  nodes: EvidenceGraphNode[],
  edges: EvidenceGraphEdge[],
) {
  const grouped = new Map<EvidenceGraphLayer, EvidenceGraphNode[]>()
  for (const layer of LAYER_ORDER) grouped.set(layer, [])
  for (const item of nodes) grouped.get(item.layer)?.push(item)

  const data = nodes.map((item) => {
    const siblings = grouped.get(item.layer) ?? []
    const index = siblings.findIndex(candidate => candidate.id === item.id)
    const centerOffset = (siblings.length - 1) / 2
    const presentation = LAYER_PRESENTATION[item.layer]
    return {
      ...item,
      name: item.label,
      x: 85 + LAYER_ORDER.indexOf(item.layer) * 235,
      y: 315 + (index - centerOffset) * 92,
      symbol: NODE_SYMBOL[item.type],
      symbolSize: item.type === 'case' ? 62 : item.layer === 'gap' ? 36 : 46,
      itemStyle: {
        color: item.layer === 'gap' ? 'transparent' : presentation.color,
        borderColor: presentation.color,
        borderWidth: item.is_human_confirmed ? 3 : 1.5,
        shadowBlur: item.type === 'case' ? 18 : 4,
        shadowColor: presentation.color,
      },
      label: {
        show: true,
        position: 'bottom',
        distance: 7,
        color: '#d8e1ea',
        fontSize: 10,
        width: 120,
        overflow: 'truncate',
      },
    }
  })

  const edgeColors: Record<EvidenceGraphEdge['status'], string> = {
    recorded: '#74e6b1',
    verified: '#74e6b1',
    confirmed: '#b6eb76',
    inferred: '#e7ad5a',
    contextual: '#6fa8ff',
    rejected: '#ff6b66',
  }
  return {
    animationDuration: 650,
    tooltip: {
      trigger: 'item',
      renderMode: 'richText',
      formatter: (params: { dataType?: string; data?: EvidenceGraphNode | EvidenceGraphEdge }) => {
        const item = params.data
        if (!item) return ''
        if (params.dataType === 'edge') {
          const edge = item as EvidenceGraphEdge
          return `${edge.label}\n${getStatusPresentation(edge.status).label}\n${edge.boundary}`
        }
        const graphNode = item as EvidenceGraphNode
        return `${graphNode.label}\n${graphNode.subtitle}\n${getStatusPresentation(graphNode.status).label}`
      },
    },
    series: [{
      type: 'graph',
      layout: 'none',
      roam: true,
      zoom: 0.88,
      center: ['50%', '50%'],
      emphasis: { focus: 'adjacency', blurScope: 'global' },
      data,
      links: edges.map(item => ({
        ...item,
        lineStyle: {
          color: edgeColors[item.status],
          width: item.status === 'confirmed' ? 2.6 : 1.4,
          type: item.status === 'inferred' || item.status === 'contextual' ? 'dashed' : 'solid',
          opacity: Math.max(0.42, item.confidence),
          curveness: 0.08,
        },
        symbol: ['none', item.status === 'confirmed' ? 'arrow' : 'none'],
        symbolSize: 8,
      })),
    }],
  }
}
