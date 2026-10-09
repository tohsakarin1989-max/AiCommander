import { describe, expect, it } from 'vitest'
import { changedImportFields, correctionReceiptState, importFieldLabels, importPreviewCells, importTimeZoneLabel } from './importCorrection'
import type { FailedImportRow } from '../../services/caseImports'

describe('failed import row corrections', () => {
  it('shows distinct time and quantity roles without dropping late response fields', () => {
    expect(importFieldLabels.discovered_at).toContain('发现')
    expect(importFieldLabels.oil_volume_unit).toContain('单位')
    const cells = importPreviewCells({ row: 4, action: 'created', occurred_time: null,
      location: null, case_type: '非法转运油气', description: '合成案件原文', discovered_at: null,
      oil_volume: null, oil_volume_unit: 'unknown', source_recovery_raw: 0,
      source_collaboration_type: '内部联动', source_date_expression: '年度、月日原值', warnings: ['待核'] })
    expect(cells.find(item => item.key === 'source_recovery_raw')).toMatchObject({ value: 0 })
    expect(cells.find(item => item.key === 'source_collaboration_type')?.label).toContain('联动')
    expect(cells.find(item => item.key === 'occurred_time')?.value).toBeNull()
    expect(cells.map(item => item.key)).toContain('oil_volume_unit')
    expect(cells.map(item => item.key)).not.toContain('action')
  })
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
