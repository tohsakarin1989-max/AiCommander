import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { ApiError, createApiError, generateRequestId, needsReLogin } from '../utils/errors'

// 扩展 axios 请求配置，添加自定义属性
declare module 'axios' {
  export interface InternalAxiosRequestConfig {
    _context?: string
    _requestId?: string
    _startTime?: number
  }
}

const api = axios.create({
  baseURL: '/api',
  timeout: 120000, // 120秒，圆桌会议需要调用多个LLM
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 生成请求 ID 用于追踪
    const requestId = generateRequestId()
    config._requestId = requestId
    config._startTime = Date.now()
    config.headers['X-Request-Id'] = requestId

    // 添加认证令牌（如果存在）
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }

    // 开发环境日志
    if (import.meta.env.DEV) {
      console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`, {
        requestId,
        params: config.params,
      })
    }

    return config
  },
  (error: AxiosError) => {
    return Promise.reject(createApiError(error))
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response: AxiosResponse) => {
    // 开发环境日志：响应耗时
    if (import.meta.env.DEV) {
      const duration = Date.now() - (response.config._startTime || 0)
      console.log(
        `[API] ${response.config.method?.toUpperCase()} ${response.config.url} - ${response.status} (${duration}ms)`
      )
    }

    return response
  },
  (error: AxiosError) => {
    const context = error.config?._context
    const apiError = createApiError(error, context)

    // 开发环境日志
    if (import.meta.env.DEV) {
      const duration = Date.now() - (error.config?._startTime || 0)
      console.error(
        `[API Error] ${error.config?.method?.toUpperCase()} ${error.config?.url} - ${apiError.status || 'N/A'} (${duration}ms)`,
        {
          code: apiError.code,
          message: apiError.message,
          detail: apiError.detail,
        }
      )
    }

    // 认证失败处理
    if (needsReLogin(apiError)) {
      // 清除本地认证信息
      localStorage.removeItem('auth_token')
      // 可选：触发重新登录流程
      // window.location.href = '/login'
    }

    return Promise.reject(apiError)
  }
)

/**
 * 带上下文的 API 调用包装器
 * 用于在错误中包含更多上下文信息
 */
export async function apiCall<T>(
  fn: () => Promise<AxiosResponse<T>>,
  context: string
): Promise<T> {
  try {
    const response = await fn()
    return response.data
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }
    throw createApiError(error, context)
  }
}

/**
 * 设置请求上下文（用于错误追踪）
 */
export function withContext(context: string) {
  return {
    get: <T>(url: string, config?: Parameters<typeof api.get>[1]) =>
      api.get<T>(url, { ...config, _context: context } as typeof config),
    post: <T>(url: string, data?: unknown, config?: Parameters<typeof api.post>[2]) =>
      api.post<T>(url, data, { ...config, _context: context } as typeof config),
    put: <T>(url: string, data?: unknown, config?: Parameters<typeof api.put>[2]) =>
      api.put<T>(url, data, { ...config, _context: context } as typeof config),
    delete: <T>(url: string, config?: Parameters<typeof api.delete>[1]) =>
      api.delete<T>(url, { ...config, _context: context } as typeof config),
  }
}

export { ApiError }
export default api
