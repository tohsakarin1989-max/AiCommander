import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MapLedgerPanel from './MapLedgerPanel'

const state = vi.hoisted(() => ({ cursor: 0, hooks: [] as unknown[], epoch: 1, failed: false,
  buttons: {} as Record<string, { disabled?: boolean; onClick: () => void }>, inputs: {} as Record<string, { value: unknown; disabled?: boolean; onChange: (event: { target: { value: string } }) => void }>,
  upload: null as null | ((file: File) => unknown), select: null as null | ((value: number) => void),
  declarationSelect: null as null | ((value: string) => void),
  queries: [] as unknown[][], preview: vi.fn(), inspect: vi.fn(), enqueue: vi.fn(), ingest: vi.fn(), createTemplate: vi.fn(),
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
vi.mock('../../services/mapLedgerImports', () => ({ mapLedgerImportsApi: { fields: vi.fn(), preview: state.preview, inspect: state.inspect, enqueue: state.enqueue } }))
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }), useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
  state.queries.push(queryKey)
  return { isSuccess: !state.failed, isError: state.failed, refetch: vi.fn(), data: queryKey[0] === 'map-import-fields'
    ? { fields: [], value_states: [], groups: {} } : [{ id: 9, name: '固定模板', version: 2, header_row: 1, coordinate_system: 'wgs84', coordinate_unit: 'degree' }] }
} }))
vi.mock('./MapLedgerTemplateForm', () => ({ default: () => null }))
vi.mock('./MapImportPlan', () => ({ default: () => <p>逐行预览已读</p> }))
vi.mock('./MapIngestHistory', () => ({ default: () => null }))
vi.mock('./MapLedgerJobs', () => ({ default: () => null }))
vi.mock('antd', () => ({
  Alert: ({ message }: { message: string }) => <p>{message}</p>, Space: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Button: ({ children, disabled, onClick }: { children: ReactNode; disabled?: boolean; onClick: () => void }) => {
    state.buttons[String(children)] = { disabled, onClick }; return <button disabled={disabled}>{children}</button>
  },
  Input: (props: { 'aria-label': string; value: unknown; disabled?: boolean; onChange: (event: { target: { value: string } }) => void }) => {
    state.inputs[props['aria-label']] = props; return <input value={String(props.value)} readOnly />
  },
  InputNumber: () => null,
  Select: ({ onChange, 'aria-label': label }: { 'aria-label': string; onChange: (value: string | number) => void }) => {
    if (label === '生产台账导入模板') state.select = value => onChange(value)
    if (label === '台账完整度声明') state.declarationSelect = value => onChange(value)
    return null
  },
  Upload: ({ beforeUpload, children }: { beforeUpload: (file: File) => unknown; children: ReactNode }) => { state.upload = beforeUpload; return <div>{children}</div> },
}))

const plan = { plan_token: 'fixed-plan', publishable: true, drift: [], rows: [], counts: {}, structure: {} }
const flush = () => new Promise(resolve => setTimeout(resolve, 0))
function render() { state.cursor = 0; state.buttons = {}; return renderToStaticMarkup(<MapLedgerPanel sourceId={3} onChanged={vi.fn()} onDirtyChange={vi.fn()} />) }
async function prepare() {
  render(); state.select!(9); render()
  state.inputs['台账来源修订'].onChange({ target: { value: '月度修订' } }); render()
  const file = new File(['name\nA'], '合成台账.csv'); state.upload!(file); await flush(); render()
  state.buttons['重新预览'].onClick(); await flush(); render(); return file
}

