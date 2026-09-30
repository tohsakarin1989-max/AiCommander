import { useRef, useState } from 'react'
import { Button, Popconfirm } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { caseApi } from '../../services/cases'

function EvidenceFileRow({ caseId, referenceId, writable }: { caseId: number; referenceId: number; writable: boolean }) {
  const { user, sessionEpoch } = useAuth()
  const cache = useQueryClient()
  const [error, setError] = useState('')
  const query = useQuery({ queryKey: ['case-evidence-reference', caseId, referenceId, user?.id, sessionEpoch], queryFn: ({ signal }) => caseApi.getSourceReference(caseId, referenceId, signal), retry: false })
  const revoke = useMutation({ mutationFn: () => caseApi.revokeEvidenceFile(caseId, referenceId), onSuccess: () => {
    for (const key of ['case-evidence-reference', 'case-file-references', 'case-sources', 'case-unified-result']) void cache.invalidateQueries({ queryKey: [key, caseId] })
  } })
  const download = useMutation({ mutationFn: () => caseApi.downloadEvidenceFile(caseId, referenceId), onSuccess: blob => {
    const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = `佐证-${referenceId}`; link.click(); URL.revokeObjectURL(url)
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
  const cache = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [notice, setNotice] = useState('')
  const writable = user?.role === 'admin' || user?.role === 'analyst'
  const sources = useQuery({ queryKey: ['case-file-references', caseId, user?.id, sessionEpoch], queryFn: ({ signal }) => caseApi.getCaseSources(caseId, signal), retry: false })
  const upload = useMutation({ mutationFn: (file: File) => caseApi.uploadEvidenceFile(caseId, file), onSuccess: result => {
    setNotice(result.reused ? '本案已有相同原件，已复用材料引用。' : '佐证原件已入库。')
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
    {sources.isError ? <p role="alert">材料引用列表暂不可读，不能据此判断没有材料。</p> : sources.isPending ? <p>正在读取引用…</p> : !references.length ? <p>尚无原件引用，可先登记材料目录。</p> : <ul>{references.slice(0, 20).map(item => <EvidenceFileRow key={String(item.id)} caseId={caseId} referenceId={Number(item.id)} writable={writable} />)}</ul>}
    {references.length > 20 && <p>当前展示前 20 条材料引用，其他目录仍保留在案件记录中。</p>}
  </div>
}
