import { describe, expect, it, vi } from 'vitest'
import { mapDataIssuesApi } from './mapDataIssues'

const calls = vi.hoisted(() => ({ get: vi.fn().mockResolvedValue({ data: {} }), post: vi.fn().mockResolvedValue({ data: {} }) }))
vi.mock('./api', () => ({ default: calls }))

describe('问题标注与原件接口', () => {
  it('只发送标注，不发送设施修改，列表分页可取消', async () => {
    const signal = new AbortController().signal
    await mapDataIssuesApi.list(8, 2, signal)
    expect(calls.get).toHaveBeenCalledWith('/jurisdiction/data-issues', { params: { asset_id: 8, page: 2, page_size: 10 }, signal })
    await mapDataIssuesApi.create(8, '单位待核', { field_group: 'production', asset_version_id: 4 })
    expect(calls.post).toHaveBeenCalledWith('/jurisdiction/feedback', {
      feedback_type: 'data_issue', asset_id: 8, notes: '单位待核', source_reference: { field_group: 'production', asset_version_id: 4 },
    })
  })
  it('原件只使用本系统批次下载，不接受外部URL或路径', async () => {
    await mapDataIssuesApi.original('batch/1')
    expect(calls.get).toHaveBeenLastCalledWith('/map-ingest-runs/batch%2F1/original', { responseType: 'blob' })
  })
})
