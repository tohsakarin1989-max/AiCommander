import { describe, expect, it } from 'vitest'
import type { EvidenceGraphNode, EvidenceGraphPayload } from '../../services/evidenceGraph'
import {
  buildEvidenceGraphOption,
  filterEvidenceGraph,
  getGraphHealthPresentation,
  getStatusPresentation,
} from './evidenceGraphPresentation'


const node = (patch: Partial<EvidenceGraphNode>): EvidenceGraphNode => ({
  id: patch.id ?? 'case:1',
  type: patch.type ?? 'case',
  layer: patch.layer ?? 'subject',
  label: patch.label ?? 'EG-001',
  subtitle: patch.subtitle ?? '案件主体',
  status: patch.status ?? 'recorded',
  confidence: patch.confidence ?? 1,
  source_ref: patch.source_ref ?? 'case:1',
  is_human_confirmed: patch.is_human_confirmed ?? false,
  detail: patch.detail ?? {},
})


const payload = (): EvidenceGraphPayload => ({
  case_id: 1,
  case_number: 'EG-001',
  generated_at: '2026-09-08T00:00:00',
  source_snapshot: { algorithm: 'sha256', data_version: 'abc123', scope: 'case:1' },
  summary: {
    total_nodes: 4,
    total_edges: 3,
    source_nodes: 1,
    confirmed_nodes: 1,
    inferred_nodes: 1,
    gap_nodes: 1,
    traceability_rate: 100,
    graph_health: 'review_needed',
  },
  nodes: [
    node({}),
    node({ id: 'evidence:1', type: 'case_evidence', layer: 'source', status: 'recorded' }),
    node({ id: 'well:1', type: 'well', layer: 'context', status: 'verified' }),
    node({ id: 'gap:1', type: 'gap', layer: 'gap', status: 'missing' }),
  ],
  edges: [
    { id: 'e1', source: 'case:1', target: 'evidence:1', relation: 'records', label: '原始材料', status: 'verified', confidence: 1, evidence_refs: ['case:1'], boundary: '' },
    { id: 'e2', source: 'case:1', target: 'well:1', relation: 'spatial_reference', label: '空间参考', status: 'contextual', confidence: 0.6, evidence_refs: ['case:1', 'well:1'], boundary: '不能证明事实关联' },
    { id: 'e3', source: 'case:1', target: 'gap:1', relation: 'requires', label: '待补证', status: 'inferred', confidence: 0, evidence_refs: ['case:1'], boundary: '待人工核验' },
  ],
  review_queue: [],
  boundary: { read_only: true, statements: ['图谱只读'] },
})


describe('evidenceGraphPresentation', () => {
  it('filters contextual and gap branches without removing the case subject', () => {
    const filtered = filterEvidenceGraph(payload(), {
      showContext: false,
      showInferred: true,
      showGaps: false,
    })

    expect(filtered.nodes.map(item => item.id)).toEqual(['case:1', 'evidence:1'])
    expect(filtered.edges.map(item => item.id)).toEqual(['e1'])
  })

  it('lays out an evidence corridor from subject to source, context and gaps', () => {
    const option = buildEvidenceGraphOption(payload().nodes, payload().edges)
    const series = option.series[0]
    const positions = Object.fromEntries(series.data.map(item => [item.id, item.x]))

    expect(positions['case:1']).toBeLessThan(positions['evidence:1'])
    expect(positions['evidence:1']).toBeLessThan(positions['well:1'])
    expect(positions['well:1']).toBeLessThan(positions['gap:1'])
    expect(series.layout).toBe('none')
  })

  it('labels inferred and contextual states without presenting them as facts', () => {
    expect(getStatusPresentation('inferred').label).toBe('待人工确认')
    expect(getStatusPresentation('contextual').label).toBe('仅作参考')
    expect(getStatusPresentation('confirmed').label).toBe('人工确认')
  })

  it('turns graph health into an explicit review instruction', () => {
    expect(getGraphHealthPresentation('review_needed')).toEqual({
      label: '存在待复核断链',
      tone: 'warn',
    })
    expect(getGraphHealthPresentation('complete').tone).toBe('ok')
  })
})
