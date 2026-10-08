import { describe, expect, it } from 'vitest'
import { changedImportFields, correctionReceiptState, importTimeZoneLabel } from './importCorrection'
import type { FailedImportRow } from '../../services/caseImports'

describe('failed import row corrections', () => {
  it('submits only changed source fields, preserving whitespace and empty correction', () => {
    expect(changedImportFields({ description: ' 原文 ', longitude: 'bad', latitude: '47' },
      { description: ' 原文 ', longitude: '', latitude: '47', operational_area_id: '9' }))
      .toEqual({ longitude: '' })
  })
  it('does not submit unchanged null cells or omitted fields', () => {
    expect(changedImportFields({ location: null, description: '原文' }, { location: '' })).toEqual({})
  })
  it('refresh distinguishes unchanged, concurrently changed and no longer failed rows without rebasing the draft', () => {
    const selected: FailedImportRow = { row: 4, revision: 2, values: { longitude: 'wrong' }, time_zone: 'UTC', status: 'failed', error: 'bad input' }
    const draft = { longitude: '124.7' }
    expect(correctionReceiptState(selected, [selected]).state).toBe('same')
    expect(correctionReceiptState(selected, [{ ...selected, revision: 3 }]).state).toBe('changed')
    expect(correctionReceiptState(selected, []).state).toBe('absent')
    expect(draft).toEqual({ longitude: '124.7' }); expect(selected.revision).toBe(2)
  })
  it('new business time is explicit but missing legacy template timezone remains UTC', () => {
    expect(importTimeZoneLabel('Asia/Shanghai')).toContain('北京时间 UTC+8')
    expect(importTimeZoneLabel()).toContain('UTC 世界协调时')
    expect(importTimeZoneLabel('UTC')).toContain('不自动改为北京时间')
  })
})
