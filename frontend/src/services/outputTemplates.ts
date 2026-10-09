import api from './api'

export type OutputColumn = { key: string; label: string }
export type OutputConfiguration = { columns: OutputColumn[] } | { sections: string[] }
export type OutputTemplateKind = 'case_ledger' | 'material_sections'
export type OutputTemplate = {
  id: string; name: string; kind: OutputTemplateKind; version: number; operational_area_id: number
  configuration: OutputConfiguration; boundary: string
}
export const outputTemplatesApi = {
  columns: async (signal?: AbortSignal) => (await api.get<OutputColumn[]>('/case-exports/columns', { signal })).data,
  list: async (kind: OutputTemplateKind, signal?: AbortSignal) =>
    (await api.get<OutputTemplate[]>('/case-exports/templates', { params: { kind }, signal })).data,
  save: async (kind: OutputTemplateKind, name: string, configuration: OutputConfiguration, operational_area_id: number) =>
    (await api.post<OutputTemplate>('/case-exports/templates', { kind, name, configuration, operational_area_id })).data,
}
