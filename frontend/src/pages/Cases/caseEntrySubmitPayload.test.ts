import { describe, expect, it } from 'vitest'
import { buildCaseEntrySubmitPayload } from './caseEntrySubmitPayload'

const timeValue = (iso: string) => ({
  toISOString: () => iso,
})

describe('道路车辆参数', () => {
  it('保留选填道路参数，并允许编辑时清空，不改成零或油量', () => {
    const result = buildCaseEntrySubmitPayload({ bonus_has_vehicle: true,
      initial_vehicles: [{ id: 9, road_vehicle_kind: 'truck', height_m: 3.2, gross_weight_t: 12.5 }],
    }, { mode: 'edit' })
    expect(result.initial_vehicles).toEqual([{ id: 9, road_vehicle_kind: 'truck', height_m: 3.2, gross_weight_t: 12.5 }])
    const cleared = buildCaseEntrySubmitPayload({ bonus_has_vehicle: true,
      initial_vehicles: [{ id: 9, height_m: null, gross_weight_t: null }],
    }, { mode: 'edit' })
    expect(cleared.initial_vehicles).toEqual([{ id: 9, height_m: null, gross_weight_t: null }])
  })
})

describe('caseEntrySubmitPayload', () => {
  it('案发地点唯一精确点控制主地图点，区域或删除不残留旧点，发现点不投影', () => {
    const values = { latitude: 46, longitude: 123, initial_locations: [{ role: 'incident', precision: 'exact', ui_latitude: 47, ui_longitude: 124 }] }
    expect(buildCaseEntrySubmitPayload(values, { mode: 'edit' })).toMatchObject({ latitude: 47, longitude: 124 })
    expect(buildCaseEntrySubmitPayload({ ...values, initial_locations: [{ role: 'incident', precision: 'area' }] }, { mode: 'edit' })).toMatchObject({ latitude: null, longitude: null })
    expect(buildCaseEntrySubmitPayload({ ...values, initial_locations: [] }, { mode: 'edit', hadIncidentLocations: true })).toMatchObject({ latitude: null, longitude: null })
    expect(buildCaseEntrySubmitPayload({ ...values, initial_locations: [{ role: 'discovery', precision: 'exact', ui_latitude: 47, ui_longitude: 124 }] }, { mode: 'edit' })).toMatchObject({ latitude: 46, longitude: 123 })
  })
  it('未知时间可保存且清除旧精确值，不发送旧人员车辆 JSON', () => {
    const payload = buildCaseEntrySubmitPayload({ time_precision: 'unknown', occurred_time: timeValue('2026-06-05T01:00:00Z'), time_expression: '近期', oil_volume: 9,
      involved_persons: [{ name: '旧人' }], vehicle_info: [{ plate: '旧车' }],
    }, { mode: 'create' })
    expect(payload).toMatchObject({ occurred_time: null, occurred_from: null, occurred_to: null, time_precision: 'unknown', oil_volume_unit: 'unknown', time_expression: '近期' })
    expect(payload).not.toHaveProperty('involved_persons'); expect(payload).not.toHaveProperty('vehicle_info')
  })

  it('区间保留两端，不编造发生时刻；不同测量环节和单位原样保留', () => {
    const payload = buildCaseEntrySubmitPayload({ time_precision: 'interval', occurred_time: timeValue('2026-06-05T01:00:00Z'), occurred_from: timeValue('2026-06-01T00:00:00Z'), occurred_to: timeValue('2026-06-03T00:00:00Z'),
      initial_measurements: [{ id: 22, case_id: 7, value: 0, unit: 'liter', stage: 'seized' }, { value: 5, unit: 'kg', stage: 'transferred' }],
    }, { mode: 'edit' })
    expect(payload).toMatchObject({ occurred_time: null, occurred_from: '2026-06-01T00:00:00Z', occurred_to: '2026-06-03T00:00:00Z' })
    expect(payload.initial_measurements).toEqual([{ id: 22, value: 0, unit: 'liter', stage: 'seized', measured_at: null }, { value: 5, unit: 'kg', stage: 'transferred', measured_at: null }])
  })

  it('来源集合读取失败时不替换旧数据；经纬度按 GeoJSON 轴序保存', () => {
    const rows = [{ id: 2, case_id: 7, role: 'discovery', precision: 'exact', ui_latitude: 47, ui_longitude: 124 }]
    const payload = buildCaseEntrySubmitPayload({ initial_locations: rows, initial_measurements: [] }, { mode: 'edit' })
    expect(payload.initial_locations).toEqual([{ id: 2, role: 'discovery', precision: 'exact', geometry: { type: 'Point', coordinates: [124, 47] } }])
    const failed = buildCaseEntrySubmitPayload({ initial_locations: rows, initial_measurements: [] }, { mode: 'edit', includeLocations: false, includeMeasurements: false })
    expect(failed).not.toHaveProperty('initial_locations'); expect(failed).not.toHaveProperty('initial_measurements')
    const cleared = buildCaseEntrySubmitPayload({ initial_locations: [{ geometry: { type: 'Point', coordinates: [124, 47] }, ui_latitude: null, ui_longitude: null, precision: 'unknown' }] }, { mode: 'edit' })
    expect(cleared.initial_locations?.[0].geometry).toBeNull()
  })

  it('编辑保留同值不同明细的 ID 与顺序，新建不携带旧案 ID', () => {
    const values = {
      initial_locations: [8, 3].map(id => ({ id, case_id: 7, role: 'discovery', precision: 'unknown' })),
      initial_measurements: [9, 2].map(id => ({ id, case_id: 7, value: 1, unit: 'liter' })),
    }
    const edit = buildCaseEntrySubmitPayload(values, { mode: 'edit' })
    expect(edit.initial_locations?.map(row => row.id)).toEqual([8, 3])
    expect(edit.initial_measurements?.map(row => row.id)).toEqual([9, 2])
    const create = buildCaseEntrySubmitPayload(values, { mode: 'create' })
    for (const row of [...(create.initial_locations || []), ...(create.initial_measurements || [])]) {
      expect(row).not.toHaveProperty('id')
      expect(row).not.toHaveProperty('case_id')
    }
  })

  it('removes UI-only bonus scope switches from the API payload', () => {
    const payload = buildCaseEntrySubmitPayload({
      operational_area_id: 12,
      occurred_time: timeValue('2026-06-05T01:00:00.000Z'),
      description: '现场发现异常',
      bonus_has_vehicle: true,
      bonus_has_person: false,
      bonus_has_oil: true,
      bonus_has_police: false,
    }, { mode: 'create' })

    expect(payload).toMatchObject({
      occurred_time: '2026-06-05T01:00:00.000Z',
      operational_area_id: 12,
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

  it('关闭材料开关不抹除已录入的处置资料或把未知反馈改为否', () => {
    const payload = buildCaseEntrySubmitPayload({
      occurred_time: timeValue('2026-06-05T01:00:00.000Z'),
      bonus_has_oil: false,
      bonus_has_police: false,
      oil_nature: undefined,
      oil_volume: undefined,
      water_cut: undefined,
      oil_handling: '移交公安',
      police_reported: false,
      case_filed: false,
      police_officer: '已记录联系人',
      police_phone: '已记录联系方式',
    }, { mode: 'edit' })

    expect(payload).toMatchObject({
      oil_handling: '移交公安',
      police_officer: '已记录联系人',
      police_phone: '已记录联系方式',
    })
    expect(payload).not.toHaveProperty('police_reported')
    expect(payload).not.toHaveProperty('case_filed')
    expect(payload.oil_volume).not.toBeNull()
  })

  it('显式反馈只发更改项，清除为未知发null，不提交只读标记', () => {
    const payload = buildCaseEntrySubmitPayload({ police_reported: false, case_filed: null,
      feedback_known_fields: ['police_reported'], feedback_changed_fields: ['case_filed'] }, { mode: 'edit' })
    expect(payload).toHaveProperty('case_filed', null)
    expect(payload).not.toHaveProperty('police_reported')
    expect(payload).not.toHaveProperty('feedback_known_fields')
    expect(payload).not.toHaveProperty('feedback_changed_fields')
  })

  it('新建发现地点只写对应明细，不投影为案发主坐标；未知不猜角色', () => {
    const values = { location: '某路口', latitude: 46, longitude: 123, initial_locations: [], entry_location_role: 'discovery' }
    expect(buildCaseEntrySubmitPayload(values, { mode: 'create' })).toMatchObject({ latitude: null, longitude: null,
      initial_locations: [{ role: 'discovery', description: '某路口', precision: 'exact', geometry: { type: 'Point', coordinates: [123, 46] } }] })
    const unknown = buildCaseEntrySubmitPayload({ location: '某区域', initial_locations: [], entry_location_role: 'unknown' }, { mode: 'create' })
    expect(unknown.initial_locations).toEqual([{ role: 'mentioned', description: '某区域', precision: 'unknown', geometry: null }])
    expect(unknown).not.toHaveProperty('entry_location_role')
  })

  it('编辑时明确新增发现地点不替换旧主点，并避免重复相同明细', () => {
    const place = { role: 'discovery', description: '某路口', precision: 'exact', geometry: { type: 'Point', coordinates: [123, 46] } }
    const payload = buildCaseEntrySubmitPayload({ location: '某路口', latitude: 46, longitude: 123,
      initial_locations: [place], entry_location_role: 'discovery' }, { mode: 'edit', legacyCoordinates: { latitude: 47, longitude: 124 } })
    expect(payload).toMatchObject({ latitude: 47, longitude: 124 })
    expect(payload.initial_locations).toHaveLength(1)
  })
})
