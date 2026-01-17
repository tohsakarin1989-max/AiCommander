import api from './api'
import type { MeetingStatus } from '../types'

export interface Meeting {
  id: number
  meeting_id: string
  case_ids: number[]
  status: MeetingStatus
  moderator_model_id: number
  analyst_model_ids: number[]
  final_report_id?: number
  created_at: string
  completed_at?: string
}

export interface MeetingCreate {
  case_ids: number[]
  moderator_model_id: number
  analyst_model_ids: number[]
}

export interface MeetingCreateResponse {
  meeting_id: string
  status: MeetingStatus
}

export interface Conversation {
  id: number
  round_number: number
  speaker_model_id: number
  message_type: 'analysis' | 'ranking' | 'summary' | 'comment'
  content: string
  created_at: string
}

// 分析结果类型
export interface AnalysisResult {
  analyst_index: number
  model_name: string
  features?: {
    keywords?: string[]
    entities?: Record<string, string[]>
    summary?: string
  }
  relations?: {
    type: string
    description: string
    confidence: number
  }[]
  risk_assessment?: string
  recommendations?: string[]
  raw_content?: string
}

// 排名结果类型
export interface RankingItem {
  anonymous_id: string
  rank: number
  score: number
  comment?: string
}

export interface RankingResult {
  analyst_index: number
  rankings: RankingItem[]
  overall_comment?: string
}

// 最终报告类型
export interface MeetingReport {
  meeting_id: string
  summary: string
  key_findings: string[]
  risk_assessment?: string
  recommendations?: string[]
  consensus_points?: string[]
  disagreement_points?: string[]
  aggregated_rankings?: {
    original_index: number
    average_score: number
    average_rank: number
    vote_count: number
  }[]
  generated_at: string
}

export const meetingApi = {
  /**
   * 创建并启动会议
   */
  createMeeting: async (data: MeetingCreate): Promise<MeetingCreateResponse> => {
    const response = await api.post<MeetingCreateResponse>('/meetings', data)
    return response.data
  },

  /**
   * 获取会议列表
   */
  getMeetings: async (skip = 0, limit = 100): Promise<Meeting[]> => {
    const response = await api.get<Meeting[]>('/meetings', { params: { skip, limit } })
    return response.data
  },

  /**
   * 获取会议详情
   */
  getMeeting: async (meetingId: string): Promise<Meeting> => {
    const response = await api.get<Meeting>(`/meetings/${meetingId}`)
    return response.data
  },

  /**
   * 获取会议对话记录
   */
  getConversations: async (meetingId: string): Promise<Conversation[]> => {
    const response = await api.get<Conversation[]>(`/meetings/${meetingId}/conversations`)
    return response.data
  },

  /**
   * 获取会议最终报告
   */
  getReport: async (meetingId: string): Promise<MeetingReport> => {
    const response = await api.get<MeetingReport>(`/meetings/${meetingId}/report`)
    return response.data
  },

  /**
   * 获取各分析员的分析结果
   */
  getAnalyses: async (meetingId: string): Promise<AnalysisResult[]> => {
    const response = await api.get<AnalysisResult[]>(`/meetings/${meetingId}/analyses`)
    return response.data
  },

  /**
   * 获取排名结果
   */
  getRankings: async (meetingId: string): Promise<RankingResult[]> => {
    const response = await api.get<RankingResult[]>(`/meetings/${meetingId}/rankings`)
    return response.data
  },
}
