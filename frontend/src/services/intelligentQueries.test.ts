import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { intelligentQueriesApi, queryEntryContext } from './intelligentQueries'

vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

describe('助手初始选择与请求兼容', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.post).mockResolvedValue({ data: { id: 'new' } }) })

  it('保留原始提问与服务端追问契约', async () => {
    await intelligentQueriesApi.create('统计')
    expect(api.post).toHaveBeenLastCalledWith('/intelligent-queries', { query: '统计' })
    await intelligentQueriesApi.create('继续', 'parent')
    expect(api.post).toHaveBeenLastCalledWith('/intelligent-queries', { query: '继续', parent_query_id: 'parent' })
  })

  it('提交页面条件但不提交原文、权限或客户端版本', async () => {
    const entry = queryEntryContext(new URLSearchParams('caseId=42&statuses=pending&statuses=closed&has_geo=false&keyword=管线'))
    await intelligentQueriesApi.create('查看当前案件', undefined, entry.initialContext)
    expect(api.post).toHaveBeenCalledExactlyOnceWith('/intelligent-queries', {
      query: '查看当前案件', initial_context: { source_case_id: 42,
        filters: { statuses: ['pending', 'closed'], has_geo: false, keyword: '管线' } },
    })
  })

  it('禁止同时覆盖初始条件和追问上下文', async () => {
    await expect(intelligentQueriesApi.create('继续', 'parent', { source_case_id: 42, filters: {} })).rejects.toThrow('不能混用')
    expect(api.post).not.toHaveBeenCalled()
    expect(queryEntryContext(new URLSearchParams('query=parent&caseId=42')).error).toContain('不能混用')
  })

  it('共用案件页白名单，不携带分页、报告标识和未知值', () => {
    const entry = queryEntryContext(new URLSearchParams('case_types=盗油&case_types=盗窃&oil_types=原油&operational_area_id=2&start_date=2026-09-01T00%3A00%3A00Z&end_date=2026-10-01T00%3A00%3A00Z&page=4&resultId=private&source_hash=untrusted'))
    expect(entry).toEqual({ initialContext: { filters: {
      case_types: ['盗油', '盗窃'], oil_types: ['原油'], operational_area_id: 2,
      start_date: '2026-09-01T00:00:00Z', end_date: '2026-10-01T00:00:00Z',
    } } })
  })

  it.each(['caseId=0', 'caseId=abc', 'has_geo=maybe', 'operational_area_id=-1',
    'start_date=bad', 'start_date=2026-10-01&end_date=2026-09-01'])('无效条件不可悄悄丢弃：%s', query => {
    const entry = queryEntryContext(new URLSearchParams(query))
    expect(entry.error).toBeTruthy()
    expect(entry.initialContext).toBeUndefined()
  })

  it('空白条件不创建空上下文，false 条件保持有效', () => {
    expect(queryEntryContext(new URLSearchParams('keyword=+++&page=2'))).toEqual({})
    expect(queryEntryContext(new URLSearchParams('has_geo=false'))).toEqual({ initialContext: { filters: { has_geo: false } } })
    expect(api.post).not.toHaveBeenCalled()
  })

  it('读取、取消及导出仍使用原有任务身份，不自行重放或创建', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: {} })
    const signal = new AbortController().signal
    await intelligentQueriesApi.read('query/1', signal)
    expect(api.get).toHaveBeenLastCalledWith('/intelligent-queries/query%2F1', { signal })
    await intelligentQueriesApi.document('query/1', 'docx', signal)
    expect(api.get).toHaveBeenLastCalledWith('/intelligent-queries/query%2F1/document.docx', { responseType: 'blob', signal })
    await intelligentQueriesApi.cancel('query/1')
    expect(api.post).toHaveBeenCalledExactlyOnceWith('/intelligent-queries/query%2F1/cancel')
  })
})
