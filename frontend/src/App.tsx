import { lazy, Suspense, useState } from 'react'
import { createBrowserRouter, RouterProvider, Navigate, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp, ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import Layout from './components/Layout'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Login from './pages/Auth/Login'
import RuntimeFeatureGate from './components/RuntimeFeatureGate'
import { getThemeTokens } from './theme/themeMode'
import { ThemeProvider, useThemeMode } from './theme/ThemeContext'

const Showcase = lazy(() => import('./pages/Showcase/Showcase'))
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
const Topics = lazy(() => import('./pages/Topics/Topics'))
const Dashboard = lazy(() => import('./pages/Dashboard/Dashboard'))
const AgentCenter = lazy(() => import('./pages/Agents/IntelligenceRuntimeCenter'))
const AgentLab = lazy(() => import('./pages/Agents/AgentCenter'))
const CaseGraph = lazy(() => import('./pages/Graphs/CaseGraph'))
const EvidenceGraph = lazy(() => import('./pages/Graphs/EvidenceGraph'))
const SituationWorkbench = lazy(() => import('./pages/Situation/SituationWorkbench'))
const AreaAnalysis = lazy(() => import('./pages/AreaAnalysis/AreaAnalysis'))
const IntelliInspect = lazy(() => import('./pages/IntelliInspect/IntelliInspect'))
const Suggestions = lazy(() => import('./pages/Suggestions/Suggestions'))
const EventCenter = lazy(() => import('./pages/Events/EventCenter'))
const Jurisdiction = lazy(() => import('./pages/Jurisdiction/Jurisdiction'))
const UserManagement = lazy(() => import('./pages/Settings/UserManagement'))
const Setup = lazy(() => import('./pages/Settings/Setup'))

const queryClient = new QueryClient()

const PageFallback = () => (
  <div className="empty-state" style={{ height: '60vh' }}>
    <div className="icon">⌛</div>
    <div>模块加载中</div>
  </div>
)

export function caseReviewDestination(search: string): string {
  const caseId = new URLSearchParams(search).get('caseId')
  return caseId && /^[1-9]\d*$/.test(caseId) ? `/cases?caseId=${caseId}` : '/cases'
}

export function LegacyCaseReviewRedirect() {
  const { search } = useLocation()
  return <Navigate to={caseReviewDestination(search)} replace />
}

export function spaceTimeDestination(search: string, hash = ''): string {
  const params = new URLSearchParams(search)
  params.set('regional_view', 'time')
  return `/area-analysis?${params}${hash}`
}

export function LegacySpaceTimeRedirect() {
  const { search, hash } = useLocation()
  return <Navigate to={spaceTimeDestination(search, hash)} replace />
}

export function conclusionDestination(search: string) {
  const params = new URLSearchParams(search)
  const id = params.get('conclusionId')
  if (id && /^[1-9]\d*$/.test(id)) return `/reports?kind=conclusion&resultId=${id}`
  const caseId = params.get('caseId')
  return `/reports?catalogKind=conclusion${caseId && /^[1-9]\d*$/.test(caseId) ? `&subject=case&subjectId=${caseId}` : ''}`
}
function LegacyConclusionRedirect() {
  return <Navigate to={conclusionDestination(useLocation().search)} replace />
}

export function AuthenticatedApp() {
  const { phase, user, sessionEpoch } = useAuth()

  if (phase !== 'authenticated' || !user) {
    return <Login />
  }

  const adminOnly = (element: React.ReactNode) => (
    user.role === 'admin' ? element : <Navigate to="/dashboard" replace />
  )

  return (
    <Layout key={`${user.id}:${sessionEpoch}`}>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/"                element={<Navigate to="/workbench" replace />} />
          <Route path="/workbench"       element={<Workbench />} />
          <Route path="/dashboard"       element={<Dashboard />} />
          <Route path="/showcase" element={user.role !== 'viewer' ? <RuntimeFeatureGate feature="showcase" label="能力演示"><Showcase /></RuntimeFeatureGate> : <Navigate to="/dashboard" replace />} />
          <Route path="/cases"           element={<Cases />} />
          <Route path="/cases/map"       element={<CasesMap />} />
          <Route path="/cases/bonus"     element={<RuntimeFeatureGate feature="bonus_accounting" label="奖金核算"><CaseBonusAccounting /></RuntimeFeatureGate>} />
          <Route path="/cases/features"  element={adminOnly(<CaseFeatures />)} />
          <Route path="/case-intelligence" element={<CaseIntelligence />} />
          <Route path="/situation"       element={<SituationWorkbench />} />
          <Route path="/cases/spacetime" element={<LegacySpaceTimeRedirect />} />
          <Route path="/meetings"        element={<Meetings />} />
          <Route path="/reports"         element={<Reports />} />
          <Route path="/conclusions"     element={<LegacyConclusionRedirect />} />
          <Route path="/deployment"      element={adminOnly(<Deployment />)} />
          <Route path="/case-review"     element={<LegacyCaseReviewRedirect />} />
          <Route path="/area-analysis"   element={<AreaAnalysis />} />
          <Route path="/suggestions"     element={<Suggestions />} />
          <Route path="/events"          element={<EventCenter />} />
          <Route path="/jurisdiction"    element={<Jurisdiction />} />
          <Route path="/graphs/serial"   element={<CaseGraph />} />
          <Route path="/graphs/evidence" element={<EvidenceGraph />} />
          <Route path="/assistant"       element={<Assistant />} />
          <Route path="/topics"          element={<Topics />} />
          <Route path="/agent-lab" element={adminOnly(<RuntimeFeatureGate feature="agent_lab" label="Agent 试用"><AgentLab /></RuntimeFeatureGate>)} />
          <Route path="/agents"          element={adminOnly(<AgentCenter />)} />
          <Route path="/settings"        element={adminOnly(<Settings />)} />
          <Route path="/settings/users"  element={adminOnly(<UserManagement />)} />
          <Route path="/settings/setup"  element={adminOnly(<Setup />)} />
          <Route path="/intelli-inspect" element={user.role !== 'viewer' ? <RuntimeFeatureGate feature="showcase" label="自动化实验"><IntelliInspect /></RuntimeFeatureGate> : <Navigate to="/dashboard" replace />} />
          <Route path="*" element={<div className="empty-state" style={{height:'60vh'}}><div className="icon">◈</div><div>页面未找到</div></div>} />
        </Routes>
      </Suspense>
    </Layout>
  )
}

let applicationRouter: ReturnType<typeof createBrowserRouter> | undefined
function getApplicationRouter() {
  applicationRouter ??= createBrowserRouter([
    { path: '*', element: <AuthProvider><AuthenticatedApp /></AuthProvider> },
  ])
  return applicationRouter
}

function App() {
  const [router] = useState(getApplicationRouter)
  const { mode } = useThemeMode()
  const themeConfig = getThemeTokens(mode)

  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
          token: {
            ...themeConfig.tokens,
            colorTextLightSolid: mode === 'dark' ? '#10251e' : '#ffffff',
            borderRadius:       4,
            controlHeight:      36,
            fontFamily:         '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
            fontSize:           14,
          },
          components: {
            Layout: {
              siderBg: '#242a2b',
              headerBg: themeConfig.tokens.colorBgContainer,
              bodyBg: themeConfig.tokens.colorBgLayout,
            },
            Modal: { borderRadiusLG: 4, borderRadiusSM: 4 },
            Drawer: { borderRadius: 0 },
            Button: { borderRadius: 4 },
            Input:  { borderRadius: 4 },
            Select: { borderRadius: 4 },
            Tag:    { borderRadius: 4 },
            Table:  { borderRadius: 0 },
            Card:   { borderRadius: 4 },
          },
        }}
      >
        <AntdApp>
          <RouterProvider router={router} />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>
  )
}

export default function ThemedApp() { return <ThemeProvider><App /></ThemeProvider> }
