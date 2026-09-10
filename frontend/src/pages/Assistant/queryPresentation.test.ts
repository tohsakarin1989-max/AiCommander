import { describe, expect, it } from 'vitest'
import { activeQuery, failureText, queryIdValid, requestFailure, rowsOf, textValue } from './queryPresentation'

describe('query states and safe presentation', () => {
  it('polls only queued and running tasks', () => {
    expect(activeQuery('queued')).toBe(true)
    expect(activeQuery('running')).toBe(true)
    for (const state of ['completed', 'cancelled', 'failed', 'degraded', 'expired', undefined]) expect(activeQuery(state)).toBe(false)
  })
  it('never conflates unavailable and empty', () => {
    expect(failureText('query_model_unavailable')).toContain('内网模型不可用')
    expect(requestFailure({ response: { status: 403 } })).toContain('不能继续显示')
    expect(requestFailure({ response: { status: 404 } }, true)).toContain('尚未启用')
    expect(requestFailure(new Error('secret'))).not.toContain('secret')
  })
  it('bounds route ids and avoids rendering unknown objects', () => {
    expect(queryIdValid('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')).toBe(true)
    expect(queryIdValid('../cases')).toBe(false)
    expect(rowsOf([null, [], 'bad', { id: 1 }])).toEqual([{ id: 1 }])
    expect(textValue(0)).toBe('0')
    expect(textValue({ secret: true })).toBe('未提供')
  })
})
