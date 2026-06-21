import { useState, useRef, useEffect } from 'react'
import {
  RobotOutlined,
  UserOutlined,
  FileTextOutlined,
  DatabaseOutlined,
  SendOutlined,
  MessageOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { aiApi } from '../../services/ai'
import type { ChatMessage, ChatResponse, SourceItem } from '../../types'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { Input } from 'antd'
import './Assistant.css'

const { TextArea } = Input

const HINT_QUESTIONS = [
  '最近有哪些案件？',
  '案件统计信息',
  '最新的分析报告是什么？',
  '案件的地理分布情况',
  '高风险案件有哪些？',
]

const Assistant: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  const { data: stats, error: statsError } = useQuery({
    queryKey: ['assistant-stats'],
    queryFn: () => aiApi.assistant.getStats(),
    retry: 1,
  })

  const chatMutation = useMutation({
    mutationFn: aiApi.assistant.chat,
    onSuccess: (response: ChatResponse) => {
      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: response.answer || response.response,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, assistantMessage])
      setIsLoading(false)
    },
    onError: (error: any) => {
      const errorMessage: ChatMessage = {
        role: 'assistant',
        content: `抱歉，处理您的问题时出现错误：${error.response?.data?.detail || error.message || '未知错误'}`,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, errorMessage])
      setIsLoading(false)
    },
  })

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSend = (text?: string) => {
    const content = (text ?? inputValue).trim()
    if (!content || isLoading) return

    const userMessage: ChatMessage = {
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInputValue('')
    setIsLoading(true)

    chatMutation.mutate({
      query: content,
      conversation_history: messages,
    })
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSourceClick = (source: SourceItem) => {
    if (source.type === 'case' && source.id) {
      navigate(`/cases?caseId=${source.id}`)
    } else if (source.type === 'report' && source.meeting_id) {
      navigate(`/meetings?meetingId=${source.meeting_id}`)
    }
  }

  const getWelcomeText = () => {
    if (stats) {
      return `您好！我是 AI 案件分析助手。当前系统中有 ${stats.total_cases} 起案件，已完成 ${stats.recent_meetings} 个分析报告。请告诉我您想了解什么？`
    }
    return '您好！我是 AI 案件分析助手。我可以帮您查询案件信息、分析报告等。请告诉我您想了解什么？'
  }

  return (
    <div className="page-scrollable">
      {/* 页面标题 */}
      <div className="page-title">
        <h1>智能助手</h1>
        <span className="sub">AI ASSISTANT</span>
        {stats && !statsError && (
          <span className="chip" style={{ marginLeft: 'auto' }}>
            案件 <span style={{ color: 'var(--accent)', marginLeft: 4 }}>{stats.total_cases}</span>
            <span style={{ color: 'var(--ink-3)', margin: '0 4px' }}>·</span>
            报告 <span style={{ color: 'var(--accent)', marginLeft: 4 }}>{stats.recent_meetings}</span>
          </span>
        )}
      </div>

      {/* 主体双栏布局 */}
      <div className="assistant-layout">

        {/* 左侧：会话历史 */}
        <div className="assistant-sidebar">
          <div className="card">
            <div className="card-head">
              <MessageOutlined className="ico" />
              <span className="ti">会话历史</span>
            </div>
            <div className="card-body scroll">
              {messages.length === 0 ? (
                <div className="empty-state" style={{ padding: '20px 14px' }}>
                  <div className="icon"><MessageOutlined /></div>
                  <span>暂无会话</span>
                </div>
              ) : (
                messages
                  .filter((m) => m.role === 'user')
                  .map((m, i) => (
                    <div key={i} className={`conv-item${i === 0 ? ' active' : ''}`}>
                      <div className="conv-item__id">MSG-{String(i + 1).padStart(3, '0')}</div>
                      <div className="conv-item__preview">{m.content}</div>
                    </div>
                  ))
              )}
            </div>
          </div>
        </div>

        {/* 右侧：聊天主区 */}
        <div className="assistant-chat">
          {/* 消息列表 */}
          <div className="assistant-messages">
            {messages.length === 0 ? (
              <div className="assistant-welcome">
                <div className="assistant-welcome__icon"><RobotOutlined /></div>
                <div className="assistant-welcome__title">{getWelcomeText()}</div>
                <div className="assistant-welcome__hints">
                  {HINT_QUESTIONS.map((q) => (
                    <div
                      key={q}
                      className="assistant-welcome__hint"
                      onClick={() => handleSend(q)}
                    >
                      {q}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((msg, index) => {
                const isUser = msg.role === 'user'
                let sources: ChatResponse['sources'] = []
                if (!isUser && index === messages.length - 1) {
                  const lastResponse = chatMutation.data as ChatResponse | undefined
                  if (lastResponse?.sources) {
                    sources = lastResponse.sources
                  }
                }
                return (
                  <div key={index} className={`msg-row${isUser ? ' msg-row--user' : ''}`}>
                    <div className={`msg-avatar${isUser ? ' msg-avatar--user' : ' msg-avatar--ai'}`}>
                      {isUser ? <UserOutlined /> : <RobotOutlined />}
                    </div>
                    <div className="msg-body">
                      <div className={`msg-bubble${isUser ? ' msg-bubble--user' : ' msg-bubble--ai'}`}>
                        <pre>{msg.content}</pre>
                        {msg.timestamp && (
                          <div className="msg-time" style={{ marginTop: 6 }}>
                            {dayjs(msg.timestamp).format('HH:mm:ss')}
                          </div>
                        )}
                      </div>
                      {sources && sources.length > 0 && (
                        <div className="msg-sources">
                          <span className="msg-sources__label">来源</span>
                          {sources.map((source, idx) => (
                            <div
                              key={idx}
                              className="msg-source-tag"
                              onClick={() => handleSourceClick(source)}
                            >
                              {source.type === 'case' ? <DatabaseOutlined /> : <FileTextOutlined />}
                              {source.type === 'case'
                                ? source.case_number || `案件 #${source.id}`
                                : `报告 ${source.meeting_id}`}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })
            )}

            {isLoading && (
              <div className="msg-loading-row">
                <div className="msg-avatar msg-avatar--ai"><RobotOutlined /></div>
                <div className="msg-loading-bubble">
                  <div className="pulse-dots">
                    <div className="pulse-dot" />
                    <div className="pulse-dot" />
                    <div className="pulse-dot" />
                  </div>
                  <span className="msg-loading-label">正在思考...</span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* 输入区 */}
          <div className="assistant-input-area">
            <div className="assistant-input-row">
              <TextArea
                className="assistant-textarea"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="输入您的问题，按 Enter 发送，Shift+Enter 换行..."
                autoSize={{ minRows: 1, maxRows: 5 }}
                disabled={isLoading}
              />
              <button
                className="btn-primary"
                onClick={() => handleSend()}
                disabled={isLoading || !inputValue.trim()}
                style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              >
                <SendOutlined />
                发送
              </button>
            </div>
            <div className="assistant-input-hint">
              ENTER 发送 · SHIFT+ENTER 换行 · 点击来源标签可跳转详情
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Assistant
