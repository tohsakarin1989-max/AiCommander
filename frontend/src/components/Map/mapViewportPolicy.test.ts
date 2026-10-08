import { describe, expect, it } from 'vitest'
import { createViewportPolicy } from './mapViewportPolicy'

describe('地图查找仅明确操作改变视角', () => {
  it('保持视角时首轮适配，后续图层刷新及相同定位请求不再移动', () => {
    const policy = createViewportPolicy(); policy.enter('area1:snapshot1', false)
    expect(policy.fit(true)).toBe(true); expect(policy.fit(true)).toBe(false)
    expect(policy.locate({ id: 'click1', latitude: 46, longitude: 125 })).toBe(true)
    policy.enter('area1:snapshot1', false)
    expect(policy.locate({ id: 'click1', latitude: 46, longitude: 125 })).toBe(false)
    expect(policy.fit(true)).toBe(false)
    expect(policy.locate({ id: 'click2', latitude: 46, longitude: 125 })).toBe(true)
    expect(policy.focus('asset:1', true)).toBe(true); expect(policy.focus('asset:1', true)).toBe(false)
  })
  it('切换地图版本可重新适配；默认不启用的页面保留旧行为，非法坐标不移动', () => {
    const policy = createViewportPolicy(); policy.enter('area1:snapshot1', true)
    expect(policy.fit(true)).toBe(false)
    policy.enter('area2:snapshot2', false); expect(policy.fit(true)).toBe(true)
    expect(policy.fit(false)).toBe(true); expect(policy.fit(false)).toBe(true)
    expect(policy.locate({ id: 'bad', latitude: NaN, longitude: 125 })).toBe(false)
  })
})
