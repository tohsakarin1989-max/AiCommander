import { describe, expect, it } from 'vitest'

import { canAccessAgentLab, isAgentLabEnabled, isBonusAccountingEnabled } from './features'

describe('feature flags', () => {
  it('keeps bonus accounting private unless it is explicitly enabled', () => {
    expect(isBonusAccountingEnabled({})).toBe(false)
    expect(isBonusAccountingEnabled({ VITE_ENABLE_BONUS_ACCOUNTING: 'false' })).toBe(false)
    expect(isBonusAccountingEnabled({ VITE_ENABLE_BONUS_ACCOUNTING: 'true' })).toBe(true)
  })

  it('keeps Agent Lab hidden unless it is explicitly enabled', () => {
    expect(isAgentLabEnabled({})).toBe(false)
    expect(isAgentLabEnabled({ VITE_ENABLE_AGENT_LAB: 'false' })).toBe(false)
    expect(isAgentLabEnabled({ VITE_ENABLE_AGENT_LAB: 'true' })).toBe(true)
  })

  it('allows only analysts and admins to enter an enabled Agent Lab', () => {
    expect(canAccessAgentLab('admin', true)).toBe(true)
    expect(canAccessAgentLab('analyst', true)).toBe(true)
    expect(canAccessAgentLab('viewer', true)).toBe(false)
    expect(canAccessAgentLab('admin', false)).toBe(false)
  })
})
