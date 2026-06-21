import { describe, expect, it } from 'vitest'
import { buildBonusEntryHints } from './caseBonusEntryHints'

describe('caseBonusEntryHints', () => {
  it('does not prompt vehicle or person indicators until the corresponding bonus switches are enabled', () => {
    const hints = buildBonusEntryHints({
      description: '现场抓获1人，查扣皮卡车1台。',
      initial_vehicles: [{ plate_number: '黑E12345' }],
      initial_persons: [{ name: '张某' }],
      bonus_has_vehicle: false,
      bonus_has_person: false,
    })

    expect(hints).toEqual([])
  })

  it('prompts only enabled bonus indicators during case entry', () => {
    const hints = buildBonusEntryHints({
      description: '现场抓获1人，查扣皮卡车1台。',
      initial_vehicles: [{ plate_number: '黑E12345' }],
      initial_persons: [{ name: '张某' }],
      bonus_has_vehicle: true,
      bonus_has_person: true,
    })

    expect(hints.map(item => item.key)).toEqual(['vehicle_category', 'person_disposition'])
    expect(hints[0].label).toBe('车辆考核类别')
    expect(hints[1].label).toBe('人员处理类型')
    expect(hints.every(item => item.blocking)).toBe(true)
  })

  it('prompts oil and police indicators only after those scopes are enabled', () => {
    const hints = buildBonusEntryHints({
      bonus_has_oil: true,
      bonus_has_police: true,
      oil_nature: '被盗原油',
      oil_volume: 1.2,
      police_reported: true,
    })

    expect(hints.map(item => item.key)).toEqual(['oil_measurement', 'police_case'])
    expect(hints[0].detail).toContain('检斤含水率')
    expect(hints[0].detail).toContain('原油处理方式')
    expect(hints[1].detail).toContain('公安出警人')
  })

  it('does not warn when the described bonus indicators have been filled', () => {
    const hints = buildBonusEntryHints({
      description: '现场抓获1人，查扣5吨以下机动车1台。',
      initial_vehicles: [{ vehicle_type: '5吨以下机动车', plate_number: '黑E12345' }],
      initial_persons: [{ name: '张某', handling_status: '行政拘留' }],
      bonus_has_vehicle: true,
      bonus_has_person: true,
      bonus_has_oil: true,
      bonus_has_police: true,
      oil_nature: '被盗原油',
      oil_volume: 1.2,
      water_cut: 4,
      oil_handling: '检斤入库',
      police_reported: true,
      police_officer: '张警官',
      police_phone: '00000000000',
    })

    expect(hints).toEqual([])
  })
})
