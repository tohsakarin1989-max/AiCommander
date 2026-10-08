import type { MapRowClassification, MapLedgerPreview, MapRetryRequest } from '../../services/mapLedgerImports'
import { formatStoredTime } from '../../utils/caseValues'
export const mapRowLabels: Record<MapRowClassification, string> = {
  new: '新增', updated: '更新', unchanged: '未变', identity_pending: '身份待对应', conflict: '冲突', failed: '失败',
}
export const groupLabels: Record<string, string> = { geometry: '坐标组', water_cut: '含水率组', production: '产量组', details: '其他基础资料组' }
export const valueStateLabels: Record<string, string> = { set: '明确赋值', not_provided: '未提供', unknown: '明确未知', clear: '明确清空', withdraw: '撤销来源声明' }
export const groupReasonLabels: Record<string, string> = {
  same_source_update: '同一来源更新', source_priority: '按来源优先级采用', same_values: '值与口径未变',
  manual_group_decision: '已有人工明确决定，需核对', unresolved_equal_priority: '同级来源冲突尚未解决',
  lower_priority: '不能覆盖更高优先级来源', equal_priority: '同级来源不一致，待明确采用',
  withdraw_other_source_forbidden: '不能撤销其他来源声明', unit_or_basis_changed_requires_confirmation: '单位、周期或测量口径变化，需明确确认',
  incomplete_coupled_group: '字段组不完整，不自动拼接旧值', manual_selection: '按明确理由人工采用',
}
export function displayMapValue(value: unknown): string {
  if (value == null || value === '') return '未提供'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
}
export function mapPreviewCanCommit(preview: MapLedgerPreview | null): boolean {
  return !!preview?.plan_token && preview.publishable && !preview.drift.length
}
export function prepareMapRetry(claimId: number, values: Record<string, unknown>, templateId?: number): MapRetryRequest {
  return { request_id: crypto.randomUUID(), template_id: templateId, rows: [{ claim_id: claimId, values: JSON.parse(JSON.stringify(values)) }] }
}
export function mapImportError(error: unknown): { code?: string; message: string } {
  const detail = (error as { detail?: { detail?: { code?: string; message?: string } } } | null)?.detail?.detail
  return { code: detail?.code, message: detail?.message || (error instanceof Error ? error.message : '操作未完成') }
}
export function downloadMapFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob), link = document.createElement('a')
  link.href = url; link.download = filename.replace(/[\\/\u0000-\u001f]/g, '_') || '生产台账原件'
  link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function mapReceivedTime(value?: string | null): string {
  if (!value) return '接收时间未记录'
  if (!/(Z|[+-]\d{2}:\d{2})$/i.test(value)) return `${value}（历史记录未标明时区）`
  return `${formatStoredTime(value)}（北京时间）`
}
