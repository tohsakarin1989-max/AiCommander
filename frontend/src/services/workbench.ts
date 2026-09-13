import api from './api'

export interface DailyWorkbenchCase {
  id: number
  case_number: string
  occurred_time: string | null
  location: string | null
  case_status: string
  pipeline_status: string | null
  profile_ready: boolean
  information_gaps: string[]
  target_path: string
}

export interface DailyWorkbench {
  schema_version: 'daily-workbench-5.0-1'
  generated_at: string
  summary: {
    total_cases: number
    needs_information: number
    analysis_pending: number
    analysis_ready: number
  }
  cases: DailyWorkbenchCase[]
  pagination: { limit: number; offset: number; returned: number; total: number }
}

export type WorkbenchStage =
  | 'data_review'
  | 'experience_generate'
  | 'experience_review'
  | 'report_generate'
  | 'report_review'
  | 'completed'

export interface WorkbenchTask {
  id: string
  task_type: Exclude<WorkbenchStage, 'completed'>
  source_type: 'case'
  source_id: number
  case_number: string
  stage: Exclude<WorkbenchStage, 'completed'>
  priority: 'high' | 'medium' | 'low'
  title: string
  why: string
  impact: string
  next_action: string
  target_path: string
  evidence_refs: string[]
}

export interface WorkbenchSession {
  id: string
  task_type: WorkbenchTask['task_type']
  source_type: 'case'
  source_id: number | null
  status: 'active' | 'completed' | 'abandoned'
  entry_path: string
  last_path: string
  page_transitions: number
  started_at: string
  last_activity_at: string
  completed_at: string | null
}

export interface WorkbenchSummary {
  total_cases: number
  actionable_cases: number
  data_review: number
  experience_review: number
  report_review: number
  completed: number
  pending_approvals: number
}

export interface TodayWorkbench {
  generated_at: string
  role: 'admin' | 'analyst' | 'viewer'
  can_track_work: boolean
  summary: WorkbenchSummary
  pipeline: { stage: WorkbenchStage; label: string; count: number }[]
  tasks: WorkbenchTask[]
  active_session: WorkbenchSession | null
  boundary: string
}

export interface WorkbenchMetricBlock {
  started: number
  completed: number
  abandoned: number
  active: number
  completion_rate: number
  avg_duration_seconds: number | null
  avg_page_transitions: number | null
}

export interface WorkbenchMetrics {
  scope: 'self' | 'team'
  days: number
  totals: WorkbenchMetricBlock
  by_task_type: Array<{ task_type: WorkbenchTask['task_type'] } & WorkbenchMetricBlock>
  business_acceptance_status: 'measurable' | 'insufficient_sample'
  sample_threshold: number
  measurement_boundary: string
}

export const workbenchApi = {
  daily: async (params: { limit?: number; offset?: number } = {}): Promise<DailyWorkbench> => {
    const response = await api.get<DailyWorkbench>('/workbench/daily', { params })
    return response.data
  },
  today: async (): Promise<TodayWorkbench> => {
    const response = await api.get<TodayWorkbench>('/workbench/today')
    return response.data
  },
  activeSession: async (): Promise<WorkbenchSession | null> => {
    const response = await api.get<WorkbenchSession | null>('/workbench/sessions/active')
    return response.data
  },
  startSession: async (task: WorkbenchTask): Promise<{ created: boolean; session: WorkbenchSession }> => {
    const response = await api.post<{ created: boolean; session: WorkbenchSession }>('/workbench/sessions', {
      task_type: task.task_type,
      source_type: task.source_type,
      source_id: task.source_id,
      entry_path: task.target_path,
    })
    return response.data
  },
  recordEvent: async (
    sessionId: string,
    event: 'page_view' | 'completed' | 'abandoned',
    path?: string,
  ): Promise<WorkbenchSession> => {
    const response = await api.post<WorkbenchSession>(`/workbench/sessions/${sessionId}/events`, {
      event,
      path,
    })
    return response.data
  },
  metrics: async (days = 30): Promise<WorkbenchMetrics> => {
    const response = await api.get<WorkbenchMetrics>('/workbench/metrics', { params: { days } })
    return response.data
  },
}
