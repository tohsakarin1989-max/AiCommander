import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { resultsApi, isResultKind, resultPath, materialCatalogPath, materialSourcePath, materialFilename, type ResultItem } from './results'
vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
describe('统一材料接口', () => {
  beforeEach(() => vi.resetAllMocks())
  it('只按类型与固定ID读取，错误身份响应拒绝', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { kind: 'facility', id: 'other', content_sha256: 'a'.repeat(64), document: { blocks: [] } } })
    await expect(resultsApi.read('facility', 'wanted')).rejects.toThrow('material_contract_invalid')
    expect(api.get).toHaveBeenCalledWith('/results/facility/wanted', { signal: undefined })
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
})
