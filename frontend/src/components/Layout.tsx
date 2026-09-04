import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { LogoutOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'
import { runtimeApi } from '../services/runtime'
import { useAuth } from '../auth/AuthContext'
import { agentLabEnabled, bonusAccountingEnabled, canAccessAgentLab } from '../config/features'
import type { ThemeMode } from '../theme/themeMode'
import './Layout.css'

interface LayoutProps {
  children: React.ReactNode
  themeMode: ThemeMode
  onToggleTheme: () => void
}

const NAV_ITEMS = [
  { label: '大屏', num: '01', paths: ['/dashboard'] },
  { label: '案件', num: '02', paths: bonusAccountingEnabled ? ['/cases', '/cases/map', '/cases/spacetime', '/cases/bonus', '/cases/features', '/graphs/serial'] : ['/cases', '/cases/map', '/cases/spacetime', '/cases/features', '/graphs/serial'] },
  { label: '研判', num: '03', paths: ['/case-review', '/suggestions', '/case-intelligence', '/area-analysis', '/jurisdiction', '/reports', '/conclusions'] },
  { label: '数智', num: '04', paths: ['/intelli-inspect'] },
  { label: '助手', num: '05', paths: agentLabEnabled ? ['/assistant', '/agents'] : ['/assistant'] },
  { label: '设置', num: '06', paths: ['/settings', '/settings/users'], adminOnly: true },
]

type SubNavItem = { label: string; path: string }

const SUB_NAVS: { paths: string[]; items: SubNavItem[] }[] = [
  {
    paths: agentLabEnabled ? ['/assistant', '/agents'] : ['/assistant'],
    items: [
      { label: '研判助手', path: '/assistant' },
      ...(agentLabEnabled ? [{ label: 'Agent Lab', path: '/agents' }] : []),
    ],
  },
  {
    paths: bonusAccountingEnabled ? ['/cases', '/cases/map', '/cases/spacetime', '/cases/bonus', '/cases/features', '/graphs/serial'] : ['/cases', '/cases/map', '/cases/spacetime', '/cases/features', '/graphs/serial'],
    items: [
      { label: '案件列表', path: '/cases' },
      { label: '地图视图', path: '/cases/map' },
      { label: '时空研判', path: '/cases/spacetime' },
      ...(bonusAccountingEnabled ? [{ label: '奖金核算', path: '/cases/bonus' }] : []),
      { label: '特征提取', path: '/cases/features' },
      { label: '关系图谱', path: '/graphs/serial' },
    ],
  },
  {
    paths: ['/case-review', '/suggestions', '/case-intelligence', '/area-analysis', '/jurisdiction', '/reports', '/conclusions'],
    items: [
      { label: '闭环工作台', path: '/case-review' },
      { label: '待办中心', path: '/suggestions' },
      { label: '案件研判', path: '/case-intelligence' },
      { label: '时空区域', path: '/area-analysis' },
      { label: '辖区底座', path: '/jurisdiction' },
      { label: '分析报告', path: '/reports' },
      { label: '情报结论', path: '/conclusions' },
    ],
  },
  {
    paths: ['/settings', '/settings/users'],
    items: [
      { label: '系统配置', path: '/settings' },
      { label: '用户与权限', path: '/settings/users' },
    ],
  },
]

function Clock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  const pad = (n: number) => String(n).padStart(2, '0')
  const days = ['日', '一', '二', '三', '四', '五', '六']
  return (
    <div className="topbar-clock">
      <div className="t">
        <span>{pad(time.getHours())}</span>
        <span className="sep">:</span>
        <span>{pad(time.getMinutes())}</span>
        <span className="sep">:</span>
        <span>{pad(time.getSeconds())}</span>
      </div>
      <div className="d">
        {time.getFullYear()}-{pad(time.getMonth() + 1)}-{pad(time.getDate())}
        {' · '}星期{days[time.getDay()]}
      </div>
    </div>
  )
}

