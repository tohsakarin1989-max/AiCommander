import { describe, expect, it } from 'vitest'

import { isBonusAccountingEnabled } from './features'

describe('feature flags', () => {
  it('keeps bonus accounting private unless it is explicitly enabled', () => {
    expect(isBonusAccountingEnabled({})).toBe(false)
    expect(isBonusAccountingEnabled({ VITE_ENABLE_BONUS_ACCOUNTING: 'false' })).toBe(false)
    expect(isBonusAccountingEnabled({ VITE_ENABLE_BONUS_ACCOUNTING: 'true' })).toBe(true)
  })
})
