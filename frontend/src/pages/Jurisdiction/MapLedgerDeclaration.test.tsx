import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { emptyLedgerDeclaration, ledgerDeclarationPayload } from './MapLedgerDeclaration'
import { LedgerComparisonView } from './MapLedgerComparison'
import type { MapLedgerComparison } from '../../services/mapLedgerImports'

vi.mock('antd', () => ({
  Input: () => null, Select: () => null,
  Alert: ({ message }: { message: string }) => <p>{message}</p>,
  Table: ({ dataSource, columns }: { dataSource: Record<string, unknown>[]; columns: Array<{ dataIndex?: string; render?: (value: unknown) => ReactNode }> }) =>
    <div>{dataSource.map((row, i) => <p key={i}>{columns.map((column, j) => <span key={j}>{column.render ? column.render(row[column.dataIndex || '']) : String(row[column.dataIndex || ''])}</span>)}</p>)}</div>,
}))
describe('完整度声明与缺席表达', () => {
  it('未知不伪装增量或完整，明确声明必须有范围和带时区的业务期间', () => {
    expect(ledgerDeclarationPayload(emptyLedgerDeclaration)).toBeUndefined()
    const draft = { mode: 'full' as const, scopeKey: ' north ', scopeDescription: '合成北区', validFrom: '2026-10-01T00:00:00+08:00', validTo: '2026-11-01T00:00:00+08:00' }
    expect(ledgerDeclarationPayload(draft)?.scope_key).toBe('north')
    expect(() => ledgerDeclarationPayload({ ...draft, validFrom: '2026-10-01T00:00:00' })).toThrow('带时区')
    expect(() => ledgerDeclarationPayload({ ...draft, scopeKey: '' })).toThrow('范围')
    expect(() => ledgerDeclarationPayload({ ...draft, validTo: draft.validFrom })).toThrow('有效起止')
  })
  it('候选预览与执行回执分开，未出现始终待核且不显示停用操作', () => {
    const result: MapLedgerComparison = { status: 'comparable', reason: 'adjacent_full_ledgers', phase: 'preview', boundary: '仅待核，不表示停产',
      baseline_run_id: 'old', previous_count: 2, current_count: 1, missing_count: 1,
      missing: [{ source_record_id: 'B', claim_id: 12, asset_id: 5, row_number: 3 }], rows_complete: true }
    const preview = renderToStaticMarkup(<LedgerComparisonView comparison={result} />)
    expect(preview).toContain('尚未执行'); expect(preview).toContain('设施原状态不变')
    const receipt = renderToStaticMarkup(<LedgerComparisonView comparison={{ ...result, phase: 'executed' }} />)
    expect(receipt).not.toContain('尚未执行'); expect(receipt).toContain('均为待核')
  })
  it('受限结果不把空白当作缺席零项，不展示旧数量', () => {
    const html = renderToStaticMarkup(<LedgerComparisonView comparison={{ status: 'not_comparable', reason: 'data_restricted_or_unavailable', phase: 'executed', boundary: '仅待核' }} />)
    expect(html).toContain('不展示缺席条目与数量'); expect(html).not.toContain('未出现 0')
  })
})
