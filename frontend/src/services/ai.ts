/**
 * AI 功能服务
 * 合并：圆桌会议、AI 助手、智能体、结论工厂
 */
import api from './api'
import type {
  Meeting,
  MeetingCreate,
  MeetingReport,
  AnalysisResult,
  RankingResult,
  Conversation,
  ChatRequest,
  ChatResponse,
  ConclusionDraft,
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
  ChatRequest,
  ChatResponse,
  AgentTask,
  Conclusion,
  ConclusionFilters,
  MeetingTemplate,
  MeetingTemplateCreate,
  MeetingTemplateUpdate,
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
    /** 发送对话请求 */
    chat: async (request: ChatRequest) => {
      const response = await api.post<ChatResponse>('/assistant/chat', request)
      return response.data
    },

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
    /** 执行智能体任务 */
    run: async (query: string, caseIds?: number[]) => {
      const response = await api.post<AgentTask>('/agents/run', { query, case_ids: caseIds || [] })
      return response.data
    },

    /** 获取任务列表 */
    list: async () => {
      const response = await api.get<AgentTask[]>('/agents/tasks')
      return response.data
    },
  },

  // ---------- 结论工厂 ----------
  conclusion: {
    /** 生成结论 */
    generate: async (caseId: number) => {
      const response = await api.post<Conclusion>('/conclusions/generate', { case_id: caseId })
      return response.data
    },

    /** 从会议报告生成结论 */
    generateFromMeeting: async (meetingId: string) => {
      const response = await api.post<Conclusion>(`/conclusions/from-meeting/${meetingId}`)
      return response.data
    },

    /** 将结论关联到会议 */
    linkToMeeting: async (conclusionId: number, meetingId: string) => {
      const response = await api.post<{ id: number; meeting_id: string; message: string }>(
        `/conclusions/${conclusionId}/link-meeting`,
        null,
        { params: { meeting_id: meetingId } }
      )
      return response.data
    },

    /** 获取结论列表 */
    list: async (filters?: ConclusionFilters) => {
      const response = await api.get<Conclusion[]>('/conclusions', { params: filters })
      return response.data
    },

    /** 获取结论详情 */
    get: async (id: number) => {
      const response = await api.get<Conclusion>(`/conclusions/${id}`)
      return response.data
    },

    /** 提交审核反馈 */
    review: async (id: number, data: { action: 'approve' | 'reject' | 'flag'; note?: string }) => {
      const response = await api.post(`/conclusions/${id}/review`, data)
      return response.data
    },

    draft: async (caseId: number): Promise<ConclusionDraft> => {
      const response = await api.post<ConclusionDraft>('/conclusions/draft', { case_id: caseId })
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
export const conclusionApi = aiApi.conclusion
