import type { TrajectoryReview } from '../../types'

export function summarizeTrajectoryReview(review: TrajectoryReview) {
  return {
    title: '路径条件复盘',
    factCount: review.facts.length,
    conditionCount: review.path_conditions.length,
    inferenceCount: review.inferences.length,
    gapCount: review.information_gaps.length,
    suggestionCount: review.reusable_suggestions.length,
    boundary: review.boundary,
    deprecated: Boolean(review.deprecated),
  }
}
