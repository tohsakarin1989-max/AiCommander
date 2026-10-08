import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Layout from './Layout'

const state = vi.hoisted(() => ({ path: '/workbench', role: 'admin', lab: false, version: '5.4.0-stable' as string | undefined }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, role: state.role, display_name: '测试用户' }, logout: vi.fn() }) }))
vi.mock('../theme/ThemeContext', () => ({ useThemeMode: () => ({ mode: 'dark', toggle: vi.fn() }) }))
vi.mock('../config/useRuntimeFeatures', () => ({ useRuntimeFeatures: () => ({ availability: {
  bonus_accounting: 'disabled', legacy_operations: 'disabled', showcase: 'disabled', agent_lab: state.lab ? 'enabled' : 'disabled',
}, query: { data: { version: state.version } } }) }))
vi.mock('react-router-dom', () => ({
  useLocation: () => ({ pathname: state.path, search: '?caseId=7' }), useNavigate: () => vi.fn(),
  Link: ({ to, children, ...props }: { to: string; children: ReactNode }) => <a href={to} {...props}>{children}</a>,
}))
vi.mock('./Facility/FacilityDossierDrawer', () => ({ default: () => null }))
vi.mock('antd', () => ({
  Avatar: () => null, Button: ({ children }: { children: ReactNode }) => <button>{children}</button>, Drawer: () => null,
  Breadcrumb: ({ items }: { items: { title: string }[] }) => <p>{items.map(item => item.title).join(' / ')}</p>,
  Select: ({ value, options }: { value: string; options: { value: string; label: string }[] }) => <p>{options.find(item => item.value === value)?.label}</p>,
}))

describe('精简导航后的深链页面归属', () => {
  beforeEach(() => { state.path = '/workbench'; state.role = 'admin'; state.lab = false; state.version = '5.4.0-stable' })
  it('版本未读取时不冒充本地或历史版本', () => {
    state.version = undefined
    expect(renderToStaticMarkup(<Layout>{null}</Layout>)).toContain('运行版本 待确认')
    state.version = '7.0.0-stable'
    expect(renderToStaticMarkup(<Layout>{null}</Layout>)).toContain('运行版本 7.0.0-stable')
  })
  it('日常只保留工作台，不挂载旧首页或工作会话壳', () => {
    const html = renderToStaticMarkup(<Layout><p>日常内容</p></Layout>)
    expect(html).toContain('工作台 / 日常工作')
    expect(html).not.toContain('历史工作会话操作'); expect(html).not.toContain('页面未找到')
    expect(html).not.toContain('href="/legacy-home')
  })
  it('待判断事项归日常工作，但普通工作台不挂载历史会话操作', () => {
    state.path = '/suggestions'; state.role = 'analyst'
    const html = renderToStaticMarkup(<Layout>待判断内容</Layout>)
    expect(html).toContain('工作台 / 待判断事项')
    expect(html).not.toContain('历史工作会话操作'); expect(html).not.toContain('系统运维')
  })
  it('关闭实验开关只隐藏菜单，管理员门控页仍显示正确标题', () => {
    state.path = '/agent-lab'
    const html = renderToStaticMarkup(<Layout>功能尚未启用</Layout>)
    expect(html).toContain('系统运维 / Agent 试用'); expect(html).not.toContain('页面未找到')
    expect(html).not.toContain('href="/agent-lab')
    expect(html).toContain('功能尚未启用')
  })
})
