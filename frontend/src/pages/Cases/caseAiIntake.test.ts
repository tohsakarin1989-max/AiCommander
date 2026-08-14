import { describe, expect, it } from 'vitest'
import {
  buildCaseAiIntakeApplication,
  buildCaseAiIntakeEntryFlags,
  formatAiIntakeValue,
} from './caseAiIntake'
import type { CaseStructurePreview } from '../../types'

describe('caseAiIntake', () => {
  const preview: CaseStructurePreview = {
    case_fields: {
      occurred_time: '2026-05-06T02:30:00',
      report_time: '2026-05-06T03:00:00',
      report_unit: '敖南保卫班',
      location: '三号井场',
      oil_volume: 1.2,
      water_cut: 8,
      vehicle_handling: '移交公安',
      person_handling: '移交公安',
      police_reported: true,
      police_officer: '姚警官',
      police_phone: '18846680071',
      security_officers: ['张伟', '王艳龙'],
    },
    field_sources: {},
    entities: {
      plate_numbers: ['辽A12345'],
      person_count: 2,
      material_hints: [],
    },
    suggested_evidence: [],
    warnings: [],
    confidence: 0.78,
    boundary: '候选字段需确认',
    candidates: [
      { field: 'title', label: '标准化标题', value: '三号井场涉油盗窃', source: '组合', confidence: 0.75, status: 'candidate' },
      { field: 'description', label: '案情摘要', value: '三号井场查获车辆盗运原油。', source: '摘要', confidence: 0.72, status: 'candidate' },
      { field: 'location', label: '案发地点', value: '三号井场', source: '地点片段', confidence: 0.78, status: 'candidate' },
    ],
  }

  it('builds editable form patch and keeps reference-only candidates separate', () => {
    const result = buildCaseAiIntakeApplication(preview, '原始案情')

    expect(result.patch.location).toBe('三号井场')
    expect(result.patch.description).toBe('三号井场查获车辆盗运原油。')
    expect(result.patch.report_unit).toBe('敖南保卫班')
    expect(result.patch.police_phone).toBe('18846680071')
    expect(result.patch.security_officers).toEqual(['张伟', '王艳龙'])
    expect(result.patch.oil_volume).toBe(1.2)
    expect(result.shouldOpenAdvancedFields).toBe(true)
    expect(result.writableCandidates.map(item => item.field)).toContain('location')
    expect(result.referenceCandidates.map(item => item.field)).toContain('title')
  })

  it('turns extracted clues into optional bonus scope flags', () => {
    const result = buildCaseAiIntakeApplication(preview, '原始案情')
    const flags = buildCaseAiIntakeEntryFlags(preview, result.patch)

    expect(flags.bonus_has_vehicle).toBe(true)
    expect(flags.bonus_has_person).toBe(true)
    expect(flags.bonus_has_oil).toBe(true)
    expect(flags.bonus_has_police).toBe(true)
    expect(flags.initial_vehicles).toEqual([{ plate_number: '辽A12345', handling_status: '移交公安' }])
  })

  it('formats values for compact candidate cards', () => {
    expect(formatAiIntakeValue(true)).toBe('是')
    expect(formatAiIntakeValue(null)).toBe('待确认')
    expect(formatAiIntakeValue({ plate_number: '辽A12345' })).toBe('{"plate_number":"辽A12345"}')
  })
})
