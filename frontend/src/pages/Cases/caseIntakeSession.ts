export interface IntakeConflict { field: string; current: unknown; proposed: unknown }

function empty(value: unknown): boolean {
  return value == null || (typeof value === 'string' && !value.trim()) || (Array.isArray(value) && value.length === 0)
}

/** Candidates may fill omissions, never replace the single original narrative or an operator's choice. */
export function mergeIntakeCandidates(current: Record<string, unknown>, candidates: Record<string, unknown>, manualFields: Set<string>) {
  const patch: Record<string, unknown> = {}, conflicts: IntakeConflict[] = []
  for (const [field, proposed] of Object.entries(candidates)) {
    if (field === 'description' || empty(proposed)) continue
    const value = current[field]
    const unchosenDefault = (['time_precision', 'oil_volume_unit'].includes(field) && value === 'unknown')
      || (field.startsWith('bonus_has_') && value === false)
    if (!manualFields.has(field) && (empty(value) || unchosenDefault)) patch[field] = proposed
    else if (JSON.stringify(value) !== JSON.stringify(proposed)) conflicts.push({ field, current: value, proposed })
  }
  return { patch, conflicts }
}

/** v7/v8 drafts may contain an auxiliary original. Keep it if no primary narrative exists. */
export function restoreIntakeDescription(snapshot: Record<string, unknown>): Record<string, unknown> {
  const values = { ...(snapshot.values as Record<string, unknown> || {}) }
  if (empty(values.description) && typeof snapshot.assistant_text === 'string') values.description = snapshot.assistant_text
  return values
}

export type IntakeSessionState = 'editing' | 'saving_draft' | 'submitting' | 'outcome_unknown' | 'saved' | 'conflict'
export function intakeSessionState(input: { dirty: boolean; savingDraft?: boolean; submitting?: boolean; outcomeUnknown?: boolean; conflict?: boolean; savedAt?: string }): IntakeSessionState {
  if (input.conflict) return 'conflict'
  if (input.submitting) return 'submitting'
  if (input.outcomeUnknown) return 'outcome_unknown'
  if (input.savingDraft) return 'saving_draft'
  return !input.dirty && input.savedAt ? 'saved' : 'editing'
}
