import { describe, expect, it } from 'vitest'
import {
  ACTION_LABELS,
  TYPE_LABELS,
  WORKFLOW_FILTERS,
  buildSuggestionDetail,
  buildSuggestionStats,
  filterSuggestions,
  filterSuggestionsByWorkflow,
  getSuggestionWorkflowBucket,
  getSuggestionRoute,
} from './suggestionPresentation'
import type { WorkSuggestion } from '../../services/suggestions'

const base = {
  priority: 'medium',
  status: 'open',
  created_at: '2026-06-04T10:00:00',
  target_type: 'case',
} satisfies Partial<WorkSuggestion>

function suggestion(patch: Partial<WorkSuggestion>): WorkSuggestion {
  return {
    id: patch.id || 's1',
    type: patch.type || 'analysis',
    title: patch.title || '待办',
    description: patch.description || '描述',
    target_id: patch.target_id ?? 1,
    action: patch.action || 'open_case',
    ...base,
    ...patch,
  } as WorkSuggestion
}

describe('suggestionPresentation', () => {
  it('labels upgraded suggestion types and safe actions without patrol dispatch wording', () => {
    expect(TYPE_LABELS.bonus).toBe('奖金核算')
    expect(TYPE_LABELS.alert).toBe('数智告警')
    expect(TYPE_LABELS.experience).toBe('经验卡')
    expect(TYPE_LABELS.report_quality).toBe('报告质量')
    expect(TYPE_LABELS.processing_card).toBe('案件处理卡')
    expect(ACTION_LABELS.review_processing_card).toBe('查看处理卡')
    expect(ACTION_LABELS.review_prevention_reference).toBe('查看防控参考')
    expect(Object.values(ACTION_LABELS).join(' ')).not.toContain('生成巡逻')
    expect(Object.values(TYPE_LABELS).join(' ')).not.toContain('巡逻部署')
  })

  it('builds priority and category stats for the review queue', () => {
    const items = [
      suggestion({ id: 'bonus', type: 'bonus', priority: 'high' }),
      suggestion({ id: 'alert', type: 'alert', priority: 'medium' }),
      suggestion({ id: 'exp', type: 'experience', priority: 'low' }),
    ]

    const stats = buildSuggestionStats(items)

    expect(stats.total).toBe(3)
    expect(stats.priority.high).toBe(1)
    expect(stats.type.bonus).toBe(1)
    expect(filterSuggestions(items, 'alert')).toHaveLength(1)
  })

  it('routes only to low-risk review and navigation surfaces', () => {
    expect(getSuggestionRoute(suggestion({ action: 'review_bonus_data', target_id: 188 }))).toBe('/cases/bonus?caseId=188')
    expect(getSuggestionRoute(suggestion({ action: 'review_conclusion', target_id: 12 }))).toBe('/conclusions?conclusionId=12')
    expect(getSuggestionRoute(suggestion({ action: 'open_alert_triage_pack', target_id: 9 }))).toBe('/intelli-inspect?alertId=9')
    expect(getSuggestionRoute(suggestion({ action: 'review_experience_card', target_id: 7 }))).toBe('/case-intelligence?caseId=7')
    expect(getSuggestionRoute(suggestion({ action: 'review_processing_card', target_id: 188 }))).toBe('/cases?caseId=188')
    expect(getSuggestionRoute(suggestion({ action: 'review_prevention_reference', target_id: '萨中北线' }))).toBe('/case-intelligence?area=%E8%90%A8%E4%B8%AD%E5%8C%97%E7%BA%BF')
    expect(getSuggestionRoute(suggestion({ action: 'create_patrol', target_id: '萨中北线' }))).toBeNull()
  })

  it('classifies work items into business workflow buckets for the left rail', () => {
    const bonusMetric = suggestion({
      type: 'bonus',
      action: 'review_bonus_data',
      title: '车辆考核类别缺失',
      description: '关键核算指标缺失，整案暂不测算。',
    })
    const materialGap = suggestion({
      type: 'bonus',
      action: 'review_bonus_materials',
      title: '检斤含水单据缺失',
      description: '佐证材料缺口，补齐后进入人工复核。',
    })
    const alert = suggestion({ type: 'alert', action: 'open_alert_triage_pack', title: '数智告警待核查' })

    expect(WORKFLOW_FILTERS.map(filter => filter.label)).toContain('奖金核算指标缺口')
    expect(getSuggestionWorkflowBucket(bonusMetric)).toBe('bonus_metric_gap')
    expect(getSuggestionWorkflowBucket(materialGap)).toBe('bonus_material_gap')
    expect(getSuggestionWorkflowBucket(alert)).toBe('alert')
    expect(filterSuggestionsByWorkflow([bonusMetric, materialGap, alert], 'bonus_metric_gap')).toEqual([bonusMetric])
  })

  it('builds a review detail panel with fact inference suggestion and boundary sections', () => {
    const item = suggestion({
      id: 'b1',
      type: 'bonus',
      priority: 'high',
      action: 'review_bonus_data',
      target_id: 188,
      title: '车辆考核类别缺失',
      description: '已出现车辆线索，但未明确摩托车、5吨以下、5吨以上等车辆考核类别。',
    })

    const detail = buildSuggestionDetail(item)

    expect(detail.targetLabel).toBe('case:188')
    expect(detail.facts.join(' ')).toContain('车辆考核类别缺失')
    expect(detail.inferences.join(' ')).toContain('高优先级')
    expect(detail.suggestions.join(' ')).toContain('进入奖金核算')
    expect(detail.boundary).toContain('仅供人工复核')
    expect(detail.boundary).not.toContain('生成巡逻')
  })
})
