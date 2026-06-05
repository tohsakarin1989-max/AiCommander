export type CaseEntryReadinessStatus = 'ready' | 'attention' | 'idle'

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

export interface CaseEntryReadinessValues extends CaseBonusEntryValues {
  latitude?: unknown
  longitude?: unknown
  location?: unknown
  case_type?: unknown
}

export interface CaseEntryReadinessItem {
  key: 'map_analysis' | 'ai_preprocess' | 'bonus_accounting' | 'conclusion_layering' | 'experience_card'
  label: string
  status: CaseEntryReadinessStatus
  impact: string
  action: string
}

function hasText(value: unknown): boolean {
  if (value == null) return false
  return String(value).trim().length > 0
}

function numeric(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function hasValidCoordinate(values: CaseEntryReadinessValues): boolean {
  const lat = numeric(values.latitude)
  const lng = numeric(values.longitude)
  return lat != null && lng != null && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180
}

function descriptionLength(values: CaseEntryReadinessValues): number {
  if (values.description == null) return 0
  return String(values.description).trim().length
}

function hasBonusScope(values: CaseEntryReadinessValues): boolean {
  return Boolean(
    values.bonus_has_vehicle
      || values.bonus_has_person
      || values.bonus_has_oil
      || values.bonus_has_police
  )
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

function hasVehicleCategory(values: CaseBonusEntryValues): boolean {
  const rows = values.initial_vehicles || []
  return rows.some(row => hasText(row?.vehicle_type))
}

function hasPersonSignal(values: CaseBonusEntryValues, text: string): boolean {
  const rows = values.initial_persons || []
  return rows.some(rowHasAnyValue)
    || hasText(values.involved_persons)
    || hasText(values.person_handling)
    || containsAny(text, ['抓获', '人员', '嫌疑人', '司机', '一人', '1人'])
}

function hasPersonDisposition(values: CaseBonusEntryValues): boolean {
  const rows = values.initial_persons || []
  return rows.some(row => hasText(row?.handling_status))
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
  ].filter(hasText).map(value => String(value)).join(' ')
  const hints: CaseBonusEntryHint[] = []

  if (values.bonus_has_vehicle && !hasVehicleCategory(values)) {
    hints.push({
      key: 'vehicle_category',
      label: '车辆考核类别',
      detail: hasVehicleSignal(values, text)
        ? '已出现车辆线索，但未明确摩托车、5吨以下、5吨以上等车辆考核类别。'
        : '已开启涉案车辆奖励，但未填写车辆考核类别。',
      action: '可在涉案车辆中选择车辆考核类别；不填写可以保存案件，但整案奖金暂不测算。',
      blocking: true,
    })
  }

  if (values.bonus_has_person && !hasPersonDisposition(values)) {
    hints.push({
      key: 'person_disposition',
      label: '人员处理类型',
      detail: hasPersonSignal(values, text)
        ? '已出现抓获/涉案人员线索，但未明确行政拘留、刑事拘留等处理结果。'
        : '已开启抓获人员奖励，但未填写人员处理类型。',
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

export function buildCaseEntryReadiness(
  values: CaseEntryReadinessValues,
  bonusHints: CaseBonusEntryHint[] = buildBonusEntryHints(values)
): CaseEntryReadinessItem[] {
  const hasCoordinate = hasValidCoordinate(values)
  const hasLocation = hasText(values.location)
  const descLength = descriptionLength(values)
  const hasEnoughDescription = descLength >= 30
  const hasBasicDescription = descLength >= 12
  const bonusScopeEnabled = hasBonusScope(values)
  const blockingBonusHints = bonusHints.filter(item => item.blocking)

  const mapItem: CaseEntryReadinessItem = hasCoordinate
    ? {
        key: 'map_analysis',
        label: '地图研判',
        status: 'ready',
        impact: '可进入空间分布、附近要素和链条距离计算。',
        action: '坐标已具备，可保存后参与地图研判。',
      }
    : {
        key: 'map_analysis',
        label: '地图研判',
        status: 'attention',
        impact: hasLocation ? '已填写地点文本，但系统无法稳定计算距离和热区。' : '缺少地点或坐标，地图类分析只能待补。',
        action: '建议用地图选点或填写经纬度；道路、村屯等公共要素由地图参考层补充。',
      }

  const preprocessItem: CaseEntryReadinessItem = hasEnoughDescription
    ? {
        key: 'ai_preprocess',
        label: 'AI 预处理',
        status: 'ready',
        impact: '案情描述足以提取时间、地点、对象和处置线索。',
        action: '可点击自动提取，生成结构化字段供后续研判复用。',
      }
    : {
        key: 'ai_preprocess',
        label: 'AI 预处理',
        status: 'attention',
        impact: hasBasicDescription ? '案情已有基础内容，但发现方式、对象或处置结果可能提取不完整。' : '案情描述偏短，模型只能生成很弱的结构化结果。',
        action: '建议补充发现方式、涉案对象、处置结果、作案条件和证据来源。',
      }

  const bonusItem: CaseEntryReadinessItem = blockingBonusHints.length
    ? {
        key: 'bonus_accounting',
        label: '奖金核算',
        status: 'attention',
        impact: `已开启核算范围，但仍缺 ${blockingBonusHints.map(item => item.label).join('、')}。`,
        action: '案件可以保存；补齐会影响金额的指标前，整案奖金暂不测算。',
      }
    : bonusScopeEnabled
      ? {
          key: 'bonus_accounting',
          label: '奖金核算',
          status: 'ready',
          impact: '已开启的核算范围暂无关键指标缺口。',
          action: '保存后可进入奖金核算页查看材料佐证和人工复核。',
        }
      : {
          key: 'bonus_accounting',
          label: '奖金核算',
          status: 'idle',
          impact: '当前未开启奖金条目，不会参与奖金测算。',
          action: '如案件涉及车辆、人员、涉油或公安佐证，再打开对应开关填写。',
        }

  const conclusionItem: CaseEntryReadinessItem = hasBasicDescription && (hasCoordinate || hasLocation)
    ? {
        key: 'conclusion_layering',
        label: '结论分层',
        status: 'ready',
        impact: '具备事实、推断和建议分层的最低输入条件。',
        action: '保存后系统会在案件详情中展示事实依据、推断边界和建议。',
      }
    : {
        key: 'conclusion_layering',
        label: '结论分层',
        status: 'attention',
        impact: '缺少案情或地点基础信息，结论分层容易只剩泛化表述。',
        action: '至少补齐案发地点和关键事实，再让系统生成分层结论。',
      }

  const experienceItem: CaseEntryReadinessItem = hasEnoughDescription && (hasCoordinate || hasLocation || hasText(values.case_type))
    ? {
        key: 'experience_card',
        label: '经验卡',
        status: 'ready',
        impact: '具备沉淀作案条件、发现方式和复用建议的基础信息。',
        action: '保存后会自动生成经验卡，可在同类案件中复用。',
      }
    : {
        key: 'experience_card',
        label: '经验卡',
        status: 'attention',
        impact: '案情要素不足，经验卡会缺少作案条件或可复用建议。',
        action: '建议补充作案条件、发现方式、防护短板和证据缺口。',
      }

  return [mapItem, preprocessItem, bonusItem, conclusionItem, experienceItem]
}
