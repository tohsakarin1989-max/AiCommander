import type { FailedImportRow } from '../../services/caseImports'

export type FormatCorrection = 'trim' | 'numeric_width'
export interface BulkFormatRow { row: number; revision: number; changes: Record<string, string>; previous: string }
const numericFields = new Set(['latitude', 'longitude', 'oil_volume', 'oil_value', 'water_cut', 'loss_amount'])

/** A formatting plan is deliberately narrower than editing business facts in bulk. */
export function buildBulkFormatCorrections(rows: FailedImportRow[], selected: number[], error: string, field: string, rule: FormatCorrection): BulkFormatRow[] {
  if (rule === 'numeric_width' && !numericFields.has(field)) throw new Error('数字格式整理只允许数值字段')
  const wanted = new Set(selected)
  return rows.flatMap(row => {
    if (!wanted.has(row.row) || row.status !== 'failed' || row.error !== error || row.values[field] == null) return []
    const previous = row.values[field]!
    const value = rule === 'trim' ? previous.trim() : previous.trim().replace(/[０-９．－＋]/g, character => String.fromCharCode(character.charCodeAt(0) - 0xfee0))
    if (value === previous || (rule === 'numeric_width' && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value))) return []
    return [{ row: row.row, revision: row.revision, changes: { [field]: value }, previous }]
  })
}

export function assertBulkRevisions(plan: BulkFormatRow[], rows: FailedImportRow[]): void {
  if (!plan.length || plan.some(item => !rows.some(row => row.row === item.row && row.status === 'failed' && row.revision === item.revision)))
    throw new Error('部分失败行已变化，请重新读取并预览；未自动采用新版本')
}
