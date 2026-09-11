import { useEffect, useRef, useState } from 'react'
import { Button, Radio } from 'antd'
import L from 'leaflet'
import type { FeatureCollection } from 'geojson'
import 'leaflet/dist/leaflet.css'
import { mountOfflineBasemap, type BasemapStatus } from '../../components/Map/offlineBasemap'
import { BasemapNotice } from '../../components/Map/BasemapNotice'

export default function CoverageGeometryMap({ baseline, scenario, areaId, snapshotRef }: {
  baseline?: FeatureCollection; scenario?: FeatureCollection; areaId: number; snapshotRef?: string | null
}) {
  const host = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const group = useRef<L.GeoJSON | null>(null)
  const fitted = useRef(false)
  const retry = useRef(() => {})
  const [mode, setMode] = useState<'baseline' | 'scenario'>('baseline')
  const [status, setStatus] = useState<BasemapStatus>('loading')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!host.current) return
    const instance = L.map(host.current, { center: [47, 125], zoom: 10, zoomAnimation: false })
    map.current = instance
    fitted.current = false
    const stop = snapshotRef ? mountOfflineBasemap(instance, { operationalAreaId: areaId, snapshotRef, onStatus: setStatus }) : null
    if (!stop) setStatus('unavailable')
    retry.current = stop?.retry ?? (() => {})
    const observer = new ResizeObserver(() => instance.invalidateSize({ pan: false }))
    observer.observe(host.current)
    return () => { observer.disconnect(); stop?.(); instance.remove(); map.current = null; group.current = null }
  }, [areaId, snapshotRef])
  useEffect(() => {
    const instance = map.current
    if (!instance) return
    group.current?.remove()
    group.current = null
    const collection = mode === 'baseline' ? baseline : scenario
    setFailed(false)
    if (!collection) return
    try {
      const layer = L.geoJSON(collection, {
        style: feature => {
          const kind = feature?.properties?.kind
          return kind === 'registered_boundary' ? { color: '#a4acb9', fillOpacity: 0, weight: 2, dashArray: '6 4' }
            : kind === 'unique_overlap' ? { color: '#ffca63', fillColor: '#ffca63', fillOpacity: .45, weight: 1 }
              : { color: '#45d9c0', fillColor: '#45d9c0', fillOpacity: .25, weight: 1 }
        },
        onEachFeature: (feature, layer) => layer.bindTooltip(feature.properties?.kind === 'registered_boundary'
          ? '登记范围（不是通行边界）' : feature.properties?.kind === 'unique_overlap' ? '重复覆盖区域，已去重' : '已知名义覆盖，不是实际摄像视场'),
      })
      group.current = layer
      layer.addTo(instance)
      if (!fitted.current && layer.getBounds().isValid()) {
        instance.fitBounds(layer.getBounds(), { padding: [20, 20], maxZoom: 16 })
        fitted.current = true
      }
    } catch { group.current?.remove(); group.current = null; setFailed(true) }
  }, [baseline, scenario, mode, areaId, snapshotRef])
  return <div className="sw-coverage-geometry">
    <div className="sw-coverage-road-actions"><Radio.Group value={mode} onChange={event => setMode(event.target.value)} aria-label="覆盖地图方案">
      <Radio.Button value="baseline">基准覆盖</Radio.Button><Radio.Button value="scenario">方案覆盖</Radio.Button>
    </Radio.Group><Button onClick={() => { const bounds = group.current?.getBounds(); if (bounds?.isValid()) map.current?.fitBounds(bounds, { padding: [20, 20], maxZoom: 16 }) }}>复位地图</Button></div>
    <p>虚线：登记边界；青色：覆盖并集；黄色：去重重叠。底图版本：{snapshotRef ?? '未绑定，不使用后来发布的底图代替'}。</p>
    <div style={{ position: 'relative' }}><div ref={host} style={{ height: 360, width: '100%' }} aria-label="名义覆盖地图" />
      <BasemapNotice status={status} onRetry={() => retry.current()} /></div>
    {failed && <p role="alert">成果几何无法展示，未绘制替代范围。</p>}
    {!(mode === 'baseline' ? baseline : scenario) && <p>本方案没有可展示的成果几何。</p>}
  </div>
}
