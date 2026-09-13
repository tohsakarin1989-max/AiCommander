import api from './api'

export type SuggestionPriority = 'high' | 'medium' | 'low'
export type SuggestionWorkflow = 'all' | 'coordinate_gap' | 'data_quality' | 'processing_card'
  | 'bonus_metric_gap' | 'bonus_material_gap' | 'alert' | 'conclusion_review'
  | 'report_followup' | 'experience' | 'event_review' | 'area_reference'
export type SuggestionType =
  | 'data_quality'
  | 'analysis'
  | 'review'
  | 'workflow'
  | 'bonus'
  | 'alert'
  | 'experience'
  | 'report_quality'
  | 'processing_card'

export type SuggestionAction =
  | 'open_case'
  | 'preprocess_case'
  | 'review_conclusion'
  | 'convert_event_to_case'
  | 'generate_conclusion_from_meeting'
  | 'open_analysis_package'
  | 'review_bonus_data'
  | 'review_bonus_materials'
  | 'open_alert_triage_pack'
  | 'review_experience_card'
  | 'generate_experience_card'
  | 'review_processing_card'
  | 'review_prevention_reference'
  | string

export interface WorkSuggestion {
  id: string
  type: SuggestionType | string
  priority: SuggestionPriority
  title: string
  description: string
  target_type: 'case' | 'event' | 'conclusion' | 'meeting' | 'area' | 'alert' | string
  target_id: number | string
  action: SuggestionAction
  status: string
  created_at: string
  meta?: Record<string, unknown>
  workflow?: Exclude<SuggestionWorkflow, 'all'>
}

export interface SuggestionsResponse {
  suggestions: WorkSuggestion[]
  total: number
  generated_at: string
  offset?: number
  limit?: number
  has_more?: boolean
  summary?: {
    total: number
    priority: Record<SuggestionPriority, number>
    type: Record<string, number>
    workflow: Record<string, number>
  }
}

export const suggestionsApi = {
  list: async (params?: { limit?: number; offset?: number; status?: string; workflow?: SuggestionWorkflow }): Promise<SuggestionsResponse> => {
    const response = await api.get<SuggestionsResponse>('/suggestions/', { params })
    return response.data
  },
}
