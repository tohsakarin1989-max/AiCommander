import { beforeEach, describe, expect, it, vi } from 'vitest'
import { caseDraftsApi, type CaseDraftSave } from './caseDrafts'
import { caseApi } from './cases'
import { caseImportsApi } from './caseImports'

const requests = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('./api', () => ({ default: requests }))

describe('私有恢复与严格编辑接口契约', () => {
  beforeEach(() => { vi.clearAllMocks(); for (const fn of Object.values(requests)) fn.mockResolvedValue({ data: {} }) })
  it('草稿保存重试使用相同目标和版本，不自动改变请求', async () => {
    const payload: CaseDraftSave = { expected_revision: 2, operational_area_id: 1, schema_version: 1, form_snapshot: { values: { description: '未完成合成内容' } } }
    await caseDraftsApi.save('same-draft', payload); await caseDraftsApi.save('same-draft', payload)
    expect(requests.put.mock.calls).toEqual([['/case-drafts/same-draft', payload], ['/case-drafts/same-draft', payload]])
    await caseDraftsApi.submit('same-draft', 3, { description: '合成案情' })
    expect(requests.post).toHaveBeenCalledWith('/case-drafts/same-draft/submit', { expected_revision: 3, case_payload: { description: '合成案情' } })
    await caseDraftsApi.submit('same-draft', 3, { description: '合成案情' }, true)
    expect(requests.post).toHaveBeenLastCalledWith('/case-drafts/same-draft/submit', { expected_revision: 3, case_payload: { description: '合成案情' }, confirm_only: true })
  })
  it('版本化编辑与旧PUT分离，携带原版本；只读接口支持取消', async () => {
    const signal = new AbortController().signal
    await caseApi.getEditSnapshot(8, signal)
    expect(requests.get).toHaveBeenCalledWith('/cases/8/edit-snapshot', { signal })
    await caseApi.updateEditSnapshot(8, 9, { description: '我的修改' })
    expect(requests.put).toHaveBeenCalledWith('/cases/8/edit-snapshot', { expected_revision: 9, case_payload: { description: '我的修改' } })
  })
  it('恢复列表分页，不用本地存储代替授权服务', async () => {
    const signal = new AbortController().signal
    await caseDraftsApi.list(2, signal)
    expect(requests.get).toHaveBeenCalledWith('/case-drafts', { params: { page: 2, page_size: 20, status: 'all' }, signal })
    await caseImportsApi.batches(3, 1, signal)
    expect(requests.get).toHaveBeenCalledWith('/case-imports/batches', { params: { page: 3, page_size: 20, operational_area_id: 1 }, signal })
    await caseDraftsApi.remove('private', 4)
    expect(requests.delete).toHaveBeenCalledWith('/case-drafts/private', { params: { expected_revision: 4 } })
  })
})
