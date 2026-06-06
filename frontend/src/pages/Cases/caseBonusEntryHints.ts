export interface CaseBonusEntryHint {
  key: 'vehicle_category' | 'person_disposition' | 'oil_measurement' | 'police_case'
  label: string
  detail: string
  action: string
  blocking: boolean
}

export interface CaseBonusEntryValues {
  bonus_has_vehicle?: boolean
  bonus_has_person?: boolean
  bonus_has_oil?: boolean
  bonus_has_police?: boolean
  description?: unknown
  vehicle_handling?: unknown
  person_handling?: unknown
  vehicle_info?: unknown
  involved_persons?: unknown
  oil_nature?: unknown
  oil_volume?: unknown
  water_cut?: unknown
  oil_handling?: unknown
  police_reported?: unknown
  case_filed?: unknown
  police_officer?: unknown
  police_phone?: unknown
  initial_vehicles?: Array<Record<string, unknown>>
  initial_persons?: Array<Record<string, unknown>>
}

function textOf(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function hasText(value: unknown): boolean {
  return textOf(value).trim().length > 0
}

function rowHasAnyValue(row?: Record<string, unknown>): boolean {
  return Boolean(row && Object.values(row).some(hasText))
}

function containsAny(text: string, keywords: string[]): boolean {
  return keywords.some(keyword => text.includes(keyword))
}

function hasVehicleSignal(values: CaseBonusEntryValues, text: string): boolean {
  const rows = values.initial_vehicles || []
  return rows.some(rowHasAnyValue)
    || hasText(values.vehicle_info)
    || hasText(values.vehicle_handling)
    || containsAny(text, ['车辆', '车牌', '查扣车', '扣押车', '罐车', '皮卡', '面包车', '机动车', '摩托', '电动车', '一车', '1车'])
}

function hasVehicleCategory(values: CaseBonusEntryValues, text: string): boolean {
  const rows = values.initial_vehicles || []
  if (rows.some(row => hasText(row?.vehicle_type))) return true
  return containsAny(text, [
    '摩托车',
    '电动车',
    '5吨以下',
    '五吨以下',
    '5吨以上',
    '五吨以上',
    '重型挂车',
    '半挂',
    '机动船',
    '3吨以下',
    '三吨以下',
    '3吨以上',
    '三吨以上',
  ])
}

function hasPersonSignal(values: CaseBonusEntryValues, text: string): boolean {
  const rows = values.initial_persons || []
  return rows.some(rowHasAnyValue)
    || hasText(values.involved_persons)
    || hasText(values.person_handling)
    || containsAny(text, ['抓获', '人员', '嫌疑人', '司机', '一人', '1人'])
}

function hasPersonDisposition(values: CaseBonusEntryValues, text: string): boolean {
  const rows = values.initial_persons || []
  if (rows.some(row => hasText(row?.handling_status))) return true
  if (hasText(values.person_handling)) return true
  return containsAny(text, ['刑事拘留', '刑拘', '行政拘留', '治安拘留', '行政处罚', '治安处罚', '教育放行', '待核查'])
}

function missingOilFields(values: CaseBonusEntryValues): string[] {
  const missing: string[] = []
  if (!hasText(values.oil_nature)) missing.push('原油性质')
  if (!hasText(values.oil_volume)) missing.push('涉油数量')
  if (!hasText(values.water_cut)) missing.push('检斤含水率')
  if (!hasText(values.oil_handling)) missing.push('原油处理方式')
  return missing
}

function missingPoliceFields(values: CaseBonusEntryValues): string[] {
  const missing: string[] = []
  if (!values.police_reported && !values.case_filed) missing.push('报案/立案状态')
  if (!hasText(values.police_officer)) missing.push('公安出警人')
  if (!hasText(values.police_phone)) missing.push('公安联系电话')
  return missing
}

export function buildBonusEntryHints(values: CaseBonusEntryValues): CaseBonusEntryHint[] {
  const text = [
    values.description,
    values.vehicle_handling,
    values.person_handling,
    values.vehicle_info,
    values.involved_persons,
  ].map(textOf).join(' ')
  const hints: CaseBonusEntryHint[] = []

  if (values.bonus_has_vehicle && hasVehicleSignal(values, text) && !hasVehicleCategory(values, text)) {
    hints.push({
      key: 'vehicle_category',
      label: '车辆考核类别',
      detail: '已出现车辆线索，但未明确摩托车、5吨以下、5吨以上等车辆考核类别。',
      action: '可在涉案车辆中选择车辆考核类别；不填写可以保存案件，但整案奖金暂不测算。',
      blocking: true,
    })
  }

  if (values.bonus_has_person && hasPersonSignal(values, text) && !hasPersonDisposition(values, text)) {
    hints.push({
      key: 'person_disposition',
      label: '人员处理类型',
      detail: '已出现抓获/涉案人员线索，但未明确行政拘留、刑事拘留等处理结果。',
      action: '可在抓获/涉案人员中选择人员处理类型；不填写可以保存案件，但整案奖金暂不测算。',
      blocking: true,
    })
  }

  if (values.bonus_has_oil) {
    const missing = missingOilFields(values)
    if (missing.length > 0) {
      hints.push({
        key: 'oil_measurement',
        label: '涉油检斤处置',
        detail: `已启用涉油检斤处置条目，但仍缺少${missing.join('、')}。`,
        action: '可在涉油检斤处置中补齐；不填写可以保存案件，但对应材料门禁和复核口径会保持待补。',
        blocking: true,
      })
    }
  }

  if (values.bonus_has_police) {
    const missing = missingPoliceFields(values)
    if (missing.length > 0) {
      hints.push({
        key: 'police_case',
        label: '报案立案佐证',
        detail: `已启用报案立案佐证条目，但仍缺少${missing.join('、')}。`,
        action: '可在报案立案佐证中补齐；不填写可以保存案件，但公安接收材料会保持待补。',
        blocking: true,
      })
    }
  }

  return hints
}
