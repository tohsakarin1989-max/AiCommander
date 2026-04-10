import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import Layout from './components/Layout'
import Home from './pages/Home/Home'
import Cases from './pages/Cases/Cases'
import CasesMap from './pages/Cases/CasesMap'
import CaseFeatures from './pages/Cases/CaseFeatures'
import Meetings from './pages/Meetings/Meetings'
import Reports from './pages/Reports/Reports'
import Settings from './pages/Settings/Settings'
import Deployment from './pages/Deployment/Deployment'
import Assistant from './pages/Assistant/Assistant'
import Dashboard from './pages/Dashboard/Dashboard'
import ConclusionFactory from './pages/Conclusions/ConclusionFactory'
import AgentCenter from './pages/Agents/AgentCenter'
import CaseGraph from './pages/Graphs/CaseGraph'
import AreaAnalysis from './pages/AreaAnalysis/AreaAnalysis'
import Patrols from './pages/Patrols/Patrols'
import GangAnalysis from './pages/Gangs/GangAnalysis'
import SpaceTimeAnalysis from './pages/Cases/SpaceTimeAnalysis'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: theme.darkAlgorithm,
          token: {
            colorBgBase: '#0a0e17',
            colorBgContainer: '#0d1117',
            colorBgElevated: '#0d1117',
            colorBgLayout: '#0a0e17',
            colorBorder: '#1e293b',
            colorBorderSecondary: '#1e293b',
            colorTextBase: '#e2e8f0',
            colorTextSecondary: '#94a3b8',
            colorPrimary: '#7dd3fc',
            colorPrimaryHover: '#93c5fd',
            colorLink: '#7dd3fc',
            colorSplit: '#1e293b',
          },
          components: {
            Layout: {
              siderBg: '#0d1117',
              headerBg: '#0d1117',
              bodyBg: '#0a0e17',
              triggerBg: '#1e293b',
            },
            Menu: {
              darkItemBg: '#0d1117',
              darkSubMenuItemBg: '#0a0e17',
              darkItemSelectedBg: 'rgba(125,211,252,0.12)',
              darkItemSelectedColor: '#7dd3fc',
              darkItemColor: '#cbd5e1',
            },
          },
        }}
      >
        <BrowserRouter
          future={{
            v7_startTransition: true,
            v7_relativeSplatPath: true,
          }}
        >
          <Layout>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/cases" element={<Cases />} />
              <Route path="/cases/map" element={<CasesMap />} />
              <Route path="/cases/features" element={<CaseFeatures />} />
              <Route path="/cases/spacetime" element={<SpaceTimeAnalysis />} />
              <Route path="/meetings" element={<Meetings />} />
              <Route path="/reports" element={<Reports />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/deployment" element={<Deployment />} />
              <Route path="/assistant" element={<Assistant />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/conclusions" element={<ConclusionFactory />} />
              <Route path="/agents" element={<AgentCenter />} />
              <Route path="/graphs/serial" element={<CaseGraph />} />
              <Route path="/area-analysis" element={<AreaAnalysis />} />
              <Route path="/patrols" element={<Patrols />} />
              <Route path="/gangs" element={<GangAnalysis />} />
              <Route path="*" element={<div>页面未找到</div>} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </ConfigProvider>
    </QueryClientProvider>
  )
}

export default App