const Layout: React.FC<LayoutProps> = ({ children, themeMode, onToggleTheme }) => {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()

  // ── 真实后端状态 ──────────────────────────────────────────────
  const { data: runtime, isSuccess: backendOk, isError: backendErr } = useQuery({
    queryKey: ['runtime-status'],
    queryFn: runtimeApi.status,
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  })

  const modelDisplay = runtime
    ? `${runtime.active_model_count} 个可用模型`
    : backendErr ? '未连接' : '加载中...'
  const mcpActive = runtime?.map_configured ?? false

  // DB/后端状态
  const dbStatus = backendErr ? 'err' : backendOk ? 'ok' : 'loading'

  // ── 子导航计算 ────────────────────────────────────────────────
  const rawSubNav = SUB_NAVS.find(n => n.paths.includes(location.pathname)) ?? null
  const subNav = rawSubNav
    ? {
        ...rawSubNav,
        items: rawSubNav.items.filter(item => item.path !== '/agents' || canAccessAgentLab(user?.role)),
      }
    : null
  const isDashboard = location.pathname === '/dashboard'

  const visibleNavItems = NAV_ITEMS.filter(item => !item.adminOnly || user?.role === 'admin')

  const isActive = (item: typeof NAV_ITEMS[number]) =>
    item.paths.some(p => location.pathname === p || location.pathname.startsWith(p + '/'))

  const goto = (e: React.MouseEvent, path: string) => {
    e.preventDefault()
    navigate(path)
  }

  return (
    <div className="app-shell">

      {/* ── Topbar ── */}
      <header className="topbar">
        {/* Brand */}
        <a className="brand" href="/dashboard" onClick={e => goto(e, '/dashboard')}>
          <div className="mark">AiC</div>
          <div className="wordmark">
            <div className="n">{isDashboard ? 'AiCommander 指挥大屏' : '涉油案件指挥系统'}</div>
            <div className="s">
              {isDashboard ? '涉油案件 · 数智化研判与防控支撑系统 · ' : 'AiCommander · '}
              <span className="pulse">● 实时</span>
            </div>
          </div>
        </a>

        {/* Tab navigation */}
        <nav className="top-nav">
          {visibleNavItems.map(item => (
            <a
              key={item.num}
              href={item.paths[0]}
              className={isActive(item) ? 'active' : ''}
              onClick={e => goto(e, item.paths[0])}
            >
              {item.label} <span className="num">{item.num}</span>
            </a>
          ))}
        </nav>

        {/* Clock */}
        <Clock />

        {/* System chips */}
        <div className="sys-chips">
          <span className={`chip${dbStatus === 'ok' ? ' live' : dbStatus === 'err' ? ' err' : ''}`}>
            <span className="dot" style={dbStatus === 'err' ? { background: 'var(--err)' } : {}} />
            {dbStatus === 'err' ? '服务离线' : '实时连接'}
          </span>
          <span className="chip accent">
            <span className="dot" style={{ background: 'var(--accent)' }} />
            AI 推理中
          </span>
        </div>

        <button
          type="button"
          className="theme-toggle"
          onClick={onToggleTheme}
          title={themeMode === 'dark' ? '切换为明亮主题' : '切换为暗色主题'}
        >
          <span className="theme-toggle-k">主题</span>
          <span className="theme-toggle-v">{themeMode === 'dark' ? '暗' : '明'}</span>
        </button>

        {/* User */}
        <div className="user-badge">
          <div className="a">{user?.display_name.slice(0, 1) || '用'}</div>
          <div>
            <div className="n">{user?.display_name}</div>
            <div className="r">{user?.role === 'admin' ? '系统管理员' : user?.role === 'analyst' ? '研判人员' : '只读查看'}</div>
          </div>
          <Tooltip title="退出登录">
            <button type="button" className="user-logout" aria-label="退出登录" onClick={() => void logout()}>
              <LogoutOutlined />
            </button>
          </Tooltip>
        </div>
      </header>

      {/* ── Sub-nav（案件/研判 模块内页签）── */}
      {subNav && (
        <nav className="sub-nav">
          {subNav.items.map(item => (
            <a
              key={item.path}
              href={item.path}
              className={location.pathname === item.path ? 'active' : ''}
              onClick={e => goto(e, item.path)}
            >
              {item.label}
            </a>
          ))}
        </nav>
      )}

      {/* ── Main content ── */}
      <main className="app-main">
        {children}
      </main>

      {/* ── Status bar ── */}
      <footer className="statusbar">
        <span>
          <span className="k">数据库</span>
          <span className={`v${dbStatus === 'ok' ? ' ok' : dbStatus === 'err' ? ' err' : ''}`}>
            {dbStatus === 'err' ? '× 未连接' : `● ${runtime?.database === 'postgresql' ? 'PostgreSQL' : 'SQLite'}`}
          </span>
        </span>
        <span>
          <span className="k">缓存</span>
          <span className={`v${dbStatus === 'ok' ? ' ok' : dbStatus === 'err' ? ' err' : ''}`}>
            {runtime?.redis === 'ok' ? '● Redis' : '× Redis'}
          </span>
        </span>
        <span>
          <span className="k">模型</span>
          <span className={`v${(runtime?.active_model_count || 0) > 0 ? ' accent' : ''}`}>{modelDisplay}</span>
        </span>
        <span>
          <span className="k">地图 MCP</span>
          <span className={`v${mcpActive ? ' ok' : ''}`}>
            {mcpActive ? `${runtime?.map_provider || '地图'} 已配置` : '未配置'}
          </span>
        </span>
        <div className="statusbar-right">
          <span><span className="k">后端</span><span className={`v${dbStatus === 'ok' ? ' ok' : dbStatus === 'err' ? ' err' : ''}`}>{dbStatus === 'ok' ? '在线' : dbStatus === 'err' ? '离线' : '...'}</span></span>
          <span><span className="k">版本</span><span className="v">v{runtime?.version || '2.0.2-stable'}</span></span>
        </div>
      </footer>
    </div>
  )
}

export default Layout
