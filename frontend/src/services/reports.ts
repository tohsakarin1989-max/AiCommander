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
  list: async (params?: { skip?: number; limit?: number }): Promise<ReportListItem[]> => {
    const response = await api.get<ReportListItem[]>('/reports/', { params })
    return response.data
  },

  get: async (id: number): Promise<ReportListItem> => {
    const response = await api.get<ReportListItem>(`/reports/${id}`)
    return response.data
  },
}
