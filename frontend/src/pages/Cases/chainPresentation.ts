import type { ChainLink } from '../../types'

export function chainPresentation(link: Pick<ChainLink, 'status' | 'freshness' | 'source_change_warning'>) {
  const current = link.freshness === 'current'
  return {
    current,
    canConfirm: current && link.status === 'inferred',
    statusLabel: link.status === 'confirmed'
      ? (current ? '已人工确认' : '历史人工确认')
      : (current ? '待确认' : '历史推断，当前不可用'),
    warning: current ? null : (link.source_change_warning || '依据尚未绑定当前来源版本，仅保留历史记录。'),
  }
}
