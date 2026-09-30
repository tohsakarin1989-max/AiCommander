/**
 * AI 功能服务
 * 圆桌会议、证据问答和历史智能体记录。
 * 新研判查询统一使用 intelligentQueries 服务。
 */
import api from './api'
import type {
  Meeting,
  MeetingCreate,
  MeetingReport,
  AnalysisResult,
  RankingResult,
  Conversation,
  EvidenceQaResponse,
  AgentTask,
  Conclusion,
  ConclusionFilters,
  MeetingTemplate,
  MeetingTemplateCreate,
  MeetingTemplateUpdate,
} from '../types'

// 重新导出类型供外部使用
export type {
  Meeting,
  MeetingCreate,
  MeetingReport,
  AnalysisResult,
  RankingResult,
  Conversation,
  AgentTask,
  Conclusion,
  ConclusionFilters,
  MeetingTemplate,
  MeetingTemplateCreate,
  MeetingTemplateUpdate,
}

export interface MeetingModelOption {
  id: number
  name: string
  role: string
  is_active: boolean
}

// ==================== API 实现 ====================

export const aiApi = {
  // ---------- 会议模板 ----------
  template: {
    /** 获取模板列表 */
    list: async () => {
      const response = await api.get<MeetingTemplate[]>('/meeting-templates')
      return response.data
    },

    /** 获取模板详情 */
    get: async (id: number) => {
      const response = await api.get<MeetingTemplate>(`/meeting-templates/${id}`)
      return response.data
    },

    /** 创建模板 */
    create: async (data: MeetingTemplateCreate) => {
      const response = await api.post<{ id: number; name: string; message: string }>('/meeting-templates', data)
      return response.data
    },

    /** 更新模板 */
    update: async (id: number, data: MeetingTemplateUpdate) => {
      const response = await api.put<{ id: number; name: string; message: string }>(`/meeting-templates/${id}`, data)
      return response.data
    },

    /** 删除模板 */
    delete: async (id: number) => {
      const response = await api.delete<{ message: string }>(`/meeting-templates/${id}`)
      return response.data
    },

    /** 使用模板（获取配置并增加使用计数） */
    use: async (id: number) => {
      const response = await api.post<{
        moderator_model_id: number
        analyst_model_ids: number[]
        config: Record<string, unknown>
      }>(`/meeting-templates/${id}/use`)
      return response.data
    },
  },

  // ---------- 圆桌会议 ----------
  meeting: {
    modelOptions: async () => {
      const response = await api.get<MeetingModelOption[]>('/meetings/model-options')
      return response.data
    },
    /** 创建并启动会议 */
    create: async (data: MeetingCreate) => {
      const response = await api.post<{ meeting_id: string; status: string }>('/meetings', data)
      return response.data
    },

    /** 获取会议列表 */
    list: async (skip = 0, limit = 100) => {
      const response = await api.get<Meeting[]>('/meetings', { params: { skip, limit } })
      return response.data
    },

    /** 获取会议详情 */
    get: async (meetingId: string) => {
      const response = await api.get<Meeting>(`/meetings/${meetingId}`)
      return response.data
    },

    /** 获取会议对话记录 */
    getConversations: async (meetingId: string) => {
      const response = await api.get<Conversation[]>(`/meetings/${meetingId}/conversations`)
      return response.data
    },

    /** 获取最终报告 */
    getReport: async (meetingId: string) => {
      const response = await api.get<MeetingReport>(`/meetings/${meetingId}/report`)
      return response.data
    },

    /** 获取分析结果（第一阶段） */
    getAnalyses: async (meetingId: string) => {
      const response = await api.get<AnalysisResult[]>(`/meetings/${meetingId}/analyses`)
      return response.data
    },

    /** 获取排名结果（第二阶段） */
    getRankings: async (meetingId: string) => {
      const response = await api.get<RankingResult[]>(`/meetings/${meetingId}/rankings`)
      return response.data
    },
  },

  // ---------- AI 助手 ----------
  assistant: {
    /** 获取统计信息 */
    getStats: async () => {
      const response = await api.get<{
        total_cases: number
        available_models: number
        recent_meetings: number
      }>('/assistant/stats')
      return response.data
    },

    evidenceQa: async (payload: { query: string; case_id?: number }): Promise<EvidenceQaResponse> => {
      const response = await api.post<EvidenceQaResponse>('/assistant/evidence-qa', payload)
      return response.data
    },
  },

  // ---------- 智能体 ----------
  agent: {
    /** 获取任务列表 */
    list: async () => {
      const response = await api.get<AgentTask[]>('/agents/tasks')
      return response.data
    },
  },

}

// 向后兼容：保留原有导出
export const meetingApi = {
  createMeeting: aiApi.meeting.create,
  getMeetings: aiApi.meeting.list,
  getMeeting: aiApi.meeting.get,
  getConversations: aiApi.meeting.getConversations,
  getReport: aiApi.meeting.getReport,
  getAnalyses: aiApi.meeting.getAnalyses,
  getRankings: aiApi.meeting.getRankings,
}

export const assistantApi = aiApi.assistant
export const agentApi = aiApi.agent
