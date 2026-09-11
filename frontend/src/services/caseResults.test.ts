import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { caseResultsApi } from './caseResults'

vi.mock('./api', () => ({ default: { get: vi.fn() } }))
const hash = 'a'.repeat(64)
beforeEach(() => vi.clearAllMocks())

describe('冻结成果下载', () => {
  it('道路附件下载固定留存编号并拒绝摘要错配', async () => {
    const signal = new AbortController().signal
    const road = { id: 'saved-road', content_sha256: 'b'.repeat(64) }
    const blob = new Blob(['%PDF-test'], { type: 'application/pdf' })
    const headers = { 'x-result-content-sha256': hash, 'x-road-artifact-id': road.id, 'x-road-artifact-sha256': road.content_sha256 }
    vi.mocked(api.get).mockResolvedValue({ data: blob, headers })
    expect(await caseResultsApi.download('result', hash, 'pdf', signal, road)).toBe(blob)
    expect(api.get).toHaveBeenCalledWith('/case-results/result/document.pdf', {
      responseType: 'blob', signal, timeout: 180000, params: { road_artifact_id: road.id },
    })
    vi.mocked(api.get).mockResolvedValue({ data: blob, headers: { ...headers, 'x-road-artifact-sha256': 'wrong' } })
    await expect(caseResultsApi.download('result', hash, 'pdf', signal, road)).rejects.toThrow('道路成果版本不一致')
  })
  it('使用固定成果、取消信号和二进制请求，不请求最新成果', async () => {
    const signal = new AbortController().signal
    const blob = new Blob(['%PDF-test'], { type: 'application/pdf' })
    vi.mocked(api.get).mockResolvedValue({ data: blob, headers: { 'x-result-content-sha256': hash } })
    expect(await caseResultsApi.download('result/1', hash, 'pdf', signal)).toBe(blob)
    expect(api.get).toHaveBeenCalledWith('/case-results/result%2F1/document.pdf', {
      responseType: 'blob', signal, timeout: 180000,
    })
  })
  it.each(['hash', 'type', 'empty'])('拒绝错误的下载内容：%s', async damage => {
    vi.mocked(api.get).mockResolvedValue({
      data: new Blob([damage === 'empty' ? '' : 'test'], { type: damage === 'type' ? 'text/html' : 'application/pdf' }),
      headers: { 'x-result-content-sha256': damage === 'hash' ? 'b'.repeat(64) : hash },
    })
    await expect(caseResultsApi.download('r1', hash, 'pdf', new AbortController().signal)).rejects.toThrow('版本不一致')
  })
})
