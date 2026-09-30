import { describe, expect, it } from 'vitest'
import { navigation, navigationContext, visibleNavigation } from './navigation'

describe('统一功能导航', () => {
  it('日常只有一个工作台入口，独有历史功能保留在高级功能中', () => {
    const paths = navigation.flatMap(group => group.pages.map(page => page.path))
    expect(new Set(paths).size).toBe(paths.length)
    expect(navigation.find(group => group.label === '工作台')?.pages).toEqual([
      { label: '日常工作', path: '/workbench' },
    ])
    for (const path of ['/', '/suggestions', '/case-review', '/legacy-home', '/cases/spacetime']) expect(paths).not.toContain(path)
    const advanced = navigation.find(group => group.label === '高级功能')?.pages.map(page => page.path)
    for (const path of ['/meetings', '/graphs/serial', '/graphs/evidence', '/case-intelligence', '/deployment']) {
      expect(advanced).toContain(path)
    }
    for (const path of ['/gangs', '/patrols', '/conclusions']) expect(paths).not.toContain(path)
    expect(navigation.find(group => group.label === '案件研判')?.pages.map(page => page.path)).toContain('/topics')
    expect(navigation.find(group => group.label === '案件研判')?.pages.map(page => page.path)).not.toContain('/case-intelligence')
    expect(navigation.find(group => group.label === '指挥大屏')?.pages).toHaveLength(1)
  })
  it('区域只有一个综合入口，维护功能归系统运维，展示仍可按开关访问', () => {
    const spatial = navigation.find(group => group.label === '空间研判')!.pages
    expect(spatial.find(page => page.path === '/area-analysis')?.label).toBe('区域综合研判')
    expect(spatial.map(page => page.path)).not.toContain('/cases/spacetime')
    expect(spatial.map(page => page.path)).not.toContain('/deployment')
    const operations = navigation.find(group => group.label === '系统运维')!.pages
    for (const path of ['/agents', '/cases/features', '/agent-lab', '/settings', '/settings/users']) {
      expect(operations.find(page => page.path === path)?.adminOnly).toBe(true)
    }
    expect(visibleNavigation('analyst', () => true).flatMap(group => group.pages).map(page => page.path)).toContain('/showcase')
  })
  it('不在菜单的兼容链接仍有准确归属和标题', () => {
    expect(navigationContext('/suggestions', 'analyst')).toMatchObject({ group: '工作台', page: { label: '待判断事项' } })
    expect(navigationContext('/legacy-home', 'viewer')).toBeUndefined()
    expect(navigationContext('/cases/spacetime', 'viewer')).toMatchObject({ group: '空间研判' })
    expect(navigationContext('/agents', 'viewer')).toBeUndefined()
    expect(navigationContext('/intelli-inspect', 'analyst')).toMatchObject({ page: { label: '自动化实验' } })
    expect(navigationContext('/intelli-inspect', 'viewer')).toBeUndefined()
    expect(navigationContext('/unknown', 'admin')).toBeUndefined()
  })
  it.each(['viewer', 'analyst'])('保留 %s 权限边界', role => {
    const paths = visibleNavigation(role, () => true).flatMap(group => group.pages.map(page => page.path))
    for (const path of ['/agents', '/deployment', '/patrols', '/settings', '/settings/users', '/cases/features']) expect(paths).not.toContain(path)
    expect(paths.includes('/showcase')).toBe(role === 'analyst')
    expect(paths.includes('/topics')).toBe(role === 'analyst')
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
