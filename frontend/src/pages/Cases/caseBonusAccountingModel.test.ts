import { describe, expect, it } from 'vitest'
import type { BonusAssessment, Case } from '../../types'
import {
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
})
