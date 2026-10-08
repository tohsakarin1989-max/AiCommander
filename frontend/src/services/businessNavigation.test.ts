import { describe, expect, it } from 'vitest'
import { businessContextPath, retainTopicSelection, safeBusinessReturn } from './businessNavigation'
import { parseCaseListPosition, writeCaseFilterParams, writeCaseListPosition } from './caseContext'
import { facilityConditionTimeContext } from './facilityConditions'
import { visibleCasePage } from '../pages/Cases/caseSearch'
import { dossierSourcePath } from './regionalContext'

describe('业务来源与列表位置', () => {
  it('非法筛选或请求失败时不继续用同键缓存显示列表、数量和分面', () => {
    const cached = { items: [{ id: 1 }], total: 12, facets: { case_types: { other: 12 } } }
    expect(visibleCasePage(cached, true)).toBeUndefined()
    expect(visibleCasePage(cached, false)).toBe(cached)
  })
  it('案件到设施与材料保持时间、来源线索及原列表位置，不带密钥', () => {
    const source = new URLSearchParams('caseId=3&assetId=7&case_page=4&case_page_size=20&valid_at=2026-10-01T00:00:00Z&known_at=2026-10-02T00:00:00Z&mapSnapshot=m-1&sourceRevision=8&token=private')
    const url = businessContextPath('/reports?resultId=r-1', source, '/cases')
    const next = new URLSearchParams(url.split('?')[1])
    expect(next.has('assetId')).toBe(false); expect(next.get('sourceRevision')).toBe('8')
    expect(next.get('known_at')).toBe(source.get('known_at'))
    const back = safeBusinessReturn(next.get('return_to'))!
    expect(back).toContain('case_page=4'); expect(back).toContain('caseId=3'); expect(back).toContain('assetId=7')
    expect(url).not.toContain('private'); expect(next.get('resultId')).toBe('r-1')
    expect(new URLSearchParams(businessContextPath('/topics?source=case&sourceId=3', next, '/reports').split('?')[1]).get('return_to')).toBe(back)
  })
  it('只允许已知站内入口，不接受外部或嵌套返回地址', () => {
    for (const value of ['https://evil.test', '//evil.test', '/\\evil.test', '/api/cases', '/cases\n', '/cases#other']) expect(safeBusinessReturn(value)).toBeNull()
    expect(safeBusinessReturn('/cases?caseId=3&return_to=https://evil.test&password=x')).toBe('/cases?caseId=3')
  })
  it('从设施明细打开案件保留原专题返回位置，不让旧设施抽屉遮挡案件', () => {
    const link = dossierSourcePath('/cases?caseId=8', new URLSearchParams('assetId=9&return_to=%2Ftopics%3Ftopic%3Dtopic-1%26revision%3D2'))
    const params = new URLSearchParams(link.split('?')[1])
    expect(params.get('return_to')).toBe('/topics?topic=topic-1&revision=2')
    expect(params.has('assetId')).toBe(false)
  })
  it('专题固定版本不清除原始范围与返回位置', () => {
    const params = new URLSearchParams('source=case&sourceId=3&caseId=3&valid_at=2026-10-01T00:00:00Z&return_to=%2Fcases%3Fcase_page%3D4')
    const frozen = retainTopicSelection(params, 't-1', 2)
    expect(frozen.get('revision')).toBe('2'); expect(frozen.get('caseId')).toBe('3')
    expect(frozen.get('return_to')).toBe('/cases?case_page=4'); expect(frozen.has('source')).toBe(false)
    expect(retainTopicSelection(frozen, 't-1').has('revision')).toBe(false)
  })
  it('URL 保存分页；新筛选仅回第一页，不清每页大小', () => {
    const value = writeCaseListPosition(new URLSearchParams('caseId=8'), 4, 20)
    expect(parseCaseListPosition(value)).toEqual({ page: 4, pageSize: 20, error: undefined })
    expect(parseCaseListPosition(writeCaseFilterParams(value, { keyword: '油' }))).toEqual({ page: 1, pageSize: 20, error: undefined })
    for (const query of ['case_page=-1', 'case_page_size=999', 'case_page=2&case_page=3']) expect(parseCaseListPosition(new URLSearchParams(query)).error).toBeTruthy()
  })
  it('从候选到设施使用原成果完整时间和获知截止，未知不套当前为历史', () => {
    expect(facilityConditionTimeContext({ state: 'partial', valid_at: null, known_at: '2026-09-05T00:00:00Z', version_id: null,
      query_interval: { from: '2026-09-01T00:00:00Z', to: '2026-09-03T00:00:00Z' }, knowledge_mode: 'retrospective' }, 'r-1')).toMatchObject({
      valid_at: null, valid_from: '2026-09-01T00:00:00Z', valid_to: '2026-09-03T00:00:00Z', known_at: '2026-09-05T00:00:00Z', knowledge_mode: 'as_known', resultRef: 'r-1',
    })
    expect(facilityConditionTimeContext(undefined, 'old')).toMatchObject({ valid_at: null, valid_from: null, valid_to: null, known_at: null, time_scope: 'unknown' })
  })
})
