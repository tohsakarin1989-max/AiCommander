import type { AiIntakeCandidate, CaseCreate, CaseStructurePreview } from '../../types'

export const CASE_AI_INTAKE_FORM_FIELDS = new Set([
  'occurred_time',
  'report_time',
  'location',
  'case_type',
  'description',
  'oil_type',
  'oil_volume',
  'oil_value',
  'oil_nature',
  'water_cut',
  'source_type',
  'police_reported',
  'case_filed',
  'person_handling',
  'vehicle_handling',
  'oil_handling',
  'report_unit',
  'source_detail',
  'police_officer',
  'police_phone',
  'security_officers',
  'facility_type',
  'facility_owner',
  'modus_operandi',
  'operation_role',
  'current_stage',
])

const ADVANCED_INTAKE_FIELDS = new Set([
  'oil_type',
  'oil_volume',
  'oil_value',
  'oil_nature',
  'water_cut',
  'facility_type',
  'facility_owner',
  'modus_operandi',
  'person_handling',
  'vehicle_handling',
  'oil_handling',
])

function hasValue(value: unknown): boolean {
  return value !== undefined && value !== null && value !== ''
}

export interface CaseAiIntakeApplication {
  patch: Partial<CaseCreate>
  writableCandidates: AiIntakeCandidate[]
  referenceCandidates: AiIntakeCandidate[]
  shouldOpenAdvancedFields: boolean
}

export function buildCaseAiIntakeApplication(
  preview: CaseStructurePreview,
  sourceText: string
): CaseAiIntakeApplication {
  const patch: Record<string, unknown> = {}

  Object.entries(preview.case_fields || {}).forEach(([field, value]) => {
    if (CASE_AI_INTAKE_FORM_FIELDS.has(field) && hasValue(value)) {
      patch[field] = value
    }
  })

  const descriptionCandidate = preview.candidates?.find(
    item => item.field === 'description' && hasValue(item.value),
  )
  if (!hasValue(patch.description) && descriptionCandidate) {
    patch.description = descriptionCandidate.value
  }
  if (!hasValue(patch.description) && sourceText.trim()) {
    patch.description = sourceText.trim()
  }

  const writableCandidates = (preview.candidates || []).filter(item =>
    CASE_AI_INTAKE_FORM_FIELDS.has(item.field),
  )
  const referenceCandidates = (preview.candidates || []).filter(item =>
    !CASE_AI_INTAKE_FORM_FIELDS.has(item.field),
  )

  return {
    patch: patch as Partial<CaseCreate>,
    writableCandidates,
    referenceCandidates,
    shouldOpenAdvancedFields: Object.keys(patch).some(field => ADVANCED_INTAKE_FIELDS.has(field)),
  }
}

export function buildCaseAiIntakeEntryFlags(
  preview: CaseStructurePreview,
  patch: Partial<CaseCreate>,
): Record<string, unknown> {
  const flags: Record<string, unknown> = {}
  const plateNumbers = preview.entities?.plate_numbers || []
  const personCount = preview.entities?.person_count || 0

  if (patch.vehicle_handling || plateNumbers.length > 0) {
    flags.bonus_has_vehicle = true
    flags.initial_vehicles = [
      {
        plate_number: plateNumbers[0],
        handling_status: patch.vehicle_handling,
      },
    ].filter(row => row.plate_number || row.handling_status)
  }

  if (patch.person_handling || personCount > 0) {
    flags.bonus_has_person = true
    flags.initial_persons = [
      {
        role: '涉案人员',
        handling_status: patch.person_handling,
      },
    ]
  }

  if (patch.oil_nature || patch.oil_volume != null || patch.water_cut != null || patch.oil_handling) {
    flags.bonus_has_oil = true
  }

  if (patch.police_reported || patch.case_filed) {
    flags.bonus_has_police = true
  }

  return flags
}

export function formatAiIntakeValue(value: unknown): string {
  if (value === true) return '是'
  if (value === false) return '否'
  if (value === null || value === undefined || value === '') return '待确认'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)))
  if (typeof value === 'string') return value.length > 90 ? `${value.slice(0, 87)}...` : value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}
