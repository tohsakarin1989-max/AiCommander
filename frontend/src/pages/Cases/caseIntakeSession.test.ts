import { describe, expect, it } from 'vitest'
import { mergeIntakeCandidates, restoreIntakeDescription, intakeSessionState } from './caseIntakeSession'

describe('single-source intake session', () => {
  it('fills blanks but never replaces manual facts, explicit false or zero', () => {
    const result = mergeIntakeCandidates({ description: '原始全文', location: '手工地点', oil_volume: 0, police_reported: false },
      { description: '自动摘要', location: '提取地点', oil_volume: 2, police_reported: true, case_type: '涉油' }, new Set())
    expect(result.patch).toEqual({ case_type: '涉油' })
    expect(result.conflicts.map(item => item.field)).toEqual(['location', 'oil_volume', 'police_reported'])
  })
  it('preserves manually cleared fields and populated child collections', () => {
    const result = mergeIntakeCandidates({ location: '', initial_vehicles: [{ plate_number: '已核对' }] },
      { location: '候选', initial_vehicles: [{ plate_number: '提取' }] }, new Set(['location']))
    expect(result.patch).toEqual({})
    expect(result.conflicts).toHaveLength(2)
  })
  it('can fill untouched unknown defaults but does not overwrite explicit unknown', () => {
    expect(mergeIntakeCandidates({ time_precision: 'unknown' }, { time_precision: 'exact' }, new Set()).patch).toEqual({ time_precision: 'exact' })
    expect(mergeIntakeCandidates({ time_precision: 'unknown' }, { time_precision: 'exact' }, new Set(['time_precision'])).patch).toEqual({})
  })
  it('keeps old private auxiliary text recoverable without replacing original description', () => {
    expect(restoreIntakeDescription({ values: { description: '人工原文' }, assistant_text: '旧辅助原文' }).description).toBe('人工原文')
    expect(restoreIntakeDescription({ values: {}, assistant_text: '旧辅助原文' }).description).toBe('旧辅助原文')
  })
  it('does not label pending writes or unacknowledged edits as saved', () => {
    expect(intakeSessionState({ dirty: true, savedAt: '2026-10-09' })).toBe('editing')
    expect(intakeSessionState({ dirty: true, savingDraft: true })).toBe('saving_draft')
    expect(intakeSessionState({ dirty: false, outcomeUnknown: true })).toBe('outcome_unknown')
    expect(intakeSessionState({ dirty: false, savedAt: '2026-10-09' })).toBe('saved')
  })
})
