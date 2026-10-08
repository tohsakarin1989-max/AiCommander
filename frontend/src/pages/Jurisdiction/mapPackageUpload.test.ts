import { describe, expect, it, vi } from 'vitest'
import { mapPackageStatus, packageFilesToUpload, uploadPackageFiles } from './mapPackageUpload'
import type { MapPackageImport } from '../../services/mapPackageImports'

const run = (status: MapPackageImport['status'] = 'receiving'): MapPackageImport => ({
  id: 'synthetic', bundle_id: 'public-map', status, manifest_hash: 'sha', total_chunks: 2, received_chunks: 1,
  missing_chunks: ['second.part'], error_code: null, publish_ready: false, registration: null, progress_basis: 'receipts',
})
const file = (name: string, size = 1) => ({ name, size }) as File

describe('分片地图任务续传', () => {
  it('按服务器缺片续传，不重复发送已接收文件；失败验包允许替换已有分片', () => {
    const files = [file('first.part'), file('second.part')]
    expect(packageFilesToUpload(run(), files)).toEqual([files[1]])
    expect(packageFilesToUpload({ ...run('failed'), missing_chunks: [] }, files)).toEqual(files)
    expect(packageFilesToUpload(run('validating'), files)).toEqual([])
  })
  it('同名或越界分片在发送前拒绝，不把选择文件视作验包通过', () => {
    expect(() => packageFilesToUpload(run(), [file('same.part'), file('same.part')])).toThrow('重名')
    expect(() => packageFilesToUpload(run(), [file('large.part', 16 * 1024 * 1024 + 1)])).toThrow('16 MiB')
    expect(mapPackageStatus(run('render_validated'))).toContain('等待注册')
    expect(mapPackageStatus({ ...run('render_validated'), registration: { public_bundle_id: 3, acceptance_scope: 'offline_display', routing_available: false, current_changed: false, reused: false } })).toContain('尚未代表已发布')
  })
  it('网络失败保留原选择；串行停止，不擅自提交或注册', async () => {
    const files = [file('first.part'), file('second.part')]
    const upload = vi.fn().mockRejectedValue(new Error('timeout')), onProgress = vi.fn()
    await expect(uploadPackageFiles({ ...run(), missing_chunks: files.map(item => item.name) }, files,
      { signal: new AbortController().signal, upload, onProgress })).rejects.toThrow('timeout')
    expect(upload).toHaveBeenCalledTimes(1); expect(onProgress).not.toHaveBeenCalled()
    expect(files).toHaveLength(2)
  })
  it('暂停后不上传下一片，任务编号不变以便刷新恢复', async () => {
    const controller = new AbortController(), files = [file('first.part'), file('second.part')]
    const upload = vi.fn().mockImplementation(async () => { controller.abort() }), onProgress = vi.fn()
    await uploadPackageFiles({ ...run(), missing_chunks: files.map(item => item.name) }, files,
      { signal: controller.signal, upload, onProgress })
    expect(upload).toHaveBeenCalledTimes(1)
    expect(upload.mock.calls[0][0]).toBe('synthetic'); expect(onProgress).not.toHaveBeenCalled()
  })
})
