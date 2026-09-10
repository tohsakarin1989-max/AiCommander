import api from './api'
import type { CaseImportError, CaseImportOptions } from './cases'

export interface ImportTemplate {
  id: string
  name: string
  operational_area_id: number | null
  settings: CaseImportOptions
}
export interface ImportHeaders {
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
export const caseImportsApi = {
  templates: async (signal?: AbortSignal): Promise<ImportTemplate[]> =>
    (await api.get('/case-imports/templates', { signal })).data,
  saveTemplate: async (name: string, areaId: number | undefined, settings: CaseImportOptions): Promise<ImportTemplate> =>
    (await api.post('/case-imports/templates', { name, operational_area_id: areaId, settings })).data,
  inspect: async (file: File, areaId: number | undefined, settings: CaseImportOptions): Promise<ImportHeaders> => {
    const data = new FormData()
    data.append('file', file)
    return (await api.post('/case-imports/inspect', data, { headers: { 'Content-Type': 'multipart/form-data' }, params: {
      operational_area_id: areaId, worksheet: settings.worksheet || undefined, header_row: settings.header_row,
    } })).data
  },
  getRows: async (batchId: string, signal?: AbortSignal): Promise<ImportRowReceipt> =>
    (await api.get(`/case-imports/batches/${encodeURIComponent(batchId)}`, { signal })).data,
  correct: async (batchId: string, row: number, revision: number, changes: Record<string, string>): Promise<ImportCorrectionResult> =>
    (await api.post(`/case-imports/batches/${encodeURIComponent(batchId)}/retry`, {
      rows: [{ row, revision, changes }],
    })).data,
}
