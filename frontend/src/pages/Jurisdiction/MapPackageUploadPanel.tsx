import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, Progress, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { mapPackageImportsApi } from '../../services/mapPackageImports'
import { mapPackageStatus, uploadPackageFiles } from './mapPackageUpload'

function PackageUploadWorkspace({ onRegistered }: { onRegistered: (bundleId: number) => void }) {
  const { user, sessionEpoch } = useAuth()
  const [manifest, setManifest] = useState<File | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [runId, setRunId] = useState('')
  const [restoreId, setRestoreId] = useState('')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const [notice, setNotice] = useState('')
  const [progress, setProgress] = useState({ done: 0, total: 0, name: '' })
  const mounted = useRef(true)
  const busyRef = useRef(false)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; controller.current?.abort() } }, [])
  const task = useQuery({
    queryKey: ['map-package-import', user?.id, sessionEpoch, runId],
    queryFn: ({ signal }) => mapPackageImportsApi.get(runId, signal), enabled: !!runId,
    refetchInterval: query => ['queued', 'validating'].includes(query.state.data?.status || '') ? 3000 : false,
    retry: false, gcTime: 0,
  })
  const run = task.isSuccess ? task.data : undefined
  const act = async (work: () => Promise<void>) => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true); setFailure(''); setNotice('')
    try { await work() } catch (error) {
      if (mounted.current) setFailure(`${error instanceof Error ? error.message : '请求未完成'}。保留任务及所选文件；请刷新任务核对后继续，当前地图不会因此切换。`)
    } finally { busyRef.current = false; if (mounted.current) setBusy(false) }
  }
  const create = () => act(async () => {
    if (!manifest || manifest.size <= 0 || manifest.size > 2 * 1024 * 1024) throw new Error('请选择不超过 2 MiB 的 manifest.json')
    controller.current = new AbortController()
    const result = await mapPackageImportsApi.create(manifest, controller.current.signal)
    if (!mounted.current) return
    if (result.id !== runId) { setFiles([]); setProgress({ done: 0, total: 0, name: '' }) }
    else void task.refetch()
    setRunId(result.id); setRestoreId(result.id)
    setNotice('任务已保存。请保留任务编号，关闭后可凭编号恢复；重复提交同一清单会找回同一任务。')
  })
  const upload = () => act(async () => {
    if (!run) return
    controller.current = new AbortController()
    await uploadPackageFiles(run, files, { signal: controller.current.signal, upload: mapPackageImportsApi.upload,
      onProgress: (done, total, name) => { if (mounted.current) setProgress({ done, total, name }) } })
    if (!mounted.current) return
    await task.refetch()
    setNotice(controller.current.signal.aborted ? '已暂停。刷新后按服务器缺片清单继续。' : '所选分片已上传；上传回执不等于验包通过，更不等于地图发布。')
  })
  return <section aria-label="分片地图包上传与恢复" style={{ margin: '16px 0' }}>
    <Alert type="info" showIcon message="分片上传、后台验包、注册、构建发布分别确认"
      description="仅接收已制作的公共地图分片包。此处不会下载地图、启用道路路由或自动切换当前版本。旧 ZIP 路径仍可使用。" />
    <Space direction="vertical" style={{ width: '100%', marginTop: 12 }}>
      <label>地图分片清单（manifest.json）<input type="file" accept=".json" disabled={busy}
        onChange={event => { setManifest(event.target.files?.[0] || null); setFailure('') }} /></label>
      <Button disabled={!manifest || busy} onClick={() => void create()}>创建或找回同清单任务</Button>
      <Space.Compact style={{ width: '100%' }}>
        <Input aria-label="恢复地图上传任务编号" placeholder="粘贴以前保留的任务编号" value={restoreId} disabled={busy}
          onChange={event => setRestoreId(event.target.value)} />
        <Button disabled={busy || !restoreId.trim()} onClick={() => {
          if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(restoreId.trim())) { setFailure('任务编号格式不正确，请使用完整编号。'); return }
          if (restoreId.trim() === runId) { void task.refetch(); return }
          setRunId(restoreId.trim()); setFiles([]); setFailure(''); setNotice(''); setProgress({ done: 0, total: 0, name: '' })
        }}>恢复任务</Button>
      </Space.Compact>
      {notice && <Alert type="info" showIcon message={notice} />}
      {failure && <Alert type="warning" showIcon role="alert" message={failure} />}
      {task.isError && <Alert type="error" showIcon message="任务读取失败或当前无权访问；旧缓存不作为可操作状态。" />}
      {runId && <p>任务编号：<code>{runId}</code> <Button size="small" disabled={busy} loading={task.isFetching} onClick={() => void task.refetch()}>刷新任务</Button></p>}
      {run && <>
        <p><strong>{mapPackageStatus(run)}</strong> · 地图包 {run.bundle_id}</p>
        <p>服务器已接收 {run.received_chunks} / {run.total_chunks} 片（仅上传回执）。</p>
        {run.error_code && <Alert type="warning" showIcon message={`验包错误：${run.error_code}`} description="可替换已损坏分片，再提交后台验包；上一有效地图继续使用。" />}
        <details><summary>缺片清单（{run.missing_chunks.length}）</summary><pre style={{ maxHeight: 180, overflow: 'auto' }}>{run.missing_chunks.join('\n') || '上传回执已齐，仍需后台检查内容。'}</pre></details>
        {['receiving', 'failed'].includes(run.status) && <>
          <label>选择 .part 分片，可一次多选<input key={runId} type="file" accept=".part" multiple disabled={busy}
            onChange={event => { setFiles(Array.from(event.target.files || [])); setFailure('') }} /></label>
          <p>已选 {files.length} 片。{run.status === 'failed' ? '重验前请重新上传需要替换的分片；服务端将核对清单摘要。' : '只补服务器缺少的分片，已接收分片自动跳过。'}</p>
          {progress.total > 0 && <div><Progress percent={Math.round(progress.done / progress.total * 100)} status="normal" /><span>{progress.name}</span></div>}
          <Space><Button disabled={busy || !files.length} onClick={() => void upload()}>上传所选分片</Button>
            {busy && <Button onClick={() => controller.current?.abort()}>暂停本次上传</Button>}
            <Button disabled={busy || run.status !== 'receiving' || run.missing_chunks.length > 0} onClick={() => void act(async () => {
              await mapPackageImportsApi.submit(run.id)
              if (mounted.current) { await task.refetch(); setNotice('已交后台验包，可稍后凭任务编号回来查看。尚未注册或发布。') }
            })}>提交后台验包</Button></Space>
        </>}
        {run.status === 'render_validated' && <Button disabled={busy} onClick={() => void act(async () => {
          const result = await mapPackageImportsApi.register(run.id)
          if (mounted.current) { onRegistered(result.public_bundle_id); await task.refetch(); setNotice('已注册为离线显示地图包。请在下方选择厂区、构建并明确发布；道路路由不因此启用。') }
        })}>{run.registration ? '使用已注册地图包' : '注册为可构建地图包'}</Button>}
      </>}
    </Space>
  </section>
}

export default function MapPackageUploadPanel(props: { onRegistered: (bundleId: number) => void }) {
  const { user, sessionEpoch } = useAuth()
  return <PackageUploadWorkspace key={`${user?.id}:${sessionEpoch}`} {...props} />
}
