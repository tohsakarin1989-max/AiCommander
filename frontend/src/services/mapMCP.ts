import api from './api'

export interface LocationInfo {
  latitude: number
  longitude: number
  address?: string
  province?: string
  city?: string
  district?: string
  street?: string
}

export interface POI {
  name: string
  type: string
  address: string
  location: string
  distance: number
  tel?: string
}

export interface MapMCPAnalysis {
  location_info: {
    success: boolean
    location: LocationInfo
  }
  nearby_pois: {
    success: boolean
    pois: POI[]
    count: number
  }
  weather_info: {
    success: boolean
    weather: any
  }
  ai_analysis: any
}

export const mapMCPApi = {
  getLocationInfo: async (latitude: number, longitude: number): Promise<any> => {
    const response = await api.post('/map-mcp/location-info', {
      latitude,
      longitude,
    })
    return response.data
  },

  searchNearbyPOIs: async (
    latitude: number,
    longitude: number,
    keywords = '加油站|油库|管线|设施',
    radius = 1000
  ): Promise<any> => {
    const response = await api.post('/map-mcp/nearby-pois', {
      latitude,
      longitude,
      keywords,
      radius,
    })
    return response.data
  },

  getWeather: async (city: string): Promise<any> => {
    const response = await api.get(`/map-mcp/weather/${city}`)
    return response.data
  },

  analyzeCaseLocation: async (caseId: number): Promise<MapMCPAnalysis> => {
    const response = await api.post(`/map-mcp/analyze-case-location/${caseId}`)
    return response.data
  },

  getComprehensiveAnalysis: async (caseId: number): Promise<any> => {
    const response = await api.post(`/map-mcp/comprehensive-analysis/${caseId}`)
    return response.data
  },
}

