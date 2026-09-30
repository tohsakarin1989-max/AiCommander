import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { caseApi } from './cases'

vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

describe('来源与原件服务契约', () => {
  beforeEach(() => vi.clearAllMocks())
  it('来源读取是带取消信号的纯 GET，失败不返回假空列表', async () => {
    const signal = new AbortController().signal
    vi.mocked(api.get).mockResolvedValue({ data: [] })
    await caseApi.getCaseSources(7, signal); await caseApi.getCaseSourceRevision(7, 25, signal)
    await caseApi.getCaseLocations(7, signal); await caseApi.getCaseMeasurements(7, signal)
    expect(api.get).toHaveBeenNthCalledWith(1, '/cases/7/sources', { signal })
    expect(api.get).toHaveBeenNthCalledWith(2, '/cases/7/sources/25', { signal })
    expect(api.get).toHaveBeenNthCalledWith(3, '/cases/7/locations', { signal })
    expect(api.get).toHaveBeenNthCalledWith(4, '/cases/7/measurements', { signal })
    expect(api.post).not.toHaveBeenCalled()
    vi.mocked(api.get).mockRejectedValue(new Error('403'))
    await expect(caseApi.getCaseLocations(7)).rejects.toThrow('403')
  })
  it('仅上传选定文件，下载与撤销只使用服务端引用编号', async () => {
    const file = new File(['%PDF-1.7'], '佐证.pdf', { type: 'application/pdf' })
    vi.mocked(api.post).mockResolvedValue({ data: { reference_id: 9, reused: false } })
    await caseApi.uploadEvidenceFile(7, file)
    const [url, data, config] = vi.mocked(api.post).mock.calls[0]
    expect(url).toBe('/cases/7/evidence-files')
    expect((data as FormData).get('file')).toBe(file)
    expect(config?.headers).toEqual({ 'Content-Type': 'multipart/form-data' })
    vi.mocked(api.get).mockResolvedValue({ data: new Blob(['pdf']) })
    await caseApi.downloadEvidenceFile(7, 9)
    expect(api.get).toHaveBeenCalledWith('/cases/7/source-references/9/file', { responseType: 'blob' })
    await caseApi.revokeEvidenceFile(7, 9)
    expect(api.post).toHaveBeenLastCalledWith('/cases/7/source-references/9/revoke')
  })
})
