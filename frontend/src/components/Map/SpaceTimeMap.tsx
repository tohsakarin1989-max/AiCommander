/**
 * 时空研判专用地图
 * - 热力图：案件空间密度
 * - 预测热点圈：编号1-N，颜色按风险等级
 */

import React, { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet.heat'
import { CachedTileLayer } from './CachedTileLayer'
import { escapeHtml } from '../../utils/html'

export interface HeatPoint {
  lat: number
  lng: number
  intensity?: number
}

export interface PredictionHotspot {
  lat: number
  lng: number
  radiusKm: number
  riskLevel: 'high' | 'medium' | 'low'
  index: number
  label: string
}

interface SpaceTimeMapProps {
  heatPoints: HeatPoint[]
  predictionHotspots?: PredictionHotspot[]
  height?: string | number
  center?: [number, number]
}

const RISK_COLORS = {
  high: '#ef4444',
  medium: '#f59e0b',
  low: '#22c55e',
}

const SpaceTimeMap: React.FC<SpaceTimeMapProps> = ({
  heatPoints,
  predictionHotspots = [],
  height = 500,
  center,
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const heatRef = useRef<L.HeatLayer | null>(null)
  const hotspotLayersRef = useRef<L.Layer[]>([])

  // 初始化地图（只运行一次）
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = L.map(containerRef.current, {
      center: center ?? [46.5977, 125.1034],
      zoom: 11,
      zoomControl: true,
    })
    mapRef.current = map

    new CachedTileLayer(
      'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      { subdomains: 'abc', maxZoom: 19, attribution: '© OpenStreetMap contributors' }
    ).addTo(map)

    // 初始化空热力图层
    heatRef.current = L.heatLayer([], {
      radius: 28,
      blur: 20,
      maxZoom: 17,
      max: 1.0,
      gradient: { 0.3: '#22c55e', 0.6: '#f59e0b', 1.0: '#ef4444' },
    }).addTo(map)

    return () => {
      try {
        // 先清空热力图再停止，避免 _redraw 回调在 map 销毁后触发
        if (heatRef.current) {
          heatRef.current.setLatLngs([])
          heatRef.current = null
        }
        map.stop()
      } catch (_) { /* ignore */ }
      map.remove()
      mapRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 热力图点位更新
  useEffect(() => {
    if (!heatRef.current || !mapRef.current) return
    const pts = heatPoints.map(
      (p) => [p.lat, p.lng, p.intensity ?? 1.0] as [number, number, number]
    )
    try { heatRef.current.setLatLngs(pts) } catch (_) { return }

    if (pts.length > 0 && mapRef.current) {
      const bounds = L.latLngBounds(heatPoints.map((p) => [p.lat, p.lng]))
      mapRef.current.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 })
    }
  }, [heatPoints])

  // 预测热点圈更新
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    hotspotLayersRef.current.forEach((l) => map.removeLayer(l))
    hotspotLayersRef.current = []

    predictionHotspots.forEach((h) => {
      const color = RISK_COLORS[h.riskLevel]

      // 半透明范围圈
      const circle = L.circle([h.lat, h.lng], {
        radius: h.radiusKm * 1000,
        color,
        fillColor: color,
        fillOpacity: 0.08,
        weight: 2,
        dashArray: '8 5',
      })
        .addTo(map)
        .bindPopup(`<div style="font-size:12px">${escapeHtml(h.label)}</div>`)

      // 编号标记
      const marker = L.marker([h.lat, h.lng], {
        icon: L.divIcon({
          className: '',
          html: `<div style="background:${color};color:#fff;border-radius:50%;width:26px;height:26px;
            display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;
            border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.5)">${h.index}</div>`,
          iconSize: [26, 26],
          iconAnchor: [13, 13],
        }),
      }).addTo(map)

      hotspotLayersRef.current.push(circle, marker)
    })
  }, [predictionHotspots])

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

export default SpaceTimeMap
