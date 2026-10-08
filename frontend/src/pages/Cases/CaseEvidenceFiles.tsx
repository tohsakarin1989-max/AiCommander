import { useEffect, useRef, useState } from 'react'
import { Button, Popconfirm } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { caseApi } from '../../services/cases'

function EvidenceFileRow({ caseId, referenceId, writable }: { caseId: number; referenceId: number; writable: boolean }) {
  const { user, sessionEpoch } = useAuth()
  const cache = useQueryClient()
  const [error, setError] = useState('')
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  const query = useQuery({ queryKey: ['case-evidence-reference', caseId, referenceId, user?.id, sessionEpoch], queryFn: ({ signal }) => caseApi.getSourceReference(caseId, referenceId, signal), retry: false })
  const revoke = useMutation({ mutationFn: () => caseApi.revokeEvidenceFile(caseId, referenceId), onSuccess: () => {
    for (const key of ['case-evidence-reference', 'case-file-references', 'case-sources', 'case-unified-result']) void cache.invalidateQueries({ queryKey: [key, caseId] })
  } })
  const download = useMutation({ mutationFn: () => caseApi.downloadEvidenceFile(caseId, referenceId), onSuccess: blob => {
    if (!active.current) return
    const extension = ({ 'application/pdf': 'pdf', 'image/png': 'png', 'image/jpeg': 'jpg' } as Record<string, string>)[blob.type || query.data?.evidence?.media_type || '']
    const title = (query.data?.locator?.title || `案件${caseId}-佐证${referenceId}`).replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').slice(0, 100)
    const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = extension && !title.toLowerCase().endsWith(`.${extension}`) ? `${title}.${extension}` : title; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }, onError: () => setError('材料暂不可下载，未使用目录路径代替文件。') })
  if (query.isError) return <li role="alert">材料引用暂不可读取。</li>
  if (!query.data) return <li>正在核对材料引用…</li>
  const available = query.data.availability === 'available'
  return <li><strong>{query.data.locator?.title || `材料引用 ${referenceId}`}</strong> · {available ? '原件已入库' : query.data.availability === 'revoked' ? '已撤销，保留历史' : '仅目录记录，未确认原件'}
    <div><Button size="small" disabled={!available} loading={download.isPending} onClick={() => { setError(''); download.mutate() }}>下载原件</Button>{writable && available && <Popconfirm title="撤销此原件的可用状态？历史引用保留。" onConfirm={() => revoke.mutate()}><Button size="small" loading={revoke.isPending}>撤销可用状态</Button></Popconfirm>}</div>
    {(error || revoke.isError) && <p role="alert">{error || '撤销未完成，请重试。'}</p>}
  </li>
}

export default function CaseEvidenceFiles({ caseId }: { caseId: number }) {
  const { user, sessionEpoch } = useAuth()
  return <ScopedCaseEvidenceFiles key={`${caseId}:${user?.id}:${sessionEpoch}`} caseId={caseId} />
}

function ScopedCaseEvidenceFiles({ caseId }: { caseId: number }) {
  const { user, sessionEpoch } = useAuth()
  const cache = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [notice, setNotice] = useState('')
  const [pages, setPages] = useState<Array<number | undefined>>([undefined])
  const writable = user?.role === 'admin' || user?.role === 'analyst'
  const sources = useQuery({ queryKey: ['case-file-references', caseId, user?.id, sessionEpoch, pages[pages.length - 1]], queryFn: ({ signal }) => caseApi.getCaseSources(caseId, signal, { limit: 1, reference_kind: 'evidence', references_limit: 20, before_reference: pages[pages.length - 1] }), retry: false })
  const upload = useMutation({ mutationFn: (file: File) => caseApi.uploadEvidenceFile(caseId, file), onSuccess: result => {
    setNotice(result.reused ? '本案已有相同原件，已复用材料引用。' : '佐证原件已入库。')
    setPages([undefined])
    if (input.current) input.current.value = ''
    for (const key of ['case-file-references', 'case-sources', 'case-evidence', 'case-unified-result']) void cache.invalidateQueries({ queryKey: [key, caseId] })
  }, onError: () => setNotice('上传未完成。请检查文件类型、大小和当前权限，原案件记录不受影响。') })
  const references = sources.isError ? [] : (sources.data?.references || []).filter(item => item.kind === 'evidence' && typeof item.id === 'number')
  return <div className="detail-section case-source-details"><h3>佐证原件与稳定引用</h3>
    <p>仅保存原件，不执行 OCR 或文件中的指令。目录登记不代表文件已入库。</p>
    {writable && <label>上传 PNG、JPEG 或 PDF（不超过 4 MiB）<input ref={input} type="file" accept="image/png,image/jpeg,application/pdf" disabled={upload.isPending} onChange={event => {
      const file = event.target.files?.[0]; if (!file) return
      if (!file.size || file.size > 4 * 1024 * 1024) { setNotice('文件须为 1 字节至 4 MiB。'); return }
      setNotice(''); upload.mutate(file)
    }} /></label>}
    {upload.isPending && <p role="status">正在保存原件…</p>}{notice && <p role={upload.isError ? 'alert' : 'status'}>{notice}</p>}
    {sources.isError ? <p role="alert">材料引用列表暂不可读，不能据此判断没有材料。<Button onClick={() => void sources.refetch()}>重试</Button></p> : sources.isPending ? <p>正在读取引用…</p> : !references.length ? <p>本页无原件引用，可返回上一页或登记材料目录。</p> : <ul>{references.map(item => <EvidenceFileRow key={String(item.id)} caseId={caseId} referenceId={Number(item.id)} writable={writable} />)}</ul>}
    <nav aria-label="佐证原件分页"><Button disabled={pages.length === 1 || sources.isFetching} onClick={() => setPages(previous => previous.slice(0, -1))}>上一页</Button><span>第 {pages.length} 页</span><Button disabled={sources.isError || !sources.data?.next_before_reference || sources.isFetching} onClick={() => setPages(previous => [...previous, sources.data!.next_before_reference!])}>下一页</Button></nav>
  </div>
}
