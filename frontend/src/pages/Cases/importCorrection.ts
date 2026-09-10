export function changedImportFields(source: Record<string, string | null>, draft: Record<string, string>) {
  return Object.fromEntries(Object.keys(source)
    .filter(key => Object.prototype.hasOwnProperty.call(draft, key) && draft[key] !== (source[key] ?? ''))
    .map(key => [key, draft[key]]))
}

export const importFieldLabels: Record<string, string> = {
  occurred_time: '案发时间', report_time: '报告时间', description: '案情描述',
  longitude: '经度', latitude: '纬度', location: '案发地点', case_type: '案件类型',
  report_unit: '报告单位', security_team: '保卫队', modus_operandi: '作案手法',
  source_type: '来源类型', source_detail: '来源详情', police_reported: '是否报警',
  case_filed: '是否立案', police_officer: '民警姓名', police_phone: '民警电话',
  oil_type: '油品类型', oil_volume: '涉油量', oil_nature: '油品性质', water_cut: '含水率',
  facility_type: '设施类型', facility_owner: '设施归属', vehicle_handling: '车辆处理',
  person_handling: '人员处理', oil_handling: '油品处理', operation_role: '作案环节', current_stage: '当前阶段',
}
