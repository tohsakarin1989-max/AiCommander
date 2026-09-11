import React, { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import 'leaflet/dist/leaflet.css'
import type { CaseMarker, ChainLinkLine, ChainPosition, SerialGroup } from '../../types'
import { mountOfflineBasemap, type BasemapStatus } from './offlineBasemap'
import { BasemapNotice } from './BasemapNotice'
import markerIcon2xUrl from 'leaflet/dist/images/marker-icon-2x.png'
import markerIconUrl from 'leaflet/dist/images/marker-icon.png'
import markerShadowUrl from 'leaflet/dist/images/marker-shadow.png'
import { escapeHtml } from '../../utils/html'
import { hypothesisRegionColor, hypothesisSupportLabel, parseCircleHypothesisRegion } from './caseHypothesisMap'

// 修复 Leaflet 默认图标路径问题（Vite 打包时 marker 图标会丢失）
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2xUrl,
  iconUrl: markerIconUrl,
  shadowUrl: markerShadowUrl,
})

interface LeafletMapProps {
  markers?: CaseMarker[]
  serialGroups?: SerialGroup[]
  chainLinks?: ChainLinkLine[]
  chainSearchRadiusKm?: number
  height?: number | string
  center?: [number, number]
  zoom?: number
  onMarkerClick?: (marker: CaseMarker) => void
  operationalAreaId?: number
  snapshotRef?: string
  referencePath?: Array<[number, number]>
  referenceRoadSegments?: Array<Array<[number, number]>>
  productionAssetIds?: number[]
  hypothesisRegions?: Array<{
    id: string
    hypothesis_type: string
    title: string
    claim: string
    confidence?: number
    ruleSupport?: number
    region?: Record<string, unknown> | null
    supporting_evidence: string[]
    counter_evidence: string[]
    information_gaps: string[]
  }>
}

const RISK_COLORS: Record<string, string> = {
  high: '#ef4444',
  medium: '#f59e0b',
  low: '#22c55e',
  default: '#7dd3fc',
}

const CHAIN_COLORS: Record<ChainPosition, string> = {
  upstream: '#ef4444',
  midstream: '#f59e0b',
  downstream: '#3b82f6',
  unknown: '#94a3b8',
}

const PRODUCTION_COLORS: Record<string, string> = {
  well: '#ef4444',
  station: '#f97316',
  valve: '#f59e0b',
  storage: '#d97706',
  road: '#38bdf8',
  access_road: '#7dd3fc',
  path: '#a7f3d0',
  village: '#22c55e',
  residential: '#84cc16',
  camera: '#a78bfa',
  lighting: '#facc15',
  alarm: '#fb7185',
  checkpoint: '#60a5fa',
}

function productionColor(properties: Record<string, unknown> | null | undefined): string {
  const assetType = typeof properties?.asset_type === 'string' ? properties.asset_type : ''
  return PRODUCTION_COLORS[assetType] ?? '#94a3b8'
}

function productionPopup(properties: Record<string, unknown> | null | undefined): string {
  const name = typeof properties?.name === 'string' ? properties.name : '未命名生产要素'
  const assetType = typeof properties?.asset_type === 'string' ? properties.asset_type : '未知'
  const source = typeof properties?.source === 'string' ? properties.source : '未知'
  const verification = properties?.verified === true ? '已核验' : '待核验'
  return `<div style="font-size:12px;line-height:1.7;min-width:180px">
    <div style="font-weight:700">${escapeHtml(name)}</div>
    <div>类型：${escapeHtml(assetType)}</div>
    <div>来源：${escapeHtml(source)}</div>
    <div>状态：${verification}</div>
    <div style="color:#64748b">研判版本冻结生产图层</div>
  </div>`
}

function validFeatureCollection(payload: unknown): payload is FeatureCollection {
  if (!payload || typeof payload !== 'object') return false
  const value = payload as { type?: unknown; features?: unknown }
  return value.type === 'FeatureCollection' && Array.isArray(value.features)
}

function markerHtml(position: ChainPosition | undefined, color: string, size: number): string {
  const common = `width:${size}px;height:${size}px;background:${color};border:2px solid #fff;box-shadow:0 0 8px ${color},0 2px 4px rgba(0,0,0,0.42)`
  if (position === 'upstream') {
    return `<div style="${common};clip-path:polygon(25% 4%,75% 4%,100% 50%,75% 96%,25% 96%,0 50%)"></div>`
  }
  if (position === 'midstream') {
    return `<div style="${common};transform:rotate(45deg);border-radius:2px"></div>`
  }
  if (position === 'downstream') {
    return `<div style="${common};border-radius:2px"></div>`
  }
  return `<div style="${common};border-radius:50%"></div>`
}

