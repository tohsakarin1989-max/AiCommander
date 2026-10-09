import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CaseImportBulkCorrections from './CaseImportBulkCorrections'
import type { FailedImportRow } from '../../services/caseImports'

const state = vi.hoisted(() => ({ values: [] as unknown[], index: 0, getRows: vi.fn(), correctMany: vi.fn(),
  buttons: {} as Record<string, { disabled: boolean; click: () => unknown }>, confirmed: false,
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(), useState: (initial: unknown) => {
  const index = state.index++
  if (state.values.length <= index) state.values[index] = initial
  return [state.values[index], (value: unknown) => { state.values[index] = typeof value === 'function' ? value(state.values[index]) : value }]
} }))
vi.mock('../../services/caseImports', () => ({ caseImportsApi: { getRows: state.getRows, correctMany: state.correctMany } }))
vi.mock('antd', () => ({ Select: () => null, Alert: ({ message }: { message: string }) => <p>{message}</p>,
  Button: ({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => unknown; disabled: boolean }) => {
    state.buttons[String(children)] = { disabled, click: onClick }; return <button disabled={disabled}>{children}</button>
  } }))
const rows: FailedImportRow[] = [2, 3].map(row => ({ row, revision: 1, values: { longitude: `１２${row}．５` },
  status: 'failed', error: '经度格式错误', time_zone: 'UTC' }))
function render() {
  state.index = 0
  return renderToStaticMarkup(<CaseImportBulkCorrections batchId="batch-1" rows={rows} disabled={false}
    onCorrected={vi.fn()} onBusyChange={vi.fn()} onDirtyChange={vi.fn()} refresh={vi.fn().mockResolvedValue(undefined)} />)
}
describe('bulk format preview and guarded retry UI', () => {
  beforeEach(() => {
    vi.clearAllMocks(); state.buttons = {}
    state.values = ['经度格式错误', [2, 3], 'longitude', 'numeric_width', [], false, false, '', '', false]
    state.getRows.mockResolvedValue({ rows })
    state.correctMany.mockResolvedValue({ batch_id: 'batch-1', created: 2, rows: [], errors: [], batch_created_total: 2 })
  })
  it('shows both source rows before permitting a confirmed multi-row retry', async () => {
    render(); state.buttons['预览影响行'].click()
    const preview = render()
    expect(preview).toContain('１２2．５'); expect(preview).toContain('123.5')
    expect(state.buttons['仅重试预览中的失败行'].disabled).toBe(true)
    state.values[5] = true; render(); state.buttons['仅重试预览中的失败行'].click()
    await vi.waitFor(() => expect(state.correctMany).toHaveBeenCalledWith('batch-1', [
      { row: 2, revision: 1, changes: { longitude: '122.5' } },
      { row: 3, revision: 1, changes: { longitude: '123.5' } },
    ]))
    expect(state.getRows).toHaveBeenCalledWith('batch-1')
  })
  it('does not submit when the current receipt changed; retains the preview and blocks retries', async () => {
    render(); state.buttons['预览影响行'].click(); state.values[5] = true
    state.getRows.mockResolvedValue({ rows: [{ ...rows[0], revision: 2 }, rows[1]] })
    render(); state.buttons['仅重试预览中的失败行'].click()
    await vi.waitFor(() => expect(state.values[9]).toBe(true))
    const html = render()
    expect(state.correctMany).not.toHaveBeenCalled()
    expect(html).toContain('预览仍保留')
    expect(state.buttons['仅重试预览中的失败行'].disabled).toBe(true)
  })
})
