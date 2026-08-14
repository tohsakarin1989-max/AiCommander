import { describe, expect, it } from 'vitest'
import { buildCaseEntryReadiness } from './caseEntryReadiness'

describe('caseEntryReadiness', () => {
  it('checks standard reporting fields from the business management rules', () => {
    const incomplete = buildCaseEntryReadiness({
      description: '现场发现异常',
    })

    const incompleteItem = incomplete.find(item => item.key === 'standard_reporting')
    expect(incompleteItem?.status).toBe('attention')
    expect(incompleteItem?.impact).toContain('报送保卫班')

    const ready = buildCaseEntryReadiness({
      occurred_time: '2026-05-06T02:30:00',
      report_time: '2026-05-06T03:00:00',
      report_unit: '敖南保卫班',
      location: '肇源县茂兴镇幸福村东约一公里',
      source_type: '巡逻发现',
      oil_nature: '被盗原油',
      security_officers: ['张伟', '王艳龙'],
      description: '2026年5月6日2时30分，敖南保卫班在肇源县茂兴镇幸福村东约一公里抓获盗油车辆1台，车内被盗原油1.2吨，含水率8%，抓获人员2人并移交公安，原油检斤入库。',
    })

    expect(ready.find(item => item.key === 'standard_reporting')?.status).toBe('ready')
  })

  it('marks map, preprocessing and experience work as needing attention when core entry data is missing', () => {
    const items = buildCaseEntryReadiness({
      description: '现场发现异常',
    })

    expect(items.find(item => item.key === 'map_analysis')?.status).toBe('attention')
    expect(items.find(item => item.key === 'ai_preprocess')?.status).toBe('attention')
    expect(items.find(item => item.key === 'experience_card')?.action).toContain('作案条件')
  })

  it('marks analysis features ready when coordinate and enough case description exist', () => {
    const items = buildCaseEntryReadiness({
      latitude: 46.59,
      longitude: 125.12,
      location: '新站作业区',
      description: '夜间巡护时发现管线附近有新鲜车辙和疑似盗采痕迹，现场已封控并记录处置情况。',
      case_type: '管线周边盗采',
    })

    expect(items.find(item => item.key === 'map_analysis')?.status).toBe('ready')
    expect(items.find(item => item.key === 'ai_preprocess')?.status).toBe('ready')
    expect(items.find(item => item.key === 'conclusion_layering')?.status).toBe('ready')
    expect(items.find(item => item.key === 'experience_card')?.status).toBe('ready')
  })

  it('keeps bonus accounting idle until the user opens a relevant accounting scope', () => {
    const items = buildCaseEntryReadiness({
      description: '现场抓获1人，查扣皮卡车1台。',
      initial_vehicles: [{ plate_number: '黑E12345' }],
      initial_persons: [{ name: '张某' }],
      bonus_has_vehicle: false,
      bonus_has_person: false,
    })

    expect(items.find(item => item.key === 'bonus_accounting')?.status).toBe('idle')
  })

  it('surfaces only enabled bonus accounting gaps before saving the case', () => {
    const items = buildCaseEntryReadiness({
      description: '现场查扣皮卡车1台，未抓获人员。',
      initial_vehicles: [{ plate_number: '黑E12345' }],
      bonus_has_vehicle: true,
      bonus_has_person: false,
    })

    const bonusItem = items.find(item => item.key === 'bonus_accounting')
    expect(bonusItem?.status).toBe('attention')
    expect(bonusItem?.impact).toContain('车辆考核类别')
    expect(bonusItem?.impact).not.toContain('人员处理类型')
  })

  it('treats enabled empty vehicle and person scopes as bonus data gaps', () => {
    const items = buildCaseEntryReadiness({
      description: '现场发现涉油线索，准备补录奖励核算口径。',
      bonus_has_vehicle: true,
      bonus_has_person: true,
      initial_vehicles: [{}],
      initial_persons: [{}],
    })

    const bonusItem = items.find(item => item.key === 'bonus_accounting')
    expect(bonusItem?.status).toBe('attention')
    expect(bonusItem?.impact).toContain('车辆考核类别')
    expect(bonusItem?.impact).toContain('人员处理类型')
  })

  it('does not let description keywords replace explicit bonus draft fields', () => {
    const items = buildCaseEntryReadiness({
      description: '现场查扣电动车1台，人员已行政拘留，准备录入核算口径。',
      bonus_has_vehicle: true,
      bonus_has_person: true,
      initial_vehicles: [{}],
      initial_persons: [{}],
    })

    const bonusItem = items.find(item => item.key === 'bonus_accounting')
    expect(bonusItem?.status).toBe('attention')
    expect(bonusItem?.impact).toContain('车辆考核类别')
    expect(bonusItem?.impact).toContain('人员处理类型')
  })
})