function makeCaseIcon(marker: CaseMarker): L.DivIcon {
  const size = 18
  const color = marker.chainPosition ? CHAIN_COLORS[marker.chainPosition] : RISK_COLORS[marker.riskLevel || 'default']
  return L.divIcon({
    className: '',
    html: markerHtml(marker.chainPosition, color, size),
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

const LeafletMap: React.FC<LeafletMapProps> = ({
  markers = [],
  serialGroups = [],
  chainLinks = [],
  chainSearchRadiusKm = 20,
  height = 500,
  center,
  zoom = 11,
  onMarkerClick,
  operationalAreaId,
  snapshotRef = 'current',
  referencePath,
  referenceRoadSegments,
  productionAssetIds = [],
  hypothesisRegions = [],
}) => {
  const mapRef = useRef<L.Map | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const layersRef = useRef<L.Layer[]>([])
  const highlightLayersRef = useRef<L.Layer[]>([])
  const [productionLayerStatus, setProductionLayerStatus] = useState<string | null>(null)
  const [basemapStatus, setBasemapStatus] = useState<BasemapStatus>('loading')
  const retryBasemapRef = useRef<() => void>(() => {})
  const productionAssetKey = productionAssetIds
    .filter(id => Number.isSafeInteger(id) && id > 0)
    .slice(0, 50)
    .sort((left, right) => left - right)
    .join(',')

  const defaultCenter: [number, number] = (() => {
    if (center) return center
    if (markers.length === 0) return [46.5977, 125.1034] // 大庆市中心
    const avgLat = markers.reduce((s, m) => s + m.lat, 0) / markers.length
    const avgLng = markers.reduce((s, m) => s + m.lng, 0) / markers.length
    return [avgLat, avgLng]
  })()

  // 初始化地图（只运行一次）
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = L.map(containerRef.current, {
      center: defaultCenter,
      zoom,
      zoomControl: true,
      zoomAnimation: false,
    })
    mapRef.current = map

    let disposed = false
    let productionLayer: L.GeoJSON | null = null
    const controller = new AbortController()
    setProductionLayerStatus(productionAssetKey ? '正在加载研判版本生产图层…' : null)
    const stopBasemap = mountOfflineBasemap(map, {
      operationalAreaId, snapshotRef, onStatus: setBasemapStatus,
      onConfig: config => { void (async () => {
      if (!center && markers.length === 0 && config.bounds) {
        map.fitBounds(config.bounds, { padding: [24, 24] })
      }
      if (!productionAssetKey) return
      if (!config.productionLayerUrl) throw new Error('missing_production_layer_url')
      const separator = config.productionLayerUrl.includes('?') ? '&' : '?'
      const productionLayerUrl = `${config.productionLayerUrl}${separator}asset_ids=${encodeURIComponent(productionAssetKey)}&limit=50`
      const response = await fetch(productionLayerUrl, {
        cache: 'no-store',
        credentials: 'same-origin',
        signal: controller.signal,
      })
      if (!response.ok) throw new Error(`production_layer_http_${response.status}`)
      const payload: unknown = await response.json()
      if (!validFeatureCollection(payload)) throw new Error('invalid_production_layer')
      if (disposed) return
      productionLayer = L.geoJSON(payload, {
        pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
          radius: 5,
          color: productionColor(feature.properties),
          fillColor: productionColor(feature.properties),
          fillOpacity: 0.78,
          weight: 1.5,
        }),
        style: (feature?: Feature<Geometry, Record<string, unknown>>) => ({
          color: productionColor(feature?.properties),
          fillColor: productionColor(feature?.properties),
          fillOpacity: 0.1,
          opacity: 0.72,
          weight: 2,
        }),
        onEachFeature: (feature, layer) => {
          layer.bindPopup(productionPopup(feature.properties), { maxWidth: 260 })
        },
      }).addTo(map)
      setProductionLayerStatus(
        payload.features.length > 0
          ? `已加载 ${payload.features.length} 个研判证据设施`
          : '当前候选未关联可展示的生产设施',
      )
    })().catch(error => {
      if (!disposed && !(error instanceof DOMException && error.name === 'AbortError')) {
        console.warn('冻结生产图层加载失败', error)
        setProductionLayerStatus('冻结生产图层暂不可用，候选范围仍可查看')
      }
    }) },
    })
    retryBasemapRef.current = stopBasemap.retry

    return () => {
      disposed = true
      controller.abort()
      stopBasemap()
      retryBasemapRef.current = () => {}
      if (productionLayer && map.hasLayer(productionLayer)) map.removeLayer(productionLayer)
      // 先停止所有动画，再销毁，避免 Leaflet zoom 动画竞态报错
      try { map.stop() } catch (_) { /* ignore */ }
      map.remove()
      mapRef.current = null
    }
  }, [operationalAreaId, snapshotRef, productionAssetKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // 当 markers / serialGroups / chainLinks 变化时，更新图层
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    // 清除旧图层
    layersRef.current.forEach((l) => map.removeLayer(l))
    layersRef.current = []
    highlightLayersRef.current.forEach((l) => map.removeLayer(l))
    highlightLayersRef.current = []

    const clearHighlight = () => {
      highlightLayersRef.current.forEach((l) => map.removeLayer(l))
      highlightLayersRef.current = []
    }

    const addSearchRadius = (link: ChainLinkLine) => {
      clearHighlight()
      const color = link.status === 'confirmed' ? '#22c55e' : '#f59e0b'
      const circles = [
        L.circle([link.from.lat, link.from.lng], {
          radius: chainSearchRadiusKm * 1000,
          color,
          weight: 1,
          opacity: 0.45,
          fillOpacity: 0.03,
          dashArray: '6 6',
        }).addTo(map),
        L.circle([link.to.lat, link.to.lng], {
          radius: chainSearchRadiusKm * 1000,
          color,
          weight: 1,
          opacity: 0.28,
          fillOpacity: 0.02,
          dashArray: '6 6',
        }).addTo(map),
      ]
      highlightLayersRef.current.push(...circles)
    }

    const mappedHypotheses = hypothesisRegions.flatMap(item => {
      const region = parseCircleHypothesisRegion(item.region)
      return region ? [{ item, region }] : []
    })

    mappedHypotheses.forEach(({ item, region }) => {
      const color = hypothesisRegionColor(item.hypothesis_type)
      const circle = L.circle([region.latitude, region.longitude], {
        radius: region.radiusM,
        color,
        weight: 2,
        opacity: 0.9,
        fillColor: color,
        fillOpacity: 0.16,
        dashArray: item.hypothesis_type === 'activity_area' ? '7 5' : undefined,
      }).addTo(map)
      const supporting = item.supporting_evidence[0] || '暂无'
      const counter = item.counter_evidence[0] || item.information_gaps[0] || '仍需现场核查'
      circle.bindPopup(
        `<div style="font-size:12px;line-height:1.7;min-width:240px">
          <div style="font-weight:700;color:${color}">${escapeHtml(item.title)}</div>
          <div>${escapeHtml(item.claim)}</div>
          <div>${escapeHtml(hypothesisSupportLabel(item))}</div>
          <div>支持：${escapeHtml(supporting)}</div>
          <div>反向/缺口：${escapeHtml(counter)}</div>
          <div style="color:#94a3b8">区域半径约 ${Math.round(region.radiusM)} 米，仅供人工核查</div>
        </div>`,
        { maxWidth: 320 },
      )
      layersRef.current.push(circle)
      const caseMarker = markers[0]
      if (caseMarker) {
        const line = L.polyline(
          [[caseMarker.lat, caseMarker.lng], [region.latitude, region.longitude]],
          { color, weight: 1.5, opacity: 0.7, dashArray: '6 5' },
        ).addTo(map)
        layersRef.current.push(line)
      }
    })

    // 绘制链条推断连线
    chainLinks.forEach((link) => {
      const color = link.status === 'confirmed' ? '#22c55e' : '#f59e0b'
      const line = L.polyline(
        [[link.from.lat, link.from.lng], [link.to.lat, link.to.lng]],
        {
          color,
          weight: link.status === 'confirmed' ? 3 : 2,
          dashArray: link.status === 'confirmed' ? undefined : '7 5',
          opacity: link.status === 'confirmed' ? 0.92 : 0.72,
        }
      ).addTo(map)
      line.bindPopup(
        `<div style="font-size:12px;line-height:1.8;min-width:220px">
          <div style="font-weight:700;margin-bottom:4px">${link.status === 'confirmed' ? '已确认链条' : '疑似链条推断'}</div>
          <div>${escapeHtml(link.from.caseNumber)} → ${escapeHtml(link.to.caseNumber)}</div>
          <div>距离：${link.distanceKm.toFixed(1)} km · 时间差：${link.timeDiffDays} 天</div>
          <div>置信度：${Math.round(link.confidence * 100)}%</div>
          ${link.reasoning ? `<div>${escapeHtml(link.reasoning)}</div>` : ''}
        </div>`,
        { maxWidth: 280 }
      )
      line.on('click', () => addSearchRadius(link))
      layersRef.current.push(line)

      if (link.status === 'confirmed') {
        const midLat = (link.from.lat + link.to.lat) / 2
        const midLng = (link.from.lng + link.to.lng) / 2
        const arrow = L.marker([midLat, midLng], {
          icon: L.divIcon({
            className: '',
            html: `<div style="color:${color};font-size:18px;font-weight:700;text-shadow:0 1px 3px rgba(0,0,0,.5)">→</div>`,
            iconSize: [18, 18],
            iconAnchor: [9, 9],
          }),
          interactive: false,
        }).addTo(map)
        layersRef.current.push(arrow)
      }
    })

    // 绘制串案连线
    serialGroups.forEach((group) => {
      const groupMarkers = markers.filter((m) => group.caseIds.includes(m.id))
      if (groupMarkers.length < 2) return
      const latlngs = groupMarkers.map((m): [number, number] => [m.lat, m.lng])
      const line = L.polyline(latlngs, {
        color: group.color || '#a78bfa',
        weight: 2,
        dashArray: '6 4',
        opacity: 0.8,
      }).addTo(map)
      layersRef.current.push(line)
    })

    // 绘制案件标记
    markers.forEach((marker) => {
      const icon = makeCaseIcon(marker)
      const m = L.marker([marker.lat, marker.lng], { icon })
        .addTo(map)
        .bindPopup(
          `<div style="font-size:12px;line-height:1.8;min-width:180px">
            <div style="font-weight:700;margin-bottom:4px">${escapeHtml(marker.caseNumber)}</div>
            <div>类型：${escapeHtml(marker.caseType || '未知')}</div>
            ${marker.chainPosition ? `<div>链条：${marker.chainPosition === 'upstream' ? '盗采环节' : marker.chainPosition === 'midstream' ? '运输环节' : marker.chainPosition === 'downstream' ? '囤储环节' : '未分类'}</div>` : ''}
            <div>时间：${escapeHtml(marker.occurredTime ? marker.occurredTime.slice(0, 10) : '未知')}</div>
            ${marker.modus ? `<div>手法：${escapeHtml(marker.modus)}</div>` : ''}
          </div>`,
          { maxWidth: 240 }
        )

      if (onMarkerClick) {
        m.on('click', () => onMarkerClick(marker))
      }
      layersRef.current.push(m)
    })

    // 有 markers 时自动调整视野
    if (markers.length > 0 || mappedHypotheses.length > 0) {
      const points: Array<[number, number]> = [
        ...markers.map((marker): [number, number] => [marker.lat, marker.lng]),
        ...mappedHypotheses.map(({ region }): [number, number] => [region.latitude, region.longitude]),
      ]
      const bounds = L.latLngBounds(points)
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 })
    }
  }, [markers, serialGroups, chainLinks, chainSearchRadiusKm, onMarkerClick, operationalAreaId, hypothesisRegions])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !referencePath || referencePath.length < 2) return
    const line = L.polyline(referencePath, { color: '#38bdf8', weight: 4, opacity: .9 }).addTo(map)
    line.bindTooltip('已知路网参考路径，不是实际行驶轨迹')
    map.fitBounds(line.getBounds(), { padding: [30, 30], maxZoom: 15 })
    return () => { if (map.hasLayer(line)) map.removeLayer(line) }
  }, [referencePath, operationalAreaId, snapshotRef])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !referenceRoadSegments?.length) return
    // A multi-polyline preserves disconnected branches; never join them or fill an area.
    const lines = L.polyline(referenceRoadSegments, {
      renderer: L.canvas(), color: PRODUCTION_COLORS.road, weight: 4, opacity: .9,
    }).addTo(map)
    lines.bindTooltip('预算内道路段参考；未显示不代表不可达')
    map.fitBounds(lines.getBounds(), { padding: [30, 30], maxZoom: 15 })
    return () => { if (map.hasLayer(lines)) map.removeLayer(lines) }
  }, [referenceRoadSegments, operationalAreaId, snapshotRef])

  return (
    <div
      style={{
        position: 'relative',
        height,
        width: '100%',
        borderRadius: 6,
        overflow: 'hidden',
        border: '1px solid #1e293b',
      }}
    >
      <div ref={containerRef} style={{ height: '100%', width: '100%' }} />
      <BasemapNotice status={basemapStatus} onRetry={() => retryBasemapRef.current()} />
      {productionLayerStatus && (
        <div style={{
          position: 'absolute',
          left: 10,
          bottom: 10,
          zIndex: 500,
          maxWidth: 'calc(100% - 20px)',
          padding: '5px 8px',
          background: 'rgba(15, 23, 42, 0.86)',
          border: '1px solid rgba(148, 163, 184, 0.35)',
          color: '#e2e8f0',
          fontSize: 11,
          lineHeight: 1.4,
        }}>
          {productionLayerStatus}
        </div>
      )}
    </div>
  )
}

export default LeafletMap
