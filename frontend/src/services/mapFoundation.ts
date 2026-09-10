import api from './api'
import type { JurisdictionAsset } from './jurisdiction'

export interface OperationalArea {
  id: number
  code: string
  name: string
  boundary?: Record<string, unknown> | null
  is_default: boolean
  status: string
}

export interface MapSource {
  id: number
  source_key: string
  name: string
  source_type: 'ledger' | 'manual' | 'internal_gis' | 'public_map'
  trust_rank: number
  status: string
  description?: string | null
  operational_area: OperationalArea
}

export interface MapImportTemplate {
  id: number
  source_id: number
  name: string
  sheet_name?: string | null
  header_row: number
  field_mapping: Record<string, string>
  coordinate_system: string
  axis_order: 'lon_lat' | 'lat_lon'
  coordinate_unit: 'degree' | 'meter'
  version: number
  is_active: boolean
}

export interface MapPreview {
  source_id: number
  template_id?: number | null
  publishable: boolean
  total_rows: number
  valid_rows: number
  quarantined_rows: number
  errors: Array<{ row: number; code: string; message: string }>
  sample: Array<Record<string, unknown>>
}

export interface MapIngestRun {
  id: string
  source_id: number
  template_id: number
  status: string
  filename: string
  source_revision: string
  file_hash: string
  total_rows: number
  valid_rows: number
  quarantined_rows: number
  created_assets: number
  updated_assets: number
  errors: Array<{ row: number; code: string; message: string }>
  idempotent_replay: boolean
}

export interface MapConflict {
  id: number
  run_id: string
  source_id: number
  row_number: number
  source_record_id?: string | null
  source_revision: string
  status: string
  error_code?: string | null
  error_message?: string | null
  asset_id?: number | null
}

export interface MapSourceCreate {
  source_key: string
  name: string
  source_type: MapSource['source_type']
  trust_rank?: number
  operational_area_id?: number
  description?: string
}

export interface PublicMapBundle {
  id: number
  bundle_id: string
  provider: string
  source_version: string
  license: string
  bounds: number[]
  sha256: string
  status: string
  imported_at: string
  idempotent_replay: boolean
}

export interface MapSnapshot {
  id: string
  version: string
  operational_area_id: number
  public_bundle_id: number
  status: 'ready' | 'current' | 'superseded'
  manifest: Record<string, unknown>
  feature_watermark: string
  built_at: string
  published_at?: string | null
  idempotent_replay: boolean
}

export interface MapSnapshotFeature {
  type: 'Feature'
  id: number
  geometry?: Record<string, unknown> | null
  properties: {
    snapshot_feature_id: number
    asset_id: number
    asset_version_id?: number | null
    name: string
    asset_type: string
    source?: string | null
    status?: string | null
    verified?: boolean | null
    verification_state?: string | null
    address?: string | null
    description?: string | null
    risk_level?: number | null
    confidence_score?: number | null
    tags?: string[] | null
    attributes?: Record<string, unknown> | null
  }
}

export interface MapSnapshotLayers {
  type: 'FeatureCollection'
  snapshot_id: string
  snapshot_version: string
  truncated: boolean
  features: MapSnapshotFeature[]
}

export function snapshotLayersToAssets(layers: MapSnapshotLayers): JurisdictionAsset[] {
  return layers.features.map(feature => {
    const properties = feature.properties
    const geometry = feature.geometry ?? null
    const coordinates = geometry?.type === 'Point' && Array.isArray(geometry.coordinates)
      ? geometry.coordinates
      : null
    const longitude = coordinates && typeof coordinates[0] === 'number' ? coordinates[0] : null
    const latitude = coordinates && typeof coordinates[1] === 'number' ? coordinates[1] : null
    return {
      id: properties.asset_id,
      name: properties.name,
      asset_type: properties.asset_type,
      geometry_type: typeof geometry?.type === 'string' ? geometry.type : 'point',
      latitude,
      longitude,
      geometry,
      address: properties.address,
      description: properties.description,
      source: properties.source,
      status: properties.status,
      risk_level: properties.risk_level,
      confidence_score: properties.confidence_score,
      verified: properties.verified,
      tags: properties.tags,
      attributes: properties.attributes,
    }
  })
}

export interface MapTemplateCreate {
  source_id: number
  name: string
  sheet_name?: string
  header_row: number
  field_mapping: Record<string, string>
  coordinate_system: string
  axis_order: 'lon_lat' | 'lat_lon'
  coordinate_unit: 'degree' | 'meter'
}

