import React from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import Layout from './components/Layout'
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

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <BrowserRouter
          future={{
            v7_startTransition: true,
            v7_relativeSplatPath: true,
          }}
        >
          <Layout>
            <Routes>
              <Route path="/" element={<div>首页</div>} />
              <Route path="/cases" element={<Cases />} />
              <Route path="/cases/map" element={<CasesMap />} />
              <Route path="/cases/features" element={<CaseFeatures />} />
              <Route path="/meetings" element={<Meetings />} />
              <Route path="/reports" element={<Reports />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/deployment" element={<Deployment />} />
              <Route path="/assistant" element={<Assistant />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/conclusions" element={<ConclusionFactory />} />
              <Route path="/agents" element={<AgentCenter />} />
              <Route path="/graphs/serial" element={<CaseGraph />} />
              <Route path="*" element={<div>页面未找到</div>} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </ConfigProvider>
    </QueryClientProvider>
  )
}

export default App
