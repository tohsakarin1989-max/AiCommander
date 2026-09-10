/**
 * 指挥大屏 - 领导研判视图
 * - 三栏并列：左趋势 / 中地图 / 右 AI 产出
 * - SVG viewBox 缩放 / 平移（按钮 + 鼠标滚轮 + 拖拽）
 * - 列表慢速自动轮播，悬停暂停
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  AimOutlined,
  AlertOutlined,
  CalendarOutlined,
  DatabaseOutlined,
  FireOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { aiApi, automationAlertApi, caseApi, patrolApi, reportApi, suggestionsApi } from '../../services'
import { authApi } from '../../services/auth'
import { jurisdictionApi, type WellAttentionOverview } from '../../services/jurisdiction'
import type { AreaRisk, Case, ChainLink } from '../../types'
import AutoScrollList from './AutoScrollList'
import {
  buildDashboardModel,
  buildWellAttentionDashboardView,
  type DashboardAutomationAlert,
  type DashboardConclusionDraft,
  type DashboardHotspot,
  type DashboardKpi,
  type DashboardReportDraft,
} from './dashboardCommandModel'
import DashboardRiskMap, { type DashboardMapLayer } from './DashboardRiskMap'
import './Dashboard.css'

interface DashboardStatistics {
  total_cases: number
  today_cases: number
  pending_cases: number
  resolved_cases: number
  this_week_cases: number
  this_month_cases: number
}

const EMPTY_CASES: Case[] = []
const EMPTY_AREA_RISKS: AreaRisk[] = []
const EMPTY_HOTSPOTS: DashboardHotspot[] = []
const EMPTY_ALERTS: DashboardAutomationAlert[] = []
const EMPTY_CHAIN_LINKS: ChainLink[] = []
const EMPTY_REPORTS: DashboardReportDraft[] = []
const EMPTY_CONCLUSIONS: DashboardConclusionDraft[] = []
const EMPTY_SUGGESTIONS: NonNullable<Awaited<ReturnType<typeof suggestionsApi.list>>['suggestions']> = []

const DASHBOARD_CASE_STATUS_LABEL: Record<string, string> = {
  pending: '待处理',
  processing: '处理中',
  completed: '已完成',
  resolved: '已办结',
  failed: '异常',
}

function Panel({ className = '', title, meta, children }: {
  className?: string
  title: string
  meta?: ReactNode
  children: ReactNode
}) {
  return (
    <article className={`card db-command-card ${className}`}>
      <div className="card-head db-command-head">
        <span className="ico">◆</span>
        <span className="ti">{title}</span>
        <span className="db-spacer" />
        {meta && <span className="db-head-meta">{meta}</span>}
      </div>
      <div className="card-body db-command-body">{children}</div>
    </article>
  )
}

function KpiCard({ item, icon }: { item: DashboardKpi; icon: ReactNode }) {
  return (
    <div
      className={`kpill db-command-kpi db-command-kpi--${item.tone || 'normal'}`}
      title={`${item.label} ${item.value} ${item.detail}，口径：${item.scope}`}
    >
      <div className="db-kpi-icon">{icon}</div>
      <div className="db-kpi-main">
        <div className="db-kpi-topline">
          <div className="lbl">{item.label}</div>
          <div className="scope">口径：{item.scope}</div>
        </div>
        <div className="db-kpi-value-row">
          <div className="val">{item.value}</div>
          <div className="sub">{item.detail}</div>
        </div>
      </div>
    </div>
  )
}

function TrendBars({ buckets }: { buckets: ReturnType<typeof buildDashboardModel>['weeklyTrend'] }) {
  return (
    <div className="db-trend-bars">
      <div className="db-trend-axis"><span>高</span><span>低</span></div>
      {buckets.map(bucket => (
        <div className="db-trend-bar-wrap" key={bucket.label}>
          <div
            className={`db-trend-bar db-trend-bar--${bucket.tone}`}
            style={{ height: `${bucket.height}%` }}
            title={`${bucket.label}: ${bucket.count} 起`}
          />
          <span>{bucket.label}</span>
        </div>
      ))}
    </div>
  )
}

const Dashboard = () => {
  const [wsConnected, setWsConnected] = useState(false)
  const [cases, setCases] = useState<Case[]>([])
  const [statistics, setStatistics] = useState<DashboardStatistics>({
    total_cases: 0,
    today_cases: 0,
    pending_cases: 0,
    resolved_cases: 0,
    this_week_cases: 0,
    this_month_cases: 0,
  })
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [mapLayer, setMapLayer] = useState<DashboardMapLayer>('attention')
  const [activeAreaId, setActiveAreaId] = useState<number | null>(null)

  const dashRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)

  const areaScopesQuery = useQuery({
    queryKey: ['my-area-scopes'],
    queryFn: authApi.myAreaScopes,
    staleTime: 5 * 60_000,
  })

  useEffect(() => {
    const scopes = areaScopesQuery.data ?? []
    if (scopes.length === 0) return
    if (activeAreaId && scopes.some(scope => scope.operational_area_id === activeAreaId)) return
    const preferred = scopes.find(scope => scope.is_default) ?? scopes[0]
    setActiveAreaId(preferred.operational_area_id)
  }, [activeAreaId, areaScopesQuery.data])

  useEffect(() => {
    if (activeAreaId == null) return undefined
    setCases([])
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/ws/dashboard?operational_area_id=${encodeURIComponent(String(activeAreaId))}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws
    ws.onopen = () => setWsConnected(true)
    ws.onerror = () => setWsConnected(false)
    ws.onclose = () => setWsConnected(false)
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'initial_data') {
          setCases(data.data.cases || [])
          if (data.data.statistics) setStatistics(previous => ({ ...previous, ...data.data.statistics }))
        }
        if (data.type === 'update') {
          if (data.data?.new_cases) {
            setCases(previous => {
              const ids = new Set(previous.map(item => item.id))
              return [...data.data.new_cases.filter((item: Case) => !ids.has(item.id)), ...previous].slice(0, 100)
            })
          }
          if (data.data?.statistics) setStatistics(previous => ({ ...previous, ...data.data.statistics }))
        }
      } catch (_) {
        setWsConnected(false)
      }
    }
    return () => ws.close()
  }, [activeAreaId])

  const { data: queriedCases } = useQuery<Case[]>({
    queryKey: ['dashboard-cases', activeAreaId],
    queryFn: () => caseApi.getCases({
      limit: 100,
      operational_area_id: activeAreaId as number,
    }),
    enabled: activeAreaId != null,
    refetchInterval: 60_000,
  })
  const { data: areaRisks } = useQuery<AreaRisk[]>({
    queryKey: ['dashboard-area-risks'],
    queryFn: () => patrolApi.getAreaRisks({ limit: 5, min_risk: 0.5 }),
    refetchInterval: 120_000,
  })
  const { data: rawHotspots } = useQuery<DashboardHotspot[]>({
    queryKey: ['dashboard-map-hotspots', activeAreaId],
    queryFn: () => caseApi.getHotspots(1.0, 3, activeAreaId as number),
    enabled: activeAreaId != null,
    refetchInterval: 120_000,
  })
  const { data: chainMapData } = useQuery({
    queryKey: ['dashboard-chain-map-data'],
    queryFn: () => caseApi.getChainMapData(),
    refetchInterval: 120_000,
  })
  const { data: automationAlerts } = useQuery<DashboardAutomationAlert[]>({
    queryKey: ['dashboard-automation-alerts'],
    queryFn: () => automationAlertApi.list({ limit: 20 }),
    refetchInterval: 120_000,
    retry: false,
  })
  const { data: reports } = useQuery<DashboardReportDraft[]>({
    queryKey: ['dashboard-reports'],
    queryFn: () => reportApi.list({ limit: 40 }),
    refetchInterval: 120_000,
    retry: false,
  })
  const { data: conclusions } = useQuery<DashboardConclusionDraft[]>({
    queryKey: ['dashboard-conclusions'],
    queryFn: () => aiApi.conclusion.list(),
    refetchInterval: 120_000,
    retry: false,
  })
  const { data: suggestionsData } = useQuery({
    queryKey: ['dashboard-suggestions'],
    queryFn: () => suggestionsApi.list({ limit: 30, status: 'open' }),
    refetchInterval: 120_000,
    retry: false,
  })
  const { data: wellAttention } = useQuery<WellAttentionOverview>({
    queryKey: ['dashboard-well-attention', activeAreaId],
    queryFn: () => jurisdictionApi.getWellAttentionOverview(30, 1, activeAreaId as number),
    enabled: activeAreaId != null,
    refetchInterval: 120_000,
    retry: false,
  })

  const dashboardCases = cases.length > 0 ? cases : (queriedCases ?? EMPTY_CASES)
  const dashboardCaseIds = useMemo(
    () => new Set(dashboardCases.map(item => item.id)),
    [dashboardCases],
  )
  const dashboardChainLinks = useMemo(
    () => (chainMapData?.chain_links ?? EMPTY_CHAIN_LINKS).filter(
      (link: ChainLink) => dashboardCaseIds.has(link.case_id_a) && dashboardCaseIds.has(link.case_id_b),
    ),
    [chainMapData, dashboardCaseIds],
  )
  const activeAreaName = areaScopesQuery.data?.find(
    scope => scope.operational_area_id === activeAreaId,
  )?.area_name

  const model = useMemo(() => buildDashboardModel({
    cases: dashboardCases,
    chainLinks: dashboardChainLinks,
    areaRisks: areaRisks ?? EMPTY_AREA_RISKS,
    hotspots: rawHotspots ?? EMPTY_HOTSPOTS,
    automationAlerts: automationAlerts ?? EMPTY_ALERTS,
    reports: reports ?? EMPTY_REPORTS,
    conclusions: conclusions ?? EMPTY_CONCLUSIONS,
    suggestions: suggestionsData?.suggestions ?? EMPTY_SUGGESTIONS,
    statistics,
  }), [dashboardCases, dashboardChainLinks, areaRisks, rawHotspots, automationAlerts, reports, conclusions, suggestionsData, statistics])
  const wellView = useMemo(
    () => buildWellAttentionDashboardView(wellAttention),
    [wellAttention],
  )

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) dashRef.current?.requestFullscreen?.()
    else document.exitFullscreen?.()
  }, [])

  useEffect(() => {
    const handleFullscreen = () => setIsFullscreen(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', handleFullscreen)
    return () => document.removeEventListener('fullscreenchange', handleFullscreen)
  }, [])

  const leadershipKpis: Array<{ item: DashboardKpi; icon: ReactNode }> = [
    { item: model.kpis.monthlyCases, icon: <CalendarOutlined /> },
    { item: wellView.kpis.wells, icon: <DatabaseOutlined /> },
    { item: wellView.kpis.attentionWells, icon: <FireOutlined /> },
    { item: wellView.kpis.observations, icon: <AlertOutlined /> },
    { item: wellView.kpis.attentionRegions, icon: <AimOutlined /> },
    { item: wellView.kpis.aiStatus, icon: <RobotOutlined /> },
  ]
  const recentCaseItems = dashboardCases.slice(0, 8).map(caseItem => ({
    title: caseItem.case_number,
    detail: `${caseItem.location || '未知地点'} · ${DASHBOARD_CASE_STATUS_LABEL[caseItem.status] || caseItem.status}`,
    tone: caseItem.latitude != null && caseItem.longitude != null ? 'good' : 'warn',
    route: '/cases',
  } satisfies ReturnType<typeof buildDashboardModel>['aiOutputs'][number]))

  return (
    <div className="db-command-main" ref={dashRef}>
      <section className="db-command-summary">
        {leadershipKpis.map(kpi => (
          <KpiCard key={kpi.item.label} item={kpi.item} icon={kpi.icon} />
        ))}
      </section>

      <section className="db-command-board">
        <Panel className="db-panel-trend" title="风险迹象趋势" meta="近 7 天">
          <TrendBars buckets={wellView.signalTrend} />
        </Panel>

        <Panel className="db-panel-risk" title="重点关注井点">
          <AutoScrollList items={wellView.topWells} durationSeconds={42} />
        </Panel>

        <Panel className="db-panel-material" title="最新异常痕迹">
          <AutoScrollList items={wellView.recentSignals} durationSeconds={46} />
        </Panel>

        <Panel className="db-panel-latest" title="最新案件动态" meta="实时更新">
          <AutoScrollList
            items={recentCaseItems.length ? recentCaseItems : [{ title: '暂无最新案件', detail: '等待案件录入后展示。', tone: 'empty' }]}
            durationSeconds={54}
          />
        </Panel>

        <Panel
          className="db-panel-map"
          title="井点风险迹象与案件态势"
          meta={areaScopesQuery.data && areaScopesQuery.data.length > 1 ? (
            <label>
              <span className="sr-only">当前厂区</span>
              <select
                aria-label="当前厂区"
                value={activeAreaId ?? ''}
                onChange={event => setActiveAreaId(Number(event.target.value))}
              >
                {areaScopesQuery.data.map(scope => (
                  <option key={scope.operational_area_id} value={scope.operational_area_id}>
                    {scope.area_name}
                  </option>
                ))}
              </select>
            </label>
          ) : (activeAreaName || '当前厂区')}
        >
          <div className="db-command-map">
            <div className="db-map-layer-tabs" role="group" aria-label="地图图层">
              {([
                ['attention', '综合关注'],
                ['signals', '痕迹事实'],
                ['cases', '历史案件'],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={mapLayer === value ? 'is-active' : ''}
                  onClick={() => setMapLayer(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <DashboardRiskMap
              key={activeAreaId ?? 'no-area'}
              layer={mapLayer}
              wells={wellView.wellPoints}
              signals={wellView.signalPoints}
              cases={model.mapPoints}
              chainLines={model.chainLines}
              hotspots={rawHotspots ?? EMPTY_HOTSPOTS}
              isFullscreen={isFullscreen}
              onToggleFullscreen={toggleFullscreen}
              operationalAreaId={activeAreaId ?? undefined}
            />
            <div className="db-map-legend">
              {mapLayer === 'cases' ? (
                <>
                  <span className="fact">案件事实点位</span>
                  <span className="infer">链条推断关系</span>
                  <span className="gap">待核坐标 {model.sourceStats.missingCoordinateCount}</span>
                </>
              ) : (
                <>
                  <span className="well-high">高关注井点</span>
                  <span className="well-watch">一般关注井点</span>
                  <span className="signal">风险迹象 {wellView.signalPoints.length}</span>
                </>
              )}
              <span className="public-map">公共地图要素</span>
            </div>
            <div className="db-map-source">
              <strong>产出口径</strong>
              {mapLayer === 'cases' ? (
                <>
                  <span>坐标=案件经纬度</span>
                  <span>热区=30天密度</span>
                  <span>关系=链条接口</span>
                  <span>缺口=坐标/材料</span>
                </>
              ) : (
                <>
                  <span>井点=油区资产</span>
                  <span>痕迹=现场事件</span>
                  <span>热度=综合关注度</span>
                  <span>边界=非犯罪预测</span>
                </>
              )}
              <span>底图=OpenStreetMap/本地缓存</span>
            </div>
            <div className="db-map-boundary-note">{wellView.boundary}</div>
          </div>
        </Panel>

        <Panel className="db-panel-focus" title="重点关注井点">
          <div className="db-command-focus-grid">
            {wellView.focusCards.map(card => (
              <div className="db-focus-card" key={card.label}>
                <span>{card.label}</span>
                <strong>{card.value}</strong>
              </div>
            ))}
          </div>
        </Panel>

        <Panel className="db-panel-ai" title="AI 关注区域与井点">
          <AutoScrollList items={wellView.aiAttention} durationSeconds={48} />
        </Panel>

        <Panel className="db-panel-review" title="防控布置建议">
          <AutoScrollList items={wellView.deploymentSuggestions} durationSeconds={50} />
        </Panel>

        <Panel className="db-panel-quality" title="井点数据质量" meta="实时">
          <AutoScrollList items={wellView.dataQuality} durationSeconds={54} />
        </Panel>
      </section>

      <div className="db-command-status">
        <span className={`chip${wsConnected ? ' live' : ' db-ws-err'}`}>
          <span className="dot" style={wsConnected ? {} : { background: 'var(--err)' }} />
          {wsConnected ? '实时数据在线' : '实时通道未连接'}
        </span>
        <span>坐标案件 {model.sourceStats.coordinateCount}</span>
        <span>热点 {model.sourceStats.hotspotCount}</span>
        <span>链条连线 {model.sourceStats.chainLineCount}</span>
        <span>监测井点 {wellView.wellPoints.length}</span>
        <span>风险迹象 {wellView.signalPoints.length}</span>
      </div>
    </div>
  )
}

export default Dashboard
