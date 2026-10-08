import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CaseImportCorrections from './CaseImportCorrections'
import type { FailedImportRow, ImportCorrectionResult, ImportRowReceipt } from '../../services/caseImports'

const state = vi.hoisted(() => ({ values: [] as unknown[], index: 0,
  mutation: {} as { onError: () => void; onSuccess: (result: ImportCorrectionResult) => void },
  receipt: {} as ImportRowReceipt, buttons: {} as Record<string, () => Promise<void> | void>,
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = state.index++
    if (state.values.length <= index) state.values[index] = initial
    return [state.values[index], (value: unknown) => { state.values[index] = typeof value === 'function' ? value(state.values[index]) : value }]
  },
}))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1 }, sessionEpoch: 1 }) }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useQuery: () => ({ isSuccess: true, data: state.receipt, refetch: async () => ({ isSuccess: true, data: state.receipt }) }),
  useMutation: (options: typeof state.mutation) => { state.mutation = options; return { isPending: false, mutate: vi.fn() } },
}))
vi.mock('antd', () => ({
  Alert: ({ message }: { message: string }) => <p>{message}</p>, Spin: () => <span />,
  Select: () => <select />,
  Button: ({ children, onClick, disabled }: { children: React.ReactNode; onClick?: () => Promise<void> | void; disabled?: boolean }) => {
    if (onClick) state.buttons[String(children)] = onClick
    return <button disabled={disabled}>{children}</button>
  },
  Input: { TextArea: ({ value, 'aria-label': label }: { value: string; 'aria-label': string }) => <textarea aria-label={label} readOnly value={value} /> },
}))

const selected = (): FailedImportRow => ({ row: 4, revision: 2, values: { longitude: 'wrong', description: '合成原文' }, time_zone: 'UTC', status: 'failed', error: '经度格式不符' })
function render() {
  state.index = 0
  return renderToStaticMarkup(<CaseImportCorrections batchId="batch" onCorrected={vi.fn()} onBusyChange={vi.fn()} />)
}
describe('失败行修正保留输入且不静默跨版本', () => {
  beforeEach(() => {
    state.values = [true, selected(), { longitude: '124.7', description: '我的待提交修正' }, '', '', false, null]
    state.receipt = { batch_id: 'batch', retry_available: true, created_total: 0, rows: [selected()] }
    state.buttons = {}
  })
  it('提交错误后原选中行和修正输入仍可见，提交按钮停用直到刷新确认', () => {
    render(); state.mutation.onError()
    const html = render()
    expect(state.values[1]).toEqual(selected()); expect(state.values[2]).toEqual({ longitude: '124.7', description: '我的待提交修正' })
    expect(html).toContain('我的待提交修正'); expect(html).toContain('修正输入仍保留')
    expect(html).toContain('<button disabled="">仅重试此失败行</button>')
  })
  it('刷新发现他人新版本时保留输入，明确确认后才更换比较基准', async () => {
    render(); state.mutation.onError()
    state.receipt.rows = [{ ...selected(), revision: 3, values: { longitude: '125.0', description: '其他人更正' } }]
    await state.buttons['刷新失败行']()
    let html = render()
    expect((state.values[1] as FailedImportRow).revision).toBe(2); expect(html).toContain('其他人更正'); expect(html).toContain('我的待提交修正')
    await state.buttons['已核对最新回执，保留我的修正继续']()
    html = render()
    expect((state.values[1] as FailedImportRow).revision).toBe(3); expect(html).toContain('我的待提交修正')
    expect(html).not.toContain('<button disabled="">仅重试此失败行</button>')
  })
  it('业务校验仍失败也不清输入；明确成功才清除', () => {
    render()
    state.mutation.onSuccess({ batch_id: 'batch', created: 0, batch_created_total: 0, rows: [{ ...selected(), revision: 3 }], errors: [{ row: 4, error: '仍需核对' }] })
    expect(render()).toContain('我的待提交修正')
    state.mutation.onSuccess({ batch_id: 'batch', created: 1, batch_created_total: 1, rows: [], errors: [] })
    expect(state.values[1]).toBeNull(); expect(state.values[2]).toEqual({})
  })
})
