import type { MapPackageImport } from '../../services/mapPackageImports'

export function mapPackageStatus(run: MapPackageImport): string {
  if (run.registration) return '已注册，可选择地图包构建；尚未代表已发布'
  const labels: Record<MapPackageImport['status'], string> = {
    receiving: '等待补齐分片', queued: '已排队，等待后台验包', validating: '后台正在验包',
    render_validated: '显示内容验包通过，等待注册', failed: '验包失败，当前地图保持不变',
  }
  return labels[run.status] || '任务状态待读取'
}

export function packageFilesToUpload(run: MapPackageImport, files: File[]): File[] {
  if (!['receiving', 'failed'].includes(run.status)) return []
  const names = new Set<string>()
  for (const file of files) {
    if (!/^[a-z0-9][a-z0-9_-]{0,99}\.part$/.test(file.name) || file.size <= 0 || file.size > 16 * 1024 * 1024) {
      throw new Error(`分片 ${file.name} 名称或大小不符合要求，单片应为 1 字节至 16 MiB。`)
    }
    if (names.has(file.name)) throw new Error(`选择了重名分片 ${file.name}，请核对文件。`)
    names.add(file.name)
  }
  // Failed content must be replaceable even when receipt counts say complete.
  return run.status === 'failed' ? files : files.filter(file => run.missing_chunks.includes(file.name))
}

export async function uploadPackageFiles(run: MapPackageImport, files: File[], options: {
  signal: AbortSignal
  upload: (id: string, file: File, signal: AbortSignal) => Promise<unknown>
  onProgress: (completed: number, total: number, name: string) => void
}): Promise<void> {
  const selected = packageFilesToUpload(run, files)
  if (!selected.length) throw new Error('所选文件没有待补分片，请先刷新任务核对缺片清单。')
  for (let index = 0; index < selected.length; index += 1) {
    if (options.signal.aborted) return
    await options.upload(run.id, selected[index], options.signal)
    if (options.signal.aborted) return
    options.onProgress(index + 1, selected.length, selected[index].name)
  }
}
