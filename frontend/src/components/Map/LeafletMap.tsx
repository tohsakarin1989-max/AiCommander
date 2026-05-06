import React, { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { CaseMarker, SerialGroup } from '../../types'
import { CachedTileLayer } from './CachedTileLayer'

// 修复 Leaflet 默认图标路径问题（Vite 打包时 marker 图标会丢失）
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
})

interface LeafletMapProps {
  markers?: CaseMarker[]
  serialGroups?: SerialGroup[]
  height?: number | string
  center?: [number, number]
  zoom?: number
  onMarkerClick?: (marker: CaseMarker) => void
}

const RISK_COLORS: Record<string, string> = {
  high: '#ef4444',
  medium: '#f59e0b',
  low: '#22c55e',
  default: '#7dd3fc',
}

function makeCircleIcon(color: string): L.DivIcon {
  const size = 18
  return L.divIcon({
    className: '',
    html: `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 0 8px ${color},0 2px 4px rgba(0,0,0,0.4)"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

const LeafletMap: React.FC<LeafletMapProps> = ({
  markers = [],
  serialGroups = [],
  height = 500,
  center,
  zoom = 11,
  onMarkerClick,
}) => {
  const mapRef = useRef<L.Map | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const layersRef = useRef<L.Layer[]>([])

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
    })
    mapRef.current = map

    // OpenStreetMap 底图（国内可访问）
    new CachedTileLayer(
      'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        subdomains: 'abc',
        maxZoom: 19,
      }
    ).addTo(map)

    return () => {
      // 先停止所有动画，再销毁，避免 Leaflet zoom 动画竞态报错
      try { map.stop() } catch (_) { /* ignore */ }
      map.remove()
      mapRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 当 markers / serialGroups 变化时，更新图层
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    // 清除旧图层
    layersRef.current.forEach((l) => map.removeLayer(l))
    layersRef.current = []

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
      const color = RISK_COLORS[marker.riskLevel || 'default']
      const icon = makeCircleIcon(color)
      const m = L.marker([marker.lat, marker.lng], { icon })
        .addTo(map)
        .bindPopup(
          `<div style="font-size:12px;line-height:1.8;min-width:180px">
            <div style="font-weight:700;margin-bottom:4px">${marker.caseNumber}</div>
            <div>类型：${marker.caseType || '未知'}</div>
            <div>时间：${marker.occurredTime ? marker.occurredTime.slice(0, 10) : '未知'}</div>
            ${marker.modus ? `<div>手法：${marker.modus}</div>` : ''}
          </div>`,
          { maxWidth: 240 }
        )

      if (onMarkerClick) {
        m.on('click', () => onMarkerClick(marker))
      }
      layersRef.current.push(m)
    })

    // 有 markers 时自动调整视野
    if (markers.length > 0) {
      const bounds = L.latLngBounds(markers.map((m) => [m.lat, m.lng]))
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 })
    }
  }, [markers, serialGroups, onMarkerClick])

  return (
    <div
      ref={containerRef}
      style={{
        height,
        width: '100%',
        borderRadius: 6,
        overflow: 'hidden',
        border: '1px solid #1e293b',
      }}
    />
  )
}

export default LeafletMap
