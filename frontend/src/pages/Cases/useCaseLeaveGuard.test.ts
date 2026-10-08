import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { useCaseLeaveGuard } from './useCaseLeaveGuard'

const state = vi.hoisted(() => ({ blocker: { state: 'unblocked', proceed: vi.fn(), reset: vi.fn() }, block: vi.fn(), effects: [] as Array<() => unknown> }))
vi.mock('react', () => ({ useEffect: (effect: () => unknown) => state.effects.push(effect) }))
vi.mock('react-router-dom', () => ({ useBlocker: (active: boolean) => { state.block(active); return state.blocker } }))
describe('页内离开确认使用路由正式阻断机制', () => {
  beforeEach(() => {
    vi.clearAllMocks(); state.effects = []; state.blocker.state = 'unblocked'
    vi.stubGlobal('window', { confirm: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })
  })
  afterEach(() => vi.unstubAllGlobals())
  it('取消离开会复位阻断，不改写history；确认才继续', () => {
    state.blocker.state = 'blocked'
    vi.mocked(window.confirm).mockReturnValue(false)
    useCaseLeaveGuard(true); state.effects[0]()
    expect(state.block).toHaveBeenCalledWith(true); expect(state.blocker.reset).toHaveBeenCalledOnce(); expect(state.blocker.proceed).not.toHaveBeenCalled()
    vi.mocked(window.confirm).mockReturnValue(true); state.effects[0]()
    expect(state.blocker.proceed).toHaveBeenCalledOnce()
  })
  it('脏表单刷新提示；保存后的非脏表单不阻挡刷新', () => {
    useCaseLeaveGuard(true); const cleanup = state.effects[1]() as () => void
    const handler = vi.mocked(window.addEventListener).mock.calls[0][1] as (event: BeforeUnloadEvent) => void
    const event = { preventDefault: vi.fn(), returnValue: undefined } as unknown as BeforeUnloadEvent
    handler(event); expect(event.preventDefault).toHaveBeenCalled(); expect(event.returnValue).toBe('')
    cleanup(); expect(window.removeEventListener).toHaveBeenCalledWith('beforeunload', handler)
    state.effects = []; vi.mocked(window.addEventListener).mockClear()
    useCaseLeaveGuard(false); state.effects[1]()
    const cleanHandler = vi.mocked(window.addEventListener).mock.calls[0][1] as (event: BeforeUnloadEvent) => void
    const cleanEvent = { preventDefault: vi.fn() } as unknown as BeforeUnloadEvent
    cleanHandler(cleanEvent); expect(cleanEvent.preventDefault).not.toHaveBeenCalled()
  })
})
