import { formCaseTime, serializeCaseTime } from '../../utils/caseValues'
import type { CaseEditSnapshot } from '../../services/cases'
import { CASE_AI_INTAKE_FORM_FIELDS } from './caseAiIntake'
import { caseLocationDraft } from './caseLocationDraft'
import { knownFeedbackValue } from './caseFeedback'

const timeFields = new Set(['occurred_time', 'occurred_from', 'occurred_to', 'discovered_at', 'report_time', 'measured_at'])
const formFields = new Set([...CASE_AI_INTAKE_FORM_FIELDS, 'operational_area_id', 'latitude', 'longitude', 'loss_amount', 'security_level',
  'upstream_source', 'downstream_destination', 'involved_items', 'suspect_roles', 'initial_vehicles', 'initial_persons', 'initial_locations',
  'initial_measurements', 'bonus_has_vehicle', 'bonus_has_person', 'bonus_has_oil', 'bonus_has_police',
  'feedback_changed_fields', 'feedback_initial_known_fields', 'entry_location_role'])

export function entryFormValues(values: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(values).filter(([field]) => formFields.has(field)))
}

/** Dates retain their selected business timezone; unfinished fields stay unfinished. */
export function serializeEntryValues(values: Record<string, unknown>): Record<string, unknown> {
  const zone = String(values.time_timezone || 'Asia/Shanghai')
  const visit = (input: unknown, field = ''): unknown => {
    if (input === undefined) return null
    if (timeFields.has(field)) return serializeCaseTime(input, zone) ?? null
    if (Array.isArray(input)) return input.map(item => visit(item))
    if (input && typeof input === 'object') return Object.fromEntries(Object.entries(input).map(([key, value]) => [key, visit(value, key)]))
    return input
  }
  return Object.fromEntries(Object.entries(entryFormValues(values)).map(([field, value]) => [field, visit(value, field)]))
}

export function restoreEntryValues(values: Record<string, unknown>): Record<string, unknown> {
  const zone = String(values.time_timezone || 'Asia/Shanghai')
  const visit = (input: unknown, field = ''): unknown => {
    if (timeFields.has(field)) return typeof input === 'string' ? formCaseTime(input, zone) : null
    if (Array.isArray(input)) return input.map(item => visit(item))
    if (input && typeof input === 'object') return Object.fromEntries(Object.entries(input).map(([key, value]) => [key, visit(value, key)]))
    return input
  }
  return visit(values) as Record<string, unknown>
}

export function editSnapshotValues(snapshot: CaseEditSnapshot): Record<string, unknown> {
  const row = snapshot.case
  return restoreEntryValues(entryFormValues({ ...row,
    police_reported: knownFeedbackValue(row, 'police_reported'), case_filed: knownFeedbackValue(row, 'case_filed'),
    feedback_changed_fields: [], feedback_initial_known_fields: row.feedback_known_fields || [], entry_location_role: 'unknown',
    time_precision: row.time_precision || (row.occurred_time ? 'exact' : row.occurred_from && row.occurred_to ? 'interval' : 'unknown'),
    time_timezone: row.time_timezone || 'Asia/Shanghai', oil_volume_unit: row.oil_volume_unit || 'unknown',
    initial_vehicles: snapshot.initial_vehicles.map(vehicle => ({ id: vehicle.id, vehicle_type: vehicle.vehicle_type,
      plate_number: vehicle.plate_number, handling_status: vehicle.handling_status, road_vehicle_kind: vehicle.road_vehicle_kind,
      height_m: vehicle.height_m, gross_weight_t: vehicle.gross_weight_t, oil_volume: vehicle.oil_volume, oil_volume_unit: vehicle.oil_volume_unit || 'unknown' })),
    initial_persons: snapshot.initial_persons.map(person => ({ id: person.id, name: person.name, role: person.role, handling_status: person.handling_status })),
    initial_locations: snapshot.initial_locations.map(caseLocationDraft),
    initial_measurements: snapshot.initial_measurements,
    bonus_has_vehicle: snapshot.initial_vehicles.length > 0 || Boolean(row.vehicle_handling),
    bonus_has_person: snapshot.initial_persons.length > 0 || Boolean(row.person_handling),
    bonus_has_oil: row.oil_volume != null || row.water_cut != null || row.oil_handling || row.oil_nature ? true : undefined,
    bonus_has_police: row.police_reported || row.case_filed || row.police_officer || row.police_phone ? true : undefined,
  }))
}

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(',')}}`
  return JSON.stringify(value ?? null)
}

export function entryDifferenceFields(mine: Record<string, unknown>, latest: Record<string, unknown>): string[] {
  return [...new Set([...Object.keys(mine), ...Object.keys(latest)])].filter(field => stable(mine[field]) !== stable(latest[field]))
}

export function resolveEntryDifferences(mine: Record<string, unknown>, latest: Record<string, unknown>, choices: Record<string, 'mine' | 'latest'>): Record<string, unknown> {
  const differences = entryDifferenceFields(mine, latest)
  if (differences.some(field => !choices[field])) throw new Error('请逐项确认所有差异')
  return { ...latest, ...Object.fromEntries(differences.filter(field => choices[field] === 'mine').map(field => [field, mine[field]])) }
}
