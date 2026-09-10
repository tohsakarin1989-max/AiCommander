import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { mountOfflineBasemap, type BasemapStatus } from '../../components/Map/offlineBasemap'
import { BasemapNotice } from '../../components/Map/BasemapNotice'

interface Point { name: string; latitude: number | null; longitude: number | null }
interface Props { casePoint: Point; facilities: Point[] }

/** Public display only. No production layer, cases or facility API is queried. */
export default function ShowcaseMap({ casePoint, facilities }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const retry = useRef<() => void>(() => {})
  const [status, setStatus] = useState<BasemapStatus>('loading')
  const [version, setVersion] = useState('待加载')
  useEffect(() => {
    if (!container.current) return
    const map = L.map(container.current, { center: [46.6, 125.1], zoom: 12,
      zoomAnimation: false, preferCanvas: false })
    const points = [casePoint, ...facilities]
    for (const [index, point] of points.entries()) {
      if (point.latitude == null || point.longitude == null ||
          !Number.isFinite(point.latitude) || !Number.isFinite(point.longitude)) continue
      const label = document.createElement('span')
      label.textContent = point.name
      L.circleMarker([point.latitude, point.longitude], { radius: index === 0 ? 8 : 6,
        color: index === 0 ? '#ff9866' : '#68bdd6', fillOpacity: .8 }).bindTooltip(label).addTo(map)
    }
    const stop = mountOfflineBasemap(map, { onStatus: setStatus,
      onConfig: config => setVersion(config.snapshotId || '历史栅格地图') })
    retry.current = stop.retry
    const resize = new ResizeObserver(() => map.invalidateSize({ pan: false }))
    resize.observe(container.current)
    return () => { resize.disconnect(); stop(); retry.current = () => {}; map.stop(); map.remove() }
  }, [casePoint, facilities])

  return <section className="showcase-section" aria-label="展示公共底图">
    <h3>公共离线底图 / 合成点位</h3>
    <p>橙色为合成案件，蓝色为合成设施，均不是真实业务点位。底图版本：{version}</p>
    <div className="showcase-map-host"><div ref={container} className="showcase-map" />
      <strong className="showcase-map-watermark">合成点位 · 非真实案件与井位</strong>
      <BasemapNotice status={status} onRetry={() => retry.current()} />
    </div>
    <p>底图来自当前授权的内网地图服务；不加载生产图层。该底图仅供展示，不参与本次合成评分，也不是道路通行证明。</p>
  </section>
}
