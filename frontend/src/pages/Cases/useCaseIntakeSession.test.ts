import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCaseDraftAutosave } from './useCaseIntakeSession'

const hooks = vi.hoisted(() => ({ effects: [] as Array<() => (() => void) | undefined>, ref: { current: undefined as unknown } }))
vi.mock('react', () => ({ useEffect: (effect: () => (() => void) | undefined) => hooks.effects.push(effect),
  useRef: (initial: unknown) => { hooks.ref.current = initial; return hooks.ref }, useCallback: (callback: unknown) => callback, useState: vi.fn() }))

describe('private server draft autosave scheduling', () => {
  beforeEach(() => { hooks.effects = []; vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })
  it('debounces changes and cancels an old pending timer before saving the newest snapshot', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    useCaseDraftAutosave({ enabled: true, blocked: false, changeVersion: 1, save })
    const cleanup = hooks.effects[0]()
    await vi.advanceTimersByTimeAsync(1000); expect(save).not.toHaveBeenCalled()
    cleanup?.()
    useCaseDraftAutosave({ enabled: true, blocked: false, changeVersion: 2, save })
    const cleanupLatest = hooks.effects[1]()
    await vi.advanceTimersByTimeAsync(1499); expect(save).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1); expect(save).toHaveBeenCalledOnce()
    cleanupLatest?.()
  })
  it('does not auto-retry an unknown outcome, conflict, closed form or ongoing submission', async () => {
    const save = vi.fn()
    useCaseDraftAutosave({ enabled: true, blocked: true, changeVersion: 3, save })
    useCaseDraftAutosave({ enabled: false, blocked: false, changeVersion: 4, save })
    hooks.effects.forEach(effect => effect())
    await vi.advanceTimersByTimeAsync(10000)
    expect(save).not.toHaveBeenCalled()
  })
  it('cancels on leaving and never queues a late background write', async () => {
    const save = vi.fn()
    useCaseDraftAutosave({ enabled: true, blocked: false, changeVersion: 1, save })
    hooks.effects[0]()?.()
    await vi.advanceTimersByTimeAsync(2000)
    expect(save).not.toHaveBeenCalled()
  })
})
