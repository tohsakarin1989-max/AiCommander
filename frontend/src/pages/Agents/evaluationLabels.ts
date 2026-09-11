import type { EvaluationLabel, EvaluationLabels } from '../../services/governance'

export type LabelDraft = { state: 'unlabeled' | 'negative' | 'positive'; labels: EvaluationLabel[] }
export function existingLabel(data: EvaluationLabels, id: number): LabelDraft {
  return data.ground_truth[String(id)]?.length ? { state: 'positive', labels: data.ground_truth[String(id)] }
    : { state: data.negative_case_ids.includes(id) ? 'negative' : 'unlabeled', labels: [] }
}
export function labelPayload(data: EvaluationLabels, drafts: Record<number, LabelDraft>) {
  const ground_truth: Record<string, EvaluationLabel[]> = {}
  const negative_case_ids: number[] = []
  for (const id of data.case_ids) {
    const draft = drafts[id] || existingLabel(data, id)
    if (draft.state === 'negative') negative_case_ids.push(id)
    if (draft.state === 'positive') {
      if (!draft.labels.length || draft.labels.some(label => !label.expected_asset_ids.length && !label.expected_region_grid?.trim()))
        throw new Error('positive_label_requires_verified_target')
      ground_truth[String(id)] = draft.labels
    }
  }
  return { ground_truth, negative_case_ids }
}