function fileBody(file: File): FormData {
  const formData = new FormData()
  formData.append('file', file)
  return formData
}

export const mapFoundationApi = {
  listAreas: async (): Promise<OperationalArea[]> => {
    const response = await api.get<OperationalArea[]>('/operational-areas')
    return response.data
  },

  createArea: async (payload: {
    code: string
    name: string
    boundary?: number[] | Record<string, unknown> | null
    is_default?: boolean
  }): Promise<OperationalArea> => {
    const response = await api.post<OperationalArea>('/operational-areas', payload)
    return response.data
  },

  updateArea: async (
    areaId: number,
    payload: Partial<Pick<OperationalArea, 'name' | 'boundary' | 'is_default' | 'status'>>,
  ): Promise<OperationalArea> => {
    const response = await api.put<OperationalArea>(`/operational-areas/${areaId}`, payload)
    return response.data
  },

  listSources: async (): Promise<MapSource[]> => {
    const response = await api.get<MapSource[]>('/map-sources')
    return response.data
  },

  createSource: async (payload: MapSourceCreate): Promise<MapSource> => {
    const response = await api.post<MapSource>('/map-sources', payload)
    return response.data
  },

  listTemplates: async (sourceId?: number): Promise<MapImportTemplate[]> => {
    const response = await api.get<MapImportTemplate[]>('/map-import-templates', {
      params: sourceId ? { source_id: sourceId } : undefined,
    })
    return response.data
  },

  createTemplate: async (payload: MapTemplateCreate): Promise<MapImportTemplate> => {
    const response = await api.post<MapImportTemplate>('/map-import-templates', payload)
    return response.data
  },

  preview: async (sourceId: number, file: File, templateId?: number): Promise<MapPreview> => {
    const response = await api.post<MapPreview>(
      `/map-sources/${sourceId}/preview`,
      fileBody(file),
      {
        params: templateId ? { template_id: templateId } : undefined,
        headers: { 'Content-Type': 'multipart/form-data' },
      },
    )
    return response.data
  },

  ingest: async (
    sourceId: number,
    templateId: number,
    file: File,
    sourceRevision?: string,
  ): Promise<MapIngestRun> => {
    const response = await api.post<MapIngestRun>(
      `/map-sources/${sourceId}/ingest`,
      fileBody(file),
      {
        params: { template_id: templateId, source_revision: sourceRevision || undefined },
        headers: { 'Content-Type': 'multipart/form-data' },
      },
    )
    return response.data
  },

  listConflicts: async (): Promise<MapConflict[]> => {
    const response = await api.get<MapConflict[]>('/map-conflicts')
    return response.data
  },

  resolveConflict: async (id: number, decision: 'reject' | 'retry', note?: string): Promise<MapConflict> => {
    const response = await api.post<MapConflict>(`/map-conflicts/${id}/resolve`, { decision, note })
    return response.data
  },

  importOfflineBundle: async (file: File): Promise<PublicMapBundle> => {
    const response = await api.post<PublicMapBundle>('/map-bundles/import', fileBody(file), {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  },

  listOfflineBundles: async (): Promise<PublicMapBundle[]> => {
    const response = await api.get<PublicMapBundle[]>('/map-bundles')
    return response.data
  },

  buildSnapshot: async (operationalAreaId: number, publicBundleId: number): Promise<MapSnapshot> => {
    const response = await api.post<MapSnapshot>('/map-snapshots/build', {
      operational_area_id: operationalAreaId,
      public_bundle_id: publicBundleId,
    })
    return response.data
  },

  listSnapshots: async (operationalAreaId?: number): Promise<MapSnapshot[]> => {
    const response = await api.get<MapSnapshot[]>('/map-snapshots', {
      params: operationalAreaId ? { operational_area_id: operationalAreaId } : undefined,
    })
    return response.data
  },

  publishSnapshot: async (snapshotId: string): Promise<MapSnapshot> => {
    const response = await api.post<MapSnapshot>(`/map-snapshots/${snapshotId}/publish`)
    return response.data
  },

  rollbackSnapshot: async (snapshotId: string): Promise<MapSnapshot> => {
    const response = await api.post<MapSnapshot>(`/map-snapshots/${snapshotId}/rollback`)
    return response.data
  },

  getCurrentLayers: async (operationalAreaId?: number): Promise<MapSnapshotLayers> => {
    const response = await api.get<MapSnapshotLayers>('/maps/current/layers', {
      params: operationalAreaId ? { operational_area_id: operationalAreaId } : undefined,
    })
    return response.data
  },
}
