import { describe, expect, it } from 'vitest'
import { chainPresentation } from './chainPresentation'

describe('chain source validity', () => {
  it('allows only a current inferred source to be confirmed', () => {
    expect(chainPresentation({ status: 'inferred', freshness: 'current' }).canConfirm).toBe(true)
    for (const freshness of ['source_changed', 'legacy_unversioned', 'source_unavailable', undefined] as const) {
      const view = chainPresentation({ status: 'inferred', freshness })
      expect(view.canConfirm).toBe(false)
      expect(view.warning).toBeTruthy()
    }
  })
  it('retains a changed-source human decision as history rather than current evidence', () => {
    const view = chainPresentation({ status: 'confirmed', freshness: 'source_changed', source_change_warning: '原文已更新' })
    expect(view.statusLabel).toBe('历史人工确认')
    expect(view.warning).toBe('原文已更新')
    expect(view.canConfirm).toBe(false)
  })
})
