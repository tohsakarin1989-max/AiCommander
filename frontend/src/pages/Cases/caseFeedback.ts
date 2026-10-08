import type { Case } from '../../types'

export const feedbackFields = ['police_reported', 'case_filed'] as const
export type FeedbackField = typeof feedbackFields[number]
type FeedbackSource = Pick<Case, FeedbackField | 'feedback_known_fields'>

/** A historical boolean without a knowledge marker is not a verified answer. */
export function knownFeedbackValue(source: FeedbackSource, field: FeedbackField): boolean | null {
  return source.feedback_known_fields?.includes(field) && typeof source[field] === 'boolean' ? source[field]! : null
}

export function feedbackDescription(source: FeedbackSource, field: FeedbackField): string {
  const known = knownFeedbackValue(source, field)
  if (known !== null) return field === 'police_reported' ? (known ? '已报案' : '明确未报案') : (known ? '已立案' : '明确未立案')
  const label = field === 'police_reported' ? '报案情况未知' : '立案情况未获反馈'
  return typeof source[field] === 'boolean'
    ? `${label}（旧记录${source[field] ? '为是' : '为否'}，来源未确认）` : label
}

export function changedFeedbackFields(current: unknown, field: FeedbackField): FeedbackField[] {
  return [...new Set([...(Array.isArray(current) ? current.filter(value => feedbackFields.includes(value)) : []), field])]
}

export function feedbackFormChoice(values: Record<string, unknown>, field: FeedbackField): 'yes' | 'no' | 'unknown' {
  const marked = [values.feedback_changed_fields, values.feedback_initial_known_fields]
    .some(fields => Array.isArray(fields) && fields.includes(field))
  return marked && typeof values[field] === 'boolean' ? values[field] ? 'yes' : 'no' : 'unknown'
}

export function feedbackSubmission(values: Record<string, unknown>, _mode: 'create' | 'edit'): Record<string, boolean | null> {
  const changed = Array.isArray(values.feedback_changed_fields) ? values.feedback_changed_fields : []
  return Object.fromEntries(feedbackFields.flatMap(field => {
    const value = values[field]
    if (!changed.includes(field)) return []
    return [[field, typeof value === 'boolean' ? value : null]]
  }))
}
