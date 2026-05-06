import { useMemo } from 'react'
import type { Case, MapConfig } from '../../../types'

export interface MapUrlOptions {
  lat: number
  lng: number
  allCases?: Case[]
}

/**
 * 根据地图配置生成地图 URL
 * 支持 OpenStreetMap、Mapbox、高德、百度等地图服务
 */
export function useMapUrl(mapConfig: MapConfig | undefined) {
  const generateMapUrl = useMemo(() => {
    return (options: MapUrlOptions): string => {
      const { lat, lng, allCases } = options
      const provider = mapConfig?.provider || 'openstreetmap'
      const apiKey = mapConfig?.api_key || ''

      if (provider === 'openstreetmap') {
        return generateOpenStreetMapUrl(lat, lng, allCases)
      } else if (provider === 'mapbox' && apiKey) {
        return generateMapboxUrl(lat, lng, apiKey, allCases)
      } else if (provider === 'amap' && apiKey) {
        return generateAmapUrl(lat, lng, apiKey, allCases)
      } else if (provider === 'baidu' && apiKey) {
        return generateBaiduMapUrl(lat, lng, apiKey, allCases)
      } else {
        // 默认使用 OpenStreetMap
        return generateOpenStreetMapUrl(lat, lng, allCases)
      }
    }
  }, [mapConfig])

  return { generateMapUrl }
}

function generateOpenStreetMapUrl(lat: number, lng: number, allCases?: Case[]): string {
  if (allCases && allCases.length > 0) {
    const lats = allCases.map((c) => c.latitude!)
    const lngs = allCases.map((c) => c.longitude!)
    const minLat = Math.min(...lats)
    const maxLat = Math.max(...lats)
    const minLng = Math.min(...lngs)
    const maxLng = Math.max(...lngs)
    const centerLat = (minLat + maxLat) / 2
    const centerLng = (minLng + maxLng) / 2

    return `https://www.openstreetmap.org/export/embed.html?bbox=${minLng - 0.01}%2C${
      minLat - 0.01
    }%2C${maxLng + 0.01}%2C${maxLat + 0.01}&layer=mapnik&marker=${centerLat}%2C${centerLng}`
  } else {
    return `https://www.openstreetmap.org/export/embed.html?bbox=${lng - 0.01}%2C${
      lat - 0.01
    }%2C${lng + 0.01}%2C${lat + 0.01}&layer=mapnik&marker=${lat}%2C${lng}`
  }
}

function generateMapboxUrl(
  lat: number,
  lng: number,
  apiKey: string,
  allCases?: Case[]
): string {
  if (allCases && allCases.length > 0) {
    const lats = allCases.map((c) => c.latitude!)
    const lngs = allCases.map((c) => c.longitude!)
    const centerLat = lats.reduce((a, b) => a + b, 0) / lats.length
    const centerLng = lngs.reduce((a, b) => a + b, 0) / lngs.length
    const markers = allCases
      .map((c) => `pin-s+ff0000(${c.longitude},${c.latitude})`)
      .join(',')
    return `https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/${markers}/${centerLng},${centerLat},11/800x600?access_token=${apiKey}`
  } else {
    return `https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/pin-s+ff0000(${lng},${lat})/${lng},${lat},14/800x600?access_token=${apiKey}`
  }
}

function generateAmapUrl(
  lat: number,
  lng: number,
  apiKey: string,
  allCases?: Case[]
): string {
  if (allCases && allCases.length > 0) {
    const centerLat =
      allCases.reduce((sum, c) => sum + (c.latitude || 0), 0) / allCases.length
    const centerLng =
      allCases.reduce((sum, c) => sum + (c.longitude || 0), 0) / allCases.length
    const markers = allCases.map((c) => `${c.longitude},${c.latitude}`).join(';')
    return `https://webapi.amap.com/maps?v=1.4.15&key=${apiKey}&center=${centerLng},${centerLat}&markers=${markers}&zoom=12`
  } else {
    return `https://webapi.amap.com/maps?v=1.4.15&key=${apiKey}&center=${lng},${lat}&markers=${lng},${lat}&zoom=14`
  }
}

function generateBaiduMapUrl(
  lat: number,
  lng: number,
  apiKey: string,
  allCases?: Case[]
): string {
  if (allCases && allCases.length > 0) {
    const centerLat =
      allCases.reduce((sum, c) => sum + (c.latitude || 0), 0) / allCases.length
    const centerLng =
      allCases.reduce((sum, c) => sum + (c.longitude || 0), 0) / allCases.length
    const markers = allCases
      .map((c, i) => `${c.longitude},${c.latitude}|${i + 1}`)
      .join(';')
    return `https://api.map.baidu.com/staticimage/v2?ak=${apiKey}&center=${centerLng},${centerLat}&width=800&height=600&zoom=12&markers=${markers}`
  } else {
    return `https://api.map.baidu.com/staticimage/v2?ak=${apiKey}&center=${lng},${lat}&width=800&height=600&zoom=14&markers=${lng},${lat}`
  }
}

/**
 * 检查地图配置是否需要 API Key
 */
export function needsApiKey(provider: string): boolean {
  return ['mapbox', 'amap', 'baidu'].includes(provider)
}

/**
 * 获取地图提供商显示名称
 */
export function getProviderDisplayName(provider: string): string {
  const names: Record<string, string> = {
    openstreetmap: 'OpenStreetMap',
    mapbox: 'Mapbox',
    amap: '高德地图',
    baidu: '百度地图',
  }
  return names[provider] || provider.toUpperCase()
}
