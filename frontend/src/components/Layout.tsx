import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApartmentOutlined, DesktopOutlined, FileTextOutlined, FolderOpenOutlined, HomeOutlined, LogoutOutlined, MenuOutlined, RobotOutlined, SettingOutlined, UserOutlined } from '@ant-design/icons'
import { Avatar, Breadcrumb, Button, Drawer, Select } from 'antd'
import { useAuth } from '../auth/AuthContext'
import { useRuntimeFeatures } from '../config/useRuntimeFeatures'
import { navigation, visibleNavigation } from '../config/navigation'
import ActiveWorkSessionBar from './ActiveWorkSessionBar'
import './Layout.css'
import { MoonOutlined, SunOutlined } from '@ant-design/icons'
import { useThemeMode } from '../theme/ThemeContext'
import { caseContextPath } from '../services/caseContext'

const icons = [HomeOutlined, DesktopOutlined, FolderOpenOutlined, ApartmentOutlined, ApartmentOutlined, FileTextOutlined, RobotOutlined, SettingOutlined]

export default function Layout({ children }: { children: React.ReactNode }) {
  const { mode, toggle } = useThemeMode()
  const { user, logout } = useAuth()
  const { availability, query: { data: runtime } } = useRuntimeFeatures()
  const location = useLocation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  useEffect(() => setOpen(false), [location.pathname])
  const groups = visibleNavigation(user?.role || 'viewer', feature => availability[feature] === 'enabled')
  const current = groups.find(group => group.pages.some(page => page.path === location.pathname))
  const page = current?.pages.find(item => item.path === location.pathname)
  const secondary = current && current.pages.length > 1
  const contextPath = (path: string) => ['/cases', '/cases/map', '/case-intelligence', '/graphs/evidence', '/graphs/serial', '/assistant', '/reports', '/conclusions'].includes(path)
    ? caseContextPath(path, new URLSearchParams(location.search)) : path
  const sidebar = <>
    <Link className="workspace-brand" to="/workbench"><strong>AiCommander</strong><span>涉油案件研判</span></Link>
    <nav className="primary-navigation" aria-label="一级功能菜单">
      {groups.map(group => {
        const Icon = icons[navigation.findIndex(item => item.label === group.label)]
        return <Link key={group.label} className={`${current?.label === group.label ? 'selected' : ''} ${group.label === '系统设置' ? 'settings-entry' : ''}`} to={contextPath(group.pages[0].path)} aria-current={current?.label === group.label ? 'page' : undefined}><Icon /><span>{group.label}</span></Link>
      })}
    </nav>
    <div className="workspace-account">
      <button className="workspace-theme-toggle" type="button" role="switch" aria-checked={mode === 'dark'} aria-label="深色主题" onClick={toggle}>{mode === 'dark' ? <MoonOutlined /> : <SunOutlined />}<span>{mode === 'dark' ? '深色主题' : '浅色主题'}</span><span className="theme-switch-track" aria-hidden="true" /></button>
      <div className="account-identity"><Avatar icon={<UserOutlined />} /><div><strong>{user?.display_name}</strong><span>{user?.role === 'admin' ? '系统管理员' : user?.role === 'analyst' ? '研判人员' : '只读查看'}</span></div></div>
      <small className="workspace-version">运行版本 {runtime?.version || '5.2.0-stable'}</small>
      <button type="button" onClick={() => void logout()}><LogoutOutlined />退出登录</button>
    </div>
  </>
  return <div className={`app-shell workspace-shell ${secondary ? 'with-secondary' : ''}`}>
    <aside className="workspace-sidebar">{sidebar}</aside>
    <Drawer className="workspace-nav-drawer" title="功能导航" placement="left" width={260} open={open} onClose={() => setOpen(false)}>{sidebar}</Drawer>
    {secondary && <aside className="workspace-secondary"><h2>{current.label}</h2><nav aria-label="二级功能菜单">{current.pages.map(item => <Link key={item.path} to={contextPath(item.path)} className={item.path === location.pathname ? 'selected' : ''} aria-current={item.path === location.pathname ? 'page' : undefined}>{item.label}</Link>)}</nav></aside>}
    <div className="workspace-body">
      <header className="workspace-header"><Button className="mobile-nav-trigger" icon={<MenuOutlined />} aria-label="打开导航" onClick={() => setOpen(true)} /><Breadcrumb items={[{ title: current?.label || 'AiCommander' }, { title: page?.label || '页面未找到' }]} />
        {secondary && <Select aria-label="当前功能页面" className="compact-secondary" value={location.pathname} onChange={(path: string) => navigate(contextPath(path))} options={current.pages.map(item => ({ label: item.label, value: item.path }))} />}
      </header>
      {location.pathname === '/legacy-home' && <ActiveWorkSessionBar />}
      <main className="app-main" data-page={location.pathname}>{children}</main>
    </div>
  </div>
}
