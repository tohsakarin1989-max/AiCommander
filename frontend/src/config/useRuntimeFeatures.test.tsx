import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRuntimeFeatures } from './useRuntimeFeatures'

const state = vi.hoisted(() => ({
  phase: 'authenticated', compiledBonus: true, compiledAgent: true,
  failed: false, pending: false,
  features: { legacy_operations: false, bonus_accounting: false, agent_lab: false, showcase: false } as Record<string, boolean> | undefined,
  queryEnabled: undefined as boolean | undefined,
}))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ phase: state.phase }) }))
vi.mock('./features', () => ({
  get bonusAccountingEnabled() { return state.compiledBonus },
  get agentLabEnabled() { return state.compiledAgent },
}))
vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: { enabled: boolean }) => {
    state.queryEnabled = options.enabled
    return { data: { features: state.features }, isError: state.failed, isPending: state.pending, refetch: vi.fn() }
  },
}))

function readFeatures() {
  let result!: ReturnType<typeof useRuntimeFeatures>
  function Probe() { result = useRuntimeFeatures(); return null }
  renderToStaticMarkup(<Probe />)
  return result
}

describe('运行时能力开关', () => {
  beforeEach(() => {
    state.phase = 'authenticated'; state.compiledBonus = true; state.compiledAgent = true
    state.failed = false; state.pending = false
    state.features = { legacy_operations: false, bonus_accounting: false, agent_lab: false, showcase: false }
  })

  it('构建允许但后台关闭时明确禁用，两个开关都开启才可用', () => {
    expect(readFeatures().availability.bonus_accounting).toBe('disabled')
    state.features!.bonus_accounting = true
    expect(readFeatures().bonusAccountingEnabled).toBe(true)
    state.compiledBonus = false
    expect(readFeatures().availability.bonus_accounting).toBe('disabled')
  })

  it('未登录时不请求运行状态', () => {
    state.phase = 'anonymous'
    expect(readFeatures().availability.legacy_operations).toBe('loading')
    expect(state.queryEnabled).toBe(false)
  })

  it('请求失败不使用上次开启状态，也不误判成确认关闭', () => {
    state.features!.legacy_operations = true; state.failed = true
    const result = readFeatures()
    expect(result.availability.legacy_operations).toBe('unavailable')
    expect(result.legacyOperationsEnabled).toBe(false)
  })

  it('旧服务缺少能力字段时显示无法确认而不是关闭', () => {
    state.features = undefined
    expect(readFeatures().availability.legacy_operations).toBe('unavailable')
  })

  it('首次读取完成前不渲染可选业务模块', () => {
    state.pending = true
    expect(readFeatures().availability.legacy_operations).toBe('loading')
  })
})
