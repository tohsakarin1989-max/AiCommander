import api from './api'

export interface MapPackageRegistration {
  public_bundle_id: number
  acceptance_scope: string
  routing_available: boolean
  current_changed: boolean
  reused: boolean
}

export interface MapPackageImport {
  id: string
  bundle_id: string
  status: 'receiving' | 'queued' | 'validating' | 'render_validated' | 'failed'
  manifest_hash: string
  total_chunks: number
  received_chunks: number
  missing_chunks: string[]
  error_code: string | null
  publish_ready: false
  registration: MapPackageRegistration | null
  auto_publication?: Record<string, unknown> | null
  progress_basis: string
}

export const mapPackageImportsApi = {
  create: async (manifest: File, signal?: AbortSignal): Promise<MapPackageImport> =>
    (await api.post('/map-package-imports', manifest, { headers: { 'Content-Type': 'application/json' }, signal })).data,
  get: async (id: string, signal?: AbortSignal): Promise<MapPackageImport> =>
    (await api.get(`/map-package-imports/${encodeURIComponent(id)}`, { signal })).data,
  upload: async (id: string, file: File, signal?: AbortSignal): Promise<{ name: string; size_bytes: number; sha256: string }> =>
    (await api.put(`/map-package-imports/${encodeURIComponent(id)}/chunks/${encodeURIComponent(file.name)}`, file,
      { headers: { 'Content-Type': 'application/octet-stream' }, signal })).data,
  submit: async (id: string): Promise<MapPackageImport> =>
    (await api.post(`/map-package-imports/${encodeURIComponent(id)}/submit`)).data,
  register: async (id: string): Promise<MapPackageRegistration> =>
    (await api.post(`/map-package-imports/${encodeURIComponent(id)}/register`)).data,
}
