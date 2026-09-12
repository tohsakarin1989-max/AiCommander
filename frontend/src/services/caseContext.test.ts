import { describe, expect, it } from 'vitest'
import { caseContextPath, parseCaseContextParams, writeCaseFilterParams } from './caseContext'

describe('业务页面条件接续', () => {
  it('保留多选、时间和案件选择，不继承别的报告/查询身份', () => {
    const params = new URLSearchParams('caseId=18&statuses=pending&statuses=closed&has_geo=false&resultId=old&query=old')
    const next = new URLSearchParams(caseContextPath('/cases/map', params).split('?')[1])
    expect(parseCaseContextParams(next)).toEqual({ caseId: 18, filters: { statuses: ['pending', 'closed'], has_geo: false }, error: undefined })
    expect(next.has('resultId')).toBe(false)
    expect(next.has('query')).toBe(false)
    expect(new URLSearchParams(caseContextPath('/cases?caseId=9', params).split('?')[1]).get('caseId')).toBe('9')
  })
  it('复位只清筛选，不清当前案件或页面身份', () => {
    const params = writeCaseFilterParams(new URLSearchParams('caseId=1&query=x'), { keyword: '管线', statuses: ['pending'], start_date: '2026-09-01T00:00:00Z' })
    expect(parseCaseContextParams(params).filters.keyword).toBe('管线')
    expect(writeCaseFilterParams(params, {}).toString()).toBe('caseId=1&query=x')
  })
  it('非法条件明确报错，不悄悄扩大范围', () => {
    for (const query of ['caseId=0', 'caseId=12bad', 'operational_area_id=-1', 'has_geo=maybe', 'start_date=invalid', 'start_date=2026-09-02&end_date=2026-09-01']) {
      expect(parseCaseContextParams(new URLSearchParams(query)).error).toBeTruthy()
    }
  })
})
