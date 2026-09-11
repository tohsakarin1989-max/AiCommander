import type { NewRoadGeometryEvidence, RoadFeature } from './internalRoads'

export interface NewRoadConnectionRow {
  segment: number
  endpoint: 'start' | 'end'
  node: string
}

export function buildNewRoadEvidence(feature: RoadFeature, hash: string, rows: NewRoadConnectionRow[]): NewRoadGeometryEvidence {
  const coordinates = feature.geometry.coordinates
  const count = feature.geometry.type === 'LineString' ? 1
    : feature.geometry.type === 'MultiLineString' && Array.isArray(coordinates) ? coordinates.length : 0
  if (feature.properties.kind !== 'road' || !count || !/^[a-f0-9]{64}$/.test(hash.trim()))
    throw new Error('请核对道路类型，并填写公共道路源文件的 64 位 SHA-256。')
  const seen = new Set<string>()
  const segments = new Set<number>()
  const connections = rows.map(row => {
    const node = String(row.node ?? '').trim()
    if (!Number.isInteger(row.segment) || row.segment < 1 || row.segment > count
      || !['start', 'end'].includes(row.endpoint) || !/^[1-9][0-9]*$/.test(node)
      || !Number.isSafeInteger(Number(node))) throw new Error('请填写有效的分段序号、端点和公共节点编号。')
    const key = `${row.segment}:${row.endpoint}`
    if (seen.has(key)) throw new Error('同一分段的同一端点只能记录一次。')
    seen.add(key); segments.add(row.segment)
    return { component: row.segment - 1, endpoint: row.endpoint, osm_node_id: Number(node) }
  })
  if (segments.size !== count) throw new Error('每个独立分段至少需要一个已核验连接点；不要为断开的路段猜测连接。')
  return { kind: 'new_road', public_source_sha256: hash.trim(), connections }
}
