import api from './api'
import type { CaseImportError, CaseImportOptions } from './cases'

export interface ImportTemplate {
  id: string
  name: string
  operational_area_id: number | null
  settings: CaseImportOptions
}
export interface ImportHeaders {
  import_preset?: 'security_ledger' | null
  header_row?: number
  warnings?: string[]
  headers: string[]
  worksheets: string[]
  worksheet: string | null
  suggested_mapping: Record<string, string>
}

export interface FailedImportRow {
  row: number
  revision: number
  status: 'failed' | 'created'
  error: string | null
  values: Record<string, string | null>
  time_zone: string
}
export interface ImportRowReceipt {
  batch_id: string
  retry_available: boolean
  created_total: number
  rows: FailedImportRow[]
}
export interface ImportCorrectionResult {
  batch_id: string
  created: number
  batch_created_total: number
  rows: FailedImportRow[]
  errors: CaseImportError[]
}
export interface RecentImportBatch {
  batch_id: string; created_at: string; operational_area_id: number | null
  total: number | null; success: number | null; failed: number | null; duplicate: null
  state: 'partial' | 'completed' | 'legacy_receipt'; retry_available: boolean
  worksheet: string | null; time_zone: string | null
}
export const caseImportsApi = {
  batches: async (page = 1, areaId?: number, signal?: AbortSignal): Promise<{ items: RecentImportBatch[]; total: number; page: number; page_size: number }> =>
    (await api.get('/case-imports/batches', { params: { page, page_size: 20, operational_area_id: areaId }, signal })).data,
  templates: async (signal?: AbortSignal): Promise<ImportTemplate[]> =>
    (await api.get('/case-imports/templates', { signal })).data,
  saveTemplate: async (name: string, areaId: number | undefined, settings: CaseImportOptions): Promise<ImportTemplate> =>
    (await api.post('/case-imports/templates', { name, operational_area_id: areaId, settings })).data,
  inspect: async (file: File, areaId: number | undefined, settings: CaseImportOptions): Promise<ImportHeaders> => {
    const data = new FormData()
    data.append('file', file)
    return (await api.post('/case-imports/inspect', data, { headers: { 'Content-Type': 'multipart/form-data' }, params: {
      operational_area_id: areaId, worksheet: settings.worksheet || undefined, header_row: settings.header_row,
      import_preset: settings.import_preset || undefined,
    } })).data
  },
  getRows: async (batchId: string, signal?: AbortSignal): Promise<ImportRowReceipt> =>
    (await api.get(`/case-imports/batches/${encodeURIComponent(batchId)}`, { signal })).data,
  correct: async (batchId: string, row: number, revision: number, changes: Record<string, string>): Promise<ImportCorrectionResult> =>
    (await api.post(`/case-imports/batches/${encodeURIComponent(batchId)}/retry`, {
      rows: [{ row, revision, changes }],
    })).data,
  correctMany: async (batchId: string, rows: Array<{ row: number; revision: number; changes: Record<string, string> }>): Promise<ImportCorrectionResult> =>
    (await api.post(`/case-imports/batches/${encodeURIComponent(batchId)}/retry`, { rows })).data,
}
