import { describe, expect, it, vi } from 'vitest'
import { caseApi } from './cases'
import api from './api'

vi.mock('./api', () => ({ default: { post: vi.fn() } }))

describe('case import time interpretation', () => {
  it('passes the same explicit timezone for preview and commit', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { created: 0 } })
    const file = new Blob(['occurred_time,description']) as File
    await caseApi.previewImportCases(file, 1, { time_zone: 'Asia/Shanghai' })
    await caseApi.importCases(file, false, 1, { time_zone: 'Asia/Shanghai' })
    const calls = vi.mocked(api.post).mock.calls
    expect(calls[calls.length - 2]?.[2]?.params).toMatchObject({ dry_run: true, time_zone: 'Asia/Shanghai' })
    expect(calls[calls.length - 1]?.[2]?.params).toMatchObject({ dry_run: false, time_zone: 'Asia/Shanghai' })
  })
  it('preserves explicit ignored columns in the serialized mapping', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { created: 0 } })
    await caseApi.previewImportCases(new Blob(['fixture']) as File, 1, {
      field_mapping: { 日期: 'occurred_time', 内容: 'description', 案情描述: null },
    })
    const calls = vi.mocked(api.post).mock.calls
    expect(JSON.parse(calls[calls.length - 1][2]?.params.field_mapping)).toEqual({
      日期: 'occurred_time', 内容: 'description', 案情描述: null,
    })
  })
})
