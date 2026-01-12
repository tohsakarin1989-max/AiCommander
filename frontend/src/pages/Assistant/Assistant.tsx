import React, { useState, useRef, useEffect } from 'react'
import {
  Card,
  Input,
  Button,
  Avatar,
  Typography,
  Space,
  Tag,
  Spin,
  Alert,
  Empty,
  Divider,
  message,
} from 'antd'
import {
  SendOutlined,
  RobotOutlined,
  UserOutlined,
  FileTextOutlined,
  DatabaseOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { assistantApi, ChatMessage, ChatResponse } from '../../services/assistant'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'

const { TextArea } = Input
const { Text, Paragraph } = Typography

const Assistant: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  const { data: stats, error: statsError } = useQuery({
    queryKey: ['assistant-stats'],
    queryFn: () => assistantApi.getStats(),
    retry: 1,
  })

  const chatMutation = useMutation({
    mutationFn: assistantApi.chat,
    onSuccess: (response: ChatResponse) => {
      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: response.answer,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, assistantMessage])
      setIsLoading(false)
    },
    onError: (error: any) => {
      console.error('Chat error:', error)
      const errorMessage: ChatMessage = {
        role: 'assistant',
        content: `抱歉，处理您的问题时出现错误：${error.response?.data?.detail || error.message || '未知错误'}`,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, errorMessage])
      setIsLoading(false)
      message.error('发送消息失败，请稍后重试')
    },
  })

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSend = async () => {
    if (!inputValue.trim() || isLoading) return

    const userMessage: ChatMessage = {
      role: 'user',
      content: inputValue.trim(),
      timestamp: new Date().toISOString(),
    }

    setMessages((prev) => [...prev, userMessage])
    const currentInput = inputValue.trim()
    setInputValue('')
    setIsLoading(true)

    try {
      chatMutation.mutate({
        query: currentInput,
        conversation_history: messages,
      })
    } catch (error) {
      console.error('Send error:', error)
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSourceClick = (source: ChatResponse['sources'][0]) => {
    if (source.type === 'case' && source.id) {
      navigate(`/cases?caseId=${source.id}`)
    } else if (source.type === 'report' && source.meeting_id) {
      navigate(`/meetings?meetingId=${source.meeting_id}`)
    }
  }

  const getWelcomeMessage = () => {
    if (stats) {
      return `您好！我是AI案件分析智能助手。当前系统中有 ${stats.total_cases} 起案件，已完成 ${stats.completed_meetings} 个分析报告。我可以帮您查询案件信息、分析报告等。请告诉我您想了解什么？`
    }
    return '您好！我是AI案件分析智能助手。我可以帮您查询案件信息、分析报告等。请告诉我您想了解什么？'
  }

  return (
    <div style={{ height: 'calc(100vh - 200px)', display: 'flex', flexDirection: 'column' }}>
      <Card
        title={
          <Space>
            <RobotOutlined style={{ fontSize: 20, color: '#1890ff' }} />
            <span>智能助手</span>
            {stats && (
              <Tag color="blue">
                案件: {stats.total_cases} | 报告: {stats.completed_meetings}
              </Tag>
            )}
            {statsError && (
              <Tag color="red">统计信息加载失败</Tag>
            )}
          </Space>
        }
        style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
        bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 0 }}
      >
        {/* 消息列表 */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '16px',
            backgroundColor: '#f5f5f5',
          }}
        >
          {messages.length === 0 ? (
            <Empty
              description={
                <div>
                  <Paragraph>{getWelcomeMessage()}</Paragraph>
                  <Divider />
                  <Paragraph type="secondary">
                    <strong>您可以问我：</strong>
                  </Paragraph>
                  <ul style={{ textAlign: 'left', display: 'inline-block' }}>
                    <li>最近有哪些案件？</li>
                    <li>案件统计信息</li>
                    <li>最新的分析报告是什么？</li>
                    <li>某个案件的具体情况</li>
                    <li>案件的地理分布情况</li>
                  </ul>
                </div>
              }
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          ) : (
            <div>
              {messages.map((message, index) => {
                const isUser = message.role === 'user'
                let sources: ChatResponse['sources'] = []
                if (!isUser && index === messages.length - 1) {
                  const lastResponse = chatMutation.data as ChatResponse | undefined
                  if (lastResponse?.sources) {
                    sources = lastResponse.sources
                  }
                }

                return (
                  <div
                    key={index}
                    style={{
                      display: 'flex',
                      justifyContent: isUser ? 'flex-end' : 'flex-start',
                      marginBottom: 16,
                    }}
                  >
                    <div
                      style={{
                        maxWidth: '70%',
                        display: 'flex',
                        flexDirection: isUser ? 'row-reverse' : 'row',
                        gap: 12,
                      }}
                    >
                      <Avatar
                        icon={isUser ? <UserOutlined /> : <RobotOutlined />}
                        style={{
                          backgroundColor: isUser ? '#1890ff' : '#52c41a',
                        }}
                      />
                      <div>
                        <Card
                          size="small"
                          style={{
                            backgroundColor: isUser ? '#1890ff' : '#fff',
                            color: isUser ? '#fff' : '#000',
                            border: isUser ? 'none' : '1px solid #d9d9d9',
                          }}
                        >
                          <Paragraph
                            style={{
                              margin: 0,
                              color: isUser ? '#fff' : '#000',
                              whiteSpace: 'pre-wrap',
                            }}
                          >
                            {message.content}
                          </Paragraph>
                          {message.timestamp && (
                            <Text
                              type="secondary"
                              style={{
                                fontSize: 12,
                                color: isUser ? 'rgba(255,255,255,0.7)' : undefined,
                                display: 'block',
                                marginTop: 4,
                              }}
                            >
                              {dayjs(message.timestamp).format('HH:mm:ss')}
                            </Text>
                          )}
                        </Card>
                        {sources && sources.length > 0 && (
                          <div style={{ marginTop: 8 }}>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              相关来源：
                            </Text>
                            <Space size={4} wrap style={{ marginTop: 4 }}>
                              {sources.map((source, idx) => (
                                <Tag
                                  key={idx}
                                  icon={
                                    source.type === 'case' ? (
                                      <DatabaseOutlined />
                                    ) : (
                                      <FileTextOutlined />
                                    )
                                  }
                                  style={{ cursor: 'pointer' }}
                                  onClick={() => handleSourceClick(source)}
                                >
                                  {source.type === 'case'
                                    ? source.case_number || `案件 #${source.id}`
                                    : `报告 ${source.meeting_id}`}
                                </Tag>
                              ))}
                            </Space>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
          {isLoading && (
            <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: 16 }}>
              <Avatar icon={<RobotOutlined />} style={{ backgroundColor: '#52c41a' }} />
              <Card size="small" style={{ marginLeft: 12 }}>
                <Spin size="small" /> 正在思考...
              </Card>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* 输入区域 */}
        <div style={{ padding: '16px', borderTop: '1px solid #f0f0f0' }}>
          <Space.Compact style={{ width: '100%' }}>
            <TextArea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="输入您的问题，按 Enter 发送，Shift+Enter 换行..."
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={isLoading}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={isLoading}
              disabled={!inputValue.trim()}
              style={{ height: 'auto' }}
            >
              发送
            </Button>
          </Space.Compact>
          <Alert
            message="提示"
            description="智能助手可以帮您查询案件信息、分析报告等。如果回答中提到了具体案件或报告，您可以点击相关标签查看详情。"
            type="info"
            showIcon
            style={{ marginTop: 12 }}
          />
        </div>
      </Card>
    </div>
  )
}

export default Assistant
