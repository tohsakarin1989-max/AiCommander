import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { BrowserRouter, Navigate, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp, ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import Layout from './components/Layout'
import TweaksPanel from './components/TweaksPanel/TweaksPanel'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Login from './pages/Auth/Login'
import { agentLabEnabled, bonusAccountingEnabled, canAccessAgentLab } from './config/features'
import { getThemeTokens, normalizeThemeMode, toggleThemeMode, type ThemeMode } from './theme/themeMode'

const Home = lazy(() => import('./pages/Home/Home'))
const Workbench = lazy(() => import('./pages/Workbench/Workbench'))
const Cases = lazy(() => import('./pages/Cases/Cases'))
const CasesMap = lazy(() => import('./pages/Cases/CasesMap'))
const CaseFeatures = lazy(() => import('./pages/Cases/CaseFeatures'))
const CaseBonusAccounting = lazy(() => import('./pages/Cases/CaseBonusAccounting'))
const CaseIntelligence = lazy(() => import('./pages/CaseIntelligence/CaseIntelligence'))
const Meetings = lazy(() => import('./pages/Meetings/Meetings'))
const Reports = lazy(() => import('./pages/Reports/Reports'))
const Settings = lazy(() => import('./pages/Settings/Settings'))
const Deployment = lazy(() => import('./pages/Deployment/Deployment'))
const Assistant = lazy(() => import('./pages/Assistant/Assistant'))
const Dashboard = lazy(() => import('./pages/Dashboard/Dashboard'))
const ConclusionFactory = lazy(() => import('./pages/Conclusions/ConclusionFactory'))
const AgentCenter = lazy(() => import('./pages/Agents/IntelligenceRuntimeCenter'))
const CaseGraph = lazy(() => import('./pages/Graphs/CaseGraph'))
const EvidenceGraph = lazy(() => import('./pages/Graphs/EvidenceGraph'))
const SituationWorkbench = lazy(() => import('./pages/Situation/SituationWorkbench'))
const CaseReviewCockpit = lazy(() => import('./pages/CaseReviewCockpit/CaseReviewCockpit'))
const AreaAnalysis = lazy(() => import('./pages/AreaAnalysis/AreaAnalysis'))
const Patrols = lazy(() => import('./pages/Patrols/Patrols'))
const GangAnalysis = lazy(() => import('./pages/Gangs/GangAnalysis'))
const SpaceTimeAnalysis = lazy(() => import('./pages/Cases/SpaceTimeAnalysis'))
const IntelliInspect = lazy(() => import('./pages/IntelliInspect/IntelliInspect'))
const Suggestions = lazy(() => import('./pages/Suggestions/Suggestions'))
const EventCenter = lazy(() => import('./pages/Events/EventCenter'))
const Jurisdiction = lazy(() => import('./pages/Jurisdiction/Jurisdiction'))
const UserManagement = lazy(() => import('./pages/Settings/UserManagement'))

const queryClient = new QueryClient()

const PageFallback = () => (
  <div className="empty-state" style={{ height: '60vh' }}>
    <div className="icon">⌛</div>
    <div>模块加载中</div>
  </div>
)

interface AuthenticatedAppProps {
  themeMode: ThemeMode
  onToggleTheme: () => void
}

function AuthenticatedApp({ themeMode, onToggleTheme }: AuthenticatedAppProps) {
  const { phase, user } = useAuth()

  if (phase !== 'authenticated' || !user) {
    return <Login />
  }

  const adminOnly = (element: React.ReactNode) => (
    user.role === 'admin' ? element : <Navigate to="/dashboard" replace />
  )

  return (
    <Layout themeMode={themeMode} onToggleTheme={onToggleTheme}>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/"                element={<Home />} />
          <Route path="/workbench"       element={<Workbench />} />
          <Route path="/dashboard"       element={<Dashboard />} />
          <Route path="/cases"           element={<Cases />} />
          <Route path="/cases/map"       element={<CasesMap />} />
          <Route path="/cases/bonus"     element={bonusAccountingEnabled ? <CaseBonusAccounting /> : <Navigate to="/cases" replace />} />
          <Route path="/cases/features"  element={<CaseFeatures />} />
          <Route path="/case-intelligence" element={<CaseIntelligence />} />
          <Route path="/situation"       element={<SituationWorkbench />} />
          <Route path="/cases/spacetime" element={<SpaceTimeAnalysis />} />
          <Route path="/meetings"        element={<Meetings />} />
          <Route path="/reports"         element={<Reports />} />
          <Route path="/conclusions"     element={<ConclusionFactory />} />
          <Route path="/deployment"      element={adminOnly(<Deployment />)} />
          <Route path="/case-review"     element={<CaseReviewCockpit />} />
          <Route path="/area-analysis"   element={<AreaAnalysis />} />
          <Route path="/suggestions"     element={<Suggestions />} />
          <Route path="/events"          element={<EventCenter />} />
          <Route path="/jurisdiction"    element={<Jurisdiction />} />
          <Route path="/graphs/serial"   element={<CaseGraph />} />
          <Route path="/graphs/evidence" element={<EvidenceGraph />} />
          <Route path="/gangs"           element={<GangAnalysis />} />
          <Route path="/patrols"         element={<Patrols />} />
          <Route path="/assistant"       element={<Assistant />} />
          <Route path="/agents"          element={agentLabEnabled && canAccessAgentLab(user.role) ? <AgentCenter /> : <Navigate to="/assistant" replace />} />
          <Route path="/settings"        element={adminOnly(<Settings />)} />
          <Route path="/settings/users"  element={adminOnly(<UserManagement />)} />
          <Route path="/intelli-inspect" element={<IntelliInspect />} />
          <Route path="*" element={<div className="empty-state" style={{height:'60vh'}}><div className="icon">◈</div><div>页面未找到</div></div>} />
        </Routes>
      </Suspense>
      <TweaksPanel />
    </Layout>
  )
}

function App() {
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => (
    normalizeThemeMode(typeof window === 'undefined' ? null : window.localStorage.getItem('aic-theme'))
  ))

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode
    window.localStorage.setItem('aic-theme', themeMode)
  }, [themeMode])

  const themeConfig = useMemo(() => getThemeTokens(themeMode), [themeMode])
  const toggleTheme = () => setThemeMode(mode => toggleThemeMode(mode))

  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: themeConfig.algorithm === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
          token: {
            ...themeConfig.tokens,
            borderRadius:       0,
            fontFamily:         "'IBM Plex Sans', -apple-system, sans-serif",
            fontSize:           13,
          },
          components: {
            Layout: {
              siderBg: '#0e1520',
              headerBg: '#0e1520',
              bodyBg: '#0a0f1a',
            },
            Modal: { borderRadiusLG: 0, borderRadiusSM: 0 },
            Drawer: { borderRadius: 0 },
            Button: { borderRadius: 0 },
            Input:  { borderRadius: 0 },
            Select: { borderRadius: 0 },
            Tag:    { borderRadius: 0 },
            Table:  { borderRadius: 0 },
            Card:   { borderRadius: 0 },
          },
        }}
      >
        <AntdApp>
          <BrowserRouter>
            <AuthProvider>
              <AuthenticatedApp themeMode={themeMode} onToggleTheme={toggleTheme} />
            </AuthProvider>
          </BrowserRouter>
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>
  )
}

export default App
