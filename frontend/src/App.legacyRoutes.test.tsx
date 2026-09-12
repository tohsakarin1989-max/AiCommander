import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthenticatedApp, caseReviewDestination, LegacyCaseReviewRedirect } from './App'
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

  it('首页只进入日常工作台，旧首页仍可访问', () => {
    renderToStaticMarkup(<AuthenticatedApp />)
    const home = state.routes.find(route => route.path === '/')!.element
    expect(home.type).toBe(Navigate)
    expect(home.props).toMatchObject({ to: '/workbench', replace: true })
    expect(state.routes.find(route => route.path === '/legacy-home')).toBeDefined()
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

  it('只读账号无法绕过展示与实验入口的角色限制', () => {
    state.role = 'viewer'
    renderToStaticMarkup(<AuthenticatedApp />)
    for (const path of ['/intelli-inspect', '/showcase']) {
      expect(state.routes.find(route => route.path === path)!.element.type).toBe(Navigate)
    }
  })
})
