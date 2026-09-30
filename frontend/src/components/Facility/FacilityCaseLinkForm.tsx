import { useRef, useState } from 'react'
import { Popconfirm } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { caseApi } from '../../services/cases'
import { facilityAnalysisApi, type FacilityCaseLinkCreate } from '../../services/facilityAnalysis'
import type { CaseSources } from '../../types'

export function materialReferenceOptions(sources?: CaseSources): Array<{ id: number; label: string }> {
  const fields: Record<string, string> = { description: '案情原文', location: '地点原文', modus_operandi: '作案手法', location_detail: '地点详情' }
  return (sources?.references || []).filter(item => typeof item.id === 'number' && Number.isSafeInteger(item.id) && item.id > 0
    && (item.kind === 'evidence' || (item.kind === 'text' && item.source_revision_id === sources?.current_revision_id))).map(item => {
    const locator = item.locator && typeof item.locator === 'object' ? item.locator as Record<string, unknown> : {}
    const title = typeof locator.title === 'string' ? locator.title : item.kind === 'text' ? `原文引用${typeof locator.field === 'string' ? `（${fields[locator.field] || '原始记录'}）` : ''}` : '佐证材料'
    return { id: Number(item.id), label: `${title} · 引用 ${item.id}` }
  })
}

export default function FacilityCaseLinkForm({ assetId, initialCaseId }: { assetId: number; initialCaseId?: number | null }) {
  const { user, sessionEpoch } = useAuth()
  const cache = useQueryClient()
  const [caseId, setCaseId] = useState(initialCaseId ? String(initialCaseId) : '')
  const [lookupId, setLookupId] = useState<number | null>(null)
  const [referenceId, setReferenceId] = useState<number | null>(null)
  const [relationType, setRelationType] = useState<FacilityCaseLinkCreate['relation_type']>('mentioned')
  const [note, setNote] = useState('')
  const request = useRef<{ fingerprint: string; key: string } | null>(null)
  const query = useQuery({ queryKey: ['facility-case-link-source', user?.id, sessionEpoch, assetId, lookupId],
    queryFn: async ({ signal }) => { const [record, sources] = await Promise.all([caseApi.getCase(lookupId!, signal), caseApi.getCaseSources(lookupId!, signal)]); return { record, sources } },
    enabled: lookupId != null, retry: false, gcTime: 0 })
  const data = !query.isError && query.data?.record.id === lookupId && query.data.sources.case_id === lookupId && Number(caseId) === lookupId ? query.data : undefined
  const options = materialReferenceOptions(data?.sources)
  const selectedReference = options.find(item => item.id === referenceId)
  const reference = useQuery({ queryKey: ['facility-case-link-reference', user?.id, sessionEpoch, lookupId, referenceId],
    queryFn: ({ signal }) => caseApi.getSourceReference(lookupId!, referenceId!, signal), enabled: !!data && !!selectedReference, retry: false, gcTime: 0 })
  const usable = !reference.isError && reference.data?.id === referenceId && reference.data.availability === 'available'
  const save = useMutation({ mutationFn: async () => {
    if (!data?.sources.current_revision_id || !lookupId || !referenceId || !selectedReference || !usable || !note.trim()) throw new Error('来源未核对')
    const payload = { case_id: lookupId, source_reference_id: referenceId, source_revision_id: data.sources.current_revision_id, relation_type: relationType, note: note.trim() }
    const fingerprint = JSON.stringify(payload)
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, key: crypto.randomUUID() }
    await facilityAnalysisApi.createCaseLink(assetId, { ...payload, request_key: request.current.key })
  }, onSuccess: () => {
    for (const key of ['facility-dossier', 'map-readiness']) void cache.invalidateQueries({ queryKey: [key] })
  } })
  return <details className="facility-manual-link"><summary>按材料登记明确关联（按需）</summary>
    <p>登记材料中的地点关系，不认定实际盗取来源、嫌疑人或正式案件链条。邻近或系统候选不能代替材料依据。</p>
    <label>案件编号（系统 ID）<input type="number" min={1} step={1} value={caseId} disabled={save.isPending} onChange={event => { setCaseId(event.target.value); setLookupId(null); setReferenceId(null); save.reset() }} /></label>
    <button className="btn-ghost" disabled={save.isPending || query.isFetching || !/^[1-9]\d*$/.test(caseId) || !Number.isSafeInteger(Number(caseId))} onClick={() => {
      setReferenceId(null); save.reset(); if (lookupId === Number(caseId)) void query.refetch(); else setLookupId(Number(caseId))
    }}>核对案件与材料</button>
    {lookupId != null && (query.isError ? <p role="alert">案件或材料来源不可读取，未使用旧缓存。</p> : !data ? <p role="status">正在读取当前来源版本…</p> : <>
      <p>案件：<strong>{data.record.case_number || `#${data.record.id}`}</strong>。当前来源第 {data.sources.revisions.find(item => item.id === data.sources.current_revision_id)?.revision ?? '尚未形成'} 版。</p>
      <label>材料依据<select value={referenceId ?? ''} disabled={save.isPending} onChange={event => { setReferenceId(event.target.value ? Number(event.target.value) : null); save.reset() }}>
        <option value="">选择已有来源引用</option>{options.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
      {!options.length && <p>尚无可选来源引用，请先在案件档案补录材料；不能仅凭填写说明建立明确关联。</p>}
      {selectedReference && (reference.isError ? <p role="alert">该材料当前不可读取。</p> : reference.isFetching ? <p role="status">正在核对材料可用性…</p> : !usable ? <p role="status">该引用已撤销、仅有目录或尚不可用，不能作为此次关联依据。</p> : <p>该来源引用当前可用，保存时仍会核对案件版本与权限。</p>)}
    </>)}
    <label>材料记载的关系<select value={relationType} disabled={save.isPending} onChange={event => { setRelationType(event.target.value as FacilityCaseLinkCreate['relation_type']); save.reset() }}>
      <option value="mentioned">原文提及此设施</option><option value="incident_site">记载为案发地点</option><option value="recovery_site">记载为回收地点</option></select></label>
    <label>登记说明<textarea rows={2} maxLength={1000} value={note} disabled={save.isPending} onChange={event => { setNote(event.target.value); save.reset() }} /></label>
    <Popconfirm title="确认登记该材料记载的地点关系？不会自动形成正式研判结论。" onConfirm={() => save.mutate()}>
      <button className="btn-ghost" disabled={save.isPending || !data?.sources.current_revision_id || !usable || !selectedReference || !note.trim()}>确认登记材料关联</button></Popconfirm>
    {save.isPending && <p role="status">正在保存材料关联…</p>}{save.isSuccess && <p role="status">已保存材料关联，正在刷新档案。</p>}
    {save.isError && <p role="alert">关联未保存。请重新核对案件版本、材料与权限，不会自动换用其他依据。</p>}
  </details>
}

export function FacilityCaseLinkRevoke({ associationId }: { associationId: number }) {
  const cache = useQueryClient()
  const [note, setNote] = useState('')
  const revoke = useMutation({ mutationFn: () => facilityAnalysisApi.revokeCaseLink(associationId, note.trim()), onSuccess: () => {
    void cache.invalidateQueries({ queryKey: ['facility-dossier'] })
  } })
  return <details className="facility-manual-link"><summary>撤销此人工材料关联</summary>
    <label>撤销说明<textarea rows={2} maxLength={1000} value={note} onChange={event => setNote(event.target.value)} disabled={revoke.isPending} /></label>
    <Popconfirm title="确认撤销此人工登记关系？依据与历史记录保留。" onConfirm={() => revoke.mutate()}><button className="btn-ghost" disabled={!note.trim() || revoke.isPending}>确认撤销关联</button></Popconfirm>
    {revoke.isError && <p role="alert">撤销未完成，请核对权限后重试。</p>}{revoke.isSuccess && <p role="status">已撤销，历史依据仍保留。</p>}
  </details>
}
