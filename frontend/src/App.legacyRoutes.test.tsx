import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthenticatedApp, caseReviewDestination, conclusionDestination, LegacyCaseReviewRedirect, LegacySpaceTimeRedirect, spaceTimeDestination } from './App'
import RuntimeFeatureGate from './components/RuntimeFeatureGate'
import { Navigate } from 'react-router-dom'

const state = vi.hoisted(() => ({ role: 'admin', routes: [] as Array<{ path: string; element: ReactElement<{ feature?: string }> }> }))
vi.mock('./auth/AuthContext', () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: () => ({ phase: 'authenticated', user: { id: 1, role: state.role }, sessionEpoch: 1 }),
}))
vi.mock('./components/Layout', () => ({ default: ({ children }: { children: ReactNode }) => children }))
vi.mock('react-router-dom', () => ({
  BrowserRouter: ({ children }: { children: ReactNode }) => children,
  Routes: ({ children }: { children: ReactNode }) => children,
  Navigate: () => null,
  Route: (props: typeof state.routes[number]) => { state.routes.push(props); return null },
}))

describe('旧 Lab 与新运行中心路由边界', () => {
  beforeEach(() => { state.role = 'admin'; state.routes = [] })
  it('管理员访问旧 Lab 必须通过运行时功能门控，新运行中心保持独立', () => {
    renderToStaticMarkup(<AuthenticatedApp />)
    const lab = state.routes.find(route => route.path === '/agent-lab')!.element
    expect(lab.type).toBe(RuntimeFeatureGate)
    expect(lab.props.feature).toBe('agent_lab')
    const current = state.routes.find(route => route.path === '/agents')!.element
    expect(current.type).not.toBe(RuntimeFeatureGate)
    expect(current.type).not.toBe(Navigate)
  })
  it.each(['analyst', 'viewer'])('%s 无法绕过管理员专用页面权限', role => {
    state.role = role
    renderToStaticMarkup(<AuthenticatedApp />)
    for (const path of ['/agent-lab', '/agents', '/cases/features']) {
      expect(state.routes.find(route => route.path === path)!.element.type).toBe(Navigate)
    }
  })

  it('首页进入日常工作台，旧壳与重复模块不再挂载', () => {
    renderToStaticMarkup(<AuthenticatedApp />)
    const home = state.routes.find(route => route.path === '/')!.element
    expect(home.type).toBe(Navigate)
    expect(home.props).toMatchObject({ to: '/workbench', replace: true })
    for (const path of ['/legacy-home', '/gangs', '/patrols']) expect(state.routes.find(route => route.path === path)).toBeUndefined()
    expect(conclusionDestination('?conclusionId=3')).toBe('/reports?kind=conclusion&resultId=3')
    expect(conclusionDestination('?caseId=42')).toBe('/reports?catalogKind=conclusion&subject=case&subjectId=42')
    expect(conclusionDestination('?conclusionId=https://example.com')).toBe('/reports?catalogKind=conclusion')
    expect(state.routes.find(route => route.path === '/suggestions')).toBeDefined()
  })

  it('旧闭环入口只保留明确案件编号，不再挂载旧示例数据驾驶舱', () => {
    renderToStaticMarkup(<AuthenticatedApp />)
    expect(state.routes.find(route => route.path === '/case-review')!.element.type).toBe(LegacyCaseReviewRedirect)
    expect(caseReviewDestination('?caseId=42&panel=review')).toBe('/cases?caseId=42')
    expect(caseReviewDestination('?caseId=https://example.com')).toBe('/cases')
    expect(caseReviewDestination('?caseId=-2')).toBe('/cases')
    expect(caseReviewDestination('')).toBe('/cases')
  })

  it('模拟自动化与展示深链接均执行功能门控', () => {
    renderToStaticMarkup(<AuthenticatedApp />)
    for (const path of ['/intelli-inspect', '/showcase']) {
      const route = state.routes.find(item => item.path === path)!.element
      expect(route.type).toBe(RuntimeFeatureGate)
      expect(route.props.feature).toBe('showcase')
    }
  })

  it('旧时空深链进入综合研判时间视图，保留重复筛选、对象与锚点', () => {
    renderToStaticMarkup(<AuthenticatedApp />)
    expect(state.routes.find(route => route.path === '/cases/spacetime')!.element.type).toBe(LegacySpaceTimeRedirect)
    const search = '?caseId=42&assetId=6&eventId=7&operational_area_id=3&statuses=pending&statuses=resolved&oil_types=原油&oil_types=含油水&has_geo=false&time_scope=all_history&start_date=2026-01-01&end_date=2026-09-01'
    const destination = new URL(spaceTimeDestination(search, '#month'), 'http://localhost')
    expect(destination.pathname).toBe('/area-analysis')
    expect(destination.hash).toBe('#month')
    for (const key of new Set(new URLSearchParams(search).keys())) {
      expect(destination.searchParams.getAll(key)).toEqual(new URLSearchParams(search).getAll(key))
    }
    expect(destination.searchParams.get('regional_view')).toBe('time')
    const invalid = new URL(spaceTimeDestination('?assetId=7&assetId=8&start_date=invalid'), 'http://localhost')
    expect(invalid.searchParams.getAll('assetId')).toEqual(['7', '8'])
    expect(invalid.searchParams.get('start_date')).toBe('invalid')
  })

  it('只读账号无法绕过展示与实验入口的角色限制', () => {
    state.role = 'viewer'
    renderToStaticMarkup(<AuthenticatedApp />)
    for (const path of ['/intelli-inspect', '/showcase']) {
      expect(state.routes.find(route => route.path === path)!.element.type).toBe(Navigate)
    }
  })
})
