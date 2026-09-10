import { describe, expect, it } from 'vitest'
import { changedImportFields } from './importCorrection'

describe('failed import row corrections', () => {
  it('submits only changed source fields, preserving whitespace and empty correction', () => {
    expect(changedImportFields({ description: ' 原文 ', longitude: 'bad', latitude: '47' },
      { description: ' 原文 ', longitude: '', latitude: '47', operational_area_id: '9' }))
      .toEqual({ longitude: '' })
  })
  it('does not submit unchanged null cells or omitted fields', () => {
    expect(changedImportFields({ location: null, description: '原文' }, { location: '' })).toEqual({})
  })
})
