import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import Layout from './components/Layout'
import TweaksPanel from './components/TweaksPanel/TweaksPanel'
import { bonusAccountingEnabled } from './config/features'

const Home = lazy(() => import('./pages/Home/Home'))
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
const AgentCenter = lazy(() => import('./pages/Agents/AgentCenter'))
const CaseGraph = lazy(() => import('./pages/Graphs/CaseGraph'))
const AreaAnalysis = lazy(() => import('./pages/AreaAnalysis/AreaAnalysis'))
const Patrols = lazy(() => import('./pages/Patrols/Patrols'))
const GangAnalysis = lazy(() => import('./pages/Gangs/GangAnalysis'))
const SpaceTimeAnalysis = lazy(() => import('./pages/Cases/SpaceTimeAnalysis'))
const IntelliInspect = lazy(() => import('./pages/IntelliInspect/IntelliInspect'))
const Suggestions = lazy(() => import('./pages/Suggestions/Suggestions'))
const EventCenter = lazy(() => import('./pages/Events/EventCenter'))
const Jurisdiction = lazy(() => import('./pages/Jurisdiction/Jurisdiction'))

const queryClient = new QueryClient()

const PageFallback = () => (
  <div className="empty-state" style={{ height: '60vh' }}>
    <div className="icon">⌛</div>
    <div>模块加载中</div>
  </div>
)

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: theme.darkAlgorithm,
          token: {
            colorBgBase:        '#0e1520',
            colorBgContainer:   '#161e2e',
            colorBgElevated:    '#1c2638',
            colorBgLayout:      '#0a0f1a',
            colorBorder:        'oklch(0.32 0.014 250 / 0.7)',
            colorBorderSecondary: 'oklch(0.32 0.014 250 / 0.35)',
            colorTextBase:      '#d0d8e8',
            colorTextSecondary: '#7a8a9a',
            colorPrimary:       '#c8a44a',
            colorPrimaryHover:  '#d4b05a',
            colorLink:          '#c8a44a',
            colorSplit:         'oklch(0.32 0.014 250 / 0.7)',
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
        <BrowserRouter
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Layout>
            <Suspense fallback={<PageFallback />}>
              <Routes>
                <Route path="/"                element={<Home />} />
                <Route path="/dashboard"       element={<Dashboard />} />
                <Route path="/cases"           element={<Cases />} />
                <Route path="/cases/map"       element={<CasesMap />} />
                <Route path="/cases/bonus"     element={bonusAccountingEnabled ? <CaseBonusAccounting /> : <Navigate to="/cases" replace />} />
                <Route path="/cases/features"  element={<CaseFeatures />} />
                <Route path="/case-intelligence" element={<CaseIntelligence />} />
                <Route path="/cases/spacetime" element={<SpaceTimeAnalysis />} />
                <Route path="/meetings"        element={<Meetings />} />
                <Route path="/reports"         element={<Reports />} />
                <Route path="/conclusions"     element={<ConclusionFactory />} />
                <Route path="/deployment"      element={<Deployment />} />
                <Route path="/area-analysis"   element={<AreaAnalysis />} />
                <Route path="/suggestions"     element={<Suggestions />} />
                <Route path="/events"          element={<EventCenter />} />
                <Route path="/jurisdiction"    element={<Jurisdiction />} />
                <Route path="/graphs/serial"   element={<CaseGraph />} />
                <Route path="/gangs"           element={<GangAnalysis />} />
                <Route path="/patrols"         element={<Patrols />} />
                <Route path="/assistant"       element={<Assistant />} />
                <Route path="/agents"          element={<AgentCenter />} />
                <Route path="/settings"        element={<Settings />} />
                <Route path="/intelli-inspect" element={<IntelliInspect />} />
                <Route path="*"               element={<div className="empty-state" style={{height:'60vh'}}><div className="icon">◈</div><div>页面未找到</div></div>} />
              </Routes>
            </Suspense>
          </Layout>
        </BrowserRouter>
        <TweaksPanel />
      </ConfigProvider>
    </QueryClientProvider>
  )
}

export default App
