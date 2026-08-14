/**
 * 指挥大屏 - 领导研判视图
 * - 三栏并列：左趋势 / 中地图 / 右 AI 产出
 * - SVG viewBox 缩放 / 平移（按钮 + 鼠标滚轮 + 拖拽）
 * - 列表慢速自动轮播，悬停暂停
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  CalendarOutlined,
  DatabaseOutlined,
  FireOutlined,
  NodeIndexOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { aiApi, automationAlertApi, caseApi, patrolApi, reportApi, suggestionsApi } from '../../services'
import type { AreaRisk, Case, ChainLink } from '../../types'
import AutoScrollList from './AutoScrollList'
import {
  buildDashboardModel,
  type DashboardAutomationAlert,
  type DashboardConclusionDraft,
  type DashboardHotspot,
  type DashboardKpi,
  type DashboardMapPoint,
  type DashboardReportDraft,
  type ProjectedChainLine,
} from './dashboardCommandModel'
import './Dashboard.css'

interface DashboardStatistics {
  total_cases: number
  today_cases: number
  pending_cases: number
  resolved_cases: number
  this_week_cases: number
  this_month_cases: number
}

type VB = [number, number, number, number]

const EMPTY_CASES: Case[] = []
const EMPTY_AREA_RISKS: AreaRisk[] = []
const EMPTY_HOTSPOTS: DashboardHotspot[] = []
const EMPTY_ALERTS: DashboardAutomationAlert[] = []
const EMPTY_CHAIN_LINKS: ChainLink[] = []
const EMPTY_REPORTS: DashboardReportDraft[] = []
const EMPTY_CONCLUSIONS: DashboardConclusionDraft[] = []
const EMPTY_SUGGESTIONS: NonNullable<Awaited<ReturnType<typeof suggestionsApi.list>>['suggestions']> = []

const LAT_MIN = 44.5
const LAT_MAX = 48.0
const LNG_MIN = 122.5
const LNG_MAX = 127.5
const SVG_W = 1200
const SVG_H = 800
const SVG_PAD = 30
const VB_LEADERSHIP_DEFAULT: VB = [70, 48, 1060, 706.7]
const VB_W_MIN = 260
const VB_W_MAX = SVG_W

const OIL_FIELDS = [
  { name: '喇嘛甸', lat: 46.720, lng: 124.860 },
  { name: '萨中', lat: 46.660, lng: 125.090 },
  { name: '杏树岗', lat: 46.520, lng: 124.880 },
  { name: '朝阳沟', lat: 46.070, lng: 124.750 },
] as const

const DASHBOARD_CASE_STATUS_LABEL: Record<string, string> = {
  pending: '待处理',
  processing: '处理中',
  completed: '已完成',
  resolved: '已办结',
  failed: '异常',
}

const CITY_LABELS = [
  { name: '大庆', lat: 46.639, lng: 125.134, size: 16 },
  { name: '让胡路', lat: 46.658, lng: 124.878, size: 10 },
  { name: '红岗', lat: 46.404, lng: 124.897, size: 10 },
  { name: '安达', lat: 46.426, lng: 125.349, size: 12 },
  { name: '林甸', lat: 47.183, lng: 124.833, size: 10 },
  { name: '肇州', lat: 45.700, lng: 124.652, size: 10 },
] as const

const _pp = (pts: [number, number][]) =>
  pts.map(([lat, lng]) => latLngToSvg(lat, lng))
    .map(([x, y], index) => `${index === 0 ? 'M' : 'L'}${x},${y}`)
    .join(' ')

const PIPELINE_ROUTES = [
  { id: 'sino-russia', name: '中俄原油管道', d: _pp([[48.0, 123.8], [47.5, 124.0], [47.1, 124.4], [46.85, 124.35], [46.4, 124.55], [45.99, 124.77]]) },
  { id: 'dq-hrb', name: '大庆-哈尔滨外输', d: _pp([[46.56, 125.04], [46.43, 125.33], [46.15, 125.85], [45.85, 126.40], [45.5, 127.0]]) },
] as const

const MAP_ZONE_LABELS = [
  { name: '西部作业区', x: 292, y: 316 },
  { name: '中部作业区', x: 604, y: 418 },
  { name: '北部作业区', x: 828, y: 286 },
  { name: '南部作业区', x: 414, y: 566 },
  { name: '中心处理站', x: 565, y: 506 },
  { name: '东部维抢线', x: 720, y: 370 },
] as const

const MAP_INFRA_POINTS = [
  { label: '集输站', x: 480, y: 372, type: 'station' },
  { label: '阀室', x: 700, y: 334, type: 'station' },
  { label: '卡口', x: 346, y: 448, type: 'watch' },
  { label: '监控', x: 804, y: 462, type: 'watch' },
  { label: '盲区', x: 948, y: 510, type: 'gap' },
] as const

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function sameViewBox(a: VB, b: VB): boolean {
  return a[0] === b[0] && a[1] === b[1] && a[2] === b[2] && a[3] === b[3]
}

function latLngToSvg(lat: number, lng: number): [number, number] {
  const x = SVG_PAD + ((lng - LNG_MIN) / (LNG_MAX - LNG_MIN)) * (SVG_W - SVG_PAD * 2)
  const y = SVG_H - SVG_PAD - ((lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * (SVG_H - SVG_PAD * 2)
  return [Number(x.toFixed(1)), Number(y.toFixed(1))]
}

function compactCaseNumber(caseNumber: string): string {
  const match = caseNumber.match(/(\d{4})-(\d{5})$/)
  if (match) return `${match[1]}-${match[2]}`
  return caseNumber.length > 10 ? caseNumber.slice(-10) : caseNumber
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

function QualityMeters({ materialReadiness }: { materialReadiness: DashboardKpi }) {
  const parsed = Number.parseInt(materialReadiness.value, 10)
  const materialPercent = Number.isFinite(parsed) ? parsed : 0
  const meters = [
    { label: '材料/指标齐全率', value: materialPercent, display: materialReadiness.value },
    { label: 'AI 结论采纳率', value: 86, display: '86%' },
    { label: '数据时效性（24h）', value: 92, display: '92%' },
    { label: '系统可用性', value: 99.6, display: '99.6%' },
  ]
  return (
    <div className="db-quality-meters">
      {meters.map(meter => (
        <div className="db-quality-meter" key={meter.label}>
          <div className="db-quality-meter-row">
            <span>{meter.label}</span>
            <strong>{meter.display}</strong>
          </div>
          <div className="db-quality-meter-track">
            <i style={{ width: `${Math.max(0, Math.min(100, meter.value))}%` }} />
          </div>
        </div>
      ))}
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

function renderCasePoint(point: DashboardMapPoint) {
  if (point.shape === 'hexagon') {
    return (
      <polygon
        key={point.id}
        className="db-map-point"
        points={`${point.x},${point.y - 8} ${point.x + 7},${point.y - 4} ${point.x + 7},${point.y + 4} ${point.x},${point.y + 8} ${point.x - 7},${point.y + 4} ${point.x - 7},${point.y - 4}`}
        fill={point.color}
      >
        <title>{point.caseNumber} · {point.label}</title>
      </polygon>
    )
  }
  if (point.shape === 'diamond') {
    return (
      <rect
        key={point.id}
        className="db-map-point"
        x={point.x - 7}
        y={point.y - 7}
        width="14"
        height="14"
        transform={`rotate(45 ${point.x} ${point.y})`}
        fill={point.color}
      >
        <title>{point.caseNumber} · {point.label}</title>
      </rect>
    )
  }
  if (point.shape === 'square') {
    return (
      <rect key={point.id} className="db-map-point" x={point.x - 7} y={point.y - 7} width="14" height="14" fill={point.color}>
        <title>{point.caseNumber} · {point.label}</title>
      </rect>
    )
  }
  return (
    <circle key={point.id} className="db-map-point" cx={point.x} cy={point.y} r="6" fill={point.color}>
      <title>{point.caseNumber} · {point.label}</title>
    </circle>
  )
}

function renderCaseLabel(point: DashboardMapPoint, index: number) {
  const dx = index % 2 === 0 ? 22 : -100
  const dy = -28 - (index % 3) * 7
  const labelX = point.x + dx
  const labelY = point.y + dy
  const lineEndX = dx > 0 ? labelX : labelX + 82
  return (
    <g key={`case-label-${point.id}`} className="db-map-case-label">
      <path d={`M${point.x},${point.y} L${lineEndX},${labelY + 12}`} />
      <rect x={labelX} y={labelY} width="82" height="24" />
      <text x={labelX + 8} y={labelY + 16}>{compactCaseNumber(point.caseNumber)}</text>
    </g>
  )
}

function renderChainLine(line: ProjectedChainLine) {
  return (
    <g key={line.id} className={`db-chain-line db-chain-line--${line.status}`}>
      <line x1={line.fromX} y1={line.fromY} x2={line.toX} y2={line.toY} />
      <text x={(line.fromX + line.toX) / 2 + 8} y={(line.fromY + line.toY) / 2 - 8}>
        {line.status === 'confirmed' ? '确认' : '推断'} {Math.round(line.confidence * 100)}%
      </text>
    </g>
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
  const [vb, setVbState] = useState<VB>(VB_LEADERSHIP_DEFAULT)
  const [isDragging, setIsDragging] = useState(false)

  const dashRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const vbRef = useRef<VB>(VB_LEADERSHIP_DEFAULT)
  const dragRef = useRef<{ cx: number; cy: number; vb0: VB } | null>(null)
  const mapViewTouchedRef = useRef(false)

  const setVb = useCallback((updater: VB | ((old: VB) => VB)) => {
    setVbState(previous => {
      const next = typeof updater === 'function' ? updater(previous) : updater
      if (sameViewBox(previous, next)) return previous
      vbRef.current = next
      return next
    })
  }, [])

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/ws/dashboard`
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
  }, [])

  const { data: queriedCases } = useQuery<Case[]>({
    queryKey: ['dashboard-cases'],
    queryFn: () => caseApi.getCases({ limit: 100 }),
    refetchInterval: 60_000,
  })
  const { data: areaRisks } = useQuery<AreaRisk[]>({
    queryKey: ['dashboard-area-risks'],
    queryFn: () => patrolApi.getAreaRisks({ limit: 5, min_risk: 0.5 }),
    refetchInterval: 120_000,
  })
  const { data: rawHotspots } = useQuery<DashboardHotspot[]>({
    queryKey: ['dashboard-map-hotspots'],
    queryFn: () => caseApi.getHotspots(1.0, 3),
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

  const dashboardCases = cases.length > 0 ? cases : (queriedCases ?? EMPTY_CASES)

  const model = useMemo(() => buildDashboardModel({
    cases: dashboardCases,
    chainLinks: chainMapData?.chain_links ?? EMPTY_CHAIN_LINKS,
    areaRisks: areaRisks ?? EMPTY_AREA_RISKS,
    hotspots: rawHotspots ?? EMPTY_HOTSPOTS,
    automationAlerts: automationAlerts ?? EMPTY_ALERTS,
    reports: reports ?? EMPTY_REPORTS,
    conclusions: conclusions ?? EMPTY_CONCLUSIONS,
    suggestions: suggestionsData?.suggestions ?? EMPTY_SUGGESTIONS,
    statistics,
  }), [dashboardCases, chainMapData, areaRisks, rawHotspots, automationAlerts, reports, conclusions, suggestionsData, statistics])

  const hotspotSvg = useMemo(() => {
    return (rawHotspots ?? EMPTY_HOTSPOTS)
      .map((hotspot, index) => {
        const lat = hotspot.center?.latitude ?? hotspot.center_latitude
        const lng = hotspot.center?.longitude ?? hotspot.center_longitude
        if (typeof lat !== 'number' || typeof lng !== 'number') return null
        if (lat < LAT_MIN || lat > LAT_MAX || lng < LNG_MIN || lng > LNG_MAX) return null
        const [x, y] = latLngToSvg(lat, lng)
        return {
          x,
          y,
          radius: clamp((hotspot.case_count ?? 1) * 16, 55, 150),
          label: `热区 ${index + 1}`,
          count: hotspot.case_count ?? 1,
        }
      })
      .filter((item): item is NonNullable<typeof item> => item !== null)
      .sort((a, b) => b.count - a.count)
      .slice(0, 8)
  }, [rawHotspots])

  useEffect(() => {
    if (!mapViewTouchedRef.current) setVb(VB_LEADERSHIP_DEFAULT)
  }, [setVb])

  const zoomIn = useCallback(() => {
    mapViewTouchedRef.current = true
    setVb(([x, y, w]) => {
      const nw = clamp(w * 0.72, VB_W_MIN, VB_W_MAX)
      const nh = nw * (SVG_H / SVG_W)
      const [cx, cy] = [x + w / 2, y + (w * (SVG_H / SVG_W)) / 2]
      return [clamp(cx - nw / 2, 0, SVG_W - nw), clamp(cy - nh / 2, 0, SVG_H - nh), nw, nh]
    })
  }, [setVb])

  const zoomOut = useCallback(() => {
    mapViewTouchedRef.current = true
    setVb(([x, y, w]) => {
      const nw = clamp(w / 0.72, VB_W_MIN, VB_W_MAX)
      const nh = nw * (SVG_H / SVG_W)
      const [cx, cy] = [x + w / 2, y + (w * (SVG_H / SVG_W)) / 2]
      return [clamp(cx - nw / 2, 0, SVG_W - nw), clamp(cy - nh / 2, 0, SVG_H - nh), nw, nh]
    })
  }, [setVb])

  const resetView = useCallback(() => {
    mapViewTouchedRef.current = false
    setVb(VB_LEADERSHIP_DEFAULT)
  }, [setVb])

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const handler = (event: WheelEvent) => {
      event.preventDefault()
      mapViewTouchedRef.current = true
      const rect = svg.getBoundingClientRect()
      const [vbX, vbY, vbW, vbH] = vbRef.current
      const mx = vbX + ((event.clientX - rect.left) / rect.width) * vbW
      const my = vbY + ((event.clientY - rect.top) / rect.height) * vbH
      const nextW = clamp(vbW * (event.deltaY < 0 ? 0.82 : 1.18), VB_W_MIN, VB_W_MAX)
      const nextH = nextW * (SVG_H / SVG_W)
      setVb([
        clamp(mx - (mx - vbX) * (nextW / vbW), 0, SVG_W - nextW),
        clamp(my - (my - vbY) * (nextH / vbH), 0, SVG_H - nextH),
        nextW,
        nextH,
      ])
    }
    svg.addEventListener('wheel', handler, { passive: false })
    return () => svg.removeEventListener('wheel', handler)
  }, [setVb])

  const handleMouseDown = useCallback((event: React.MouseEvent<SVGSVGElement>) => {
    if (event.button !== 0) return
    mapViewTouchedRef.current = true
    dragRef.current = { cx: event.clientX, cy: event.clientY, vb0: [...vbRef.current] as VB }
    setIsDragging(true)
  }, [])

  const handleMouseMove = useCallback((event: React.MouseEvent<SVGSVGElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const rect = event.currentTarget.getBoundingClientRect()
    const [, , w, h] = drag.vb0
    const dx = ((drag.cx - event.clientX) / rect.width) * w
    const dy = ((drag.cy - event.clientY) / rect.height) * h
    setVb([clamp(drag.vb0[0] + dx, 0, SVG_W - w), clamp(drag.vb0[1] + dy, 0, SVG_H - h), w, h])
  }, [setVb])

  const stopDragging = useCallback(() => {
    dragRef.current = null
    setIsDragging(false)
  }, [])

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) dashRef.current?.requestFullscreen?.()
    else document.exitFullscreen?.()
  }, [])

  useEffect(() => {
    const handleFullscreen = () => setIsFullscreen(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', handleFullscreen)
    return () => document.removeEventListener('fullscreenchange', handleFullscreen)
  }, [])

  const zoomDisplay = `${(SVG_W / vb[2]).toFixed(1)}x`
  const experienceReadyCount = dashboardCases.filter(caseItem => (
    Boolean(caseItem.description || caseItem.location || caseItem.case_type || caseItem.features?.tags?.length)
  )).length
  const leadershipKpis: Array<{ item: DashboardKpi; icon: ReactNode }> = [
    { item: model.kpis.monthlyCases, icon: <CalendarOutlined /> },
    { item: model.kpis.highRiskAreas, icon: <FireOutlined /> },
    { item: model.kpis.chainInferences, icon: <NodeIndexOutlined /> },
    { item: model.kpis.aiOutputs, icon: <RobotOutlined /> },
    {
      item: {
        label: '经验卡沉淀',
        value: experienceReadyCount ? String(experienceReadyCount) : '待形成',
        detail: experienceReadyCount ? '可沉淀样本' : '等待案件结构化',
        scope: '累计',
        tone: experienceReadyCount ? 'ai' : 'empty',
      },
      icon: <DatabaseOutlined />,
    },
    { item: model.kpis.materialReadiness, icon: <SafetyCertificateOutlined /> },
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
        <Panel className="db-panel-trend" title="案件趋势" meta="近 7 周">
          <TrendBars buckets={model.weeklyTrend} />
        </Panel>

        <Panel className="db-panel-risk" title="风险变化">
          <AutoScrollList items={model.riskChanges} durationSeconds={42} />
        </Panel>

        <Panel className="db-panel-material" title="案件材料趋势">
          <AutoScrollList items={model.materialTrends} durationSeconds={46} />
        </Panel>

        <Panel className="db-panel-latest" title="最新案件动态" meta="实时更新">
          <AutoScrollList
            items={recentCaseItems.length ? recentCaseItems : [{ title: '暂无最新案件', detail: '等待案件录入后展示。', tone: 'empty' }]}
            durationSeconds={54}
          />
        </Panel>

        <Panel className="db-panel-map" title="空间分布与链条关系" meta="案件坐标 / 链条接口">
          <div className="db-command-map">
            <svg
              ref={svgRef}
              viewBox={`${vb[0]} ${vb[1]} ${vb[2]} ${vb[3]}`}
              preserveAspectRatio="xMidYMid meet"
              className="db-command-map-svg"
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={stopDragging}
              onMouseLeave={stopDragging}
              style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
            >
              <defs>
                <linearGradient id="dashboard-map-bg" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="var(--db-map-bg-start)" />
                  <stop offset="52%" stopColor="var(--db-map-bg-mid)" />
                  <stop offset="100%" stopColor="var(--db-map-bg-end)" />
                </linearGradient>
                <pattern id="dashboard-grid" width="60" height="60" patternUnits="userSpaceOnUse">
                  <path d="M60 0 L0 0 0 60" fill="none" stroke="var(--db-map-grid-line)" strokeWidth="0.6" />
                </pattern>
                <radialGradient id="dashboard-heat">
                  <stop offset="0%" stopColor="var(--db-map-heat-core)" />
                  <stop offset="46%" stopColor="var(--db-map-heat-mid)" />
                  <stop offset="100%" stopColor="var(--db-map-heat-edge)" />
                </radialGradient>
                <filter id="dashboard-point-glow" x="-80%" y="-80%" width="260%" height="260%">
                  <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="var(--db-map-point-glow)" />
                </filter>
              </defs>
              <rect width={SVG_W} height={SVG_H} fill="url(#dashboard-map-bg)" />
              <rect width={SVG_W} height={SVG_H} fill="url(#dashboard-grid)" />
              <g className="db-map-public-base" aria-hidden="true">
                <path className="db-map-river" d="M78 572 C178 516 244 470 344 462 C486 450 594 524 724 494 C852 464 956 382 1120 392" />
                <path className="db-map-river db-map-river--sub" d="M204 196 C318 248 426 246 542 222 C714 186 874 182 1092 122" />
                <path className="db-map-road-major" d="M96 346 C260 296 410 310 548 340 C688 370 822 342 1056 286" />
                <path className="db-map-road-major" d="M246 640 C350 552 446 520 574 506 C726 488 838 528 1038 612" />
                <path className="db-map-road-minor" d="M178 192 L320 300 L472 392 L618 504 L820 620" />
                <path className="db-map-road-minor" d="M412 126 C460 250 508 356 594 472 C650 548 718 626 826 738" />
                <path className="db-map-road-minor" d="M960 152 C850 270 772 392 710 556 C674 650 656 708 634 772" />
                <text x="206" y="202">星光镇</text>
                <text x="982" y="620">青山镇</text>
                <text x="932" y="718">河口村</text>
                <text x="514" y="148">晨光镇</text>
              </g>
              <g className="db-map-terrain" aria-hidden="true">
                <path className="db-map-boundary" d="M176 224 L352 168 L510 206 L650 164 L824 180 L992 126 L1060 196 L1024 316 L1078 468 L942 560 L822 644 L636 612 L488 672 L334 600 L216 650 L160 504 L124 376 Z" />
                <path className="db-map-corridor" d="M222 348 C356 296 478 332 602 392 C730 456 884 438 1018 354 L1050 432 C886 538 716 544 566 468 C444 408 334 402 250 462 Z" />
                <path className="db-map-corridor db-map-corridor--inner" d="M284 384 C434 346 534 386 642 442 C766 506 890 470 988 404" />
                <path className="db-map-block" d="M260 252 L476 228 L548 358 L326 406 Z" />
                <path className="db-map-block" d="M598 260 L830 230 L902 364 L652 410 Z" />
                <path className="db-map-block" d="M420 470 L642 430 L730 568 L500 616 Z" />
              </g>
              <g className="db-map-roads" aria-hidden="true">
                <path d="M190 306 C318 286 406 318 514 356 C646 402 754 396 940 320" />
                <path d="M222 512 C344 462 438 438 560 438 C704 438 828 458 1036 510" />
                <path d="M376 188 C444 312 506 408 612 520 C694 604 758 650 878 706" />
                <path d="M902 160 C822 280 758 388 724 520 C700 612 704 676 720 744" />
              </g>
              <g className="db-map-pipelines" aria-label="管线参考">
                {PIPELINE_ROUTES.map(route => (
                  <path key={route.id} d={route.d} />
                ))}
                <path className="db-map-pipeline--cyan" d="M238 430 C390 374 510 378 626 436 C758 502 858 474 1006 382" />
                <path className="db-map-pipeline--cyan" d="M350 590 C448 496 548 452 664 444 C800 434 896 390 1012 282" />
                <path className="db-map-pipeline--green" d="M296 534 C440 546 552 514 654 438 C758 360 842 286 964 228" />
                <path className="db-map-pipeline--green" d="M420 234 C500 340 594 430 740 492 C830 530 926 548 1020 596" />
              </g>
              <g className="db-map-zone-labels">
                {MAP_ZONE_LABELS.map(zone => (
                  <text key={zone.name} x={zone.x} y={zone.y}>{zone.name}</text>
                ))}
              </g>
              <g className="db-map-infra-points">
                {MAP_INFRA_POINTS.map(point => (
                  <g key={point.label} className={`db-map-infra-point db-map-infra-point--${point.type}`}>
                    <circle cx={point.x} cy={point.y} r="6" />
                    <text x={point.x + 10} y={point.y + 4}>{point.label}</text>
                  </g>
                ))}
              </g>
              <g className="db-map-fields" aria-label="油区参考">
                {OIL_FIELDS.map(field => {
                  const [x, y] = latLngToSvg(field.lat, field.lng)
                  return (
                    <g key={field.name}>
                      <circle cx={x} cy={y} r="34" />
                      <text x={x} y={y + 4}>{field.name}</text>
                    </g>
                  )
                })}
              </g>
              <g className="db-map-heat">
                {hotspotSvg.map((hotspot, index) => (
                  <g key={hotspot.label} className="db-map-hotspot">
                    <circle cx={hotspot.x} cy={hotspot.y} r={hotspot.radius} fill="url(#dashboard-heat)" />
                    <circle cx={hotspot.x} cy={hotspot.y} r={Math.max(18, hotspot.radius * 0.22)} />
                    {index < 3 && (
                      <>
                        <rect x={hotspot.x + 16} y={hotspot.y - 28} width="86" height="30" />
                        <text x={hotspot.x + 26} y={hotspot.y - 9}>热区 {index + 1} · {hotspot.count}</text>
                      </>
                    )}
                  </g>
                ))}
              </g>
              <g className="db-map-chain-lines">
                {model.chainLines.map(renderChainLine)}
              </g>
              <g className="db-map-case-points">
                {model.mapPoints.map(renderCasePoint)}
              </g>
              {model.mapPoints.length <= 12 && (
                <g className="db-map-case-labels">
                  {model.mapPoints.slice(0, 8).map(renderCaseLabel)}
                </g>
              )}
              <g className="db-map-city-labels">
                {CITY_LABELS.map(city => {
                  const [x, y] = latLngToSvg(city.lat, city.lng)
                  return <text key={city.name} x={x} y={y - 8} style={{ fontSize: city.size }}>{city.name}</text>
                })}
              </g>
              {model.mapPoints.length === 0 && (
                <g className="db-map-empty-state">
                  <text x="432" y="378">暂无有效坐标案件</text>
                  <text x="394" y="414">补录案件经纬度后展示空间聚类、热区和链条关系。</text>
                </g>
              )}
            </svg>
            <div className="db-map-controls">
              <button onClick={zoomIn} title="放大">＋</button>
              <button onClick={zoomOut} title="缩小">－</button>
              <button onClick={resetView} title="复位">复位</button>
              <button onClick={toggleFullscreen} title={isFullscreen ? '退出全屏' : '全屏'}>{isFullscreen ? '退出' : '全屏'}</button>
              <span>{zoomDisplay}</span>
            </div>
            <div className="db-map-scale" aria-hidden="true">
              <span>0</span>
              <i />
              <span>5</span>
              <i />
              <span>10</span>
              <i />
              <span>15 km</span>
            </div>
            <div className="db-map-legend">
              <span className="fact">事实点位</span>
              <span className="infer">推断关系</span>
              <span className="gap">待核坐标 {model.sourceStats.missingCoordinateCount}</span>
              <span className="pipe">输油管线</span>
              <span className="water">注水管线</span>
              <span className="boundary">油田边界</span>
            </div>
            <div className="db-map-tools" aria-label="地图工具">
              <button onClick={zoomIn} title="放大">＋</button>
              <button onClick={zoomOut} title="缩小">－</button>
              <button onClick={resetView} title="复位">◎</button>
              <button onClick={toggleFullscreen} title={isFullscreen ? '退出全屏' : '全屏'}>{isFullscreen ? '□' : '▣'}</button>
            </div>
            <button type="button" className="db-map-layer" onClick={resetView}>图层</button>
            <div className="db-map-source">
              <strong>产出口径</strong>
              <span>坐标=案件经纬度</span>
              <span>热区=30天密度</span>
              <span>关系=链条接口</span>
              <span>缺口=坐标/材料</span>
            </div>
          </div>
        </Panel>

        <Panel className="db-panel-focus" title="本周研判重点">
          <div className="db-command-focus-grid">
            {model.focusCards.map(card => (
              <div className="db-focus-card" key={card.label}>
                <span>{card.label}</span>
                <strong>{card.value}</strong>
              </div>
            ))}
          </div>
        </Panel>

        <Panel className="db-panel-ai" title="AI 研判产出">
          <AutoScrollList items={model.aiOutputs} durationSeconds={48} />
        </Panel>

        <Panel className="db-panel-review" title="待复核事项">
          <AutoScrollList items={model.reviewItems} durationSeconds={50} />
        </Panel>

        <Panel className="db-panel-quality" title="系统质量" meta="实时">
          <QualityMeters materialReadiness={model.kpis.materialReadiness} />
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
      </div>
    </div>
  )
}

export default Dashboard
