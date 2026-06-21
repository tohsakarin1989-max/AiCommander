import { describe, expect, it } from 'vitest'

import {
  ApiError,
  ErrorCode,
  createApiError,
  generateRequestId,
  isRetryableError,
  needsReLogin,
} from './errors'


describe('createApiError', () => {
  it('保留后端统一错误 envelope 的 message', () => {
    const error = createApiError({
      response: {
        status: 404,
        data: {
          detail: '案件不存在',
          error: {
            code: 'http_404',
            message: '案件不存在',
            request_id: 'req-test',
          },
        },
      },
    })

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe(ErrorCode.NOT_FOUND)
    expect(error.status).toBe(404)
    expect(error.message).toBe('案件不存在')
  })

  it('将 FastAPI 校验数组转换为可读消息', () => {
    const error = createApiError({
      response: {
        status: 422,
        data: {
          detail: [
            { loc: ['body', 'case_id'], msg: 'Field required', type: 'missing' },
            { loc: ['query', 'limit'], msg: 'Input should be greater than 0' },
          ],
        },
      },
    })

    expect(error.code).toBe(ErrorCode.VALIDATION_ERROR)
    expect(error.message).toBe('case_id: Field required；limit: Input should be greater than 0')
  })

  it('识别超时和重登场景', () => {
    const timeout = createApiError({ code: 'ECONNABORTED', message: 'timeout' })
    const unauthorized = createApiError({ response: { status: 401, data: {} } })

    expect(timeout.code).toBe(ErrorCode.TIMEOUT)
    expect(isRetryableError(timeout)).toBe(true)
    expect(needsReLogin(unauthorized)).toBe(true)
  })

  it('生成可用于请求追踪的 request id', () => {
    expect(generateRequestId()).toMatch(/^req_[a-z0-9]+_[a-z0-9]+$/)
  })
})
