import { describe, expect, it } from 'vitest'
import type { WorkbenchTask } from '../../services/workbench'
import {
  STAGE_LABELS,
  buildPipelineProgress,
  formatDuration,
  getTaskActionLabel,
  shouldRecordPageTransition,
  sortWorkbenchTasks,
} from './workbenchPresentation'

function task(patch: Partial<WorkbenchTask>): WorkbenchTask {
  return {
    id: patch.id || 'case:1:data_review',
    task_type: patch.task_type || 'data_review',
    source_type: 'case',
    source_id: patch.source_id || 1,
    case_number: patch.case_number || 'WB-001',
    stage: patch.stage || 'data_review',
    priority: patch.priority || 'medium',
    title: patch.title || '补齐案件数据',
    why: patch.why || '关键字段缺失',
    impact: patch.impact || '影响后续研判',
    next_action: patch.next_action || '进入案件页核验',
    target_path: patch.target_path || '/cases?caseId=1',
    evidence_refs: patch.evidence_refs || ['case:1'],
  }
}

describe('workbenchPresentation', () => {
  it('uses business-stage labels and keeps every action under human control', () => {
    expect(STAGE_LABELS.data_review).toBe('数据核验')
    expect(STAGE_LABELS.experience_review).toBe('经验复核')
    expect(STAGE_LABELS.report_review).toBe('报告复核')
    expect(Object.values(STAGE_LABELS).join(' ')).not.toContain('自动处置')
    expect(getTaskActionLabel('viewer', task({}))).toBe('查看依据')
    expect(getTaskActionLabel('analyst', task({ stage: 'report_review' }))).toBe('开始复核')
  })

  it('sorts urgent data gaps before later workflow stages', () => {
    const ordered = sortWorkbenchTasks([
      task({ id: 'report', stage: 'report_generate', priority: 'medium' }),
      task({ id: 'draft', stage: 'experience_review', priority: 'high' }),
      task({ id: 'data', stage: 'data_review', priority: 'high' }),
    ])

    expect(ordered.map(item => item.id)).toEqual(['data', 'draft', 'report'])
  })

  it('builds progress from completed and actionable case counts without false precision', () => {
    expect(buildPipelineProgress({ total_cases: 8, completed: 2 })).toEqual({
      percent: 25,
      label: '2 / 8 起完成当前闭环',
    })
    expect(buildPipelineProgress({ total_cases: 0, completed: 0 })).toEqual({
      percent: 0,
      label: '暂无案件样本',
    })
  })

  it('formats measured time as an operational duration', () => {
    expect(formatDuration(42)).toBe('42秒')
    expect(formatDuration(125)).toBe('2分05秒')
    expect(formatDuration(null)).toBe('待积累')
  })

  it('does not count the workbench control surface as a task transition', () => {
    expect(shouldRecordPageTransition('/cases', '/workbench')).toBe(false)
    expect(shouldRecordPageTransition('/cases', '/cases')).toBe(false)
    expect(shouldRecordPageTransition('/cases', '/reports')).toBe(true)
  })
})
