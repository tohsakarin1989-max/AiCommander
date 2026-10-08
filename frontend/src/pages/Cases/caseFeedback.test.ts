import { describe, expect, it } from 'vitest'
import { changedFeedbackFields, feedbackDescription, feedbackFormChoice, feedbackSubmission, knownFeedbackValue } from './caseFeedback'
import { restoreEntryValues, serializeEntryValues } from './caseDraftSnapshot'

describe('反馈已知性与安全提交', () => {
  it('旧是/否无来源标记均保留未知，明确标记的否才显示未报案', () => {
    expect(knownFeedbackValue({ police_reported: false }, 'police_reported')).toBeNull()
    expect(knownFeedbackValue({ case_filed: true }, 'case_filed')).toBeNull()
    expect(feedbackDescription({ police_reported: false }, 'police_reported')).toContain('旧记录为否，来源未确认')
    expect(feedbackDescription({ police_reported: false, feedback_known_fields: ['police_reported'] }, 'police_reported')).toBe('明确未报案')
    expect(feedbackDescription({ case_filed: false, feedback_known_fields: [] }, 'case_filed')).toContain('立案情况未获反馈')
  })
  it('编辑未触碰的旧布尔值不发送，清空反馈发送null', () => {
    expect(feedbackSubmission({ police_reported: false, case_filed: true }, 'edit')).toEqual({})
    expect(feedbackSubmission({ police_reported: false, case_filed: null, feedback_changed_fields: ['police_reported', 'case_filed'] }, 'edit'))
      .toEqual({ police_reported: false, case_filed: null })
    expect(feedbackSubmission({ police_reported: null }, 'create')).toEqual({})
  })
  it('旧草稿原始布尔值不误当确认，已确认原记录和本轮选择显示明确值', () => {
    expect(feedbackFormChoice({ police_reported: false }, 'police_reported')).toBe('unknown')
    expect(feedbackFormChoice({ police_reported: false, feedback_initial_known_fields: ['police_reported'] }, 'police_reported')).toBe('no')
    expect(feedbackFormChoice({ police_reported: true, feedback_changed_fields: ['police_reported'] }, 'police_reported')).toBe('yes')
    expect(feedbackSubmission({ police_reported: false, case_filed: true }, 'create')).toEqual({})
  })
  it('明确选择与未知值可以往返私有草稿，不把清单发给正式接口', () => {
    const fields = changedFeedbackFields(changedFeedbackFields([], 'police_reported'), 'police_reported')
    expect(fields).toEqual(['police_reported'])
    const values = { police_reported: null, feedback_changed_fields: fields, entry_location_role: 'discovery' }
    expect(restoreEntryValues(serializeEntryValues(values))).toEqual(values)
  })
})
