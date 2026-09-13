import { describe, expect, it } from 'vitest'
import { navigation, visibleNavigation } from './navigation'

describe('统一功能导航', () => {
  it('日常只有一个工作台入口，独有历史功能保留在高级功能中', () => {
    const paths = navigation.flatMap(group => group.pages.map(page => page.path))
    expect(new Set(paths).size).toBe(paths.length)
    expect(navigation.find(group => group.label === '工作台')?.pages).toEqual([
      { label: '日常工作', path: '/workbench' },
    ])
    for (const path of ['/', '/suggestions', '/case-review']) expect(paths).not.toContain(path)
    const advanced = navigation.find(group => group.label === '高级功能')?.pages.map(page => page.path)
    for (const path of ['/meetings', '/graphs/serial', '/graphs/evidence', '/conclusions', '/legacy-home']) {
      expect(advanced).toContain(path)
    }
    expect(paths).toContain('/gangs')
    expect(navigation.find(group => group.label === '指挥大屏')?.pages).toHaveLength(1)
  })
  it.each(['viewer', 'analyst'])('保留 %s 权限边界', role => {
    const paths = visibleNavigation(role, () => true).flatMap(group => group.pages.map(page => page.path))
    for (const path of ['/agents', '/deployment', '/patrols', '/settings', '/settings/users', '/cases/features']) expect(paths).not.toContain(path)
    expect(paths.includes('/showcase')).toBe(role === 'analyst')
    expect(paths.includes('/intelli-inspect')).toBe(role === 'analyst')
  })
  it('关闭功能不影响其他入口', () => {
    const paths = visibleNavigation('admin', () => false).flatMap(group => group.pages.map(page => page.path))
    expect(paths).not.toContain('/cases/bonus')
    expect(paths).not.toContain('/patrols')
    expect(paths).not.toContain('/showcase')
    expect(paths).not.toContain('/intelli-inspect')
    expect(paths).toContain('/agents')
    expect(paths).toContain('/cases/features')
  })
})
