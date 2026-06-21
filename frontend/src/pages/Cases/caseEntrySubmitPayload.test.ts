import { describe, expect, it } from 'vitest'
import { buildCaseEntrySubmitPayload } from './caseEntrySubmitPayload'

const timeValue = (iso: string) => ({
  toISOString: () => iso,
})

describe('caseEntrySubmitPayload', () => {
  it('removes UI-only bonus scope switches from the API payload', () => {
    const payload = buildCaseEntrySubmitPayload({
      occurred_time: timeValue('2026-06-05T01:00:00.000Z'),
      description: '现场发现异常',
      bonus_has_vehicle: true,
      bonus_has_person: false,
      bonus_has_oil: true,
      bonus_has_police: false,
    }, { mode: 'create' })

    expect(payload).toMatchObject({
      occurred_time: '2026-06-05T01:00:00.000Z',
      description: '现场发现异常',
    })
    expect(payload).not.toHaveProperty('bonus_has_vehicle')
    expect(payload).not.toHaveProperty('bonus_has_person')
    expect(payload).not.toHaveProperty('bonus_has_oil')
    expect(payload).not.toHaveProperty('bonus_has_police')
  })

  it('keeps compact vehicle and person drafts when their scopes are enabled', () => {
    const payload = buildCaseEntrySubmitPayload({
      occurred_time: timeValue('2026-06-05T01:00:00.000Z'),
      bonus_has_vehicle: true,
      bonus_has_person: true,
      initial_vehicles: [
        { plate_number: '黑E12345', vehicle_type: '5吨以下机动车', handling_status: '' },
        { plate_number: '' },
      ],
      initial_persons: [
        { name: '张某', handling_status: '行政拘留', role: '' },
        {},
      ],
    }, { mode: 'create' })

    expect(payload.initial_vehicles).toEqual([
      { plate_number: '黑E12345', vehicle_type: '5吨以下机动车' },
    ])
    expect(payload.initial_persons).toEqual([
      { name: '张某', handling_status: '行政拘留' },
    ])
  })

  it('returns empty draft arrays in edit mode when a scope is explicitly closed', () => {
    const payload = buildCaseEntrySubmitPayload({
      occurred_time: timeValue('2026-06-05T01:00:00.000Z'),
      bonus_has_vehicle: false,
      bonus_has_person: false,
      initial_vehicles: [{ id: 7, plate_number: '黑E12345' }],
      initial_persons: [{ id: 3, name: '张某' }],
    }, { mode: 'edit' })

    expect(payload.initial_vehicles).toEqual([])
    expect(payload.initial_persons).toEqual([])
  })

  it('omits empty draft arrays in create mode when scopes are not enabled', () => {
    const payload = buildCaseEntrySubmitPayload({
      occurred_time: timeValue('2026-06-05T01:00:00.000Z'),
      bonus_has_vehicle: false,
      bonus_has_person: false,
      initial_vehicles: [],
      initial_persons: [],
    }, { mode: 'create' })

    expect(payload).not.toHaveProperty('initial_vehicles')
    expect(payload).not.toHaveProperty('initial_persons')
  })

  it('preserves row ids and nulls clearable fields when editing existing draft rows', () => {
    const payload = buildCaseEntrySubmitPayload({
      occurred_time: timeValue('2026-06-05T01:00:00.000Z'),
      bonus_has_vehicle: true,
      bonus_has_person: true,
      initial_vehicles: [{ id: 9, plate_number: '', vehicle_type: '重型挂车', handling_status: '' }],
      initial_persons: [{ id: 4, name: '', handling_status: '刑事拘留', role: '' }],
    }, { mode: 'edit' })

    expect(payload.initial_vehicles).toEqual([
      { id: 9, plate_number: null, vehicle_type: '重型挂车', handling_status: null },
    ])
    expect(payload.initial_persons).toEqual([
      { id: 4, name: null, handling_status: '刑事拘留', role: null },
    ])
  })

  it('omits draft arrays in edit mode when the related records were not loaded', () => {
    const payload = buildCaseEntrySubmitPayload({
      occurred_time: timeValue('2026-06-05T01:00:00.000Z'),
      bonus_has_vehicle: false,
      bonus_has_person: false,
      initial_vehicles: [],
      initial_persons: [],
    }, {
      mode: 'edit',
      includeVehicleDrafts: false,
      includePersonDrafts: false,
    })

    expect(payload).not.toHaveProperty('initial_vehicles')
    expect(payload).not.toHaveProperty('initial_persons')
  })

  it('clears oil and police fields when their edit scopes are closed', () => {
    const payload = buildCaseEntrySubmitPayload({
      occurred_time: timeValue('2026-06-05T01:00:00.000Z'),
      bonus_has_oil: false,
      bonus_has_police: false,
      oil_nature: undefined,
      oil_volume: undefined,
      water_cut: undefined,
      oil_handling: undefined,
      police_reported: false,
      case_filed: false,
      police_officer: undefined,
      police_phone: undefined,
    }, { mode: 'edit' })

    expect(payload).toMatchObject({
      oil_nature: null,
      oil_volume: null,
      water_cut: null,
      oil_handling: null,
      police_reported: false,
      case_filed: false,
      police_officer: null,
      police_phone: null,
    })
  })
})
