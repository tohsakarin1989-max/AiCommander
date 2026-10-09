export function changedImportFields(source: Record<string, string | null>, draft: Record<string, string>) {
  return Object.fromEntries(Object.keys(source)
    .filter(key => Object.prototype.hasOwnProperty.call(draft, key) && draft[key] !== (source[key] ?? ''))
    .map(key => [key, draft[key]]))
}

export const importFieldLabels: Record<string, string> = {
  external_record_key: '外部稳定记录键',
  occurred_time: '案发时间', discovered_at: '发现／查获时间', report_time: '报告时间', description: '案情描述',
  occurred_from: '案发区间开始', occurred_to: '案发区间结束', time_precision: '案发时间精度', time_expression: '原始时间描述',
  longitude: '经度', latitude: '纬度', location: '原文地点（角色待核）', case_type: '案件业务类型',
  report_unit: '报告单位', security_team: '保卫队', modus_operandi: '作案手法',
  source_type: '来源类型', source_detail: '来源详情', police_reported: '是否报警',
  case_filed: '是否立案', police_officer: '民警姓名', police_phone: '民警电话',
  oil_type: '油品类型', oil_volume: '涉油量（非回收量）', oil_volume_unit: '涉油量单位', oil_nature: '油品性质', water_cut: '含水率',
  facility_type: '设施类型', facility_owner: '设施归属', vehicle_handling: '车辆处理',
  person_handling: '人员处理', oil_handling: '油品处理', operation_role: '作案环节', current_stage: '当前阶段',
}

const previewLabels: Record<string, string> = {
  row: '源行', ...importFieldLabels,
  source_date_expression: '台账日期原值（角色待核）',
  source_recovery_raw: '回收原油原值（单位未确认）',
  source_collaboration_type: '联动方式原值',
}

// Do not depend on response key order: time roles and quantity units must be visible.
export function importPreviewCells(row: Record<string, unknown>) {
  return Object.entries(previewLabels).filter(([key]) => Object.prototype.hasOwnProperty.call(row, key))
    .map(([key, label]) => ({ key, label, value: row[key] }))
}
import type { FailedImportRow } from '../../services/caseImports'

export function correctionReceiptState(selected: FailedImportRow, rows: FailedImportRow[]) {
  const latest = rows.find(row => row.row === selected.row)
  return { latest, state: !latest ? 'absent' : latest.revision === selected.revision ? 'same' : 'changed' } as const
}

export const importTimeZoneLabel = (value?: string) => value === 'Asia/Shanghai'
  ? '单位业务时间（北京时间 UTC+8）' : value === 'UTC' || !value ? 'UTC 世界协调时（旧版口径，不自动改为北京时间）' : value
