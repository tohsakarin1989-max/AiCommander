/**
 * 指挥大屏 - 领导研判视图
 * - 三栏并列：左趋势 / 中地图 / 右 AI 产出
 * - SVG viewBox 缩放 / 平移（按钮 + 鼠标滚轮 + 拖拽）
 * - 列表慢速自动轮播，悬停暂停
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { caseApi, patrolApi } from '../../services'
import type { AreaRisk, Case } from '../../types'
import AutoScrollList from './AutoScrollList'
import {
  buildDashboardModel,
  type DashboardHotspot,
  type DashboardKpi,
  type DashboardMapPoint,
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

const LAT_MIN = 44.5
const LAT_MAX = 48.0
const LNG_MIN = 122.5
const LNG_MAX = 127.5
const SVG_W = 1200
const SVG_H = 800
const SVG_PAD = 30
const VB_DEFAULT: VB = [0, 0, SVG_W, SVG_H]
const VB_W_MIN = 260
const VB_W_MAX = SVG_W

const OIL_FIELDS = [
  { name: '喇嘛甸', lat: 46.720, lng: 124.860 },
  { name: '萨中', lat: 46.660, lng: 125.090 },
  { name: '杏树岗', lat: 46.520, lng: 124.880 },
  { name: '朝阳沟', lat: 46.070, lng: 124.750 },
] as const

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

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function latLngToSvg(lat: number, lng: number): [number, number] {
  const x = SVG_PAD + ((lng - LNG_MIN) / (LNG_MAX - LNG_MIN)) * (SVG_W - SVG_PAD * 2)
  const y = SVG_H - SVG_PAD - ((lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * (SVG_H - SVG_PAD * 2)
  return [Number(x.toFixed(1)), Number(y.toFixed(1))]
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

function KpiCard({ item }: { item: DashboardKpi }) {
  return (
    <div className={`kpill db-command-kpi db-command-kpi--${item.tone || 'normal'}`}>
      <div className="lbl">{item.label}</div>
      <div className="val">{item.value}</div>
      <div className="sub">{item.detail}</div>
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
  const [vb, setVbState] = useState<VB>(VB_DEFAULT)
  const [isDragging, setIsDragging] = useState(false)

  const dashRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const vbRef = useRef<VB>(VB_DEFAULT)
  const dragRef = useRef<{ cx: number; cy: number; vb0: VB } | null>(null)

  const setVb = useCallback((updater: VB | ((old: VB) => VB)) => {
    setVbState(previous => {
      const next = typeof updater === 'function' ? updater(previous) : updater
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

  const { data: queriedCases = [] } = useQuery<Case[]>({
    queryKey: ['dashboard-cases'],
    queryFn: () => caseApi.getCases({ limit: 100 }),
    refetchInterval: 60_000,
  })
  const { data: areaRisks = [] } = useQuery<AreaRisk[]>({
    queryKey: ['dashboard-area-risks'],
    queryFn: () => patrolApi.getAreaRisks({ limit: 5, min_risk: 0.5 }),
    refetchInterval: 120_000,
  })
  const { data: rawHotspots = [] } = useQuery({
    queryKey: ['dashboard-map-hotspots'],
    queryFn: () => caseApi.getHotspots(1.0, 3),
    refetchInterval: 120_000,
  })
  const { data: chainMapData } = useQuery({
    queryKey: ['dashboard-chain-map-data'],
    queryFn: () => caseApi.getChainMapData(),
    refetchInterval: 120_000,
  })

  const dashboardCases = cases.length > 0 ? cases : queriedCases

  const model = useMemo(() => buildDashboardModel({
    cases: dashboardCases,
    chainLinks: chainMapData?.chain_links ?? [],
    areaRisks,
    hotspots: rawHotspots as DashboardHotspot[],
    statistics,
  }), [dashboardCases, chainMapData, areaRisks, rawHotspots, statistics])

  const hotspotSvg = useMemo(() => {
    return (rawHotspots as DashboardHotspot[])
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
  }, [rawHotspots])

  const zoomIn = useCallback(() => {
    setVb(([x, y, w]) => {
      const nw = clamp(w * 0.72, VB_W_MIN, VB_W_MAX)
      const nh = nw * (SVG_H / SVG_W)
      const [cx, cy] = [x + w / 2, y + (w * (SVG_H / SVG_W)) / 2]
      return [clamp(cx - nw / 2, 0, SVG_W - nw), clamp(cy - nh / 2, 0, SVG_H - nh), nw, nh]
    })
  }, [setVb])

  const zoomOut = useCallback(() => {
    setVb(([x, y, w]) => {
      const nw = clamp(w / 0.72, VB_W_MIN, VB_W_MAX)
      const nh = nw * (SVG_H / SVG_W)
      const [cx, cy] = [x + w / 2, y + (w * (SVG_H / SVG_W)) / 2]
      return [clamp(cx - nw / 2, 0, SVG_W - nw), clamp(cy - nh / 2, 0, SVG_H - nh), nw, nh]
    })
  }, [setVb])

  const resetView = useCallback(() => setVb(VB_DEFAULT), [setVb])

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const handler = (event: WheelEvent) => {
      event.preventDefault()
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

  return (
    <div className="db-command-main" ref={dashRef}>
      <section className="db-command-summary">
        <div className="card db-command-title">
          <h1>领导研判视图</h1>
          <p>趋势研判 · 链条关联 · AI 产出复核 · 经验沉淀</p>
        </div>
        <KpiCard item={model.kpis.monthlyCases} />
        <KpiCard item={model.kpis.highRiskAreas} />
        <KpiCard item={model.kpis.chainInferences} />
        <KpiCard item={model.kpis.aiOutputs} />
        <KpiCard item={model.kpis.materialReadiness} />
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
                <pattern id="dashboard-grid" width="60" height="60" patternUnits="userSpaceOnUse">
                  <path d="M60 0 L0 0 0 60" fill="none" stroke="oklch(0.32 0.014 250 / 0.22)" strokeWidth="0.6" />
                </pattern>
                <radialGradient id="dashboard-heat">
                  <stop offset="0%" stopColor="oklch(0.78 0.14 45 / 0.32)" />
                  <stop offset="100%" stopColor="oklch(0.78 0.14 45 / 0)" />
                </radialGradient>
              </defs>
              <rect width={SVG_W} height={SVG_H} fill="oklch(0.16 0.014 250)" />
              <rect width={SVG_W} height={SVG_H} fill="url(#dashboard-grid)" />
              <path className="db-map-boundary" d="M150 140 L965 74 L1068 526 L238 666 Z" />
              <g className="db-map-roads">
                <path d="M0 318 C260 312 460 318 620 316 C810 314 990 312 1200 314" />
                <path d="M620 0 C618 156 612 246 620 318 C606 474 584 612 560 800" />
                <path d="M620 318 L706 380 L930 502" />
              </g>
              <g className="db-map-pipelines">
                {PIPELINE_ROUTES.map(route => (
                  <path key={route.id} d={route.d}>
                    <title>{route.name}</title>
                  </path>
                ))}
              </g>
              <g className="db-map-fields">
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
                {hotspotSvg.map(hotspot => (
                  <g key={hotspot.label}>
                    <circle cx={hotspot.x} cy={hotspot.y} r={hotspot.radius} fill="url(#dashboard-heat)" />
                    <text x={hotspot.x + 12} y={hotspot.y - 12}>{hotspot.label} · {hotspot.count}</text>
                  </g>
                ))}
              </g>
              <g className="db-map-chain-lines">
                {model.chainLines.map(renderChainLine)}
              </g>
              <g className="db-map-case-points">
                {model.mapPoints.map(renderCasePoint)}
              </g>
              <g className="db-map-city-labels">
                {CITY_LABELS.map(city => {
                  const [x, y] = latLngToSvg(city.lat, city.lng)
                  return <text key={city.name} x={x} y={y - 8} style={{ fontSize: city.size }}>{city.name}</text>
                })}
              </g>
              {model.mapPoints.length === 0 && (
                <text className="db-map-empty" x="460" y="390">暂无有效坐标案件</text>
              )}
            </svg>
            <div className="db-map-controls">
              <button onClick={zoomIn} title="放大">＋</button>
              <button onClick={zoomOut} title="缩小">－</button>
              <button onClick={resetView} title="复位">复位</button>
              <button onClick={toggleFullscreen} title={isFullscreen ? '退出全屏' : '全屏'}>{isFullscreen ? '退出' : '全屏'}</button>
              <span>{zoomDisplay}</span>
            </div>
            <div className="db-map-legend">
              <span className="fact">事实点位</span>
              <span className="infer">推断关系</span>
              <span className="gap">待核坐标 {model.sourceStats.missingCoordinateCount}</span>
            </div>
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

        <Panel className="db-panel-quality" title="系统产出质量">
          <AutoScrollList items={model.qualityItems} durationSeconds={44} />
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
