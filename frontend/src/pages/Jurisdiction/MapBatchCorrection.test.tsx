import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MapBatchCorrection from './MapBatchCorrection'
import { ledgerBatchClaim, ledgerBatchPreview, ledgerBatchRun } from './mapLedgerBatch.fixtures'

const state = vi.hoisted(() => ({ cursor: 0, hooks: [] as unknown[], retryPreview: vi.fn(), retry: vi.fn(), complete: vi.fn(), locked: vi.fn(),
  buttons: [] as Array<{ label: string; disabled?: boolean; onClick: () => void }>,
  checkbox: null as null | { disabled?: boolean; checked?: boolean; onChange: (event: { target: { checked: boolean } }) => void },
  selects: {} as Record<string, { onChange: (value: string) => void }>,
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(), useEffect: vi.fn(),
  useState: (initial: unknown) => { const index = state.cursor++; if (!(index in state.hooks)) state.hooks[index] = initial
    return [state.hooks[index], (next: unknown) => { state.hooks[index] = typeof next === 'function' ? (next as (previous: unknown) => unknown)(state.hooks[index]) : next }] },
  useRef: (initial: unknown) => { const index = state.cursor++; if (!(index in state.hooks)) state.hooks[index] = { current: initial }; return state.hooks[index] },
}))
vi.mock('../../services/mapLedgerImports', () => ({ mapLedgerImportsApi: { retryPreview: state.retryPreview, retry: state.retry } }))
vi.mock('./MapImportPlan', () => ({ default: () => <p>完整服务端逐行预览</p> }))
vi.mock('antd', () => ({
  Alert: ({ message }: { message: string }) => <p>{message}</p>, Space: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Select: (props: { 'aria-label': string; onChange: (value: string) => void }) => { state.selects[props['aria-label']] = props; return null },
  Checkbox: (props: { children: ReactNode; disabled?: boolean; checked: boolean; onChange: (event: { target: { checked: boolean } }) => void }) => {
    state.checkbox = props; return <label>{props.children}</label>
  },
  Button: ({ children, disabled, onClick }: { children: ReactNode; disabled?: boolean; onClick: () => void }) => {
    state.buttons.push({ label: String(children), disabled, onClick }); return <button disabled={disabled}>{children}</button>
  },
  Table: ({ dataSource, columns }: { dataSource: Record<string, unknown>[]; columns: Array<{ render: (value: unknown, item: Record<string, unknown>) => ReactNode }> }) =>
    <div>{dataSource.map((item, index) => <div key={index}>{columns.map((column, col) => <span key={col}>{column.render(null, item)}</span>)}</div>)}</div>,
}))
const claims = [1, 2].map(id => ledgerBatchClaim(id, 'parent'))
const run = ledgerBatchRun('parent')
function render() {
  state.cursor = 0; state.buttons = []; state.checkbox = null
  return renderToStaticMarkup(<MapBatchCorrection run={run} claims={claims} templateId={9} fields={[]}
    onLockedChange={state.locked} onComplete={state.complete} onClose={vi.fn()} />)
}
const flush = () => new Promise(resolve => setTimeout(resolve, 0))
const button = (label: string) => state.buttons.find(item => item.label === label)!

describe('同因台账异常的预览和明确确认', () => {
  beforeEach(() => {
    state.cursor = 0; state.hooks = []; state.selects = {}; vi.clearAllMocks()
    state.retryPreview.mockResolvedValue(ledgerBatchPreview(claims))
    state.retry.mockResolvedValue({ id: 'corrected' })
  })
  it('先列原行和将变更内容、明确确认后才提交；失联保留原请求重试', async () => {
    render(); state.selects['同因异常修正方式'].onChange('numeric_format'); render()
    state.retryPreview.mockRejectedValueOnce(new Error('预览连接中断'))
    button('预览所选行修正').onClick(); await flush(); let html = render()
    expect(html).toContain('预览连接中断'); expect(state.retry).not.toHaveBeenCalled()
    button('预览所选行修正').onClick(); await flush(); html = render()
    expect(state.retryPreview.mock.calls[0]).toEqual(state.retryPreview.mock.calls[1])
    expect(html).toContain('3 / #1'); expect(html).toContain('4 / #2')
    expect(html).toContain('1.5'); expect(html).toContain('2.5')
    expect(button('确认提交所选行修正').disabled).toBe(true)
    state.checkbox!.onChange({ target: { checked: true } }); render()
    expect(button('确认提交所选行修正').disabled).toBe(false)
    state.retry.mockRejectedValueOnce(new Error('响应丢失'))
    button('确认提交所选行修正').onClick(); await flush(); html = render()
    expect(html).toContain('响应丢失'); expect(button('返回修改批量方案').disabled).toBe(true)
    expect(button('清空批量选择').disabled).toBe(true)
    button('按冻结原请求核对重试').onClick(); await flush()
    expect(state.retry.mock.calls[0]).toEqual(state.retry.mock.calls[1])
    expect(state.retry.mock.calls[0][1]).toMatchObject({ template_id: 4, plan_token: 'batch-plan', rows: [
      { claim_id: 1, values: { 编号: 'F1', 产量: '1.5' } }, { claim_id: 2, values: { 编号: 'F2', 产量: '2.5' } },
    ] })
    expect(state.complete).toHaveBeenCalledWith({ id: 'corrected' })
  })
  it('预览存在事实冲突，即使publishable为真也不能确认批量写入', async () => {
    const preview = ledgerBatchPreview(claims)
    state.retryPreview.mockResolvedValue({ ...preview, rows: [preview.rows[0], { ...preview.rows[1], classification: 'conflict' }] })
    render(); button('预览所选行修正').onClick(); await flush(); const html = render()
    expect(html).toContain('事实冲突'); expect(state.checkbox!.disabled).toBe(true)
    expect(button('确认提交所选行修正').disabled).toBe(true); expect(state.retry).not.toHaveBeenCalled()
  })
  it('明确拒绝旧行已修订后取消计划，保留选择供刷新核对，不沿用旧凭证', async () => {
    render(); button('预览所选行修正').onClick(); await flush(); render()
    state.checkbox!.onChange({ target: { checked: true } }); render()
    state.retry.mockRejectedValueOnce({ detail: { detail: { code: 'retry_row_superseded', message: '请查看最新修订' } } })
    button('确认提交所选行修正').onClick(); await flush(); const html = render()
    expect(html).toContain('请查看最新修订'); expect(html).toContain('已选 2 行')
    expect(html).not.toContain('完整服务端逐行预览'); expect(button('返回修改批量方案').disabled).toBe(false)
    expect(state.locked).toHaveBeenLastCalledWith(false)
  })
})
