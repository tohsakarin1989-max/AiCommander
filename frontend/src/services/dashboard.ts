import api from './api'

export interface DashboardActivity {
  id: string
  kind: 'case_created' | 'case_updated' | 'task' | 'analysis' | 'result'
  title: string
  recorded_at: string
  case_id: number
  case_number: string
  latitude: number | null
  longitude: number | null
  result_id?: string
  status?: string
  detail?: string
}

export interface DashboardSummary {
  activities?: DashboardActivity[]
  activity_limit?: number
  processing?: Record<'pending' | 'processing' | 'retry' | 'failed', number>
  recent_results?: DashboardActivity[]
  completion?: { completed: number; degraded: number }
  schema_version: number
  operational_area_id: number | null
  as_of: string
  state: 'ready' | 'empty'
  period: { start: string; end: string; previous_start: string; previous_end: string; days: number; timezone: string }
  metrics: { cases: number; previous_cases: number; change: number; registered_wells: number; analysis_results: number }
  definitions: { cases: string; registered_wells: string; analysis_results: string; trend: string }
  trend: { date: string; count: number }[]
  attention_scan?: { limit: number; truncated: boolean; ordering: string }
  attention: { kind: string; case_type: string | null; title: string; current_count?: number; previous_count?: number;
    id?: string; run_id?: string; claim?: string; rule_support?: number;
    supporting_evidence?: string[]; counter_evidence?: string[]; information_gaps?: string[]; evidence_refs?: string[];
    case_profile_id?: string; map_snapshot_id?: string; algorithm_version?: string;
    evidence: { case_id: number; case_number: string; latitude: number | null; longitude: number | null }[]; boundary: string }[]
  map: {
    cases: { id: number; case_number: string; latitude: number; longitude: number; case_type: string | null }[]
    wells: { id: number; name: string; latitude: number; longitude: number }[]
    coordinate_cases: number; missing_coordinate_cases: number; coordinate_wells: number
    cases_truncated: boolean; wells_truncated: boolean
  }
}

export async function getDashboardSummary(areaId: number, days: number, signal?: AbortSignal, activityLimit = 20): Promise<DashboardSummary> {
  return (await api.get<DashboardSummary>('/cases/dashboard-summary', {
    params: { operational_area_id: areaId, days, activity_limit: activityLimit }, signal,
  })).data
}
