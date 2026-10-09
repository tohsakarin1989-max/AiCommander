import { describe, expect, it } from 'vitest'
import { buildBulkFormatCorrections, assertBulkRevisions } from './importBulkCorrection'
import type { FailedImportRow } from '../../services/caseImports'

const row = (number: number, value: string, error = '经度格式错误'): FailedImportRow => ({ row: number, revision: 2, status: 'failed', error, time_zone: 'UTC', values: { longitude: value, description: '原始事实' } })
describe('same-batch same-error bulk format correction', () => {
  it('only formats selected failed rows with the same error, preserving per-row revisions', () => {
    const rows = [row(2, '１２４．５'), row(3, '１２５．５'), row(4, '125'), row(5, '１２６．５', '其他错误')]
    expect(buildBulkFormatCorrections(rows, [2, 3, 4, 5], '经度格式错误', 'longitude', 'numeric_width')).toEqual([
      { row: 2, revision: 2, changes: { longitude: '124.5' }, previous: '１２４．５' },
      { row: 3, revision: 2, changes: { longitude: '125.5' }, previous: '１２５．５' },
    ])
  })
  it('does not turn narrative, unknown numbers or successful rows into bulk facts', () => {
    expect(() => buildBulkFormatCorrections([row(1, '123')], [1], '经度格式错误', 'description', 'numeric_width')).toThrow()
    expect(buildBulkFormatCorrections([row(1, '不详'), { ...row(2, '１２５'), status: 'created' }], [1, 2], '经度格式错误', 'longitude', 'numeric_width')).toEqual([])
  })
  it('rejects a changed or removed row instead of rebasing a preview', () => {
    const source = row(2, ' 124.5 ')
    const plan = buildBulkFormatCorrections([source], [2], source.error!, 'longitude', 'trim')
    expect(() => assertBulkRevisions(plan, [{ ...source, revision: 3 }])).toThrow()
    expect(() => assertBulkRevisions(plan, [])).toThrow()
    expect(() => assertBulkRevisions(plan, [source])).not.toThrow()
  })
})
