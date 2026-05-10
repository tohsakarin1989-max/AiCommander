import type { BonusAssessment, Case } from '../../types'

export type CaseBonusGateStatus = 'ready' | 'blocked_by_materials' | 'rules_not_configured' | 'unknown'

export interface CaseBonusRow {
  caseId: number
  caseNumber: string
  location: string
  occurredTime?: string
  reportUnit?: string
  gateStatus: CaseBonusGateStatus
  missingCount: number
  qualityScore?: number | null
  suggestedAmount?: number
  readyForReview?: boolean
  assessmentLoaded: boolean
}

export interface CaseBonusSummary {
  total: number
  ready: number
  blocked: number
  rulesPending: number
  assessed: number
  readyForReview: number
  suggestedAmount: number
}

export function getMissingRequiredCount(caseItem: Case): number {
  return caseItem.quality_issues?.missing_required?.length ?? 0
}

export function inferGateStatus(caseItem: Case, assessment?: BonusAssessment): CaseBonusGateStatus {
  if (assessment) return assessment.material_gate.status
  return getMissingRequiredCount(caseItem) > 0 ? 'blocked_by_materials' : 'ready'
}

export function buildCaseBonusRows(
  cases: Case[],
  assessments: Record<number, BonusAssessment | undefined> = {}
): CaseBonusRow[] {
  return cases.map(caseItem => {
    const assessment = assessments[caseItem.id]
    return {
      caseId: caseItem.id,
      caseNumber: caseItem.case_number || `#${caseItem.id}`,
      location: caseItem.location || '未填写地点',
      occurredTime: caseItem.occurred_time,
      reportUnit: caseItem.report_unit,
      gateStatus: inferGateStatus(caseItem, assessment),
      missingCount: assessment
        ? assessment.material_gate.required_count - assessment.material_gate.satisfied_count
        : getMissingRequiredCount(caseItem),
      qualityScore: caseItem.quality_score,
      suggestedAmount: assessment?.total_suggested_amount,
      readyForReview: assessment?.ready_for_review,
      assessmentLoaded: Boolean(assessment),
    }
  })
}

export function buildCaseBonusSummary(rows: CaseBonusRow[]): CaseBonusSummary {
  return rows.reduce<CaseBonusSummary>((summary, row) => {
    summary.total += 1
    if (row.gateStatus === 'ready') summary.ready += 1
    if (row.gateStatus === 'blocked_by_materials') summary.blocked += 1
    if (row.gateStatus === 'rules_not_configured') summary.rulesPending += 1
    if (row.assessmentLoaded) summary.assessed += 1
    if (row.readyForReview) summary.readyForReview += 1
    summary.suggestedAmount += row.suggestedAmount ?? 0
    return summary
  }, {
    total: 0,
    ready: 0,
    blocked: 0,
    rulesPending: 0,
    assessed: 0,
    readyForReview: 0,
    suggestedAmount: 0,
  })
}
