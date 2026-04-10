import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

interface MapPickerProps {
  lat?: number | null
  lng?: number | null
  onChange: (lat: number, lng: number) => void
  height?: number
}

const MapPicker: React.FC<MapPickerProps> = ({
  lat,
  lng,
  onChange,
  height = 200,
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const markerRef = useRef<L.Marker | null>(null)

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const initialCenter: [number, number] =
      lat != null && lng != null ? [lat, lng] : [46.5977, 125.1034]

    const map = L.map(containerRef.current, {
      center: initialCenter,
      zoom: 12,
      zoomControl: true,
    })
    mapRef.current = map

    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      {
        attribution: '© OpenStreetMap © CARTO',
        subdomains: 'abcd',
        maxZoom: 19,
      }
    ).addTo(map)

    // 若初始值存在，放置标记
    if (lat != null && lng != null) {
      markerRef.current = L.marker([lat, lng], { draggable: true }).addTo(map)
      markerRef.current.on('dragend', (e) => {
        const pos = (e.target as L.Marker).getLatLng()
        onChange(
          Math.round(pos.lat * 1000000) / 1000000,
          Math.round(pos.lng * 1000000) / 1000000
        )
      })
    }

    // 点击地图放置/移动标记
    map.on('click', (e: L.LeafletMouseEvent) => {
      const newLat = Math.round(e.latlng.lat * 1000000) / 1000000
      const newLng = Math.round(e.latlng.lng * 1000000) / 1000000

      if (markerRef.current) {
        markerRef.current.setLatLng([newLat, newLng])
      } else {
        markerRef.current = L.marker([newLat, newLng], { draggable: true }).addTo(map)
        markerRef.current.on('dragend', (ev) => {
          const pos = (ev.target as L.Marker).getLatLng()
          onChange(
            Math.round(pos.lat * 1000000) / 1000000,
            Math.round(pos.lng * 1000000) / 1000000
          )
        })
      }
      onChange(newLat, newLng)
    })

    return () => {
      map.remove()
      mapRef.current = null
      markerRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 外部值变化时同步标记位置
  useEffect(() => {
    const map = mapRef.current
    if (!map || lat == null || lng == null) return
    if (markerRef.current) {
      markerRef.current.setLatLng([lat, lng])
    } else {
      markerRef.current = L.marker([lat, lng], { draggable: true }).addTo(map)
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
        点击地图选点，或拖动标记调整位置
      </div>
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
    </div>
  )
}

export default MapPicker
