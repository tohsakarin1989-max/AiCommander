import api from './api'
import type { MeetingReport } from '../types'

export interface ReportListItem extends MeetingReport {
  id: number
  report_type?: string
  draft_status?: string
  review_status?: string
  model_status?: string
  created_at?: string
}

export const reportApi = {
  statistics: async (): Promise<{ total_reports: number; covered_cases: number; report_meetings: number;
    scope: string; cutoff: string; complete: boolean; counting_rule: string }> => {
    const response = await api.get('/reports/statistics')
    return response.data
  },
  list: async (params?: { skip?: number; limit?: number }): Promise<ReportListItem[]> => {
    const response = await api.get<ReportListItem[]>('/reports/', { params })
    return response.data
  },

  get: async (id: number): Promise<ReportListItem> => {
    const response = await api.get<ReportListItem>(`/reports/${id}`)
    return response.data
  },
}
