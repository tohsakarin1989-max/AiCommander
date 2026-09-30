import type { CaseCreate, CaseUpdatePayload } from '../../types'
import { serializeCaseTime } from '../../utils/caseValues'

export type CaseEntrySubmitMode = 'create' | 'edit'

export interface CaseEntrySubmitPayloadOptions {
  mode: CaseEntrySubmitMode
  includeVehicleDrafts?: boolean
  includePersonDrafts?: boolean
  includeLocations?: boolean
  includeMeasurements?: boolean
  hadIncidentLocations?: boolean
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
  initial_locations?: Array<Record<string, unknown>>
  initial_measurements?: Array<Record<string, unknown>>
}

const vehicleDraftFields = ['vehicle_type', 'plate_number', 'handling_status', 'road_vehicle_kind', 'height_m', 'gross_weight_t', 'oil_volume', 'oil_volume_unit']
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
    initial_locations,
    initial_measurements,
    involved_persons: _legacyPersons,
    vehicle_info: _legacyVehicles,
    ...caseValues
  } = values

  const payload: Record<string, unknown> = {
    ...caseValues,
    occurred_time: toIsoString(caseValues.occurred_time),
    report_time: toIsoString(caseValues.report_time),
  }
  const precision = values.time_precision ?? (values.occurred_time ? 'exact' : 'unknown')
  const timestamp = (value: unknown) => serializeCaseTime(value, String(values.time_timezone || 'Asia/Shanghai')) ?? null
  payload.time_precision = precision
  payload.time_timezone = values.time_timezone || 'Asia/Shanghai'
  payload.occurred_time = precision === 'exact' ? timestamp(values.occurred_time) : null
  payload.occurred_from = precision === 'interval' ? timestamp(values.occurred_from) : null
  payload.occurred_to = precision === 'interval' ? timestamp(values.occurred_to) : null
  payload.discovered_at = timestamp(values.discovered_at)
  payload.report_time = timestamp(values.report_time)
  payload.oil_volume_unit = values.oil_volume_unit || 'unknown'
  if (options.includeLocations !== false && Array.isArray(initial_locations)) {
    payload.initial_locations = initial_locations.map(({ id: _id, case_id: _caseId, ui_latitude, ui_longitude, ...row }) => ({
      ...row, geometry: typeof ui_latitude === 'number' && typeof ui_longitude === 'number'
        ? { type: 'Point', coordinates: [ui_longitude, ui_latitude] }
        : ui_latitude !== undefined || ui_longitude !== undefined ? null : row.geometry ?? null, precision: row.precision || 'unknown',
    }))
    // The typed incident record owns the primary map point. Discovery/custody points never replace it.
    const incidents = (payload.initial_locations as Array<Record<string, unknown>>).filter(row => row.role === 'incident')
    if (incidents.length || options.hadIncidentLocations) {
      const incident = incidents.length === 1 ? incidents[0] : null
      const geometry = incident?.geometry as { type?: string; coordinates?: number[] } | null
      const exact = incident?.precision === 'exact' && geometry?.type === 'Point' && Array.isArray(geometry.coordinates)
      payload.latitude = exact ? geometry.coordinates![1] : null
      payload.longitude = exact ? geometry.coordinates![0] : null
    }
  }
  if (options.includeMeasurements !== false && Array.isArray(initial_measurements)) {
    payload.initial_measurements = initial_measurements.map(({ id: _id, case_id: _caseId, ...row }) => ({
      ...row, unit: row.unit || 'unknown', measured_at: timestamp(row.measured_at),
    }))
  }
  if (options.mode === 'edit') delete payload.operational_area_id

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
    payload.oil_volume_unit = 'unknown'
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
