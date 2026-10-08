import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MapLedgerPanel from './MapLedgerPanel'

const state = vi.hoisted(() => ({ cursor: 0, hooks: [] as unknown[], epoch: 1, failed: false,
  buttons: {} as Record<string, { disabled?: boolean; onClick: () => void }>, inputs: {} as Record<string, { value: unknown; disabled?: boolean; onChange: (event: { target: { value: string } }) => void }>,
  upload: null as null | ((file: File) => unknown), select: null as null | ((value: number) => void),
  queries: [] as unknown[][], preview: vi.fn(), ingest: vi.fn(), createTemplate: vi.fn(),
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(),
  useEffect: vi.fn(),
  useState: (initial: unknown) => {
    const index = state.cursor++
    if (!(index in state.hooks)) state.hooks[index] = typeof initial === 'function' ? (initial as () => unknown)() : initial
    return [state.hooks[index], (value: unknown) => { state.hooks[index] = typeof value === 'function' ? (value as (old: unknown) => unknown)(state.hooks[index]) : value }]
  },
  useRef: (initial: unknown) => {
    const index = state.cursor++; if (!(index in state.hooks)) state.hooks[index] = { current: initial }
    return state.hooks[index]
  },
}))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 8 }, sessionEpoch: state.epoch }) }))
vi.mock('../../services/mapFoundation', () => ({ mapFoundationApi: { listTemplates: vi.fn(), createTemplate: state.createTemplate, ingest: state.ingest } }))
vi.mock('../../services/mapLedgerImports', () => ({ mapLedgerImportsApi: { fields: vi.fn(), preview: state.preview } }))
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }), useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
  state.queries.push(queryKey)
  return { isSuccess: !state.failed, isError: state.failed, refetch: vi.fn(), data: queryKey[0] === 'map-import-fields'
    ? { fields: [], value_states: [], groups: {} } : [{ id: 9, name: '固定模板', version: 2, header_row: 1, coordinate_system: 'wgs84', coordinate_unit: 'degree' }] }
} }))
vi.mock('./MapLedgerTemplateForm', () => ({ default: () => null }))
vi.mock('./MapImportPlan', () => ({ default: () => <p>逐行预览已读</p> }))
vi.mock('./MapIngestHistory', () => ({ default: () => null }))
vi.mock('antd', () => ({
  Alert: ({ message }: { message: string }) => <p>{message}</p>, Space: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Button: ({ children, disabled, onClick }: { children: ReactNode; disabled?: boolean; onClick: () => void }) => {
    state.buttons[String(children)] = { disabled, onClick }; return <button disabled={disabled}>{children}</button>
  },
  Input: (props: { 'aria-label': string; value: unknown; disabled?: boolean; onChange: (event: { target: { value: string } }) => void }) => {
    state.inputs[props['aria-label']] = props; return <input value={String(props.value)} readOnly />
  },
  Select: ({ onChange }: { onChange: (value: number) => void }) => { state.select = onChange; return null },
  Upload: ({ beforeUpload, children }: { beforeUpload: (file: File) => unknown; children: ReactNode }) => { state.upload = beforeUpload; return <div>{children}</div> },
}))

const plan = { plan_token: 'fixed-plan', publishable: true, drift: [], rows: [], counts: {}, structure: {} }
const flush = () => new Promise(resolve => setTimeout(resolve, 0))
function render() { state.cursor = 0; state.buttons = {}; return renderToStaticMarkup(<MapLedgerPanel sourceId={3} onChanged={vi.fn()} onDirtyChange={vi.fn()} />) }
async function prepare() {
  render(); state.select!(9); render()
  state.inputs['台账来源修订'].onChange({ target: { value: '月度修订' } }); render()
  const file = new File(['name\nA'], '合成台账.csv'); state.upload!(file); await flush(); render(); return file
}

describe('生产台账的页面提交可靠性', () => {
  beforeEach(() => { state.cursor = 0; state.hooks = []; state.epoch = 1; state.failed = false; state.queries = []; vi.clearAllMocks()
    state.preview.mockResolvedValue(plan); state.ingest.mockResolvedValue({ id: 'same-run', created_assets: 1, updated_assets: 0 }) })
  it('响应丢失后文件/修订/凭证冻结，同一原请求重试成功才清输入', async () => {
    const file = await prepare()
    state.ingest.mockRejectedValueOnce(new Error('响应丢失'))
    state.buttons['按预览写入合格记录'].onClick(); await flush()
    let html = render()
    expect(html).toContain('合成台账.csv'); expect(html).toContain('响应丢失'); expect(html).toContain('原文件、模板、来源修订和预览凭证已冻结')
    expect(state.inputs['台账来源修订'].value).toBe('月度修订'); expect(state.inputs['台账来源修订'].disabled).toBe(true)
    state.upload!(new File(['other'], '不能替换.csv')); render()
    expect(state.preview).toHaveBeenCalledTimes(1)
    state.buttons['用原文件与凭证核对并重试'].onClick(); await flush(); html = render()
    expect(state.ingest.mock.calls).toEqual([[3, 9, file, '月度修订', 'fixed-plan'], [3, 9, file, '月度修订', 'fixed-plan']])
    expect(html).toContain('same-run'); expect(html).not.toContain('当前文件：')
  })
  it('明确过期计划解除提交锁但保留文件，必须重新预览', async () => {
    await prepare(); state.ingest.mockRejectedValueOnce({ detail: { detail: { code: 'plan_stale', message: '来源已变化，请重新预览' } } })
    state.buttons['按预览写入合格记录'].onClick(); await flush()
    const html = render()
    expect(html).toContain('合成台账.csv'); expect(html).toContain('来源已变化，请重新预览'); expect(html).not.toContain('逐行预览已读')
    expect(state.buttons['按预览写入合格记录'].disabled).toBe(true); expect(state.inputs['台账来源修订'].disabled).toBe(false)
  })
  it('预览进行中第二次选文件不会把前一份预览配给后一份文件', async () => {
    let resolve!: (value: unknown) => void
    state.preview.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    render(); state.select!(9); render()
    const first = new File(['first'], '第一份.csv')
    state.upload!(first); state.upload!(new File(['second'], '第二份.csv'))
    resolve(plan); await flush()
    const html = render()
    expect(html).toContain('第一份.csv'); expect(html).not.toContain('第二份.csv'); expect(state.preview).toHaveBeenCalledTimes(1)
  })
  it('读取按当前登录代次隔离，错误时不展示旧模板', () => {
    render(); expect(state.queries).toContainEqual(['map-foundation-templates', 8, 1, 3])
    state.epoch = 2; state.failed = true
    expect(render()).toContain('模板读取失败，未使用旧缓存'); expect(state.queries).toContainEqual(['map-import-fields', 8, 2])
  })
})
