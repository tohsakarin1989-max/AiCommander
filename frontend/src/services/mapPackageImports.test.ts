import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mapPackageImportsApi } from './mapPackageImports'

const requests = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), put: vi.fn() }))
vi.mock('./api', () => ({ default: requests }))
describe('已有地图分片接口', () => {
  beforeEach(() => { vi.clearAllMocks(); Object.values(requests).forEach(fn => fn.mockResolvedValue({ data: {} })) })
  it('原清单与分片二进制分别发送，不改为multipart或猜测新接口', async () => {
    const manifest = { name: 'manifest.json' } as File, part = { name: 'part_01.part' } as File
    const signal = new AbortController().signal
    await mapPackageImportsApi.create(manifest, signal)
    expect(requests.post).toHaveBeenCalledWith('/map-package-imports', manifest, { headers: { 'Content-Type': 'application/json' }, signal })
    await mapPackageImportsApi.upload('fixed-run', part, signal)
    expect(requests.put).toHaveBeenCalledWith('/map-package-imports/fixed-run/chunks/part_01.part', part, { headers: { 'Content-Type': 'application/octet-stream' }, signal })
  })
  it('恢复、后台验包与注册独立调用；没有任何自动发布动作', async () => {
    const signal = new AbortController().signal
    await mapPackageImportsApi.get('fixed-run', signal); await mapPackageImportsApi.submit('fixed-run'); await mapPackageImportsApi.register('fixed-run')
    expect(requests.get).toHaveBeenCalledWith('/map-package-imports/fixed-run', { signal })
    expect(requests.post.mock.calls).toEqual([['/map-package-imports/fixed-run/submit'], ['/map-package-imports/fixed-run/register']])
  })
})
