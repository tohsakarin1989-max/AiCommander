/** 生产环境统一使用内网瓦片；浏览器缓存只用于加速。 */
export const MAP_TILE_URL =
  import.meta.env.VITE_MAP_TILE_URL || '/api/maps/tiles/current/{z}/{x}/{y}?blank_missing=true'

export const MAP_TILE_OPTIONS = {
  attribution: '内部离线地图 · 公共数据来源详见地图版本清单',
  minNativeZoom: Number(import.meta.env.VITE_MAP_MIN_NATIVE_ZOOM || 6),
  maxNativeZoom: Number(import.meta.env.VITE_MAP_MAX_NATIVE_ZOOM || 14),
  maxZoom: 19,
}

export interface ResolvedMapTileConfig {
  url: string
  renderer?: 'raster' | 'maplibre'
  styleUrl?: string
  snapshotId?: string
  productionLayerUrl?: string
  bounds?: [[number, number], [number, number]]
  manifestResolved: boolean
  options: typeof MAP_TILE_OPTIONS
}

interface MapManifest {
  schema_version?: unknown
  renderer?: unknown
  style_url?: unknown
  display_max_zoom?: unknown
  snapshot_id?: unknown
  tile_url?: unknown
  production_layer_url?: unknown
  min_zoom?: unknown
  max_zoom?: unknown
  attribution?: unknown
  bounds?: unknown
}

function zoomValue(value: unknown, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isInteger(parsed)) return fallback
  return Math.min(22, Math.max(0, parsed))
}

function withMapQuery(url: string, operationalAreaId?: number): string {
  const [base, fragment] = url.split('#', 2)
  const params: string[] = []
  if (!/[?&]blank_missing=/.test(base)) params.push('blank_missing=true')
  if (operationalAreaId != null && !/[?&]operational_area_id=/.test(base)) {
    params.push(`operational_area_id=${encodeURIComponent(String(operationalAreaId))}`)
  }
  const query = params.length > 0 ? `${base.includes('?') ? '&' : '?'}${params.join('&')}` : ''
  return `${base}${query}${fragment ? `#${fragment}` : ''}`
}

function withAreaQuery(url: string, operationalAreaId?: number): string {
  if (operationalAreaId == null || /[?&]operational_area_id=/.test(url)) return url
  const [base, fragment] = url.split('#', 2)
  const separator = base.includes('?') ? '&' : '?'
  return `${base}${separator}operational_area_id=${encodeURIComponent(String(operationalAreaId))}${fragment ? `#${fragment}` : ''}`
}

function mapBounds(value: unknown): [[number, number], [number, number]] | undefined {
  if (!Array.isArray(value) || value.length !== 4) return undefined
  const [west, south, east, north] = value.map(Number)
  if (![west, south, east, north].every(Number.isFinite)) return undefined
  if (!(west < east && south < north)) return undefined
  if (west < -180 || east > 180 || south < -85.051129 || north > 85.051129) return undefined
  return [[south, west], [north, east]]
}

/**
 * 每次挂载地图先解析 current，再把当前会话固定到不可变快照。
 * 发布/回滚只影响下一次挂载，不会把同一页面的瓦片和生产图层混成两个版本。
 */
export async function resolveMapTileConfig(
  operationalAreaId?: number,
  snapshotRef = 'current',
): Promise<ResolvedMapTileConfig> {
  const suffix = operationalAreaId != null
    ? `?operational_area_id=${encodeURIComponent(String(operationalAreaId))}`
    : ''
  try {
    const encodedSnapshot = encodeURIComponent(snapshotRef)
    const response = await fetch(`/api/maps/${encodedSnapshot}/manifest${suffix}`, {
      cache: 'no-store',
      credentials: 'same-origin',
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const manifest = await response.json() as MapManifest
    if (manifest.schema_version === '2.0' || manifest.renderer === 'maplibre') {
      const id = manifest.snapshot_id
      const bounds = mapBounds(manifest.bounds)
      if (manifest.schema_version !== '2.0' || manifest.renderer !== 'maplibre'
        || typeof id !== 'string' || !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(id)
        || (snapshotRef !== 'current' && snapshotRef !== id)
        || manifest.tile_url !== `/api/maps/tiles/${id}/{z}/{x}/{y}`
        || manifest.style_url !== `/api/maps/${id}/style.json`
        || (manifest.production_layer_url !== undefined && manifest.production_layer_url !== `/api/maps/${id}/layers`)
        || manifest.min_zoom !== 6 || manifest.max_zoom !== 16 || manifest.display_max_zoom !== 19
        || !bounds || !Array.isArray(manifest.bounds) || !manifest.bounds.every(v => typeof v === 'number')) {
        throw new Error('invalid_vector_manifest')
      }
      return {
        renderer: 'maplibre', snapshotId: id,
        url: withAreaQuery(manifest.tile_url, operationalAreaId),
        styleUrl: withAreaQuery(manifest.style_url, operationalAreaId),
        productionLayerUrl: typeof manifest.production_layer_url === 'string'
          ? withAreaQuery(manifest.production_layer_url, operationalAreaId) : undefined,
        bounds, manifestResolved: true,
        options: { ...MAP_TILE_OPTIONS, minNativeZoom: 6, maxNativeZoom: 16, maxZoom: 19 },
      }
    }
    if (typeof manifest.tile_url !== 'string' || !manifest.tile_url.trim()) {
      throw new Error('missing_tile_url')
    }
    let minNativeZoom = zoomValue(manifest.min_zoom, MAP_TILE_OPTIONS.minNativeZoom)
    let maxNativeZoom = zoomValue(manifest.max_zoom, MAP_TILE_OPTIONS.maxNativeZoom)
    if (minNativeZoom > maxNativeZoom) {
      const previousMinimum = minNativeZoom
      minNativeZoom = maxNativeZoom
      maxNativeZoom = previousMinimum
    }
    return {
      url: withMapQuery(manifest.tile_url, operationalAreaId),
      snapshotId: typeof manifest.snapshot_id === 'string' ? manifest.snapshot_id : undefined,
      productionLayerUrl: typeof manifest.production_layer_url === 'string'
        ? withAreaQuery(manifest.production_layer_url, operationalAreaId)
        : undefined,
      bounds: mapBounds(manifest.bounds),
      manifestResolved: true,
      options: {
        ...MAP_TILE_OPTIONS,
        attribution: typeof manifest.attribution === 'string' && manifest.attribution.trim()
          ? manifest.attribution
          : MAP_TILE_OPTIONS.attribution,
        minNativeZoom,
        maxNativeZoom,
        maxZoom: Math.max(MAP_TILE_OPTIONS.maxZoom, maxNativeZoom),
      },
    }
  } catch (error) {
    // A malformed vector contract must not become a raster request or switch versions.
    if (error instanceof Error && error.message === 'invalid_vector_manifest') throw error
    const fallbackUrl = snapshotRef === 'current'
      ? MAP_TILE_URL
      : `/api/maps/tiles/${encodeURIComponent(snapshotRef)}/{z}/{x}/{y}`
    return {
      url: withMapQuery(fallbackUrl, operationalAreaId),
      manifestResolved: false,
      options: MAP_TILE_OPTIONS,
    }
  }
}

/** 只有显式快照 URL 才能跨会话持久缓存；current 必须每次解析最新发布版本。 */
export function isImmutableOfflineTileUrl(url: string): boolean {
  const match = url.match(/\/api\/maps\/tiles\/([^/?#]+)\//)
  return Boolean(match && match[1] !== 'current')
}
