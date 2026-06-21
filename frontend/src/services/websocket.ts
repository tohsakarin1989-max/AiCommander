/**
 * WebSocket 服务
 * 用于实时通信，包括会议进度推送
 */

// WebSocket 基础 URL
const WS_BASE_URL = import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api`

export interface MeetingProgressData {
  stage: number
  stage_name: string
  status: 'started' | 'running' | 'completed' | 'failed'
  progress: number
  details?: Record<string, unknown>
}

export interface WebSocketMessage {
  type: string
  meeting_id?: string
  timestamp?: string
  data?: MeetingProgressData | Record<string, unknown>
  message?: string
}

type MessageHandler = (message: WebSocketMessage) => void
type ConnectionHandler = () => void

class MeetingWebSocket {
  private ws: WebSocket | null = null
  private meetingId: string | null = null
  private messageHandlers: MessageHandler[] = []
  private connectHandlers: ConnectionHandler[] = []
  private disconnectHandlers: ConnectionHandler[] = []
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null

  /**
   * 连接到会议 WebSocket
   */
  connect(meetingId: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      if (this.meetingId === meetingId) {
        return // 已连接到同一会议
      }
      this.disconnect() // 断开旧连接
    }

    this.meetingId = meetingId
    this.reconnectAttempts = 0

    const url = `${WS_BASE_URL}/ws/meeting/${meetingId}`
    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      console.log(`已连接到会议 ${meetingId} 的 WebSocket`)
      this.reconnectAttempts = 0
      this.connectHandlers.forEach(handler => handler())
    }

    this.ws.onmessage = (event) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data)
        this.messageHandlers.forEach(handler => handler(message))
      } catch (e) {
        console.error('解析 WebSocket 消息失败:', e)
      }
    }

    this.ws.onclose = () => {
      console.log(`会议 ${meetingId} 的 WebSocket 连接已关闭`)
      this.disconnectHandlers.forEach(handler => handler())
      this.attemptReconnect()
    }

    this.ws.onerror = (error) => {
      console.error('WebSocket 错误:', error)
    }
  }

  /**
   * 断开连接
   */
  disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
      this.reconnectTimeout = null
    }

    if (this.ws) {
      this.ws.close()
      this.ws = null
    }

    this.meetingId = null
    this.reconnectAttempts = 0
  }

  /**
   * 尝试重连
   */
  private attemptReconnect(): void {
    if (!this.meetingId || this.reconnectAttempts >= this.maxReconnectAttempts) {
      return
    }

    this.reconnectAttempts++
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000)

    console.log(`${delay / 1000} 秒后尝试重连 (${this.reconnectAttempts}/${this.maxReconnectAttempts})`)

    this.reconnectTimeout = setTimeout(() => {
      if (this.meetingId) {
        this.connect(this.meetingId)
      }
    }, delay)
  }

  /**
   * 发送消息
   */
  send(message: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
    }
  }

  /**
   * 发送心跳
   */
  ping(): void {
    this.send({ type: 'ping' })
  }

  /**
   * 请求当前状态
   */
  requestStatus(): void {
    this.send({ type: 'get_status' })
  }

  /**
   * 添加消息处理器
   */
  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.push(handler)
    return () => {
      const index = this.messageHandlers.indexOf(handler)
      if (index > -1) {
        this.messageHandlers.splice(index, 1)
      }
    }
  }

  /**
   * 添加连接处理器
   */
  onConnect(handler: ConnectionHandler): () => void {
    this.connectHandlers.push(handler)
    return () => {
      const index = this.connectHandlers.indexOf(handler)
      if (index > -1) {
        this.connectHandlers.splice(index, 1)
      }
    }
  }

  /**
   * 添加断开连接处理器
   */
  onDisconnect(handler: ConnectionHandler): () => void {
    this.disconnectHandlers.push(handler)
    return () => {
      const index = this.disconnectHandlers.indexOf(handler)
      if (index > -1) {
        this.disconnectHandlers.splice(index, 1)
      }
    }
  }

  /**
   * 获取连接状态
   */
  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  /**
   * 获取当前会议 ID
   */
  get currentMeetingId(): string | null {
    return this.meetingId
  }
}

// 导出单例
export const meetingWebSocket = new MeetingWebSocket()

// React Hook 用于会议进度
import { useState, useEffect, useCallback } from 'react'

export interface UseMeetingProgressReturn {
  progress: MeetingProgressData | null
  isConnected: boolean
  connect: (meetingId: string) => void
  disconnect: () => void
}

export function useMeetingProgress(initialMeetingId?: string): UseMeetingProgressReturn {
  const [progress, setProgress] = useState<MeetingProgressData | null>(null)
  const [isConnected, setIsConnected] = useState(false)

  const connect = useCallback((meetingId: string) => {
    meetingWebSocket.connect(meetingId)
  }, [])

  const disconnect = useCallback(() => {
    meetingWebSocket.disconnect()
    setProgress(null)
    setIsConnected(false)
  }, [])

  useEffect(() => {
    // 消息处理器
    const unsubMessage = meetingWebSocket.onMessage((message) => {
      if (message.type === 'meeting_progress' && message.data) {
        setProgress(message.data as MeetingProgressData)
      } else if (message.type === 'meeting_status' && message.data) {
        // 初始状态
        const status = (message.data as Record<string, string>).status
        if (status === 'completed') {
          setProgress({
            stage: 3,
            stage_name: '已完成',
            status: 'completed',
            progress: 100,
          })
        } else if (status === 'failed') {
          setProgress({
            stage: 0,
            stage_name: '失败',
            status: 'failed',
            progress: 0,
          })
        }
      }
    })

    // 连接处理器
    const unsubConnect = meetingWebSocket.onConnect(() => {
      setIsConnected(true)
    })

    // 断开连接处理器
    const unsubDisconnect = meetingWebSocket.onDisconnect(() => {
      setIsConnected(false)
    })

    // 初始连接
    if (initialMeetingId) {
      connect(initialMeetingId)
    }

    return () => {
      unsubMessage()
      unsubConnect()
      unsubDisconnect()
      disconnect()
    }
  }, [initialMeetingId, connect, disconnect])

  return { progress, isConnected, connect, disconnect }
}
