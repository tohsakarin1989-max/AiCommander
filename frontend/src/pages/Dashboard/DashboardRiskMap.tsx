import { useEffect, useRef, useState } from 'react'
import {
  AimOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  MinusOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { mountOfflineBasemap, type BasemapStatus } from '../../components/Map/offlineBasemap'
import { BasemapNotice } from '../../components/Map/BasemapNotice'
import { escapeHtml } from '../../utils/html'
import { shouldFitInitialMap } from './dailyDashboardModel'
import type {
  DashboardHotspot,
  DashboardMapPoint,
  DashboardSignalPoint,
  DashboardWellPoint,
  ProjectedChainLine,
} from './dashboardCommandModel'

export type DashboardMapLayer = 'attention' | 'signals' | 'cases'

interface DashboardRiskMapProps {
  layer: DashboardMapLayer
  wells: DashboardWellPoint[]
  signals: DashboardSignalPoint[]
  cases: DashboardMapPoint[]
  chainLines: ProjectedChainLine[]
  hotspots: DashboardHotspot[]
  isFullscreen: boolean
  onToggleFullscreen: () => void
  operationalAreaId?: number
  neutralWells?: boolean
  focus?: [number, number] | null
}

const DEFAULT_CENTER: L.LatLngExpression = [46.5977, 125.1034]
const DEFAULT_ZOOM = 8

const WELL_COLORS: Record<DashboardWellPoint['attentionLevel'], string> = {
  high: '#ef5b5b',
  medium: '#f59e0b',
  watch: '#39b9d6',
  stable: '#4ac486',
}

function hotspotCoordinate(hotspot: DashboardHotspot): [number, number] | null {
  const latitude = hotspot.center?.latitude ?? hotspot.center_latitude
  const longitude = hotspot.center?.longitude ?? hotspot.center_longitude
  if (typeof latitude !== 'number' || typeof longitude !== 'number') return null
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null
  return [latitude, longitude]
}

function fitMap(map: L.Map, bounds: L.LatLngBounds | null) {
  if (bounds?.isValid()) {
    map.fitBounds(bounds, { padding: [42, 42], maxZoom: 13 })
  } else {
    map.setView(DEFAULT_CENTER, DEFAULT_ZOOM)
  }
}

export default function DashboardRiskMap({
  layer,
  wells,
  signals,
  cases,
  chainLines,
  hotspots,
  isFullscreen,
  onToggleFullscreen,
  operationalAreaId,
  neutralWells = false,
  focus,
}: DashboardRiskMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layersRef = useRef<L.Layer[]>([])
  const boundsRef = useRef<L.LatLngBounds | null>(null)
  const fittedRef = useRef(false)
  const userInteractedRef = useRef(false)
  const [basemapStatus, setBasemapStatus] = useState<BasemapStatus>('loading')
  const retryBasemapRef = useRef<() => void>(() => {})

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = L.map(containerRef.current, {
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      zoomControl: false,
      zoomAnimation: false,
      attributionControl: true,
      // 点位显示已限额；使用 SVG，避免 Canvas 异步重绘在快速卸载时访问失效上下文。
      preferCanvas: false,
    })
    mapRef.current = map
    fittedRef.current = false
    userInteractedRef.current = false
    const container = containerRef.current
    const markInteraction = () => { userInteractedRef.current = true }
    container.addEventListener('pointerdown', markInteraction)
    container.addEventListener('wheel', markInteraction, { passive: true })

    const stopBasemap = mountOfflineBasemap(map, {
      operationalAreaId, onStatus: setBasemapStatus,
      onConfig: config => {
        if (!fittedRef.current && !userInteractedRef.current && !boundsRef.current?.isValid() && config.bounds) {
          map.fitBounds(config.bounds, { padding: [24, 24] })
        }
      },
    })
    retryBasemapRef.current = stopBasemap.retry

    const resizeObserver = new ResizeObserver(() => map.invalidateSize({ pan: false }))
    resizeObserver.observe(containerRef.current)

    return () => {
      stopBasemap()
      retryBasemapRef.current = () => {}
      resizeObserver.disconnect()
      container.removeEventListener('pointerdown', markInteraction)
      container.removeEventListener('wheel', markInteraction)
      // 先移除矢量层，再销毁 Canvas renderer，避免卸载后的重绘访问已清空上下文。
      map.eachLayer(item => { if (item instanceof L.Path) map.removeLayer(item) })
      layersRef.current = []
      map.remove()
      mapRef.current = null
    }
  }, [operationalAreaId])

  useEffect(() => {
    if (focus && mapRef.current) {
      const map = mapRef.current
      userInteractedRef.current = true
      map.setView(focus, Math.max(12, map.getZoom()))
      // 独立选择高亮：即使该授权样例不在地图500条展示集内，仍能定位看到。
      const highlight = L.circleMarker(focus, { radius: 13, color: '#f9df71', weight: 3,
        fill: false, interactive: false }).addTo(map)
      highlight.bindTooltip('所选样例案件位置', { permanent: true, direction: 'top' })
      return () => { if (map.hasLayer(highlight)) map.removeLayer(highlight) }
    }
  }, [focus])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    layersRef.current.forEach(item => map.removeLayer(item))
    layersRef.current = []
    const bounds = L.latLngBounds([])

    const addLayer = <T extends L.Layer>(item: T): T => {
      item.addTo(map)
      layersRef.current.push(item)
      return item
    }

    if (layer === 'attention' || layer === 'signals') {
      wells.forEach((well, index) => {
        const coordinate: L.LatLngExpression = [well.latitude, well.longitude]
        bounds.extend(coordinate)
        const color = WELL_COLORS[well.attentionLevel]

        if (layer === 'attention' && well.attentionScore > 0) {
          addLayer(L.circle(coordinate, {
            radius: 180 + well.attentionScore * 18,
            color,
            weight: 1,
            opacity: 0.42,
            fillColor: color,
            fillOpacity: Math.min(0.28, 0.07 + well.attentionScore / 500),
            interactive: false,
          }))
        }

        const marker = addLayer(L.circleMarker(coordinate, {
          radius: well.isHighProduction ? 8 : 6,
          color: '#ffffff',
          weight: well.isHighProduction ? 2 : 1,
          fillColor: color,
          fillOpacity: layer === 'signals' ? 0.5 : 0.96,
        }))
        marker.bindPopup(neutralWells ? `
          <div class="db-map-popup"><strong>${escapeHtml(well.name)}</strong>
          <span>登记井点，未在此计算风险或产量等级。</span></div>
        ` : `
          <div class="db-map-popup">
            <strong>${escapeHtml(well.name)}</strong>
            <span>作业区：${escapeHtml(well.region || '待补录')}</span>
            <span>综合关注度：${well.attentionScore}</span>
            <span>近30天痕迹：${well.signalCount} 条</span>
            <span>${well.isHighProduction ? '高产井' : '普通井点'} · 数据来源：辖区井点资产</span>
          </div>
        `)
        marker.bindTooltip(
          neutralWells ? escapeHtml(well.name) : `${escapeHtml(well.name)} · 关注 ${well.attentionScore}`,
          {
            className: 'db-map-leaflet-tooltip',
            direction: 'top',
            permanent: layer === 'attention' && index < 5 && well.attentionScore >= 45,
          },
        )
      })

      signals.forEach(signal => {
        const coordinate: L.LatLngExpression = [signal.latitude, signal.longitude]
        bounds.extend(coordinate)
        const confirmed = signal.reviewStatus === 'confirmed'
        const marker = addLayer(L.circleMarker(coordinate, {
          radius: 5 + Math.min(signal.severity, 5),
          color: confirmed ? '#f5b942' : '#39b9d6',
          weight: 2,
          dashArray: confirmed ? undefined : '4 3',
          fillColor: confirmed ? '#ef5b5b' : '#39b9d6',
          fillOpacity: layer === 'signals' ? 0.9 : 0.58,
        }))
        marker.bindPopup(`
          <div class="db-map-popup">
            <strong>${escapeHtml(signal.relatedAssetName)}</strong>
            <span>痕迹：${escapeHtml(signal.label)}</span>
            <span>明显程度：${signal.severity} 级</span>
            <span>复核状态：${confirmed ? '已确认' : '待复核'}</span>
            <span>数据来源：现场风险迹象事件</span>
          </div>
        `)
      })
    }

    if (layer === 'cases') {
      hotspots.forEach((hotspot, index) => {
        const coordinate = hotspotCoordinate(hotspot)
        if (!coordinate) return
        bounds.extend(coordinate)
        const count = Math.max(1, hotspot.case_count ?? 1)
        const radiusMeters = Math.max(450, (hotspot.radius_km ?? 0.6) * 1000)
        const hotspotLayer = addLayer(L.circle(coordinate, {
          radius: radiusMeters,
          color: '#ff8b62',
          weight: 1,
          opacity: 0.55,
          fillColor: '#ef5b5b',
          fillOpacity: Math.min(0.28, 0.08 + count / 80),
        }))
        hotspotLayer.bindTooltip(`案件热区 ${index + 1} · ${count} 起`, {
          className: 'db-map-leaflet-tooltip',
          direction: 'top',
        })
      })

      chainLines.forEach(line => {
        const from: L.LatLngExpression = [line.fromLatitude, line.fromLongitude]
        const to: L.LatLngExpression = [line.toLatitude, line.toLongitude]
        bounds.extend(from)
        bounds.extend(to)
        const confirmed = line.status === 'confirmed'
        const chainLayer = addLayer(L.polyline([from, to], {
          color: confirmed ? '#ff8b62' : '#39b9d6',
          weight: confirmed ? 3 : 2,
          opacity: confirmed ? 0.9 : 0.72,
          dashArray: confirmed ? undefined : '7 6',
        }))
        chainLayer.bindPopup(`
          <div class="db-map-popup">
            <strong>${confirmed ? '已确认链条' : '待确认链条推断'}</strong>
            <span>${escapeHtml(line.fromLabel)} → ${escapeHtml(line.toLabel)}</span>
            <span>距离：${line.distanceKm.toFixed(1)} km · 时间差：${line.timeDiffDays} 天</span>
            <span>置信度：${Math.round(line.confidence * 100)}%</span>
            <span>数据来源：链条关系接口</span>
          </div>
        `)
      })

      cases.forEach(casePoint => {
        const coordinate: L.LatLngExpression = [casePoint.latitude, casePoint.longitude]
        bounds.extend(coordinate)
        const marker = addLayer(L.circleMarker(coordinate, {
          radius: 6,
          color: '#ffffff',
          weight: 1.5,
          fillColor: casePoint.color,
          fillOpacity: 0.94,
        }))
        marker.bindPopup(`
          <div class="db-map-popup">
            <strong>${escapeHtml(casePoint.caseNumber)}</strong>
            <span>案件标注：${escapeHtml(casePoint.label)}</span>
            <span>坐标：${casePoint.latitude.toFixed(5)}, ${casePoint.longitude.toFixed(5)}</span>
            <span>数据来源：案件经纬度</span>
          </div>
        `)
      })
    }

    boundsRef.current = bounds.isValid() ? bounds : null
    if (shouldFitInitialMap(fittedRef.current, userInteractedRef.current, bounds.isValid())) {
      fittedRef.current = true
      fitMap(map, boundsRef.current)
    }
  }, [cases, chainLines, hotspots, layer, operationalAreaId, signals, wells, neutralWells])

  const visibleCount = layer === 'cases'
    ? cases.length + hotspots.length + chainLines.length
    : layer === 'signals'
      ? signals.length
      : wells.length
  const emptyCopy = layer === 'cases'
    ? ['暂无有效坐标案件', '补录案件经纬度后展示真实点位、热区和链条关系。']
    : layer === 'signals'
      ? ['暂无现场风险痕迹', '录入并复核井点附近车迹、油迹或设施异常后展示。']
      : ['暂无可计算井点', '请导入井号、坐标、作业区和产量指标。']

  return (
    <div className="db-dashboard-map-host">
      <div ref={containerRef} className="db-dashboard-leaflet" aria-label="真实公共地图与业务数据覆盖层" />
      <div className="db-map-native-controls" aria-label="地图控制">
        <button type="button" onClick={() => mapRef.current?.zoomIn()} title="放大"><PlusOutlined /></button>
        <button type="button" onClick={() => mapRef.current?.zoomOut()} title="缩小"><MinusOutlined /></button>
        <button type="button" onClick={() => mapRef.current && fitMap(mapRef.current, boundsRef.current)} title="复位"><AimOutlined /></button>
        <button type="button" onClick={onToggleFullscreen} title={isFullscreen ? '退出全屏' : '全屏'}>
          {isFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
        </button>
      </div>
      <BasemapNotice status={basemapStatus} onRetry={() => retryBasemapRef.current()} />
      {visibleCount === 0 && (
        <div className="db-map-real-empty" role="status">
          <strong>{emptyCopy[0]}</strong>
          <span>{emptyCopy[1]}</span>
        </div>
      )}
    </div>
  )
}
