import { describe, expect, it } from 'vitest'
import { canMaintainArea } from './maintenanceAccess'

describe('current map maintenance permission', () => {
  const scopes = [{ operational_area_id: 1, access_level: 'manage' }, { operational_area_id: 2, access_level: 'write' }]
  it('allows a scoped maintainer but does not grant write or cross-area maintenance', () => {
    expect(canMaintainArea('analyst', scopes, 1)).toBe(true)
    expect(canMaintainArea('analyst', scopes, 2)).toBe(false)
    expect(canMaintainArea('analyst', scopes, 3)).toBe(false)
    expect(canMaintainArea('viewer', scopes, 1)).toBe(false)
  })
  it('fails closed while scopes are missing, revoked or the selected area is unknown', () => {
    expect(canMaintainArea('admin', [], 1)).toBe(false)
    expect(canMaintainArea('analyst', [], 1)).toBe(false)
    expect(canMaintainArea('analyst', scopes, null)).toBe(false)
    expect(canMaintainArea('analyst', [{ operational_area_id: 1, access_level: 'read' }], 1)).toBe(false)
  })
})
