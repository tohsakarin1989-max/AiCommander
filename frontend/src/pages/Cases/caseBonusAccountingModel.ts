import type { BonusAssessment, BonusManagementContext, BonusManagementPeriodMetrics, Case } from '../../types'

export type CaseBonusGateStatus = 'ready' | 'blocked_by_data' | 'blocked_by_materials' | 'rules_not_configured' | 'unknown'

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

export interface MissingMaterialDetail {
  key: string
  label: string
  status: 'missing' | 'partial'
  category: string
  reason: string
  action: string
}

export interface BonusManagementMetricDisplay {
  label: string
  actual: number
  target: number
  remaining: number
  high: boolean
}

export interface BonusManagementDisplay {
  quarterLabel: string
  annualLabel: string
  primarySquad: string
  rulesVersion: string
  selectedCaseAmount: number
  amountStatus: string
  pricingBasis: string
  quarterCases: number
  annualCases: number
  quarterMetrics: BonusManagementMetricDisplay[]
  annualMetrics: BonusManagementMetricDisplay[]
}

export function getMissingRequiredCount(caseItem: Case): number {
  return caseItem.quality_issues?.missing_required?.length ?? 0
}

export function inferGateStatus(caseItem: Case, assessment?: BonusAssessment): CaseBonusGateStatus {
  if (assessment?.calculation_gate?.status === 'blocked_by_data') return 'blocked_by_data'
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
        ? assessment.calculation_gate?.status === 'blocked_by_data'
          ? assessment.calculation_gate.missing_items.length
          : assessment.material_gate.required_count - assessment.material_gate.satisfied_count
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
    if (row.gateStatus === 'blocked_by_data') summary.blocked += 1
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

export function buildMissingMaterialDetails(assessment: BonusAssessment): MissingMaterialDetail[] {
  const missingLabels = new Set(assessment.material_gate.missing_materials)
  return assessment.material_checks
    .filter((item): item is typeof item & { status: MissingMaterialDetail['status'] } => (
      item.required && (item.status === 'missing' || item.status === 'partial')
    ))
    .filter(item => missingLabels.size === 0 || missingLabels.has(item.label) || item.status === 'partial')
    .map(item => ({
      key: item.requirement_key,
      label: item.label,
      status: item.status,
      category: item.category,
      reason: item.trigger_reason || '奖金考核规则要求提供该项佐证',
      action: item.note || (item.status === 'partial' ? '已登记但材料不完整，请补齐附件或档案号。' : '缺少佐证材料，请补录后再复核。'),
    }))
}

function buildManagementMetrics(metrics: BonusManagementPeriodMetrics): BonusManagementMetricDisplay[] {
  return [
    {
      label: '车辆指标',
      actual: metrics.vehicle_actual,
      target: metrics.vehicle_target,
      remaining: metrics.vehicle_remaining,
      high: metrics.vehicle_high,
    },
    {
      label: '人员指标',
      actual: metrics.person_actual,
      target: metrics.person_target,
      remaining: metrics.person_remaining,
      high: metrics.person_high,
    },
  ]
}

export function buildBonusManagementDisplay(context?: BonusManagementContext): BonusManagementDisplay | null {
  if (!context) return null
  return {
    quarterLabel: context.period.quarter_label,
    annualLabel: context.period.annual_label,
    primarySquad: context.primary_squad || '未识别主控班组',
    rulesVersion: context.rules_version || '未配置版本',
    selectedCaseAmount: context.selected_case_amount,
    amountStatus: context.case_amount_status === 'provisional' ? '周期内预估' : '暂未测算',
    pricingBasis: context.pricing_basis,
    quarterCases: context.quarter.case_count,
    annualCases: context.annual.case_count,
    quarterMetrics: buildManagementMetrics(context.quarter),
    annualMetrics: buildManagementMetrics(context.annual),
  }
}
