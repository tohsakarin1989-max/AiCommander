import type { UserRole } from '../../services/auth'
import type { WorkbenchStage, WorkbenchTask } from '../../services/workbench'


export const STAGE_LABELS: Record<WorkbenchStage, string> = {
  data_review: '数据核验',
  experience_generate: '经验生成',
  experience_review: '经验复核',
  report_generate: '报告生成',
  report_review: '报告复核',
  completed: '当前闭环',
}

const STAGE_ORDER: Record<Exclude<WorkbenchStage, 'completed'>, number> = {
  data_review: 0,
  experience_review: 1,
  experience_generate: 2,
  report_review: 3,
  report_generate: 4,
}

const PRIORITY_ORDER = { high: 0, medium: 1, low: 2 }

export function sortWorkbenchTasks(tasks: WorkbenchTask[]): WorkbenchTask[] {
  return [...tasks].sort((left, right) => (
    PRIORITY_ORDER[left.priority] - PRIORITY_ORDER[right.priority]
    || STAGE_ORDER[left.stage] - STAGE_ORDER[right.stage]
    || right.source_id - left.source_id
  ))
}

export function getTaskActionLabel(role: UserRole, task: WorkbenchTask): string {
  if (role === 'viewer') return '查看依据'
  if (task.stage.endsWith('_review') || task.stage === 'data_review') return '开始复核'
  return '开始处理'
}

export function buildPipelineProgress(summary: Pick<{ total_cases: number; completed: number }, 'total_cases' | 'completed'>) {
  if (!summary.total_cases) return { percent: 0, label: '暂无案件样本' }
  return {
    percent: Math.round(summary.completed / summary.total_cases * 100),
    label: `${summary.completed} / ${summary.total_cases} 起完成当前闭环`,
  }
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return '待积累'
  if (seconds < 60) return `${seconds}秒`
  const minutes = Math.floor(seconds / 60)
  const remaining = seconds % 60
  return `${minutes}分${String(remaining).padStart(2, '0')}秒`
}

export function shouldRecordPageTransition(lastPath: string, currentPath: string): boolean {
  return currentPath !== '/workbench' && currentPath !== lastPath
}
