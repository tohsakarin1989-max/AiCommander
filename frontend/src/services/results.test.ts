import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { resultsApi, isResultKind, resultPath, materialCatalogPath, materialSourcePath, materialFilename, parseMaterialSections, type ResultItem } from './results'
vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
describe('统一材料接口', () => {
  beforeEach(() => vi.resetAllMocks())
  it('章节组合仅接受白名单，下载校验章节与版本，拒绝旧版文件', async () => {
    expect(parseMaterialSections(['boundary', 'facts'])).toEqual(['facts', 'boundary'])
    expect(parseMaterialSections(['facts', 'facts'])).toBeUndefined()
    expect(parseMaterialSections(['__proto__'])).toBeUndefined()
    const item = { kind: 'case' as const, id: 'frozen', content_sha256: 'a'.repeat(64) }
    vi.mocked(api.get).mockResolvedValue({ data: new Blob(['same-version']), headers: {
      'x-result-content-sha256': item.content_sha256, 'x-result-template': 'full', 'x-result-sections': 'facts,boundary',
    } })
    await resultsApi.document(item, 'docx', undefined, { sections: ['facts', 'boundary'] })
    expect(api.get).toHaveBeenLastCalledWith('/results/case/frozen/document.docx', expect.objectContaining({
      params: { template: 'full', expected_content_sha256: item.content_sha256, sections: ['facts', 'boundary'] },
    }))
    await expect(resultsApi.document(item, 'docx', undefined, { sections: ['gaps', 'boundary'] })).rejects.toThrow('material_sections_invalid')
    const route = new URLSearchParams(resultPath('case', 'frozen', undefined, { sections: ['facts', 'boundary'] }).split('?')[1])
    expect(route.getAll('sections')).toEqual(['facts', 'boundary'])
  })
  it('只按类型与固定ID读取，错误身份响应拒绝', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { kind: 'facility', id: 'other', content_sha256: 'a'.repeat(64), document: { blocks: [] } } })
    await expect(resultsApi.read('facility', 'wanted')).rejects.toThrow('material_contract_invalid')
    expect(api.get).toHaveBeenCalledWith('/results/facility/wanted', { signal: undefined, params: { template: 'full', expected_content_sha256: undefined } })
  })
  it('下载校验同一内容摘要，不把改变版本的文件交给用户', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: new Blob(['file']), headers: { 'x-result-content-sha256': 'b'.repeat(64) } })
    await expect(resultsApi.document({ kind: 'case', id: 'saved', content_sha256: 'a'.repeat(64) }, 'docx')).rejects.toThrow('material_version_changed')
  })
  it('设施保存和判断传递固定幂等键，不从GET偷偷创建', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    await resultsApi.freezeFacility(7, { idempotency_key: 'stable-request', valid_at: '2026-09-30T00:00:00Z' })
    expect(api.post).toHaveBeenCalledWith('/results/facilities/7', { idempotency_key: 'stable-request', valid_at: '2026-09-30T00:00:00Z' })
    const payload = { decision: 'insufficient_evidence' as const, note: '资料不足', additional_sources: [], idempotency_key: 'judgment-request' }
    await resultsApi.judge({ kind: 'facility', id: 'saved', content_sha256: 'a'.repeat(64) }, payload)
    expect(api.post).toHaveBeenLastCalledWith('/results/facility/saved/judgments', { ...payload, content_sha256: 'a'.repeat(64) })
    expect(api.get).not.toHaveBeenCalled()
  })
  it('路径仅允许固定成果类型，编号编码', () => {
    expect(isResultKind('__proto__')).toBe(false); expect(isResultKind('conclusion')).toBe(true)
    expect(resultPath('topic', 'a/b')).toBe('/reports?kind=topic&resultId=a%2Fb')
  })
  it('目录、来源与返回路径保留检索、类型、分页和业务对象，不带入旧材料ID', () => {
    const context = new URLSearchParams('kind=meeting&resultId=9&subject=case&subjectId=42&catalogQ=管线&catalogKind=meeting&catalogOffset=40&fromId=old&fromKind=case&caseId=42&statuses=pending&statuses=processing')
    const path = resultPath('meeting', '10', context)
    const params = new URLSearchParams(path.split('?')[1])
    expect(params.get('catalogQ')).toBe('管线'); expect(params.get('catalogOffset')).toBe('40'); expect(params.get('subjectId')).toBe('42')
    expect(params.get('resultId')).toBe('10'); expect(params.has('fromId')).toBe(false)
    expect(params.get('caseId')).toBe('42'); expect(params.getAll('statuses')).toEqual(['pending', 'processing'])
    const catalog = new URLSearchParams(materialCatalogPath(context).split('?')[1])
    expect(catalog.has('resultId')).toBe(false); expect(catalog.get('catalogKind')).toBe('meeting')
    const source = new URLSearchParams(materialSourcePath({ kind: 'case', id: 'source', content_sha256: 'a' }, { kind: 'meeting', id: '9', content_sha256: 'b' }, context).split('?')[1])
    expect(source.get('fromKind')).toBe('meeting'); expect(source.get('fromId')).toBe('9'); expect(source.get('catalogOffset')).toBe('40')
  })
  it('文件名可识别类型、标题、日期、冻结版本，去掉路径和控制字符', () => {
    const item = { kind: 'topic', title: '9月/管线:对照\u0000', created_at: '2026-09-30T12:00:00Z', content_sha256: 'a'.repeat(64) } as ResultItem
    expect(materialFilename(item, 'docx')).toBe('专题材料-9月_管线_对照_-2026-09-30-aaaaaaaa.docx')
  })
  it('读取指定格式携带冻结内容摘要并验证响应格式', async () => {
    const presentation = { template: 'case_summary', label: '案件资料摘要', schema_version: 'material-presentation-7.4-1',
      boundary: '通用整理格式，不是单位正式样表', options: [{ id: 'full', label: '完整资料' }, { id: 'case_summary', label: '案件资料摘要' }] }
    const data = { kind: 'case', id: 'saved', content_sha256: 'a'.repeat(64), document: { blocks: [] }, presentation }
    vi.mocked(api.get).mockResolvedValue({ data })
    const options = { template: 'case_summary' as const, expectedContentSha256: data.content_sha256 }
    expect(await resultsApi.read('case', 'saved', undefined, options)).toEqual(data)
    expect(api.get).toHaveBeenLastCalledWith('/results/case/saved', { signal: undefined, params: { template: 'case_summary', expected_content_sha256: data.content_sha256 } })
    vi.mocked(api.get).mockResolvedValue({ data: { ...data, presentation: { ...presentation, template: 'full' } } })
    await expect(resultsApi.read('case', 'saved', undefined, options)).rejects.toThrow('material_template_invalid')
    vi.mocked(api.get).mockResolvedValue({ data: { ...data, content_sha256: 'b'.repeat(64) } })
    await expect(resultsApi.read('case', 'saved', undefined, options)).rejects.toThrow('material_version_changed')
  })
  it('拒绝不适用的格式，不请求后台也不默默回退完整正文', async () => {
    await expect(resultsApi.read('meeting', 'saved', undefined, { template: 'case_summary' })).rejects.toThrow('material_template_not_applicable')
    await expect(resultsApi.document({ kind: 'topic', id: 'saved', content_sha256: 'a'.repeat(64) }, 'pdf', undefined, { template: 'period_brief' })).rejects.toThrow('material_template_not_applicable')
    expect(api.get).not.toHaveBeenCalled()
  })
  it.each(['docx', 'pdf'] as const)('导出%s同时核验格式和内容，并明确传入预期版本', async format => {
    const item = { kind: 'facility' as const, id: 'frozen', content_sha256: 'a'.repeat(64) }
    const blob = new Blob(['file'])
    vi.mocked(api.get).mockResolvedValue({ data: blob, headers: { 'x-result-content-sha256': item.content_sha256, 'x-result-template': 'facility_sheet' } })
    expect(await resultsApi.document(item, format, undefined, { template: 'facility_sheet' })).toBe(blob)
    expect(api.get).toHaveBeenLastCalledWith(`/results/facility/frozen/document.${format}`, { responseType: 'blob', signal: undefined,
      params: { template: 'facility_sheet', expected_content_sha256: item.content_sha256 } })
    vi.mocked(api.get).mockResolvedValue({ data: blob, headers: { 'x-result-content-sha256': item.content_sha256, 'x-result-template': 'full' } })
    await expect(resultsApi.document(item, format, undefined, { template: 'facility_sheet' })).rejects.toThrow('material_template_invalid')
  })
  it('来源阅读默认完整格式，返回材料保持原格式和内容版本且不携带活动设施', () => {
    const context = new URLSearchParams('kind=case&resultId=one&assetId=71&template=case_summary&catalogOffset=20&return_to=%2Fcases%3FcaseId%3D4')
    const source = new URLSearchParams(materialSourcePath({ kind: 'meeting', id: 'm', content_sha256: 'b'.repeat(64) },
      { kind: 'case', id: 'one', content_sha256: 'a'.repeat(64) }, context).split('?')[1])
    expect(source.has('template')).toBe(false); expect(source.has('assetId')).toBe(false)
    expect(source.get('fromTemplate')).toBe('case_summary'); expect(source.get('fromContentSha256')).toBe('a'.repeat(64))
    expect(source.get('return_to')).toBe('/cases?caseId=4'); expect(source.get('catalogOffset')).toBe('20')
    const returned = new URLSearchParams(resultPath('case', 'one', source, { template: 'case_summary', expectedContentSha256: 'a'.repeat(64) }).split('?')[1])
    expect(returned.get('template')).toBe('case_summary'); expect(returned.get('expected_content_sha256')).toBe('a'.repeat(64))
  })
  it('常用格式文件名附上业务格式名称，完整资料仍保持旧命名', () => {
    const item = { kind: 'case', title: '管线材料', created_at: '2026-10-05', content_sha256: 'a'.repeat(64) } as ResultItem
    expect(materialFilename(item, 'pdf', 'case_summary')).toBe('案件成果-管线材料-2026-10-05-aaaaaaaa-案件资料摘要.pdf')
    expect(materialFilename(item, 'docx')).toBe('案件成果-管线材料-2026-10-05-aaaaaaaa.docx')
  })
})
