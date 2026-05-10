import React, { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { CaseMarker, ChainLinkLine, ChainPosition, SerialGroup } from '../../types'
import { CachedTileLayer } from './CachedTileLayer'
import { escapeHtml } from '../../utils/html'

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
  chainLinks?: ChainLinkLine[]
  chainSearchRadiusKm?: number
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

const CHAIN_COLORS: Record<ChainPosition, string> = {
  upstream: '#ef4444',
  midstream: '#f59e0b',
  downstream: '#3b82f6',
  unknown: '#94a3b8',
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
}) => {
  const mapRef = useRef<L.Map | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const layersRef = useRef<L.Layer[]>([])
  const highlightLayersRef = useRef<L.Layer[]>([])

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
    if (markers.length > 0) {
      const bounds = L.latLngBounds(markers.map((m) => [m.lat, m.lng]))
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 })
    }
  }, [markers, serialGroups, chainLinks, chainSearchRadiusKm, onMarkerClick])

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