describe('生产台账的页面提交可靠性', () => {
  beforeEach(() => { state.cursor = 0; state.hooks = []; state.epoch = 1; state.failed = false; state.queries = []; vi.clearAllMocks()
    state.inspect.mockResolvedValue({ structure: { headers: ['name'], sheet_name: null, header_row: 1 }, boundary: '实际表头', compatible_templates: [], recommended_template_id: null })
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
    state.inspect.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    render(); state.select!(9); render()
    const first = new File(['first'], '第一份.csv')
    state.upload!(first); state.upload!(new File(['second'], '第二份.csv'))
    resolve({ structure: { headers: ['name'], sheet_name: null, header_row: 1 }, boundary: '实际表头', recommended_template_id: null }); await flush()
    const html = render()
    expect(html).toContain('第一份.csv'); expect(html).not.toContain('第二份.csv'); expect(state.inspect).toHaveBeenCalledTimes(1)
  })
  it('读取按当前登录代次隔离，错误时不展示旧模板', () => {
    render(); expect(state.queries).toContainEqual(['map-foundation-templates', 8, 1, 3])
    state.epoch = 2; state.failed = true
    expect(render()).toContain('模板读取失败，未使用旧缓存'); expect(state.queries).toContainEqual(['map-import-fields', 8, 2])
  })
  it('可选声明随文件和计划冻结，失联不把接收日期或新输入替换业务期间', async () => {
    render(); state.select!(9); render(); state.declarationSelect!('full'); render()
    const values = { 台账覆盖范围编号: 'north', 台账覆盖范围说明: '合成北区登记井',
      台账业务有效起点: '2026-10-01T00:00:00+08:00', 台账业务有效终点: '2026-11-01T00:00:00+08:00' }
    for (const [key, value] of Object.entries(values)) { state.inputs[key].onChange({ target: { value } }); render() }
    const file = new File(['合成'], '完整声明.csv'); state.upload!(file); await flush(); render()
    state.buttons['重新预览'].onClick(); await flush(); render()
    const scope = { mode: 'full', scope_key: 'north', scope_description: '合成北区登记井',
      valid_from: values.台账业务有效起点, valid_to: values.台账业务有效终点 }
    expect(state.preview.mock.calls[0]).toEqual([3, file, 9, undefined, scope])
    state.ingest.mockRejectedValueOnce(new Error('响应丢失'))
    state.buttons['按预览写入合格记录'].onClick(); await flush(); render()
    expect(state.inputs['台账业务有效起点'].disabled).toBe(true)
    state.buttons['用原文件与凭证核对并重试'].onClick(); await flush(); render()
    expect(state.ingest.mock.calls[0]).toEqual([3, 9, file, '', 'fixed-plan', scope])
    expect(state.ingest.mock.calls[1]).toEqual(state.ingest.mock.calls[0])
  })
  it('声明未完整时保留文件与输入，撤回声明后旧导入仍可预览', async () => {
    render(); state.select!(9); render(); state.declarationSelect!('full'); render()
    const file = new File(['合成'], '不完整声明.csv'); state.upload!(file); await flush(); render()
    state.buttons['重新预览'].onClick(); await flush()
    expect(render()).toContain('不以接收日期代替'); expect(state.preview).not.toHaveBeenCalled()
    state.declarationSelect!('unknown'); render(); state.buttons['重新预览'].onClick(); await flush()
    expect(state.preview).toHaveBeenCalledWith(3, file, 9)
  })
  it('确认模板的后台请求持久接收后才允许离页，不把排队称已采用', async () => {
    state.enqueue.mockResolvedValue({ id: 'durable-job', status: 'queued' })
    render(); state.select!(9); render()
    const file = new File(['name\nA'], '后台台账.csv')
    state.upload!(file); await flush(); render()
    state.buttons['后台整理并按来源规则采用'].onClick(); await flush()
    const html = render()
    expect(state.enqueue).toHaveBeenCalledWith(3, file, 9, '', undefined)
    expect(html).toContain('durable-job'); expect(html).toContain('整批采用前保持不变')
    expect(html).not.toContain('当前文件：')
    expect(state.preview).not.toHaveBeenCalled()
  })
  it('后台接收响应丢失后冻结请求，重试仍用同一份文件与修订', async () => {
    state.enqueue.mockRejectedValueOnce(new Error('接收响应丢失')).mockResolvedValue({ id: 'same-job', status: 'queued' })
    render(); state.select!(9); render()
    const file = new File(['name\nA'], '后台重试.csv')
    state.upload!(file); await flush(); render()
    state.buttons['后台整理并按来源规则采用'].onClick(); await flush(); render()
    expect(state.inputs['台账来源修订'].disabled).toBe(true)
    state.upload!(new File(['name\nB'], '不能替换.csv')); render()
    state.buttons['按原请求核对后台接收结果'].onClick(); await flush()
    expect(state.enqueue.mock.calls).toEqual([[3, file, 9, '', undefined], [3, file, 9, '', undefined]])
    expect(render()).toContain('same-job')
  })
})
