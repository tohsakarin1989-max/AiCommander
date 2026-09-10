import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { mountOfflineBasemap, type BasemapStatus } from '../../components/Map/offlineBasemap'
import { BasemapNotice } from '../../components/Map/BasemapNotice'
import type { JurisdictionAsset } from '../../services'
import { escapeHtml } from '../../utils/html'

interface JurisdictionAssetMapProps {
  assets: JurisdictionAsset[]
  selectedAssetId?: number | null
  height?: number | string
  onAssetClick?: (asset: JurisdictionAsset) => void
  readOnly?: boolean
  operationalAreaId?: number
  snapshotId?: string
}

const TYPE_COLORS: Record<string, string> = {
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
  patrol_point: '#14b8a6',
}

function colorFor(type?: string | null): string {
  return type ? TYPE_COLORS[type] ?? '#94a3b8' : '#94a3b8'
}

function makeAssetIcon(color: string, selected: boolean): L.DivIcon {
  const size = selected ? 22 : 16
  return L.divIcon({
    className: '',
    html: `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:2px solid ${selected ? '#fef3c7' : '#fff'};box-shadow:0 0 ${selected ? 16 : 8}px ${color},0 2px 6px rgba(0,0,0,0.45)"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

function isPair(value: unknown): value is [number, number] {
  return Array.isArray(value)
    && value.length >= 2
    && typeof value[0] === 'number'
    && typeof value[1] === 'number'
}

function lineCoordinates(asset: JurisdictionAsset): [number, number][] {
  const geometry = asset.geometry as { type?: string; coordinates?: unknown } | null | undefined
  if (!geometry?.coordinates) return []
  if (geometry.type === 'LineString' && Array.isArray(geometry.coordinates)) {
    return geometry.coordinates
      .filter(isPair)
      .map(([lng, lat]) => [lat, lng])
  }
  return []
}

function polygonCoordinates(asset: JurisdictionAsset): [number, number][] {
  const geometry = asset.geometry as { type?: string; coordinates?: unknown } | null | undefined
  if (geometry?.type !== 'Polygon' || !Array.isArray(geometry.coordinates)) return []
  const firstRing = geometry.coordinates[0]
  if (!Array.isArray(firstRing)) return []
  return firstRing
    .filter(isPair)
    .map(([lng, lat]) => [lat, lng])
}

function pointCoordinate(asset: JurisdictionAsset): [number, number] | null {
  if (asset.latitude == null || asset.longitude == null) return null
  return [asset.latitude, asset.longitude]
}

function popupHtml(asset: JurisdictionAsset, readOnly: boolean): string {
  return `
    <div style="font-size:12px;line-height:1.7;min-width:180px">
      <div style="font-weight:700;margin-bottom:4px">${escapeHtml(asset.name)}</div>
      <div>类型：${escapeHtml(asset.asset_type)}</div>
      <div>来源：${escapeHtml(asset.source || '未知')}</div>
      <div>风险：${asset.risk_level ?? 1} 级</div>
      <div>状态：${escapeHtml(asset.status || 'active')}</div>
      <div style="color:#64748b;margin-top:4px">${readOnly ? '已发布离线快照，仅供查看' : '点击图层可编辑'}</div>
    </div>
  `
}

export default function JurisdictionAssetMap({
  assets,
  selectedAssetId,
  height = 460,
  onAssetClick,
  readOnly = false,
  operationalAreaId,
  snapshotId,
}: JurisdictionAssetMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layersRef = useRef<L.Layer[]>([])
  const [basemapStatus, setBasemapStatus] = useState<BasemapStatus>('loading')
  const retryBasemapRef = useRef<() => void>(() => {})

  const defaultCenter = useMemo<[number, number]>(() => {
    const points = assets.map(pointCoordinate).filter((item): item is [number, number] => Boolean(item))
    if (points.length === 0) return [46.5977, 125.1034]
    return [
      points.reduce((sum, item) => sum + item[0], 0) / points.length,
      points.reduce((sum, item) => sum + item[1], 0) / points.length,
    ]
  }, [assets])

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = L.map(containerRef.current, {
      center: defaultCenter,
      zoom: 12,
      zoomControl: true,
      zoomAnimation: false,
    })
    mapRef.current = map
    const stopBasemap = mountOfflineBasemap(map, {
      operationalAreaId, snapshotRef: snapshotId, onStatus: setBasemapStatus,
      onConfig: config => {
        if (assets.length === 0 && config.bounds) {
          map.fitBounds(config.bounds, { padding: [24, 24] })
        }
      },
    })

    retryBasemapRef.current = stopBasemap.retry
    return () => {
      stopBasemap()
      retryBasemapRef.current = () => {}
      try { map.stop() } catch (_) { /* ignore */ }
      map.remove()
      mapRef.current = null
    }
  }, [operationalAreaId, snapshotId]) // defaultCenter is applied when this area-specific map mounts

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    layersRef.current.forEach(layer => map.removeLayer(layer))
    layersRef.current = []
    const bounds = L.latLngBounds([])

    assets.forEach(asset => {
      const color = colorFor(asset.asset_type)
      const selected = asset.id === selectedAssetId
      const lines = lineCoordinates(asset)
      const polygon = polygonCoordinates(asset)
      const point = pointCoordinate(asset)
      let layer: L.Layer | null = null

      if (lines.length >= 2) {
        lines.forEach(coord => bounds.extend(coord))
        layer = L.polyline(lines, {
          color,
          weight: selected ? 5 : 3,
          opacity: selected ? 1 : 0.82,
        })
      } else if (polygon.length >= 3) {
        polygon.forEach(coord => bounds.extend(coord))
        layer = L.polygon(polygon, {
          color,
          fillColor: color,
          weight: selected ? 4 : 2,
          fillOpacity: selected ? 0.22 : 0.12,
        })
      } else if (point) {
        bounds.extend(point)
        layer = L.marker(point, { icon: makeAssetIcon(color, selected) })
      }

      if (!layer) return
      layer.addTo(map).bindPopup(popupHtml(asset, readOnly), { maxWidth: 260 })
      layer.on('click', () => onAssetClick?.(asset))
      layersRef.current.push(layer)
    })

    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [36, 36], maxZoom: 15 })
    }
  }, [assets, operationalAreaId, readOnly, selectedAssetId, snapshotId, onAssetClick])

  return (
    <div style={{ position: 'relative', height }}>
    <div
      ref={containerRef}
      className="jurisdiction-map"
      style={{ height }}
    />
    <BasemapNotice status={basemapStatus} onRetry={() => retryBasemapRef.current()} />
    </div>
  )
}
