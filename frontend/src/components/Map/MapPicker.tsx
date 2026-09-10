import React, { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { CachedTileLayer } from './CachedTileLayer'
import { resolveMapTileConfig } from './mapTiles'

interface MapPickerProps {
  lat?: number | null
  lng?: number | null
  onChange: (lat: number, lng: number) => void
  height?: number
  operationalAreaId?: number
}

const MapPicker: React.FC<MapPickerProps> = ({
  lat,
  lng,
  onChange,
  height = 200,
  operationalAreaId,
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const markerRef = useRef<L.Marker | null>(null)
  const selectionEnabledRef = useRef(false)
  const onChangeRef = useRef(onChange)
  const [mapStatus, setMapStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading')

  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    selectionEnabledRef.current = false
    setMapStatus('loading')

    const initialCenter: [number, number] =
      lat != null && lng != null ? [lat, lng] : [46.5977, 125.1034]

    const map = L.map(containerRef.current, {
      center: initialCenter,
      zoom: 12,
      zoomControl: true,
    })
    mapRef.current = map

    let disposed = false
    let tileLayer: CachedTileLayer | null = null
    void resolveMapTileConfig(operationalAreaId).then(config => {
      if (disposed) return
      tileLayer = new CachedTileLayer(config.url, config.options)
      tileLayer.addTo(map)
      if (!config.manifestResolved) {
        selectionEnabledRef.current = false
        markerRef.current?.dragging?.disable()
        setMapStatus('unavailable')
        return
      }
      selectionEnabledRef.current = true
      markerRef.current?.dragging?.enable()
      setMapStatus('ready')
      if (lat == null && lng == null && config.bounds) {
        map.fitBounds(config.bounds, { padding: [12, 12] })
      }
    })

    // 若初始值存在，放置标记
    if (lat != null && lng != null) {
      markerRef.current = L.marker([lat, lng], { draggable: false }).addTo(map)
      markerRef.current.on('dragend', (e) => {
        if (!selectionEnabledRef.current) return
        const pos = (e.target as L.Marker).getLatLng()
        onChangeRef.current(
          Math.round(pos.lat * 1000000) / 1000000,
          Math.round(pos.lng * 1000000) / 1000000
        )
      })
    }

    // 点击地图放置/移动标记
    map.on('click', (e: L.LeafletMouseEvent) => {
      if (!selectionEnabledRef.current) return
      const newLat = Math.round(e.latlng.lat * 1000000) / 1000000
      const newLng = Math.round(e.latlng.lng * 1000000) / 1000000

      if (markerRef.current) {
        markerRef.current.setLatLng([newLat, newLng])
      } else {
        markerRef.current = L.marker([newLat, newLng], { draggable: true }).addTo(map)
        markerRef.current.on('dragend', (ev) => {
          if (!selectionEnabledRef.current) return
          const pos = (ev.target as L.Marker).getLatLng()
          onChangeRef.current(
            Math.round(pos.lat * 1000000) / 1000000,
            Math.round(pos.lng * 1000000) / 1000000
          )
        })
      }
      onChangeRef.current(newLat, newLng)
    })

    return () => {
      disposed = true
      selectionEnabledRef.current = false
      if (tileLayer && map.hasLayer(tileLayer)) map.removeLayer(tileLayer)
      try { map.stop() } catch (_) { /* ignore */ }
      map.remove()
      mapRef.current = null
      markerRef.current = null
    }
  }, [operationalAreaId]) // eslint-disable-line react-hooks/exhaustive-deps

  // 外部值变化时同步标记位置
  useEffect(() => {
    const map = mapRef.current
    if (!map || lat == null || lng == null) return
    if (markerRef.current) {
      markerRef.current.setLatLng([lat, lng])
    } else {
      markerRef.current = L.marker([lat, lng], {
        draggable: selectionEnabledRef.current,
      }).addTo(map)
      markerRef.current.on('dragend', (e) => {
        if (!selectionEnabledRef.current) return
        const pos = (e.target as L.Marker).getLatLng()
        onChangeRef.current(
          Math.round(pos.lat * 1000000) / 1000000,
          Math.round(pos.lng * 1000000) / 1000000
        )
      })
    }
    map.setView([lat, lng])
  }, [lat, lng])

  return (
    <div style={{ marginTop: 8 }}>
      <div
        style={{
          fontSize: 12,
          color: '#94a3b8',
          marginBottom: 4,
        }}
      >
        {mapStatus === 'ready'
          ? '点击地图选点，或拖动标记调整位置'
          : mapStatus === 'loading'
            ? '正在加载当前厂区离线地图…'
            : '当前厂区离线地图未配置或不可用，暂不能地图选点；可手工录入经纬度。'}
      </div>
      <div
        ref={containerRef}
        aria-disabled={mapStatus !== 'ready'}
        style={{
          height,
          width: '100%',
          borderRadius: 6,
          overflow: 'hidden',
          border: '1px solid #1e293b',
          opacity: mapStatus === 'unavailable' ? 0.72 : 1,
        }}
      />
    </div>
  )
}

export default MapPicker
