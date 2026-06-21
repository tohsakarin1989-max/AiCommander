import { describe, expect, it } from 'vitest'
import type { BonusAssessment, Case } from '../../types'
import {
  buildBonusManagementDisplay,
  buildMissingMaterialDetails,
  buildCaseBonusRows,
  buildCaseBonusSummary,
  getMissingRequiredCount,
  inferGateStatus,
} from './caseBonusAccountingModel'

const baseCase = (id: number, patch: Partial<Case> = {}): Case => ({
  id,
  case_number: `CASE-${id}`,
  occurred_time: '2026-05-01T00:00:00.000Z',
  status: 'pending',
  ...patch,
})

const assessment = (caseId: number, patch: Partial<BonusAssessment> = {}): BonusAssessment => ({
  case_id: caseId,
  case_number: `CASE-${caseId}`,
  rules_version: 'test',
  rules_configured: true,
  material_gate: {
    status: 'ready',
    required_count: 3,
    satisfied_count: 3,
    missing_materials: [],
  },
  calculation_gate: {
    status: 'ready',
    missing_items: [],
  },
  material_checks: [],
  bonus_items: [],
  total_suggested_amount: 1200,
  ready_for_review: true,
  manual_review_required: true,
  boundary: '测试',
  ...patch,
})

describe('caseBonusAccountingModel', () => {
  it('infers material gate status from case quality gaps before assessment is loaded', () => {
    const clean = baseCase(1, {
      quality_issues: { score: 90, level: 'high', category_scores: {}, missing_required: [], warnings: [], recommendations: [], facts: {} },
    })
    const blocked = baseCase(2, {
      quality_issues: {
        score: 55,
        level: 'low',
        category_scores: {},
        missing_required: [{ field: 'vehicle_transfer', label: '车辆移交单据', reason: '奖金考核佐证' }],
        warnings: [],
        recommendations: [],
        facts: {},
      },
    })

    expect(getMissingRequiredCount(blocked)).toBe(1)
    expect(inferGateStatus(clean)).toBe('ready')
    expect(inferGateStatus(blocked)).toBe('blocked_by_materials')
  })

  it('uses official assessment status and totals when a selected case has been calculated', () => {
    const rows = buildCaseBonusRows([
      baseCase(1),
      baseCase(2),
    ], {
      2: assessment(2, {
        material_gate: {
          status: 'rules_not_configured',
          required_count: 3,
          satisfied_count: 3,
          missing_materials: [],
        },
        total_suggested_amount: 0,
        ready_for_review: false,
      }),
    })
    const summary = buildCaseBonusSummary(rows)

    expect(rows.find(row => row.caseId === 2)?.gateStatus).toBe('rules_not_configured')
    expect(summary.total).toBe(2)
    expect(summary.ready).toBe(1)
    expect(summary.rulesPending).toBe(1)
    expect(summary.suggestedAmount).toBe(0)
  })

  it('prioritizes calculation data gaps over evidence material gaps', () => {
    const rows = buildCaseBonusRows([
      baseCase(3),
    ], {
      3: assessment(3, {
        material_gate: {
          status: 'ready',
          required_count: 3,
          satisfied_count: 3,
          missing_materials: [],
        },
        calculation_gate: {
          status: 'blocked_by_data',
          missing_items: [
            { key: 'person_disposition', label: '人员处理类型', detail: '缺少行政拘留、刑事拘留等处理结果' },
          ],
        },
        total_suggested_amount: 0,
        ready_for_review: false,
      }),
    })

    expect(rows[0].gateStatus).toBe('blocked_by_data')
    expect(rows[0].missingCount).toBe(1)
  })

  it('separates loaded assessment totals from inferred case-list status', () => {
    const rows = buildCaseBonusRows([
      baseCase(1),
      baseCase(2),
    ], {
      2: assessment(2),
    })
    const summary = buildCaseBonusSummary(rows)

    expect(rows.find(row => row.caseId === 1)?.assessmentLoaded).toBe(false)
    expect(rows.find(row => row.caseId === 2)?.assessmentLoaded).toBe(true)
    expect(summary.assessed).toBe(1)
    expect(summary.readyForReview).toBe(1)
    expect(summary.suggestedAmount).toBe(1200)
  })

  it('builds clear required material gap details for blocked assessments', () => {
    const gaps = buildMissingMaterialDetails(assessment(3, {
      material_gate: {
        status: 'blocked_by_materials',
        required_count: 3,
        satisfied_count: 1,
        missing_materials: ['检斤含水单据', '车辆移交单据'],
      },
      material_checks: [
        {
          requirement_key: 'weigh_water_document',
          label: '检斤含水单据',
          category: 'oil',
          required: true,
          status: 'missing',
          trigger_reason: '存在涉案油量、含水率或涉油处置记录',
          note: '缺少佐证材料',
        },
        {
          requirement_key: 'vehicle_transfer_document',
          label: '车辆移交单据',
          category: 'vehicle',
          required: true,
          status: 'partial',
          trigger_reason: '案件包含查扣车辆或车辆移交处置',
          note: '仅登记材料名称，缺少附件或档案号',
        },
        {
          requirement_key: 'police_case_document',
          label: '报案/立案/公安接收材料',
          category: 'police',
          required: false,
          status: 'not_required',
          note: '当前案件信息未触发该材料要求',
        },
      ],
    }))

    expect(gaps).toEqual([
      {
        key: 'weigh_water_document',
        label: '检斤含水单据',
        status: 'missing',
        category: 'oil',
        reason: '存在涉案油量、含水率或涉油处置记录',
        action: '缺少佐证材料',
      },
      {
        key: 'vehicle_transfer_document',
        label: '车辆移交单据',
        status: 'partial',
        category: 'vehicle',
        reason: '案件包含查扣车辆或车辆移交处置',
        action: '仅登记材料名称，缺少附件或档案号',
      },
    ])
  })

  it('builds period management display so a case amount is tied to quarter and annual indicators', () => {
    const display = buildBonusManagementDisplay({
      period_type: 'quarter',
      rules_version: '2026_official_workbook',
      pricing_basis: '按案件发生时间所属季度指标判断高低档，单案金额进入该周期人工复核，不代表直接发放。',
      case_amount_status: 'provisional',
      selected_case_amount: 4500,
      primary_squad: '案件三班',
      period: {
        year: 2026,
        quarter: 2,
        quarter_label: '2026年Q2',
        annual_label: '2026年度',
      },
      quarter: {
        start: '2026-04-01T00:00:00',
        end: '2026-07-01T00:00:00',
        case_count: 6,
        vehicle_actual: 2,
        vehicle_target: 1,
        vehicle_remaining: 0,
        vehicle_high: true,
        person_actual: 1,
        person_target: 1,
        person_remaining: 0,
        person_high: false,
      },
      annual: {
        start: '2026-01-01T00:00:00',
        end: '2027-01-01T00:00:00',
        case_count: 18,
        vehicle_actual: 5,
        vehicle_target: 4,
        vehicle_remaining: 0,
        vehicle_high: true,
        person_actual: 3,
        person_target: 4,
        person_remaining: 1,
        person_high: false,
      },
    })

    expect(display?.quarterLabel).toBe('2026年Q2')
    expect(display?.annualLabel).toBe('2026年度')
    expect(display?.amountStatus).toBe('周期内预估')
    expect(display?.quarterMetrics[0]).toEqual({
      label: '车辆指标',
      actual: 2,
      target: 1,
      remaining: 0,
      high: true,
    })
    expect(display?.annualMetrics[1].remaining).toBe(1)
    expect(display?.pricingBasis).toContain('不代表直接发放')
  })
})
