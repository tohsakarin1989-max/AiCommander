import type { FeatureCollection, Geometry } from 'geojson'
import type { RoadFeature } from '../../services/internalRoads'

const position = (value: unknown): value is number[] => Array.isArray(value) && value.length === 2
  && value.every(v => typeof v === 'number' && Number.isFinite(v))
  && Math.abs(value[0]) <= 180 && Math.abs(value[1]) <= 85
const line = (value: unknown) => Array.isArray(value) && value.length >= 2 && value.every(position)

/** 仅转换显示契约，绝不补点、吸附、合并路段或猜测入口。 */
export function roadGeometryCollection(features: RoadFeature[]): FeatureCollection {
  if (features.length > 500) throw new Error('road_display_limit')
  let vertices = 0
  const output = features.map(feature => {
    const geometry = feature.geometry
    const coordinates = geometry?.coordinates
    const valid = geometry?.type === 'Point' ? position(coordinates)
      : geometry?.type === 'LineString' ? line(coordinates)
        : geometry?.type === 'MultiLineString' && Array.isArray(coordinates) && coordinates.length > 0 && coordinates.every(line)
    if (!valid) throw new Error('road_geometry_not_displayable')
    vertices += geometry.type === 'Point' ? 1 : geometry.type === 'LineString'
      ? (coordinates as unknown[]).length : (coordinates as unknown[][]).reduce((sum, segment) => sum + segment.length, 0)
    if (vertices > 50000) throw new Error('road_display_limit')
    return { type: 'Feature' as const, id: feature.id, properties: { ...feature.properties },
      geometry: JSON.parse(JSON.stringify(geometry)) as Geometry }
  })
  return { type: 'FeatureCollection', features: output }
}
