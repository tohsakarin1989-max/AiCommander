import type { MapRowClassification, MapLedgerPreview, MapRetryRequest, MapLedgerClaim, MapLedgerRun } from '../../services/mapLedgerImports'
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

// Only template / representation failures belong in the shared correction flow.
// Identity, source conflicts, boundary violations and business facts stay individual.
const batchErrorCodes = new Set(['coordinate_system_required', 'unsupported_coordinate_system',
  'coordinate_unit_mismatch', 'transformation_required', 'template_drift', 'field_declaration_drift',
  'missing_name', 'missing_asset_type', 'invalid_coordinate', 'invalid_water_cut_range',
  'invalid_water_cut_unit', 'invalid_production_output', 'invalid_production_time', 'invalid_high_production'])
export function mapBatchError(claim: MapLedgerClaim): { key: string; field: string; message: string } | null {
  const errors = claim.plan?.errors || []
  if (claim.retry_superseded !== false || claim.plan?.classification !== 'failed'
    || !['quarantined', 'awaiting_reingest'].includes(claim.status) || !claim.raw_payload
    || errors.length !== 1 || !batchErrorCodes.has(errors[0].code)
    || claim.plan.groups.some(group => group.status === 'conflict')) return null
  const error = errors[0]
  return { key: JSON.stringify([claim.run_id, error.field, error.code, error.message]), field: error.field, message: error.message }
}
export type MapBatchChange = { kind: 'template' } | { kind: 'numeric_format'; column: string }
export function mapBatchNumericColumns(run: MapLedgerRun, claim: MapLedgerClaim): string[] {
  const keys: Record<string, string[]> = { invalid_coordinate: ['longitude', 'latitude'],
    invalid_water_cut_range: ['water_cut_min', 'water_cut_max'], invalid_production_output: ['production_output'] }
  const fields = keys[claim.plan?.errors?.[0]?.code || ''] || []
  const mapping = run.template_snapshot?.field_mapping || {}
  return [...new Set(fields.map(key => mapping[key]).filter(column => column && Object.prototype.hasOwnProperty.call(claim.raw_payload || {}, column)))]
}
export function normalizeMapNumericFormat(value: unknown): unknown {
  if (typeof value !== 'string') return value
  const normalized = value.trim().replace(/[０-９＋－．]/g, character => String.fromCharCode(character.charCodeAt(0) - 0xfee0))
  // No inferred units, comma removal, decimal shifting or conversion of blanks.
  return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(normalized) ? normalized : value
}
export function prepareMapBatchRetry(run: MapLedgerRun, claims: MapLedgerClaim[], change: MapBatchChange, templateId?: number): MapRetryRequest {
  if (!claims.length || claims.length > 200 || new Set(claims.map(row => row.id)).size !== claims.length) {
    throw new Error('一次请选择 1 至 200 条不重复的同因异常行')
  }
  const cause = mapBatchError(claims[0])
  if (!cause || claims.some(row => row.run_id !== run.id || mapBatchError(row)?.key !== cause.key)) {
    throw new Error('只能处理同批次、同字段和同一错误的未修订失败行；身份与事实冲突请逐项核对')
  }
  if (change.kind === 'template' && (!templateId || templateId === run.template_id)) {
    throw new Error('请先保存并选中明确修正后的新模板，再选择同因异常行')
  }
  if (change.kind === 'numeric_format' && claims.some(row => !mapBatchNumericColumns(run, row).includes(change.column))) {
    throw new Error('格式整理只能用于原模板明确映射的异常数字列')
  }
  const rows = claims.map(claim => {
    const values = JSON.parse(JSON.stringify(claim.raw_payload)) as Record<string, unknown>
    if (change.kind === 'numeric_format') values[change.column] = normalizeMapNumericFormat(values[change.column])
    return { claim_id: claim.id, values }
  })
  if (change.kind === 'numeric_format' && rows.every((row, index) => row.values[change.column] === claims[index].raw_payload![change.column])) {
    throw new Error('所选列没有可整理的数字格式；缺失值、单位和业务数值仍需逐行核对')
  }
  return { request_id: crypto.randomUUID(), template_id: change.kind === 'template' ? templateId : run.template_id, rows }
}

export function mapBatchPreviewCanCommit(preview: MapLedgerPreview | null, claims: MapLedgerClaim[]): boolean {
  return mapPreviewCanCommit(preview) && preview!.rows_complete !== false
    && preview!.total_rows === claims.length && preview!.rows.length === claims.length
    && new Set(preview!.rows.map(row => row.row_number)).size === claims.length
    && claims.every(claim => preview!.rows.some(row => row.row_number === claim.row_number))
    && preview!.rows.every(row => ['new', 'updated', 'unchanged'].includes(row.classification))
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
