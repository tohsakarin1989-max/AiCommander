import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MapFieldDecision from './MapFieldDecision'

const state = vi.hoisted(() => ({ cursor: 0, hooks: [] as unknown[], canResolve: true, fetching: false,
  buttons: {} as Record<string, { disabled?: boolean; onClick: () => void }>,
  input: null as null | { value: string; disabled?: boolean; onChange: (event: { target: { value: string } }) => void },
  decide: vi.fn(), refetch: vi.fn(), complete: vi.fn(), version: 8,
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(), useEffect: vi.fn(),
  useState: (initial: unknown) => { const index = state.cursor++; if (!(index in state.hooks)) state.hooks[index] = initial
    return [state.hooks[index], (next: unknown) => { state.hooks[index] = next }] },
  useRef: (initial: unknown) => { const index = state.cursor++; if (!(index in state.hooks)) state.hooks[index] = { current: initial }; return state.hooks[index] },
}))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 8 }, sessionEpoch: 3 }) }))
vi.mock('../../services/mapLedgerImports', () => ({ mapLedgerImportsApi: { fieldDecision: state.decide } }))
vi.mock('@tanstack/react-query', () => ({ useQuery: () => ({ isSuccess: true, isFetching: state.fetching, refetch: state.refetch,
  data: { asset_id: 9, asset_version: state.version, decision_id: 17, group: 'production', source_id: 3,
    state: 'set', current: { production_output: 20 }, candidate: { production_output: 28 }, can_resolve: state.canResolve } }) }))
vi.mock('antd', () => ({
  Alert: ({ message }: { message: string }) => <p>{message}</p>, Space: ({ children }: { children: ReactNode }) => <div>{children}</div>, Table: () => null,
  Input: { TextArea: (props: { value: string; disabled?: boolean; onChange: (event: { target: { value: string } }) => void }) => { state.input = props; return <textarea value={props.value} readOnly /> } },
  Button: ({ children, disabled, onClick }: { children: ReactNode; disabled?: boolean; onClick: () => void }) => {
    state.buttons[String(children)] = { disabled, onClick }; return <button disabled={disabled}>{children}</button>
  },
}))
const flush = () => new Promise(resolve => setTimeout(resolve, 0))
function render() { state.cursor = 0; state.buttons = {}; return renderToStaticMarkup(<MapFieldDecision claimId={12} group="production" fields={[]} onComplete={state.complete} onClose={vi.fn()} />) }
describe('来源冲突须明确采用完整字段组', () => {
  beforeEach(() => { state.cursor = 0; state.hooks = []; state.canResolve = true; state.fetching = false; state.version = 8; vi.clearAllMocks()
    state.decide.mockResolvedValue({ id: 'decision-run' }) })
  it('必须填写理由；请求不确定时同版本同理由重试，不能重新选择', async () => {
    render(); expect(state.buttons['确认采用该完整字段组'].disabled).toBe(true)
    state.input!.onChange({ target: { value: '人工核对原表计量记录' } }); render()
    state.decide.mockRejectedValueOnce(new Error('连接中断'))
    state.buttons['确认采用该完整字段组'].onClick(); await flush(); let html = render()
    expect(html).toContain('连接中断'); expect(state.input!.disabled).toBe(true); expect(state.buttons['刷新当前值进行比较'].disabled).toBe(true)
    state.version = 99; state.buttons['用原决定核对并重试'].onClick(); await flush(); html = render()
    expect(state.decide.mock.calls[1]).toEqual(state.decide.mock.calls[0])
    expect(state.decide.mock.calls[0][1]).toMatchObject({ group: 'production', note: '人工核对原表计量记录', expected_asset_version: 8, expected_decision_id: 17 })
    expect(state.complete).toHaveBeenCalledWith('decision-run')
  })
  it('明确版本过期才重新比较，理由保留；读取中或非当前有效资料不能采纳', async () => {
    render(); state.input!.onChange({ target: { value: '核对依据' } }); render()
    state.decide.mockRejectedValueOnce({ detail: { detail: { code: 'plan_stale', message: '当前字段已变' } } })
    state.buttons['确认采用该完整字段组'].onClick(); await flush(); render()
    expect(state.refetch).toHaveBeenCalledOnce(); expect(state.input!.value).toBe('核对依据'); expect(state.input!.disabled).toBe(false)
    state.fetching = true; render(); expect(state.buttons['确认采用该完整字段组'].disabled).toBe(true)
    state.fetching = false; state.canResolve = false
    expect(render()).toContain('不能直接覆盖当前字段'); expect(state.buttons['确认采用该完整字段组'].disabled).toBe(true)
  })
})
