import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { RoadFeature } from '../../services/internalRoads'
import { mountOfflineBasemap, type BasemapStatus } from '../../components/Map/offlineBasemap'
import { BasemapNotice } from '../../components/Map/BasemapNotice'
import { roadGeometryCollection } from './roadGeometry'

export default function RoadGeometryMap({ features, area, selectedId, onSelect }: {
  features: RoadFeature[]; area: number; selectedId?: string; onSelect: (feature: RoadFeature) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map>()
  const overlay = useRef<L.GeoJSON>()
  const select = useRef(onSelect)
  select.current = onSelect
  const retry = useRef(() => {})
  const [status, setStatus] = useState<BasemapStatus>('loading')
  const [error, setError] = useState('')
  useEffect(() => {
    if (!container.current) return
    const instance = L.map(container.current, { center: [46.6, 125], zoom: 12, zoomAnimation: false })
    map.current = instance
    const stop = mountOfflineBasemap(instance, { operationalAreaId: area, onStatus: setStatus })
    retry.current = stop.retry
    try {
      const collection = roadGeometryCollection(features)
      const layer = L.geoJSON(collection, {
        style: { color: '#38bdf8', weight: 3 },
        pointToLayer: (_feature, point) => L.circleMarker(point, { radius: 7, color: '#f59e0b', fillOpacity: 0.8 }),
        onEachFeature: (item, shape) => {
          const label = document.createElement('span')
          label.textContent = `${item.properties?.name ?? ''} · ${String(item.id)}（来源图形，连接待核）`
          shape.bindTooltip(label)
          shape.on('click', () => {
            const feature = features.find(candidate => candidate.id === item.id)
            if (feature) select.current(feature)
          })
        },
      }).addTo(instance)
      overlay.current = layer
      if (layer.getBounds().isValid()) instance.fitBounds(layer.getBounds(), { padding: [30, 70], maxZoom: 16 })
    } catch { setError('图形不能安全显示，请检查完整坐标；原始资料仍可查看。当前显示范围限纬度 ±85°。') }
    const observer = new ResizeObserver(() => instance.invalidateSize())
    observer.observe(container.current)
    return () => { observer.disconnect(); stop(); instance.remove(); map.current = undefined; overlay.current = undefined }
  }, [features, area])
  useEffect(() => {
    overlay.current?.setStyle(feature => ({ color: feature?.id === selectedId ? '#f59e0b' : '#38bdf8',
      weight: feature?.id === selectedId ? 6 : 3 }))
  }, [selectedId, features])
  return <section aria-label="道路来源图形核对">
    <p>蓝线：来源道路；圆点：入口；加粗橙色：当前选中。相交不代表连通，断开的路段不自动连接。</p>
    {error && <p role="alert">{error}</p>}
    <div style={{ position: 'relative' }}>
      <div ref={container} style={{ height: 360, width: '100%' }} />
      <BasemapNotice status={status} onRetry={() => retry.current()} />
    </div>
  </section>
}
