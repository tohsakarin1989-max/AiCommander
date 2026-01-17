/**
 * 统一错误处理工具
 */

// 错误代码枚举
export enum ErrorCode {
  // 网络错误
  NETWORK_ERROR = 'NETWORK_ERROR',
  TIMEOUT = 'TIMEOUT',

  // 认证错误
  UNAUTHORIZED = 'UNAUTHORIZED',
  FORBIDDEN = 'FORBIDDEN',

  // 请求错误
  BAD_REQUEST = 'BAD_REQUEST',
  NOT_FOUND = 'NOT_FOUND',
  CONFLICT = 'CONFLICT',
  VALIDATION_ERROR = 'VALIDATION_ERROR',

  // 服务器错误
  SERVER_ERROR = 'SERVER_ERROR',
  SERVICE_UNAVAILABLE = 'SERVICE_UNAVAILABLE',

  // 业务错误
  RATE_LIMIT = 'RATE_LIMIT',

  // 未知错误
  UNKNOWN = 'UNKNOWN',
}

// 自定义 API 错误类
export class ApiError extends Error {
  public readonly code: ErrorCode
  public readonly status?: number
  public readonly context?: string
  public readonly detail?: unknown

  constructor(
    message: string,
    code: ErrorCode = ErrorCode.UNKNOWN,
    status?: number,
    context?: string,
    detail?: unknown
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.context = context
    this.detail = detail
  }
}

// HTTP 状态码到错误代码的映射
const statusToErrorCode: Record<number, ErrorCode> = {
  400: ErrorCode.BAD_REQUEST,
  401: ErrorCode.UNAUTHORIZED,
  403: ErrorCode.FORBIDDEN,
  404: ErrorCode.NOT_FOUND,
  409: ErrorCode.CONFLICT,
  422: ErrorCode.VALIDATION_ERROR,
  429: ErrorCode.RATE_LIMIT,
  500: ErrorCode.SERVER_ERROR,
  502: ErrorCode.SERVICE_UNAVAILABLE,
  503: ErrorCode.SERVICE_UNAVAILABLE,
  504: ErrorCode.TIMEOUT,
}

// 用户友好的错误消息映射
const userFriendlyMessages: Record<ErrorCode, string> = {
  [ErrorCode.NETWORK_ERROR]: '网络连接失败，请检查网络后重试',
  [ErrorCode.TIMEOUT]: '请求超时，请稍后重试',
  [ErrorCode.UNAUTHORIZED]: '登录已过期，请重新登录',
  [ErrorCode.FORBIDDEN]: '没有权限执行此操作',
  [ErrorCode.BAD_REQUEST]: '请求参数错误，请检查输入',
  [ErrorCode.NOT_FOUND]: '请求的资源不存在',
  [ErrorCode.CONFLICT]: '数据冲突，请刷新后重试',
  [ErrorCode.VALIDATION_ERROR]: '输入信息不完整或格式错误',
  [ErrorCode.SERVER_ERROR]: '服务器错误，请稍后重试',
  [ErrorCode.SERVICE_UNAVAILABLE]: '服务暂时不可用，请稍后重试',
  [ErrorCode.RATE_LIMIT]: '请求过于频繁，请稍后重试',
  [ErrorCode.UNKNOWN]: '操作失败，请稍后重试',
}

/**
 * 从 HTTP 状态码获取错误代码
 */
export function getErrorCodeFromStatus(status: number): ErrorCode {
  return statusToErrorCode[status] || ErrorCode.UNKNOWN
}

/**
 * 获取用户友好的错误消息
 */
export function getUserFriendlyMessage(code: ErrorCode): string {
  return userFriendlyMessages[code] || userFriendlyMessages[ErrorCode.UNKNOWN]
}

/**
 * 从 Axios 错误创建 ApiError
 */
export function createApiError(error: unknown, context?: string): ApiError {
  // 网络错误（无响应）
  if (isAxiosError(error) && !error.response) {
    if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
      return new ApiError(
        getUserFriendlyMessage(ErrorCode.TIMEOUT),
        ErrorCode.TIMEOUT,
        undefined,
        context
      )
    }
    return new ApiError(
      getUserFriendlyMessage(ErrorCode.NETWORK_ERROR),
      ErrorCode.NETWORK_ERROR,
      undefined,
      context
    )
  }

  // HTTP 错误响应
  if (isAxiosError(error) && error.response) {
    const status = error.response.status
    const code = getErrorCodeFromStatus(status)
    const serverMessage = error.response.data?.detail || error.response.data?.message
    const message = serverMessage || getUserFriendlyMessage(code)

    return new ApiError(message, code, status, context, error.response.data)
  }

  // 已经是 ApiError
  if (error instanceof ApiError) {
    return error
  }

  // 其他错误
  const message = error instanceof Error ? error.message : '未知错误'
  return new ApiError(message, ErrorCode.UNKNOWN, undefined, context)
}

/**
 * 类型守卫：检查是否为 Axios 错误
 */
function isAxiosError(error: unknown): error is {
  response?: {
    status: number
    data?: { detail?: string; message?: string }
  }
  code?: string
  message?: string
} {
  return (
    typeof error === 'object' &&
    error !== null &&
    ('response' in error || 'code' in error || 'message' in error)
  )
}

/**
 * 判断错误是否可重试
 */
export function isRetryableError(error: ApiError): boolean {
  return [
    ErrorCode.NETWORK_ERROR,
    ErrorCode.TIMEOUT,
    ErrorCode.SERVICE_UNAVAILABLE,
    ErrorCode.SERVER_ERROR,
  ].includes(error.code)
}

/**
 * 判断是否需要重新登录
 */
export function needsReLogin(error: ApiError): boolean {
  return error.code === ErrorCode.UNAUTHORIZED
}

/**
 * 生成请求 ID（用于追踪）
 */
export function generateRequestId(): string {
  return `req_${Date.now().toString(36)}_${Math.random().toString(36).substring(2, 9)}`
}
