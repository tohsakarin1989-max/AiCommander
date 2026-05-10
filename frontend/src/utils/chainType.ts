import type { Case, ChainPosition } from '../types'

export const chainPositionMeta: Record<ChainPosition, {
  label: string
  shortLabel: string
  color: string
  shape: 'hexagon' | 'diamond' | 'square' | 'circle'
}> = {
  upstream: {
    label: '盗采环节',
    shortLabel: '盗采',
    color: '#ef4444',
    shape: 'hexagon',
  },
  midstream: {
    label: '运输环节',
    shortLabel: '运输',
    color: '#f59e0b',
    shape: 'diamond',
  },
  downstream: {
    label: '囤储环节',
    shortLabel: '囤储',
    color: '#3b82f6',
    shape: 'square',
  },
  unknown: {
    label: '未分类',
    shortLabel: '未知',
    color: '#94a3b8',
    shape: 'circle',
  },
}

export function getChainPosition(caseItem: Pick<Case, 'facility_type'> | { facility_type?: string | null }): ChainPosition {
  const value = String(caseItem.facility_type || '').trim()
  if (!value) return 'unknown'
  if (value.includes('管线') || value.includes('管道')) return 'upstream'
  if (value.includes('油罐车') || value.includes('罐车') || value.includes('运输')) return 'midstream'
  if (value.includes('油库') || value.includes('加油站') || value.includes('囤') || value.includes('储')) return 'downstream'
  return 'unknown'
}
