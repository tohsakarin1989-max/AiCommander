import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import RuntimeFeatureGate from './RuntimeFeatureGate'
import type { FeatureAvailability } from '../config/useRuntimeFeatures'

const state = vi.hoisted(() => ({ availability: 'disabled' as FeatureAvailability }))
vi.mock('../config/useRuntimeFeatures', () => ({ useRuntimeFeatures: () => ({
  availability: { legacy_operations: state.availability }, query: { refetch: vi.fn() },
}) }))

describe('可选模块入口', () => {
  it('关闭、加载和不可用状态都不会挂载业务页面', () => {
    const child = vi.fn(() => <p>业务页面</p>)
    const Child = child
    for (const value of ['disabled', 'loading', 'unavailable'] as const) {
      state.availability = value
      const html = renderToStaticMarkup(<RuntimeFeatureGate feature="legacy_operations" label="历史巡逻模块"><Child /></RuntimeFeatureGate>)
      expect(html).not.toContain('业务页面')
      expect(html).toContain(value === 'disabled' ? '未启用' : value === 'loading' ? '正在确认' : '状态暂不可用')
      if (value === 'unavailable') expect(html).not.toContain('未启用')
    }
    expect(child).not.toHaveBeenCalled()
  })

  it('能力确认为开启后才挂载业务页面', () => {
    state.availability = 'enabled'
    expect(renderToStaticMarkup(<RuntimeFeatureGate feature="legacy_operations" label="历史巡逻模块"><p>业务页面</p></RuntimeFeatureGate>)).toContain('业务页面')
  })
})
