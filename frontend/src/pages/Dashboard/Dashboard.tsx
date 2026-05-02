/**
 * 实时指挥大屏
 * - SVG viewBox 缩放 / 平移（鼠标滚轮 + 拖拽）
 * - 热力圈 / 脉冲环：真实热点坐标驱动
 * - 巡逻路径：真实 area_coordinates 或案件质心推导
 * - 设施图层（油库 / 加油站 / 管线节点）可切换显示
 */
import { useEffect, useState, useRef, useMemo, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { patrolApi, caseApi, keyLocationApi } from '../../services'
import type { PatrolRecord, AreaRisk, KeyLocation } from '../../types'
import './Dashboard.css'

type OverlayMode = 'scatter' | 'heat' | 'trajectory' | 'cluster'

const OVERLAY_LABELS: Record<OverlayMode, string> = {
  scatter:    '散点',
  heat:       '热力',
  trajectory: '轨迹',
  cluster:    '聚类',
}

// ── 类型 ─────────────────────────────────────────────────────────────────────

interface Case {
  id: number
  case_number: string
  occurred_time: string
  latitude: number
  longitude: number
  location?: string
  case_type?: string
  status: string
}

interface DashboardStatistics {
  total_cases:    number
  today_cases:    number
  pending_cases:  number
  resolved_cases: number
  this_week_cases:  number
  this_month_cases: number
}

// ── 工具函数 ─────────────────────────────────────────────────────────────────

function buildSparklinePoints(cases: Case[]): number[] {
  const now = new Date()
  const counts: number[] = Array(30).fill(0)
  cases.forEach((c) => {
    const diff = Math.floor((now.getTime() - new Date(c.occurred_time).getTime()) / 86_400_000)
    if (diff >= 0 && diff < 30) counts[29 - diff] += 1
  })
  return counts
}

function toPolyline(vals: number[], w: number, h: number, pad = 6): string {
  if (vals.length === 0) return ''
  const max = Math.max(...vals, 1)
  return vals
    .map((v, i) => {
      const x = pad + (i / (vals.length - 1)) * (w - pad * 2)
      const y = h - pad - (v / max) * (h - pad * 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

interface PieSlice { label: string; count: number; pct: number; color: string; offset: number }
const PIE_CIRCUMFERENCE = 2 * Math.PI * 52

function buildPieSlices(dist: { name: string; value: number }[]): PieSlice[] {
  const total = dist.reduce((s, d) => s + d.value, 0) || 1
  const colors = [
    'oklch(0.78 0.14 45)', 'oklch(0.72 0.14 285)', 'oklch(0.78 0.11 220)',
    'oklch(0.80 0.16 75)', 'oklch(0.55 0.013 250)',
  ]
  let offset = 0
  return dist.slice(0, 5).map((d, i) => {
    const pct = d.value / total
    const arc = pct * PIE_CIRCUMFERENCE
    const sl: PieSlice = { label: d.name, count: d.value, pct: Math.round(pct * 100), color: colors[i % colors.length], offset }
    offset += arc
    return sl
  })
}

// ── SVG 坐标投影（黑龙江大庆地区）────────────────────────────────────────────
const LAT_MIN = 44.5, LAT_MAX = 48.0
const LNG_MIN = 122.5, LNG_MAX = 127.5
const SVG_W = 1200, SVG_H = 800, SVG_PAD = 30

function latLngToSvg(lat: number, lng: number): [number, number] {
  const x = SVG_PAD + (lng - LNG_MIN) / (LNG_MAX - LNG_MIN) * (SVG_W - SVG_PAD * 2)
  const y = (SVG_H - SVG_PAD) - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN) * (SVG_H - SVG_PAD * 2)
  return [parseFloat(x.toFixed(1)), parseFloat(y.toFixed(1))]
}

// 100 SVG 单位对应的实际距离（经向，取中心纬度修正）
const SCALE_BAR_KM = Math.round(100 * (LNG_MAX - LNG_MIN) / (SVG_W - SVG_PAD * 2) * 111.1 * Math.cos(46.25 * Math.PI / 180))

function clamp(v: number, lo: number, hi: number) { return Math.max(lo, Math.min(hi, v) ) }

// ── 城市与区划标签（已核实坐标；安达在大庆正东 125.35°E）─────────────────────
type CityType = 'major' | 'city' | 'district' | 'county' | 'other'
const CITY_LABELS: Array<{ name: string; lat: number; lng: number; size: number; weight: string; type: CityType }> = [
  { name: '大庆',    lat: 46.639, lng: 125.134, size: 16, weight: '600', type: 'major'    },
  { name: '安达',    lat: 46.426, lng: 125.349, size: 13, weight: '500', type: 'city'     },
  { name: '肇东',    lat: 46.057, lng: 125.969, size: 13, weight: '500', type: 'city'     },
  { name: '绥化',    lat: 46.660, lng: 126.975, size: 12, weight: '500', type: 'city'     },
  { name: '让胡路',  lat: 46.658, lng: 124.878, size: 10, weight: 'normal', type: 'district' },
  { name: '红岗',    lat: 46.404, lng: 124.897, size: 10, weight: 'normal', type: 'district' },
  { name: '大同',    lat: 46.046, lng: 124.819, size: 10, weight: 'normal', type: 'district' },
  { name: '林甸',    lat: 47.183, lng: 124.833, size: 10, weight: 'normal', type: 'county'   },
  { name: '杜尔伯特', lat: 46.867, lng: 124.433, size: 10, weight: 'normal', type: 'county'  },
  { name: '肇州',    lat: 45.700, lng: 124.652, size: 10, weight: 'normal', type: 'county'   },
  { name: '肇源',    lat: 45.519, lng: 125.080, size: 10, weight: 'normal', type: 'county'   },
  { name: '明水',    lat: 47.179, lng: 125.912, size: 10, weight: 'normal', type: 'other'    },
]

// ── 涉油重要设施（已核实坐标）────────────────────────────────────────────────
const OIL_FIELDS = [
  { name: '喇嘛甸', lat: 46.720, lng: 124.860 },
  { name: '萨中',   lat: 46.660, lng: 125.090 },
  { name: '杏树岗', lat: 46.520, lng: 124.880 },
  { name: '朝阳沟', lat: 46.070, lng: 124.750 },
] as const

const OIL_FACILITIES = [
  { name: '大庆炼化',   lat: 46.560, lng: 125.040, kind: 'refinery' },
  { name: '林源输油站', lat: 45.990, lng: 124.770, kind: 'pumping'  },
  { name: '大庆石化库', lat: 46.640, lng: 125.160, kind: 'depot'    },
  { name: '安达输油站', lat: 46.415, lng: 125.330, kind: 'depot'    },
] as const

const GAS_STATIONS = [
  { lat: 46.640, lng: 124.945 },
  { lat: 46.530, lng: 125.050 },
  { lat: 46.430, lng: 125.270 },
  { lat: 46.200, lng: 125.650 },
  { lat: 46.090, lng: 124.810 },
  { lat: 46.750, lng: 124.820 },
] as const

const _pp = (pts: [number, number][]) =>
  pts.map(([la, ln]) => latLngToSvg(la, ln))
     .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x},${y}`)
     .join(' ')

const PIPELINE_ROUTES = [
  { id: 'sino-russia', name: '中俄原油管道',   width: 1.8, dasharray: '12 5', opacity: 0.70,
    d: _pp([[48.0,123.8],[47.5,124.0],[47.1,124.4],[46.85,124.35],[46.4,124.55],[45.99,124.77]]) },
  { id: 'dq-hrb',      name: '大庆-哈尔滨外输', width: 1.4, dasharray: '10 4', opacity: 0.55,
    d: _pp([[46.56,125.04],[46.43,125.33],[46.15,125.85],[45.85,126.40],[45.5,127.0]]) },
  { id: 'inner-n',     name: '内部集输北线',   width: 1.1, dasharray: '6 3',  opacity: 0.45,
    d: _pp([[46.72,124.86],[46.60,124.96],[46.56,125.04]]) },
  { id: 'inner-s',     name: '内部集输南线',   width: 1.1, dasharray: '6 3',  opacity: 0.45,
    d: _pp([[46.52,124.88],[46.54,124.96],[46.56,125.04]]) },
]

// ── viewBox 类型 ──────────────────────────────────────────────────────────────
type VB = [number, number, number, number]
const VB_DEFAULT: VB = [0, 0, 1200, 800]
const VB_W_MIN = 200
const VB_W_MAX = 1200

// ── 主组件 ───────────────────────────────────────────────────────────────────

const Dashboard: React.FC = () => {

  // ── 基础状态 ───────────────────────────────────────────────
  const [wsConnected, setWsConnected]   = useState(false)
  const [cases, setCases]               = useState<Case[]>([])
  const [statistics, setStatistics]     = useState<DashboardStatistics>({
    total_cases: 0, today_cases: 0, pending_cases: 0,
    resolved_cases: 0, this_week_cases: 0, this_month_cases: 0,
  })
  const [isPlaying, setIsPlaying]       = useState(true)
  const [overlayMode, setOverlayMode]   = useState<OverlayMode>('scatter')
  const [isFullscreen, setIsFullscreen] = useState(false)

  // ── 地图交互状态 ───────────────────────────────────────────
  const [vb, setVbState]           = useState<VB>(VB_DEFAULT)
  const [isDragging, setIsDragging] = useState(false)
  const [showFacilities, setShowFacilities] = useState(true)

  const vbRef  = useRef<VB>(VB_DEFAULT)
  const svgRef = useRef<SVGSVGElement>(null)
  // 拖拽起始信息
  const dragRef = useRef<{ cx: number; cy: number; vb0: VB } | null>(null)

  const setVb = useCallback((updater: VB | ((old: VB) => VB)) => {
    setVbState(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      vbRef.current = next
      return next
    })
  }, [])

  const wsRef         = useRef<WebSocket | null>(null)
  const dashRef       = useRef<HTMLDivElement>(null)
  const isPlayingRef  = useRef(isPlaying)
  useEffect(() => { isPlayingRef.current = isPlaying }, [isPlaying])

  // ── WebSocket ─────────────────────────────────────────────
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/ws/dashboard`
    const connect = () => {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws
      ws.onopen  = () => setWsConnected(true)
      ws.onerror = () => setWsConnected(false)
      ws.onclose = () => {
        setWsConnected(false)
        setTimeout(() => { if (wsRef.current?.readyState === WebSocket.CLOSED) connect() }, 3000)
      }
      ws.onmessage = (event) => {
        if (!isPlayingRef.current) return
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'initial_data') {
            setCases(data.data.cases || [])
            if (data.data.statistics) setStatistics(prev => ({ ...prev, ...data.data.statistics }))
          } else if (data.type === 'update') {
            if (data.data?.new_cases) {
              setCases(prev => {
                const ids = new Set(prev.map((c: Case) => c.id))
                return [...data.data.new_cases.filter((c: Case) => !ids.has(c.id)), ...prev].slice(0, 100)
              })
            }
            if (data.data?.statistics) setStatistics(prev => ({ ...prev, ...data.data.statistics }))
          }
        } catch (_) {}
      }
    }
    connect()
    return () => wsRef.current?.close()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!wsConnected) return
    const id = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN)
        wsRef.current.send(JSON.stringify({ type: 'ping' }))
    }, 30000)
    return () => clearInterval(id)
  }, [wsConnected])

  // ── 数据查询 ───────────────────────────────────────────────
  const { data: patrols = [] } = useQuery<PatrolRecord[]>({
    queryKey: ['dashboard-patrols'],
    queryFn:  () => patrolApi.list({ limit: 6 }),
    refetchInterval: 60_000,
  })
  const { data: areaRisks = [] } = useQuery<AreaRisk[]>({
    queryKey: ['dashboard-area-risks'],
    queryFn:  () => patrolApi.getAreaRisks({ limit: 3, min_risk: 0.5 }),
    refetchInterval: 120_000,
  })
  const { data: rawHotspots = [] } = useQuery({
    queryKey: ['dashboard-map-hotspots'],
    queryFn:  () => caseApi.getHotspots(1.0, 2),
    refetchInterval: 120_000,
  })
  const { data: keyLocations = [] } = useQuery<KeyLocation[]>({
    queryKey: ['dashboard-key-locations'],
    queryFn:  () => keyLocationApi.list({ status: 'active' }),
    refetchInterval: 300_000,
  })

  // ── 热点 SVG 数据 ──────────────────────────────────────────
  const hotspotSvg = useMemo(() => {
    type H = { center: { latitude: number; longitude: number }; case_count: number; radius_km: number }
    const GRADS   = ['heat-hi', 'heat-mid', 'heat-lo']
    const COLORS  = ['oklch(0.70 0.20 25)', 'oklch(0.80 0.16 75)', 'oklch(0.78 0.14 155)']
    const LABELS  = ['α', 'β', 'γ', 'δ', 'ε']
    return (rawHotspots as unknown as H[])
      .filter(h => h.center?.latitude && h.center?.longitude
        && h.center.latitude  >= LAT_MIN && h.center.latitude  <= LAT_MAX
        && h.center.longitude >= LNG_MIN && h.center.longitude <= LNG_MAX)
      .slice(0, 5)
      .map((h, i) => {
        const [sx, sy] = latLngToSvg(h.center.latitude, h.center.longitude)
        return {
          sx, sy,
          heatR:  clamp(h.case_count * 10, 60, 200),
          pulseR: clamp(h.case_count * 2 + 10, 12, 30),
          grad:   GRADS[Math.min(i, 2)],
          color:  COLORS[Math.min(i, 2)],
          count:  h.case_count,
          label:  LABELS[i],
        }
      })
  }, [rawHotspots])

  // ── 巡逻路径 SVG 数据（真实坐标 → 推导质心）────────────────
  const patrolMapItems = useMemo(() => {
    return patrols
      .filter(p => p.status === 'in_progress' || p.status === 'planned')
      .slice(0, 4)
      .map(p => {
        // 优先使用 area_coordinates
        if (p.area_coordinates && p.area_coordinates.length >= 2) {
          const valid = p.area_coordinates.filter(c =>
            c.lat >= LAT_MIN && c.lat <= LAT_MAX && c.lng >= LNG_MIN && c.lng <= LNG_MAX
          )
          if (valid.length >= 2) {
            const pts = valid.map(c => latLngToSvg(c.lat, c.lng))
            const pathD = `M ${pts.map(([x, y]) => `${x},${y}`).join(' L ')}`
            const [lx, ly] = latLngToSvg(
              valid.reduce((s, c) => s + c.lat, 0) / valid.length,
              valid.reduce((s, c) => s + c.lng, 0) / valid.length,
            )
            return { p, pathD, lx, ly }
          }
        }
        // 从关联案件质心推导
        const rel = cases.filter(c =>
          c.latitude && c.longitude && p.related_case_ids?.includes(c.id)
        )
        if (rel.length >= 1) {
          const [lx, ly] = latLngToSvg(
            rel.reduce((s, c) => s + c.latitude, 0) / rel.length,
            rel.reduce((s, c) => s + c.longitude, 0) / rel.length,
          )
          return { p, pathD: null, lx, ly }
        }
        return null
      })
      .filter((x): x is NonNullable<typeof x> => x !== null)
  }, [patrols, cases])

  // ── 风险区域轮廓 ───────────────────────────────────────────
  const riskZoneSvg = useMemo(() => {
    return areaRisks
      .filter(ar => ar.area_coordinates && ar.area_coordinates.length >= 3)
      .map(ar => {
        const valid = ar.area_coordinates!.filter(c =>
          c.lat >= LAT_MIN && c.lat <= LAT_MAX && c.lng >= LNG_MIN && c.lng <= LNG_MAX
        )
        if (valid.length < 3) return null
        const pts  = valid.map(c => latLngToSvg(c.lat, c.lng))
        const [cx, cy] = [
          pts.reduce((s, [x]) => s + x, 0) / pts.length,
          pts.reduce((s, [, y]) => s + y, 0) / pts.length,
        ]
        return { ar, svgPts: pts.map(([x, y]) => `${x},${y}`).join(' '), cx, cy }
      })
      .filter((x): x is NonNullable<typeof x> => x !== null)
  }, [areaRisks])

  // ── 案件散点 ───────────────────────────────────────────────
  const caseSvgPoints = useMemo(() =>
    cases
      .filter(c => c.latitude && c.longitude
        && c.latitude  >= LAT_MIN && c.latitude  <= LAT_MAX
        && c.longitude >= LNG_MIN && c.longitude <= LNG_MAX)
      .map(c => { const [sx, sy] = latLngToSvg(c.latitude, c.longitude); return { ...c, sx, sy } }),
    [cases],
  )

  // ── 折线图 ────────────────────────────────────────────────
  const sparklineVals = useMemo(() => buildSparklinePoints(cases), [cases])
  const sparkW = 320, sparkH = 110
  const polyPts = toPolyline(sparklineVals, sparkW, sparkH, 6)
  const areaPts = polyPts
    ? `${polyPts} ${(sparkW - 6).toFixed(1)},${(sparkH - 2).toFixed(1)} 6,${(sparkH - 2).toFixed(1)}`
    : ''

  const now      = new Date()
  const fmtDate  = (offset: number) => {
    const d = new Date(now); d.setDate(d.getDate() - offset)
    return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }
  const dateStart = fmtDate(29), dateMid = fmtDate(14), dateEnd = fmtDate(0)

  // ── 饼图 ──────────────────────────────────────────────────
  const typeDistribution = useMemo(() => {
    const m: Record<string, number> = {}
    cases.forEach(c => { const t = c.case_type || '其他'; m[t] = (m[t] || 0) + 1 })
    return Object.entries(m).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value)
  }, [cases])
  const pieSlices = useMemo(() => buildPieSlices(typeDistribution), [typeDistribution])
  const pieTotal  = useMemo(() => typeDistribution.reduce((s, d) => s + d.value, 0), [typeDistribution])

  // ── KPI ──────────────────────────────────────────────────
  const pendingCount    = statistics.pending_cases   || cases.filter(c => c.status === 'pending').length
  const processingCount = cases.filter(c => c.status === 'processing').length
  const resolvedCount   = statistics.resolved_cases  || cases.filter(c => c.status === 'resolved').length
  const totalCount      = statistics.total_cases     || cases.length
  const solveRate       = totalCount > 0 ? ((resolvedCount / totalCount) * 100).toFixed(1) : '—'

  // ── 警报行 ────────────────────────────────────────────────
  const alertRows = useMemo(() => {
    if (cases.length === 0) return [
      { sev: 'sev-crit', glyph: '!', no: 'A-0412', title: '管线开孔·让胡路 K112', sub: '柴油 · 蓝白罐车 · 已派 3 班', t: '14:22' },
      { sev: 'sev-hi',   glyph: '△', no: 'A-0411', title: '压差异常·萨尔图',       sub: '压力降 0.3 MPa · 待现场',    t: '14:18' },
      { sev: 'sev-med',  glyph: '◇', no: 'A-0409', title: '圆桌会议完成·M-8431',   sub: '4 AI 共识 · 置信 0.74',     t: '13:52' },
    ]
    const S = ['sev-crit', 'sev-hi', 'sev-med'] as const
    const G = ['!', '△', '◇']
    return cases.slice(0, 3).map((c, i) => {
      const d = new Date(c.occurred_time)
      return {
        sev: S[i], glyph: G[i], no: c.case_number,
        title: `${c.case_type || '未分类'}·${c.location || '未知地点'}`,
        sub:   c.status === 'pending' ? '待处理' : c.status === 'processing' ? '处理中' : '已解决',
        t: `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`,
      }
    })
  }, [cases])

  const PATROL_STATUS: Record<string, string> = { planned:'待命', in_progress:'执行中', completed:'完成', cancelled:'取消' }
  const PATROL_TYPE:   Record<string, string> = { routine:'日常', targeted:'重点', emergency:'紧急' }
  const activePatrols = patrols.filter(p => p.status === 'in_progress' || p.status === 'planned').slice(0, 3)

  // ── 地图交互处理 ───────────────────────────────────────────
  const zoomIn = useCallback(() => {
    setVb(([x, y, w, h]) => {
      const nw = clamp(w * 0.7, VB_W_MIN, VB_W_MAX)
      const nh = nw * (800 / 1200)
      const [cx, cy] = [x + w / 2, y + h / 2]
      return [clamp(cx - nw / 2, 0, 1200 - nw), clamp(cy - nh / 2, 0, 800 - nh), nw, nh]
    })
  }, [setVb])

  const zoomOut = useCallback(() => {
    setVb(([x, y, w, h]) => {
      const nw = clamp(w / 0.7, VB_W_MIN, VB_W_MAX)
      const nh = nw * (800 / 1200)
      const [cx, cy] = [x + w / 2, y + h / 2]
      return [clamp(cx - nw / 2, 0, 1200 - nw), clamp(cy - nh / 2, 0, 800 - nh), nw, nh]
    })
  }, [setVb])

  const resetView = useCallback(() => setVb(VB_DEFAULT), [setVb])

  // 滚轮缩放（imperative，绕鼠标位置）
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const handler = (e: WheelEvent) => {
      e.preventDefault()
      const container = svg.parentElement
      if (!container) return
      const rect = container.getBoundingClientRect()
      const [vbX, vbY, vbW, vbH] = vbRef.current
      const mx = vbX + (e.clientX - rect.left)  / rect.width  * vbW
      const my = vbY + (e.clientY - rect.top)   / rect.height * vbH
      const factor = e.deltaY < 0 ? 0.8 : 1.25
      const nw = clamp(vbW * factor, VB_W_MIN, VB_W_MAX)
      const nh = nw * (800 / 1200)
      setVb([
        clamp(mx - (mx - vbX) * (nw / vbW), 0, 1200 - nw),
        clamp(my - (my - vbY) * (nh / vbH), 0, 800  - nh),
        nw, nh,
      ])
    }
    svg.addEventListener('wheel', handler, { passive: false })
    return () => svg.removeEventListener('wheel', handler)
  }, [setVb])

  const handleMouseDown = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    dragRef.current = { cx: e.clientX, cy: e.clientY, vb0: [...vbRef.current] as VB }
    setIsDragging(true)
  }, [])

  const handleMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    const info = dragRef.current
    if (!info) return
    const container = e.currentTarget.parentElement
    if (!container) return
    const rect = container.getBoundingClientRect()
    const [,, w, h] = info.vb0
    const dx = (info.cx - e.clientX) / rect.width  * w
    const dy = (info.cy - e.clientY) / rect.height * h
    setVb([
      clamp(info.vb0[0] + dx, 0, 1200 - w),
      clamp(info.vb0[1] + dy, 0, 800  - h),
      w, h,
    ])
  }, [setVb])

  const handleMouseUp    = useCallback(() => { dragRef.current = null; setIsDragging(false) }, [])
  const handleMouseLeave = useCallback(() => { dragRef.current = null; setIsDragging(false) }, [])

  // ── 全屏 ──────────────────────────────────────────────────
  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) dashRef.current?.requestFullscreen?.()
    else document.exitFullscreen?.()
  }, [])
  useEffect(() => {
    const h = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', h)
    return () => document.removeEventListener('fullscreenchange', h)
  }, [])

  const togglePlaying = useCallback(() => setIsPlaying(p => !p), [])

  // ── 叠加层透明度 ───────────────────────────────────────────
  const heatOp    = overlayMode === 'heat'       ? 1   : overlayMode === 'cluster' ? 0.5 : 0.35
  const scatterOp = overlayMode === 'scatter'    ? 1   : overlayMode === 'heat'    ? 0.55 : 0.25
  const patrolOp  = overlayMode === 'trajectory' ? 1   : 0.45
  const clusterOp = overlayMode === 'cluster' || overlayMode === 'scatter' ? 1 : 0.2

  // 十字准星中心（顶级热点，否则地图中心）
  const crossX = hotspotSvg[0]?.sx ?? 600
  const crossY = hotspotSvg[0]?.sy ?? 400

  // 当前缩放显示
  const zoomDisplay = `${(1200 / vb[2]).toFixed(1)}×`

  return (
    <div className="db-main" ref={dashRef}>
      <div className="db-grid">

        {/* ── 左侧：英雄地图 ── */}
        <div className="card map-card">
          <div className="card-head">
            <span className="ico">◈</span>
            <span className="ti">辖区案件空间分布</span>
            <span className="chip" style={{ marginLeft: 10 }}>本年累计 · {totalCount} 案发点</span>
            <span className="db-spacer" />
            {/* 叠加层模式 */}
            <div className="db-overlay-btns">
              {(Object.keys(OVERLAY_LABELS) as OverlayMode[]).map(mode => (
                <button
                  key={mode}
                  className={`db-overlay-btn${overlayMode === mode ? ' active' : ''}`}
                  onClick={() => setOverlayMode(mode)}
                >{OVERLAY_LABELS[mode]}</button>
              ))}
            </div>
            <button
              className={`db-ctrl-btn${isPlaying ? ' db-ctrl-btn--active' : ''}`}
              onClick={togglePlaying}
              title={isPlaying ? '暂停更新' : '继续更新'}
            >{isPlaying ? '⏸' : '▶'}</button>
            <span className={`chip${wsConnected ? ' live' : ' db-ws-err'}`}>
              <span className="dot" style={wsConnected ? {} : { background: 'var(--err)' }} />
              {wsConnected ? 'WS 已连接' : 'WS 断开'}
            </span>
          </div>

          {/* 地图 SVG */}
          <div className="card-body" style={{ position: 'relative' }}>
            <svg
              ref={svgRef}
              className="map-svg"
              viewBox={`${vb[0]} ${vb[1]} ${vb[2]} ${vb[3]}`}
              preserveAspectRatio="xMidYMid meet"
              style={{ height: '100%', minHeight: 500, cursor: isDragging ? 'grabbing' : 'grab', userSelect: 'none' }}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseLeave}
            >
              <defs>
                <pattern id="grid-map"  width="60" height="60" patternUnits="userSpaceOnUse">
                  <path d="M60 0 L0 0 0 60" fill="none" stroke="oklch(0.32 0.014 250 / 0.22)" strokeWidth="0.5" />
                </pattern>
                <pattern id="grid-fine" width="15" height="15" patternUnits="userSpaceOnUse">
                  <path d="M15 0 L0 0 0 15" fill="none" stroke="oklch(0.32 0.014 250 / 0.08)" strokeWidth="0.3" />
                </pattern>
                <radialGradient id="heat-hi">
                  <stop offset="0%"   stopColor="oklch(0.70 0.20 25 / 0.45)" />
                  <stop offset="100%" stopColor="oklch(0.70 0.20 25 / 0)" />
                </radialGradient>
                <radialGradient id="heat-mid">
                  <stop offset="0%"   stopColor="oklch(0.80 0.16 75 / 0.32)" />
                  <stop offset="100%" stopColor="oklch(0.80 0.16 75 / 0)" />
                </radialGradient>
                <radialGradient id="heat-lo">
                  <stop offset="0%"   stopColor="oklch(0.78 0.14 155 / 0.26)" />
                  <stop offset="100%" stopColor="oklch(0.78 0.14 155 / 0)" />
                </radialGradient>
                <linearGradient id="land-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="oklch(0.205 0.015 250)" />
                  <stop offset="100%" stopColor="oklch(0.175 0.012 250)" />
                </linearGradient>
              </defs>

              {/* 底图：松嫩平原全覆盖，无断缝 */}
              <rect width="1200" height="800" fill="url(#land-grad)" />
              <rect width="1200" height="800" fill="url(#grid-fine)" />
              <rect width="1200" height="800" fill="url(#grid-map)" />

              {/* 扎龙湿地（大庆西北杜尔伯特境内）*/}
              <ellipse cx="420" cy="262" rx="58" ry="38"
                fill="oklch(0.38 0.08 220 / 0.18)" stroke="oklch(0.58 0.10 220 / 0.28)" strokeWidth="0.8" />
              <ellipse cx="372" cy="220" rx="32" ry="20"
                fill="oklch(0.38 0.08 220 / 0.15)" stroke="none" />

              {/* 嫩江（大庆西侧南北流向，约 lng 124.0）*/}
              <path
                d="M383,72 C372,110 361,170 349,230 C337,290 344,340 349,380 C354,420 380,460 406,510 C428,550 460,580 509,800"
                fill="none" stroke="oklch(0.58 0.12 220 / 0.72)" strokeWidth="2.8" strokeLinecap="round"
              />
              {/* 乌裕尔河（东北→西南，注入扎龙湿地）*/}
              <path
                d="M646,157 C600,175 558,200 520,241 C495,260 468,264 452,263"
                fill="none" stroke="oklch(0.58 0.10 220 / 0.50)" strokeWidth="1.5" strokeLinecap="round"
              />
              {/* 双阳河（大庆东南，流向松花江）*/}
              <path
                d="M691,369 C672,404 668,432 696,474 C722,515 760,540 808,540"
                fill="none" stroke="oklch(0.58 0.10 220 / 0.38)" strokeWidth="1.1" strokeLinecap="round"
              />

              {/* 主干道路（暖灰色，区别于蓝色河流）*/}
              <g fill="none" stroke="oklch(0.52 0.018 70 / 0.60)" strokeWidth="0.9" strokeDasharray="7 3">
                {/* G10绥满高速（东西向，大庆~lat 46.65）*/}
                <path d="M1200,313 C900,313 650,315 486,311 C350,308 180,312 0,313" />
                {/* G45大庆-广州高速（南北向，约 lng 125.1）*/}
                <path d="M621,0 C620,120 616,220 621,318 C612,430 590,540 570,800" />
                {/* 哈大高速（大庆→安达→哈尔滨，东南向）*/}
                <path d="M621,318 L680,362 L810,431 L920,484" strokeDasharray="5 4" />
                {/* 大庆→林甸道路（北向）*/}
                <path d="M621,318 C610,270 578,232 562,202" strokeDasharray="5 4" />
              </g>

              {/* ── 热力斑点：真实热点坐标 ── */}
              <g opacity={heatOp}>
                {hotspotSvg.length > 0 ? (
                  hotspotSvg.map((h, i) => (
                    <circle key={i} cx={h.sx} cy={h.sy} r={h.heatR} fill={`url(#${h.grad})`} />
                  ))
                ) : (
                  <>
                    <circle cx="340" cy="460" r="160" fill="url(#heat-hi)" />
                    <circle cx="720" cy="420" r="130" fill="url(#heat-mid)" />
                    <circle cx="980" cy="480" r="110" fill="url(#heat-lo)" />
                  </>
                )}
              </g>

              {/* ── 案件散点 ── */}
              <g opacity={scatterOp}>
                {caseSvgPoints.length > 0 ? (
                  caseSvgPoints.map(c => (
                    <circle key={c.id} cx={c.sx} cy={c.sy} r="3.5"
                      fill={c.status === 'resolved' ? 'oklch(0.78 0.14 155)' : c.status === 'processing' ? 'oklch(0.78 0.11 220)' : 'oklch(0.78 0.14 45)'}
                      opacity="0.85"
                    >
                      <title>{c.case_number} · {c.case_type || '未分类'}</title>
                    </circle>
                  ))
                ) : (
                  <>
                    <circle cx="625" cy="325" r="3.5" fill="oklch(0.78 0.14 45)" opacity=".9" />
                    <circle cx="645" cy="315" r="3.5" fill="oklch(0.78 0.14 45)" opacity=".9" />
                    <circle cx="610" cy="340" r="3.5" fill="oklch(0.78 0.14 45)" opacity=".9" />
                  </>
                )}
              </g>

              {/* ── 脉冲圈：真实热点位置 ── */}
              {hotspotSvg.length > 0 ? (
                hotspotSvg.slice(0, 3).map((h, i) => (
                  <g key={i}>
                    <circle
                      className="pulse-ring"
                      cx={h.sx} cy={h.sy}
                      r={h.pulseR}
                      fill="none"
                      stroke={h.color}
                      strokeWidth="1.8"
                      style={{ animationDelay: `${i * 0.9}s` }}
                    />
                    <circle cx={h.sx} cy={h.sy} r={h.pulseR * 0.38} fill={h.color} />
                    <circle cx={h.sx} cy={h.sy} r={h.pulseR * 0.38} fill="none" stroke="oklch(0.97 0.008 90)" strokeWidth="1" />
                  </g>
                ))
              ) : (
                <>
                  <g>
                    <circle className="pulse-ring" cx="340" cy="460" r="18" fill="none" stroke="oklch(0.70 0.20 25)" strokeWidth="1.8" />
                    <circle cx="340" cy="460" r="7" fill="oklch(0.70 0.20 25)" />
                    <circle cx="340" cy="460" r="7" fill="none" stroke="oklch(0.97 0.008 90)" strokeWidth="1" />
                  </g>
                  <g>
                    <circle className="pulse-ring" cx="720" cy="420" r="14" fill="none" stroke="oklch(0.80 0.16 75)" strokeWidth="1.4" style={{ animationDelay: '1s' }} />
                    <circle cx="720" cy="420" r="5.5" fill="oklch(0.80 0.16 75)" />
                  </g>
                </>
              )}

              {/* ── cluster 模式：聚类圈轮廓 ── */}
              {overlayMode === 'cluster' && (
                <g fill="none" stroke="oklch(0.78 0.14 45 / 0.45)" strokeWidth="1.5" strokeDasharray="6 3">
                  {hotspotSvg.length > 0 ? (
                    hotspotSvg.map((h, i) => (
                      <circle key={i} cx={h.sx} cy={h.sy} r={h.heatR * 0.55} />
                    ))
                  ) : (
                    <>
                      <circle cx="340" cy="460" r="88" />
                      <circle cx="720" cy="420" r="68" />
                      <circle cx="980" cy="480" r="55" />
                    </>
                  )}
                </g>
              )}

              {/* ── 聚类标签（分角度散开，避免重叠）── */}
              {(() => {
                const ANGLES = [0, -Math.PI / 2, Math.PI / 2, Math.PI * 0.75, -Math.PI * 0.75]
                const DIST = 60
                const items = hotspotSvg.length > 0 ? hotspotSvg : []
                return (
                  <g fontFamily="JetBrains Mono, monospace" fontSize="12" fill="oklch(0.78 0.14 45)" opacity={clusterOp}>
                    {items.map((h, i) => {
                      const angle = ANGLES[i % ANGLES.length]
                      const lx = h.sx + Math.cos(angle) * DIST
                      const ly = h.sy + Math.sin(angle) * DIST
                      const anchor = Math.cos(angle) >= 0 ? 'start' : 'end'
                      const tx = lx + (Math.cos(angle) >= 0 ? 4 : -4)
                      return (
                        <g key={i}>
                          <line
                            x1={h.sx} y1={h.sy}
                            x2={lx} y2={ly}
                            stroke="oklch(0.78 0.14 45 / 0.35)"
                            strokeWidth="0.8"
                          />
                          <text
                            x={tx} y={ly + 4}
                            textAnchor={anchor}
                            paintOrder="stroke"
                            stroke="oklch(0.12 0.012 250 / 0.82)"
                            strokeWidth="3.5"
                            strokeLinejoin="round"
                          >
                            {h.label} · {h.count} 案
                          </text>
                        </g>
                      )
                    })}
                    {hotspotSvg.length === 0 && caseSvgPoints.length > 0 && (
                      <text
                        x="520" y="280"
                        paintOrder="stroke"
                        stroke="oklch(0.12 0.012 250 / 0.75)"
                        strokeWidth="3"
                      >
                        ● 共 {caseSvgPoints.length} 个案发点（含坐标）
                      </text>
                    )}
                  </g>
                )
              })()}

              {/* ── 城市标签（真实经纬度投影，按行政级别分色）── */}
              <g fontFamily="IBM Plex Sans, sans-serif">
                {CITY_LABELS.map(c => {
                  const [cx, cy] = latLngToSvg(c.lat, c.lng)
                  const fill = c.type === 'major'    ? 'oklch(0.92 0.010 90)'
                             : c.type === 'city'     ? 'oklch(0.80 0.010 90)'
                             : c.type === 'district' ? 'oklch(0.68 0.010 90)'
                             : 'oklch(0.54 0.012 90)'
                  const dotR = c.type === 'major' ? 3.5 : c.type === 'city' ? 2.5 : 1.8
                  return (
                    <g key={c.name}>
                      <circle cx={cx} cy={cy} r={dotR} fill={fill} opacity="0.7" />
                      <text
                        x={cx} y={cy - dotR - 3}
                        fontSize={c.size}
                        fontWeight={c.weight}
                        fill={fill}
                        textAnchor="middle"
                        paintOrder="stroke"
                        stroke="oklch(0.12 0.012 250 / 0.82)"
                        strokeWidth="3"
                        strokeLinejoin="round"
                      >{c.name}</text>
                    </g>
                  )
                })}
              </g>

              {/* ── 设施图层（可切换）── */}
              {showFacilities && (
                <g>
                  {/* 输油管线（真实走向）*/}
                  {PIPELINE_ROUTES.map(p => (
                    <path key={p.id} d={p.d}
                      fill="none"
                      stroke={`oklch(0.78 0.14 45 / ${p.opacity})`}
                      strokeWidth={p.width}
                      strokeDasharray={p.dasharray}
                      strokeLinecap="round"
                    />
                  ))}
                  {/* 中俄管道泵站节点（三角形，沿管线）*/}
                  {([[48.0,123.8],[47.5,124.0],[47.1,124.4],[46.85,124.35],[46.4,124.55]] as [number,number][])
                    .map(([la, ln], i) => {
                      const [px, py] = latLngToSvg(la, ln)
                      return (
                        <polygon key={i}
                          points={`${px},${py-5} ${px+4.5},${py+4} ${px-4.5},${py+4}`}
                          fill="oklch(0.80 0.16 75)" opacity="0.82"
                        />
                      )
                    })
                  }
                  {/* 油田采区（橙色虚线圆，标注采油区范围）*/}
                  {OIL_FIELDS.map(f => {
                    const [fx, fy] = latLngToSvg(f.lat, f.lng)
                    return (
                      <g key={f.name}>
                        <circle cx={fx} cy={fy} r="28"
                          fill="oklch(0.78 0.14 45 / 0.07)"
                          stroke="oklch(0.78 0.14 45 / 0.32)"
                          strokeWidth="1" strokeDasharray="4 3"
                        />
                        <text x={fx} y={fy + 4}
                          fontFamily="JetBrains Mono, monospace" fontSize="8"
                          fill="oklch(0.76 0.14 45 / 0.88)" textAnchor="middle"
                          paintOrder="stroke" stroke="oklch(0.12 0.012 250 / 0.7)" strokeWidth="2"
                        >{f.name}</text>
                      </g>
                    )
                  })}
                  {/* 炼化/储运设施（方块=炼厂，菱形=油库/泵站）*/}
                  {OIL_FACILITIES.map(f => {
                    const [fx, fy] = latLngToSvg(f.lat, f.lng)
                    return (
                      <g key={f.name}>
                        {f.kind === 'refinery' ? (
                          <rect x={fx - 5} y={fy - 5} width="10" height="10"
                            fill="oklch(0.72 0.18 285)" stroke="oklch(0.97 0.008 90)" strokeWidth="0.8" />
                        ) : (
                          <polygon
                            points={`${fx},${fy-6} ${fx+5},${fy} ${fx},${fy+6} ${fx-5},${fy}`}
                            fill="oklch(0.72 0.14 285)" stroke="oklch(0.97 0.008 90)" strokeWidth="0.6"
                          />
                        )}
                        <text x={fx + 8} y={fy + 4}
                          fontFamily="JetBrains Mono, monospace" fontSize="9"
                          fill="oklch(0.82 0.010 90)"
                          paintOrder="stroke" stroke="oklch(0.12 0.012 250 / 0.7)" strokeWidth="2.5"
                        >{f.name}</text>
                      </g>
                    )
                  })}
                  {/* 加油站（小菱形，沿主要道路）*/}
                  {GAS_STATIONS.map((s, i) => {
                    const [sx, sy] = latLngToSvg(s.lat, s.lng)
                    return (
                      <polygon key={i}
                        points={`${sx},${sy-5} ${sx+4},${sy} ${sx},${sy+5} ${sx-4},${sy}`}
                        fill="oklch(0.78 0.11 220)" stroke="oklch(0.97 0.008 90)" strokeWidth="0.5"
                      />
                    )
                  })}
                  {/* 重要部位（用户在设置中添加的，青绿色区分）*/}
                  {keyLocations
                    .filter(kl => kl.latitude != null && kl.longitude != null
                      && kl.latitude! >= LAT_MIN && kl.latitude! <= LAT_MAX
                      && kl.longitude! >= LNG_MIN && kl.longitude! <= LNG_MAX)
                    .map(kl => {
                      const [kx, ky] = latLngToSvg(kl.latitude!, kl.longitude!)
                      const isSquare = ['oil_depot', 'refinery', 'storage'].includes(kl.location_type)
                      const isDiamond = ['pipeline_node', 'gas_station'].includes(kl.location_type)
                      const riskAlpha = 0.6 + (kl.risk_level / 10) * 0.35
                      return (
                        <g key={kl.id}>
                          {isSquare ? (
                            <rect x={kx - 6} y={ky - 6} width="12" height="12"
                              fill={`oklch(0.72 0.16 155 / ${riskAlpha})`}
                              stroke="oklch(0.92 0.12 155)" strokeWidth="1"
                            />
                          ) : isDiamond ? (
                            <polygon
                              points={`${kx},${ky-7} ${kx+6},${ky} ${kx},${ky+7} ${kx-6},${ky}`}
                              fill={`oklch(0.72 0.16 155 / ${riskAlpha})`}
                              stroke="oklch(0.92 0.12 155)" strokeWidth="1"
                            />
                          ) : (
                            <circle cx={kx} cy={ky} r="6"
                              fill={`oklch(0.72 0.16 155 / ${riskAlpha})`}
                              stroke="oklch(0.92 0.12 155)" strokeWidth="1"
                            />
                          )}
                          <text x={kx + 9} y={ky + 4}
                            fontFamily="JetBrains Mono, monospace" fontSize="9"
                            fill="oklch(0.88 0.10 155)"
                            paintOrder="stroke" stroke="oklch(0.12 0.012 250 / 0.75)" strokeWidth="2.5"
                          >
                            <title>{kl.name} · 风险{kl.risk_level}</title>
                            {kl.name.slice(0, 6)}
                          </text>
                        </g>
                      )
                    })
                  }
                </g>
              )}

              {/* ── 巡逻路线：真实数据，否则回退静态 ── */}
              <g opacity={patrolOp}>
                {patrolMapItems.length > 0 ? (
                  patrolMapItems.map((item, i) => (
                    <g key={i}>
                      {item.pathD && (
                        <path d={item.pathD}
                          stroke="oklch(0.78 0.11 220 / 0.75)"
                          strokeWidth="1.8" fill="none" strokeDasharray="8 5"
                        />
                      )}
                      {overlayMode === 'trajectory' && item.pathD && (
                        /* 路径中点处放一个方向箭头 */
                        <circle cx={item.lx} cy={item.ly} r="4" fill="oklch(0.78 0.11 220)" opacity="0.6" />
                      )}
                      <circle cx={item.lx} cy={item.ly} r="5" fill="oklch(0.78 0.11 220)" />
                      <text x={item.lx + 8} y={item.ly - 3}
                        fontFamily="JetBrains Mono, monospace" fontSize="9" fill="oklch(0.82 0.010 90)">
                        {(item.p.area_name || '').slice(0, 8)} · {item.p.status === 'in_progress' ? '进行中' : '待命'}
                      </text>
                    </g>
                  ))
                ) : (
                  /* 静态回退 */
                  <>
                    <g stroke="oklch(0.78 0.11 220 / 0.75)" strokeWidth="1.8" fill="none" strokeDasharray="8 5">
                      <path d="M 340 460 C 480 440,600 420,720 420" />
                      <path d="M 720 420 C 820 440,900 460,980 480" />
                    </g>
                    {overlayMode === 'trajectory' && (
                      <g fill="oklch(0.78 0.11 220)" stroke="none">
                        <polygon points="518,432 530,440 518,448" />
                        <polygon points="848,442 860,450 848,458" />
                      </g>
                    )}
                    <g>
                      <circle cx="520" cy="440" r="5" fill="oklch(0.78 0.11 220)" />
                      <text x="528" y="437" fontFamily="JetBrains Mono, monospace" fontSize="9" fill="oklch(0.82 0.010 90)">巡-A3 · 12:40 巡毕</text>
                    </g>
                    <g>
                      <circle cx="850" cy="450" r="5" fill="oklch(0.78 0.11 220)" />
                      <text x="858" y="447" fontFamily="JetBrains Mono, monospace" fontSize="9" fill="oklch(0.82 0.010 90)">巡-B1 · 进行中</text>
                    </g>
                  </>
                )}
              </g>

              {/* ── 高风险区域轮廓（来自 areaRisks）── */}
              {riskZoneSvg.length > 0 && (
                <g fill="none" stroke="oklch(0.78 0.14 45 / 0.4)" strokeWidth="1.2" strokeDasharray="5 3">
                  {riskZoneSvg.map((rz, i) => (
                    <g key={i}>
                      <polygon points={rz.svgPts} />
                      <text x={rz.cx + 6} y={rz.cy - 4}
                        fontFamily="JetBrains Mono, monospace" fontSize="9" fill="oklch(0.78 0.14 45 / 0.8)">
                        {rz.ar.area_name.slice(0, 6)}
                      </text>
                    </g>
                  ))}
                </g>
              )}

              {/* ── 十字准星（顶级热点中心）── */}
              <g stroke="oklch(0.97 0.008 90)" strokeWidth="0.8">
                <circle cx={crossX} cy={crossY} r="28" fill="none" strokeDasharray="3 4" />
                <line x1={crossX - 42} y1={crossY} x2={crossX + 42} y2={crossY} />
                <line x1={crossX} y1={crossY - 42} x2={crossX} y2={crossY + 42} />
              </g>

              {/* ── 指南针 ── */}
              <g transform="translate(1120 720)" fontFamily="JetBrains Mono, monospace" fontSize="11" fill="oklch(0.72 0.013 90)">
                <circle r="26" fill="oklch(0.12 0.012 250 / 0.6)" stroke="oklch(0.32 0.014 250 / 0.8)" />
                <line x1="0" y1="-26" x2="0" y2="26" stroke="oklch(0.32 0.014 250 / 0.6)" />
                <line x1="-26" y1="0" x2="26" y2="0" stroke="oklch(0.32 0.014 250 / 0.6)" />
                <polygon points="0,-26 -5,-10 5,-10" fill="oklch(0.78 0.14 45)" />
                <text x="-4" y="-30">N</text>
              </g>

              {/* ── 比例尺（100 SVG 单位 ≈ SCALE_BAR_KM km）── */}
              <g transform="translate(940 752)" fontFamily="JetBrains Mono, monospace" fontSize="11" fill="oklch(0.72 0.013 90)">
                <rect x="-8" y="-14" width="136" height="36" fill="oklch(0.12 0.012 250 / 0.65)" />
                <line x1="0"   y1="0" x2="100" y2="0" stroke="oklch(0.72 0.013 90)" strokeWidth="1.2" />
                <line x1="0"   y1="-4" x2="0"   y2="4" stroke="oklch(0.72 0.013 90)" />
                <line x1="50"  y1="-3" x2="50"  y2="3" stroke="oklch(0.72 0.013 90)" />
                <line x1="100" y1="-4" x2="100" y2="4" stroke="oklch(0.72 0.013 90)" />
                <text x="28" y="18">≈ {SCALE_BAR_KM} km</text>
              </g>
            </svg>

            {/* HUD */}
            <div className="map-hud">
              <div className="pod">VIEW · <span className="n">46.59°N</span> · <span className="n">125.11°E</span></div>
              <div className="pod">ZOOM · <span className="n">{zoomDisplay}</span></div>
              <div className="pod">WINDOW · <span className="n">P30D</span></div>
              <div className="pod">RENDER · <span className="n">{totalCount > 0 ? totalCount : 127} 案发点</span></div>
            </div>

            {/* 地图控件 */}
            <div className="map-controls">
              <button title="放大（滚轮可缩放）" onClick={zoomIn}>＋</button>
              <button title="缩小" onClick={zoomOut}>−</button>
              <button title="重置视图" onClick={resetView}>◎</button>
              <button
                title={showFacilities ? '隐藏设施图层' : '显示设施图层'}
                onClick={() => setShowFacilities(f => !f)}
                className={showFacilities ? 'active' : ''}
              >☰</button>
              <button
                title={isFullscreen ? '退出全屏' : '全屏'}
                onClick={toggleFullscreen}
                className={isFullscreen ? 'active' : ''}
              >⛶</button>
            </div>

            {/* KPI pills */}
            <div className="map-kpis">
              <div className="kpill">
                <div className="lbl">案件总数</div>
                <div className="val">{totalCount || 127}</div>
                <div className="sub"><span className="trend">↑ {statistics.today_cases || 6}</span>今日</div>
              </div>
              <div className="kpill">
                <div className="lbl">待处理</div>
                <div className="val" style={{ color: 'var(--warn)' }}>{pendingCount || 8}</div>
                <div className="sub">未超期 {Math.max(0, (pendingCount || 8) - 2)}</div>
              </div>
              <div className="kpill">
                <div className="lbl">处理中</div>
                <div className="val" style={{ color: 'var(--info)' }}>{processingCount || 14}</div>
                <div className="sub">研判 · 巡逻</div>
              </div>
              <div className="kpill">
                <div className="lbl">已侦破</div>
                <div className="val" style={{ color: 'var(--ok)' }}>{resolvedCount || 105}</div>
                <div className="sub">破案率 {solveRate !== '—' ? `${solveRate}%` : '82.7%'}</div>
              </div>
            </div>

            {/* 图例 */}
            <div className="map-legend-bottom">
              <span><span className="sw" style={{ background: 'oklch(0.70 0.20 25)' }} />高风险点</span>
              <span><span className="sw" style={{ background: 'oklch(0.80 0.16 75)' }} />中风险点</span>
              <span><span className="sw" style={{ background: 'oklch(0.78 0.14 155)' }} />低风险点</span>
              <span><span className="sw sq" style={{ background: 'oklch(0.72 0.14 285)' }} />油库</span>
              <span><span className="sw dm" style={{ background: 'oklch(0.78 0.11 220)' }} />加油站</span>
              <span><span className="sw tr" style={{ background: 'oklch(0.80 0.16 75)' }} />管线节点</span>
              <span><span className="sw" style={{ background: 'oklch(0.78 0.11 220)' }} />巡逻路径</span>
            </div>
          </div>
        </div>

        {/* ── 右侧导轨 ── */}
        <div className="db-rail">

          {/* 卡片 1：30 天趋势 */}
          <div className="card">
            <div className="card-head">
              <span className="ico">◈</span>
              <span className="ti">30 天趋势</span>
              <span className="db-spacer" />
              <span className="chip">均 {cases.length > 0 ? (cases.length / 30).toFixed(1) : '4.2'} 件/日</span>
            </div>
            <div className="card-body" style={{ padding: '10px 14px 12px' }}>
              <svg viewBox={`0 0 ${sparkW} ${sparkH}`}
                style={{ width: '100%', height: sparkH, display: 'block' }}
                preserveAspectRatio="none"
              >
                <defs>
                  <linearGradient id="grad-total" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%"   stopColor="oklch(0.78 0.14 45)" stopOpacity="0.3" />
                    <stop offset="100%" stopColor="oklch(0.78 0.14 45)" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <g stroke="oklch(0.32 0.014 250 / 0.35)" strokeWidth="0.4">
                  <line x1="0" y1="25" x2={sparkW} y2="25" />
                  <line x1="0" y1="55" x2={sparkW} y2="55" />
                  <line x1="0" y1="85" x2={sparkW} y2="85" />
                </g>
                {areaPts && <polygon points={areaPts} fill="url(#grad-total)" />}
                {polyPts && <polyline points={polyPts} fill="none" stroke="oklch(0.78 0.14 45)" strokeWidth="1.5" />}
                {polyPts && (() => {
                  const pts = polyPts.split(' ')
                  const last = pts[pts.length - 1].split(',')
                  return <circle cx={last[0]} cy={last[1]} r="3" fill="oklch(0.78 0.14 45)" />
                })()}
                <g fontFamily="JetBrains Mono, monospace" fontSize="8" fill="oklch(0.45 0.013 90)">
                  <text x="0"                  y="106">{dateStart}</text>
                  <text x={sparkW / 2 - 12}   y="106">{dateMid}</text>
                  <text x={sparkW - 32}        y="106">{dateEnd}</text>
                </g>
              </svg>
            </div>
          </div>

          {/* 卡片 2：类型分布饼图 */}
          <div className="card db-pie-card">
            <div className="card-head">
              <span className="ico">◎</span>
              <span className="ti">案件类型分布</span>
              <span className="db-spacer" />
              <span className="chip">本年</span>
            </div>
            <div className="card-body db-pie-body">
              <div className="pie-wrap">
                <svg viewBox="0 0 130 130" style={{ width: 130, height: 130 }}>
                  <g transform="translate(65 65)" fill="none" strokeWidth="16">
                    {pieSlices.length > 0
                      ? pieSlices.map((sl, i) => (
                          <circle key={i} r="52" stroke={sl.color}
                            strokeDasharray={`${(sl.pct / 100) * PIE_CIRCUMFERENCE} ${PIE_CIRCUMFERENCE}`}
                            strokeDashoffset={-sl.offset} transform="rotate(-90)" />
                        ))
                      : [
                          { color: 'oklch(0.78 0.14 45)',   da: '111 327', off: '0'    },
                          { color: 'oklch(0.72 0.14 285)',  da: '72 327',  off: '-111' },
                          { color: 'oklch(0.78 0.11 220)',  da: '59 327',  off: '-183' },
                          { color: 'oklch(0.80 0.16 75)',   da: '52 327',  off: '-242' },
                          { color: 'oklch(0.55 0.013 250)', da: '33 327',  off: '-294' },
                        ].map((sl, i) => (
                          <circle key={i} r="52" stroke={sl.color}
                            strokeDasharray={sl.da} strokeDashoffset={sl.off} transform="rotate(-90)" />
                        ))
                    }
                  </g>
                </svg>
                <div className="pie-center">
                  <div className="n">{pieTotal || 127}</div>
                  <div className="l">本年累计</div>
                </div>
              </div>
              <div className="pie-legend">
                {pieSlices.length > 0
                  ? pieSlices.map((sl, i) => (
                      <div className="row" key={i}>
                        <span className="sw" style={{ background: sl.color }} />
                        <span className="nm">{sl.label}</span>
                        <span className="pct">{sl.pct}%</span>
                        <span className="n">{sl.count}</span>
                      </div>
                    ))
                  : [
                      { color: 'oklch(0.78 0.14 45)',   nm: '管线开孔', pct: '34%', n: 43 },
                      { color: 'oklch(0.72 0.14 285)',  nm: '油库入侵', pct: '22%', n: 28 },
                      { color: 'oklch(0.78 0.11 220)',  nm: '加油站',   pct: '18%', n: 23 },
                      { color: 'oklch(0.80 0.16 75)',   nm: '罐车劫持', pct: '16%', n: 20 },
                      { color: 'oklch(0.55 0.013 250)', nm: '其他',     pct: '10%', n: 13 },
                    ].map((sl, i) => (
                      <div className="row" key={i}>
                        <span className="sw" style={{ background: sl.color }} />
                        <span className="nm">{sl.nm}</span>
                        <span className="pct">{sl.pct}</span>
                        <span className="n">{sl.n}</span>
                      </div>
                    ))
                }
              </div>
            </div>
          </div>

          {/* 卡片 3：实时警报 */}
          <div className="card">
            <div className="card-head">
              <span className="ico">⚠</span>
              <span className="ti">实时警报</span>
              <span className="db-spacer" />
              <span className="chip err">
                <span className="dot" style={{ background: 'var(--err)' }} />
                {alertRows.length} 条
              </span>
            </div>
            <div className="card-body" style={{ padding: 0, overflowY: 'auto' }}>
              {alertRows.map((a, i) => (
                <div key={i} className={`alert-row ${a.sev}`}>
                  <span className="sev" />
                  <span className="glyph">{a.glyph}</span>
                  <div className="body">
                    <div className="ti"><span className="no">{a.no}</span>{a.title}</div>
                    <div className="sub">{a.sub}</div>
                  </div>
                  <div className="t">{a.t}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 卡片 4：巡逻规划 */}
          <div className="card">
            <div className="card-head">
              <span className="ico">⊕</span>
              <span className="ti">巡逻规划</span>
              <span className="db-spacer" />
              <span className="chip">
                {patrols.filter(p => p.status === 'in_progress').length} 执行 ·{' '}
                {patrols.filter(p => p.status === 'planned').length} 待命
              </span>
            </div>
            <div className="card-body db-patrol-body">
              {activePatrols.length > 0
                ? activePatrols.map((p) => (
                    <div key={p.id} className={`patrol-row${p.status === 'in_progress' ? ' active' : ''}`}>
                      <div className={`patrol-dot patrol-dot--${p.status}`} />
                      <div className="patrol-info">
                        <div className="patrol-area">{p.area_name}</div>
                        <div className="patrol-meta">
                          {PATROL_TYPE[p.patrol_type] || p.patrol_type} ·{' '}
                          {p.officer_names?.split(',')[0] || `${p.officer_count} 人`}
                        </div>
                      </div>
                      <div className={`patrol-badge patrol-badge--${p.status}`}>
                        {PATROL_STATUS[p.status] || p.status}
                      </div>
                    </div>
                  ))
                : [
                    { area: '让胡路管线段', type: '重点', officer: '张队', status: 'in_progress' },
                    { area: '萨尔图中段',   type: '日常', officer: '李组', status: 'in_progress' },
                    { area: '安达片区',     type: '紧急', officer: '王队', status: 'planned'     },
                  ].map((p, i) => (
                    <div key={i} className={`patrol-row${p.status === 'in_progress' ? ' active' : ''}`}>
                      <div className={`patrol-dot patrol-dot--${p.status}`} />
                      <div className="patrol-info">
                        <div className="patrol-area">{p.area}</div>
                        <div className="patrol-meta">{p.type} · {p.officer}</div>
                      </div>
                      <div className={`patrol-badge patrol-badge--${p.status}`}>
                        {p.status === 'in_progress' ? '执行中' : '待命'}
                      </div>
                    </div>
                  ))
              }

              {areaRisks.length > 0 && <div className="patrol-section-label">高风险待巡</div>}
              {areaRisks.length > 0
                ? areaRisks.map((ar) => (
                    <div key={ar.id} className="patrol-risk-row">
                      <div className="patrol-risk-bar" style={{
                        background: ar.risk_score > 0.7 ? 'var(--err)' : ar.risk_score > 0.5 ? 'var(--warn)' : 'oklch(0.72 0.13 130)',
                        height: `${Math.round(ar.risk_score * 100)}%`,
                      }} />
                      <div className="patrol-info">
                        <div className="patrol-area">{ar.area_name}</div>
                        <div className="patrol-meta">
                          7日 {ar.case_count_7d} 案 ·{' '}
                          {ar.days_since_patrol != null ? `${ar.days_since_patrol} 天未巡` : '暂无巡逻记录'}
                        </div>
                      </div>
                      <div className="patrol-score">{(ar.risk_score * 10).toFixed(1)}</div>
                    </div>
                  ))
                : [
                    { area: '让胡路片区', days: 5, cases7d: 4, score: 9.1 },
                    { area: '萨尔图中段', days: 2, cases7d: 2, score: 7.4 },
                    { area: '安达片区',   days: 8, cases7d: 3, score: 5.8 },
                  ].map((ar, i) => (
                    <div key={i} className="patrol-risk-row">
                      <div className="patrol-risk-bar" style={{
                        background: ar.score > 8 ? 'var(--err)' : ar.score > 6 ? 'var(--warn)' : 'oklch(0.72 0.13 130)',
                        height: `${ar.score * 10}%`,
                      }} />
                      <div className="patrol-info">
                        <div className="patrol-area">{ar.area}</div>
                        <div className="patrol-meta">7日 {ar.cases7d} 案 · {ar.days} 天未巡</div>
                      </div>
                      <div className="patrol-score">{ar.score.toFixed(1)}</div>
                    </div>
                  ))
              }
            </div>
          </div>

        </div>{/* /db-rail */}
      </div>{/* /db-grid */}
    </div>
  )
}

export default Dashboard
