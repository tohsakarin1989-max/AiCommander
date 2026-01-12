import api from './api'

export interface Meeting {
  id: number
  meeting_id: string
  case_ids: number[]
  status: string
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

export interface Conversation {
  id: number
  round_number: number
  speaker_model_id: number
  message_type: string
  content: string
  created_at: string
}

export const meetingApi = {
  createMeeting: async (data: MeetingCreate): Promise<{ meeting_id: string; status: string }> => {
    const response = await api.post('/meetings', data)
    return response.data
  },

  getMeetings: async (skip = 0, limit = 100): Promise<Meeting[]> => {
    const response = await api.get('/meetings', { params: { skip, limit } })
    return response.data
  },

  getMeeting: async (meeting_id: string): Promise<Meeting> => {
    const response = await api.get(`/meetings/${meeting_id}`)
    return response.data
  },

  getConversations: async (meeting_id: string): Promise<Conversation[]> => {
    const response = await api.get(`/meetings/${meeting_id}/conversations`)
    return response.data
  },

  getReport: async (meeting_id: string): Promise<any> => {
    const response = await api.get(`/meetings/${meeting_id}/report`)
    return response.data
  },

  getAnalyses: async (meeting_id: string): Promise<any[]> => {
    const response = await api.get(`/meetings/${meeting_id}/analyses`)
    return response.data
  },

  getRankings: async (meeting_id: string): Promise<any[]> => {
    const response = await api.get(`/meetings/${meeting_id}/rankings`)
    return response.data
  },
}

