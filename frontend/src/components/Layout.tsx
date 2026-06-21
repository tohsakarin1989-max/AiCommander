import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { configApi } from '../services/config'
import type { AIModel } from '../types'
import { bonusAccountingEnabled } from '../config/features'
import './Layout.css'

interface LayoutProps { children: React.ReactNode }

const NAV_ITEMS = [
  { label: '大屏', num: '01', paths: ['/dashboard'] },
  { label: '案件', num: '02', paths: bonusAccountingEnabled ? ['/cases', '/cases/map', '/cases/spacetime', '/cases/bonus', '/cases/features', '/graphs/serial'] : ['/cases', '/cases/map', '/cases/spacetime', '/cases/features', '/graphs/serial'] },
  { label: '研判', num: '03', paths: ['/case-intelligence', '/area-analysis', '/jurisdiction', '/suggestions', '/reports', '/conclusions'] },
  { label: '数智', num: '04', paths: ['/intelli-inspect'] },
  { label: '助手', num: '05', paths: ['/assistant', '/agents'] },
  { label: '设置', num: '06', paths: ['/settings'] },
]

type SubNavItem = { label: string; path: string }

const SUB_NAVS: { paths: string[]; items: SubNavItem[] }[] = [
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
    paths: ['/case-intelligence', '/area-analysis', '/jurisdiction', '/suggestions', '/reports', '/conclusions'],
    items: [
      { label: '案件研判', path: '/case-intelligence' },
      { label: '时空区域', path: '/area-analysis' },
      { label: '辖区底座', path: '/jurisdiction' },
      { label: '待办中心', path: '/suggestions' },
      { label: '分析报告', path: '/reports' },
      { label: '情报结论', path: '/conclusions' },
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

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const navigate = useNavigate()
  const location = useLocation()

  // ── 真实后端状态 ──────────────────────────────────────────────
  const { data: models, isSuccess: backendOk, isError: backendErr } = useQuery<AIModel[]>({
    queryKey: ['layout-models'],
    queryFn: () => configApi.models.list(),
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  })

  const { data: mapConfig } = useQuery({
    queryKey: ['layout-map-config'],
    queryFn: () => configApi.system.getMapConfig(),
    staleTime: 120_000,
    retry: false,
  })

  // 拼接活跃模型名称列表
  const activeModels = models?.filter(m => m.is_active) ?? []
  const modelDisplay = activeModels.length > 0
    ? activeModels.map(m => m.name || m.model_name).slice(0, 4).join(' · ')
    : backendErr ? '未连接' : '加载中...'

  // MCP 是否已配置（有非空 API Key）
  // getMapConfig() 返回 {provider, api_key, api_base_url} 对象
  const mcpActive = (() => {
    if (!mapConfig) return false
    const cfg = mapConfig as unknown as { provider?: string; api_key?: string }
    // openstreetmap 不需要 key，视为已配置
    if (cfg.provider === 'openstreetmap') return true
    return !!(cfg.api_key && cfg.api_key.trim() !== '' && cfg.api_key !== 'your_api_key_here')
  })()

  // DB/后端状态
  const dbStatus = backendErr ? 'err' : backendOk ? 'ok' : 'loading'

  // ── 子导航计算 ────────────────────────────────────────────────
  const subNav = SUB_NAVS.find(n => n.paths.includes(location.pathname)) ?? null

  const isActive = (item: typeof NAV_ITEMS[0]) =>
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
            <div className="n">涉油案件指挥系统</div>
            <div className="s">AiCommander · <span className="pulse">● 实时</span></div>
          </div>
        </a>

        {/* Tab navigation */}
        <nav className="top-nav">
          {NAV_ITEMS.map(item => (
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

        {/* User */}
        <div className="user-badge">
          <div className="a">管</div>
          <div>
            <div className="n">管理员</div>
            <div className="r">涉油专案组 · 指挥</div>
          </div>
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
            {dbStatus === 'err' ? '× SQLite' : '● SQLite'}
          </span>
        </span>
        <span>
          <span className="k">缓存</span>
          <span className={`v${dbStatus === 'ok' ? ' ok' : dbStatus === 'err' ? ' err' : ''}`}>
            {dbStatus === 'err' ? '× Redis' : '● Redis'}
          </span>
        </span>
        <span>
          <span className="k">模型</span>
          <span className={`v${activeModels.length > 0 ? ' accent' : ''}`}>{modelDisplay}</span>
        </span>
        <span>
          <span className="k">地图 MCP</span>
          <span className={`v${mcpActive ? ' ok' : ''}`}>
            {mcpActive ? '已连接' : '未配置'}
          </span>
        </span>
        <div className="statusbar-right">
          <span><span className="k">后端</span><span className={`v${dbStatus === 'ok' ? ' ok' : dbStatus === 'err' ? ' err' : ''}`}>{dbStatus === 'ok' ? '在线' : dbStatus === 'err' ? '离线' : '...'}</span></span>
          <span><span className="k">版本</span><span className="v">v0.9.3</span></span>
        </div>
      </footer>
    </div>
  )
}

export default Layout
