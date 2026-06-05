import type { CaseCreate, CaseUpdatePayload } from '../../types'

export type CaseEntrySubmitMode = 'create' | 'edit'

export interface CaseEntrySubmitPayloadOptions {
  mode: CaseEntrySubmitMode
  includeVehicleDrafts?: boolean
  includePersonDrafts?: boolean
}

export interface CaseEntrySubmitValues extends Record<string, unknown> {
  occurred_time?: unknown
  report_time?: unknown
  bonus_has_vehicle?: unknown
  bonus_has_person?: unknown
  bonus_has_oil?: unknown
  bonus_has_police?: unknown
  initial_vehicles?: Array<Record<string, unknown>>
  initial_persons?: Array<Record<string, unknown>>
}

const vehicleDraftFields = ['vehicle_type', 'plate_number', 'handling_status']
const personDraftFields = ['name', 'handling_status', 'role']

function toIsoString(value: unknown): unknown {
  if (value && typeof value === 'object' && 'toISOString' in value) {
    const toISOString = (value as { toISOString?: unknown }).toISOString
    if (typeof toISOString === 'function') return toISOString.call(value)
  }
  return value
}

export function compactDraftRows<T extends Record<string, unknown>>(rows?: T[], clearableFields: string[] = []): T[] {
  return (rows || [])
    .map(row => {
      const source = row || {}
      const hasId = source.id !== undefined && source.id !== null && source.id !== ''
      const entries = Object.entries(source).flatMap(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') return [[key, value]]
        if (hasId && clearableFields.includes(key)) return [[key, null]]
        return []
      })
      return Object.fromEntries(entries) as T
    })
    .filter(row => {
      const keys = Object.keys(row)
      return keys.some(key => key !== 'id')
    })
}

export function buildCaseEntrySubmitPayload(
  values: CaseEntrySubmitValues,
  options: CaseEntrySubmitPayloadOptions
): Partial<CaseCreate> | CaseUpdatePayload {
  const {
    bonus_has_vehicle,
    bonus_has_person,
    bonus_has_oil,
    bonus_has_police,
    initial_vehicles,
    initial_persons,
    ...caseValues
  } = values

  const payload: Record<string, unknown> = {
    ...caseValues,
    occurred_time: toIsoString(caseValues.occurred_time),
    report_time: toIsoString(caseValues.report_time),
  }

  const vehicleScopeSet = typeof bonus_has_vehicle === 'boolean'
  const personScopeSet = typeof bonus_has_person === 'boolean'
  const vehicleDrafts = bonus_has_vehicle === true
    ? compactDraftRows(initial_vehicles, vehicleDraftFields)
    : []
  const personDrafts = bonus_has_person === true
    ? compactDraftRows(initial_persons, personDraftFields)
    : []
  const includeVehicleDrafts = options.includeVehicleDrafts ?? true
  const includePersonDrafts = options.includePersonDrafts ?? true

  if (includeVehicleDrafts && (vehicleDrafts.length > 0 || (options.mode === 'edit' && vehicleScopeSet))) {
    payload.initial_vehicles = vehicleDrafts
  }

  if (includePersonDrafts && (personDrafts.length > 0 || (options.mode === 'edit' && personScopeSet))) {
    payload.initial_persons = personDrafts
  }

  if (options.mode === 'edit' && bonus_has_oil === false) {
    payload.oil_nature = null
    payload.oil_volume = null
    payload.water_cut = null
    payload.oil_handling = null
  }

  if (options.mode === 'edit' && bonus_has_police === false) {
    payload.police_reported = false
    payload.case_filed = false
    payload.police_officer = null
    payload.police_phone = null
  }

  return payload as Partial<CaseCreate> | CaseUpdatePayload
}
