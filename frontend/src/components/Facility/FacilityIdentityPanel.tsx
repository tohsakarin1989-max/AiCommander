import { useRef, useState } from 'react'
import { Popconfirm } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { facilityAnalysisApi, type FacilityIdentityItem, type FacilityIdentity, type FacilityTemporalContext, type FacilityComputability, type FacilityComputabilityCheck } from '../../services/facilityAnalysis'
import { formatStoredTime } from '../../utils/caseValues'

export const readinessStateLabels: Record<FacilityComputabilityCheck['state'], string> = {
  ready: '资料就绪', missing: '资料缺失', unverified: '待核验', disconnected: '未连接', restricted: '权限受限', expired: '资料过期', unavailable: '服务暂不可用', not_checked: '尚未检查',
}
const identityLabels: Record<string, string> = { source_identified: '来源编号识别', bound: '人工已关联', revoked: '已撤销' }
const attributeLabels: Record<string, string> = { oil_type: '油品', oil_nature: '油品性质', owner_unit: '所属单位', production_unit: '生产单位', production_type: '生产类型', production_status: '生产状态', facility_category: '设施类别', production_output: '产量原文', daily_output: '日产量', daily_output_unit: '日产量单位', water_cut: '含水率', water_cut_min: '含水率下限', water_cut_max: '含水率上限', water_cut_unit: '含水率单位', operator: '管理单位', facility_use: '设施用途', capacity: '容量', capacity_unit: '容量单位', storage_type: '存储类型' }

function FacilityIdentityActions({ item, assetId }: { item: FacilityIdentityItem; assetId: number }) {
  const { user, sessionEpoch } = useAuth()
  const cache = useQueryClient()
  const [target, setTarget] = useState(String(assetId))
  const [previewId, setPreviewId] = useState<number | null>(null)
  const [note, setNote] = useState('')
  const [notice, setNotice] = useState('')
  const request = useRef<{ fingerprint: string; key: string } | null>(null)
  const preview = useQuery({ queryKey: ['facility-identity-target', user?.id, sessionEpoch, previewId],
    queryFn: ({ signal }) => facilityAnalysisApi.dossier(previewId!, {}, signal), enabled: previewId != null, retry: false, gcTime: 0 })
  const targetData = !preview.isError && preview.data?.facility.id === previewId && previewId === Number(target) ? preview.data : undefined
  const write = useMutation({ mutationFn: async (action: 'bind' | 'revoke') => {
    if (!note.trim()) throw new Error('请填写关联或撤销依据')
    if (action === 'bind' && (!targetData || previewId == null)) throw new Error('请先核对目标设施')
    const fingerprint = JSON.stringify([action, item.identity_id, item.decision_id, previewId, note.trim()])
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, key: crypto.randomUUID() }
    const decision = { note: note.trim(), previous_decision_id: item.decision_id, request_key: request.current.key }
    if (action === 'bind') await facilityAnalysisApi.bindIdentity(item.identity_id, { ...decision, asset_id: previewId! })
    else await facilityAnalysisApi.revokeIdentity(item.identity_id, decision)
  }, onSuccess: () => {
    setNotice('决定已保存，正在按当前权限重新读取来源身份。')
    for (const key of ['facility-dossier', 'map-readiness', 'facility-identity-target']) void cache.invalidateQueries({ queryKey: [key] })
  }, onError: () => setNotice('操作未完成。请刷新身份记录后核对权限、目标及决定版本；没有按名称自动重试关联。') })
  return <details className="facility-identity-actions"><summary>管理员：调整来源关联</summary>
    <p>只改变本条来源身份的关联，不按同名合并设施。撤销保留原决定历史。</p>
    <label>明确目标设施编号<input type="number" min={1} step={1} value={target} disabled={write.isPending} onChange={event => { setTarget(event.target.value); setPreviewId(null); setNotice('') }} /></label>
    <button className="btn-ghost" disabled={write.isPending || !/^[1-9]\d*$/.test(target) || !Number.isSafeInteger(Number(target))} onClick={() => { setPreviewId(Number(target)); setNotice('') }}>核对目标设施</button>
    {previewId != null && (preview.isError ? <p role="alert">目标设施当前不可读取，不能继续关联。</p> : !targetData ? <p role="status">正在核对目标设施…</p>
      : <p>将关联至：<strong>{String(targetData.facility.name)}</strong>（稳定编号 {previewId}）。请核实来源确实属于此设施。</p>)}
    <label>决定依据<textarea rows={2} maxLength={1000} value={note} disabled={write.isPending} onChange={event => setNote(event.target.value)} placeholder="填写台账编号、核验记录等依据" /></label>
    <div><Popconfirm title={`确认将此来源关联到设施 ${previewId ?? '待核对'}？`} onConfirm={() => write.mutate('bind')}>
      <button className="btn-ghost" disabled={write.isPending || !note.trim() || !targetData}>确认关联</button></Popconfirm>
      <Popconfirm title="确认撤销此来源关联？原决定历史保留。" onConfirm={() => write.mutate('revoke')}>
        <button className="btn-ghost" disabled={write.isPending || !note.trim() || item.status === 'revoked'}>撤销关联</button></Popconfirm></div>
    {write.isPending && <p role="status">正在保存决定…</p>}{notice && <p role={write.isError ? 'alert' : 'status'}>{notice}</p>}
  </details>
}

export function FacilityIdentityContent({ identity, allowManage = false }: { identity?: FacilityIdentity; allowManage?: boolean }) {
  if (!identity) return <p>当前接口尚未提供多来源身份记录。</p>
  if (identity.state === 'restricted') return <p role="status">来源身份资料受限，不显示内容或数量。</p>
  if (identity.state === 'unavailable') return <p role="alert">来源身份暂不可读，不能据此判断没有关联。</p>
  return <>
    <p>{identity.boundary}</p>
    {!identity.items?.length ? <p>尚无已登记的来源身份，不按同名自动合并。</p> : <ul className="facility-identities">{identity.items.map(item => <li key={item.identity_id}>
      <strong>{item.name || '来源名称未记录'}</strong><span>{identityLabels[item.status] || '身份状态待核'}</span>
      <p>来源：{item.source_name || `来源 ${item.source_id}`} · 台账编号：{item.identity_kind === 'unidentified' ? '编号待核' : item.source_record_id || '未记录'}</p>
      {allowManage && <FacilityIdentityActions key={`${item.identity_id}:${item.decision_id}`} item={item} assetId={identity.asset_id} />}
    </li>)}</ul>}
  </>
}

export function FacilityTemporalContent({ temporal }: { temporal?: FacilityTemporalContext }) {
  if (!temporal) return <p>当前接口尚未提供业务有效期与接收时间，未用更新时间代替。</p>
  if (temporal.state === 'restricted') return <p role="status">该时点的生产资料受限，不展示快照、版本或数量。</p>
  const available = temporal.state === 'ready' && temporal.snapshot
  return <>
    <p>{temporal.boundary}</p>
    {temporal.knowledge_mode && <p>资料口径：{temporal.knowledge_mode === 'as_known' ? '当时知道什么' : '现在回看历史'}{temporal.late_supplement ? '；含后来补录资料，不代表当时已掌握。' : ''}</p>}
    {temporal.query_interval && <p>完整业务区间：{formatStoredTime(temporal.query_interval.from)} 至 {formatStoredTime(temporal.query_interval.to)}，未使用中点代替。覆盖：{{ full: '全区间有资料', partial: '部分区间有资料', unknown: '尚不能确认' }[temporal.coverage ?? 'unknown']}；有资料不等于所有时段条件相同。</p>}
    <dl className="facility-time-grid"><div><dt>查询业务时点</dt><dd>{formatStoredTime(temporal.valid_at)}</dd></div><div><dt>系统已知截止</dt><dd>{formatStoredTime(temporal.known_at)}</dd></div></dl>
    {!available ? <p role="status">{temporal.query_interval ? '未形成覆盖所选条件的单一生产快照，分时段依据见下方；没有取中点或当前值代替。' : temporal.state === 'conflict' ? '该时点存在相互冲突的资料版本，未替用户选择一个版本。' : '该时点没有可确认的有效资料，未回退为当前生产属性。'}</p> : <>
      <p><strong>{temporal.snapshot!.name || '该版本名称未记录'}</strong> · 生产资料版本 {temporal.version_id ?? '未记录'}</p>
      <dl className="facility-time-grid"><div><dt>业务有效起始</dt><dd>{temporal.valid_from ? formatStoredTime(temporal.valid_from) : '未明确'}</dd></div><div><dt>业务有效截止</dt><dd>{temporal.valid_to ? formatStoredTime(temporal.valid_to) : '未记录截止'}</dd></div><div><dt>系统接收时间</dt><dd>{formatStoredTime(temporal.recorded_at)}</dd></div></dl>
      <dl className="facility-time-grid">{Object.entries(attributeLabels).filter(([key]) => temporal.snapshot!.attributes?.[key] != null).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{String(temporal.snapshot!.attributes![key])}</dd></div>)}</dl>
      <details><summary>该版本完整生产属性</summary><pre>{JSON.stringify(temporal.snapshot!.attributes || {}, null, 2)}</pre></details>
    </>}
    {temporal.groups && <section aria-label="分时段资料依据">{Object.entries(temporal.groups).map(([key, group]) => <details key={key}>
      <summary>{{ geometry: '坐标与转换依据', water_cut: '含水率与口径', production: '产量与周期', details: '一般生产属性' }[key] || key} · {{ full: '全区间有资料', partial: '部分资料', unknown: '未知' }[group.coverage]}</summary>
      {group.state === 'restricted' ? <p>此项资料受限，不展示片段和数量。</p> : <>
        {group.segments.map((segment, i) => <article key={i}><p>{formatStoredTime(segment.from)} 至 {formatStoredTime(segment.to)}（{segment.end_inclusive ? '含结束时点' : '不含结束时点'}）</p>
          <p>状态：{{ ready: '已有资料', set: '已登记', unknown: '未知', conflict: '资料冲突', clear: '已清空', withdraw: '已撤销', not_provided: '未提供' }[segment.state] || segment.state}</p>
          {['ready', 'set'].includes(segment.state) && <dl>{Object.entries(segment.values ?? {}).map(([field, value]) => <div key={field}><dt>{attributeLabels[field] || field}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '未知')}</dd></div>)}</dl>}
          {segment.late_supplement && <p>后来补录：不能视为当时已掌握。</p>}
          <ul>{segment.evidence_refs.map(ref => <li key={ref}>{ref}</li>)}</ul>
        </article>)}
        {!!group.gaps?.length && <p>缺口：{group.gaps.join('；')}</p>}
      </>}
    </details>)}</section>}
  </>
}

export function ComputabilityContent({ data }: { data?: FacilityComputability }) {
  if (!data) return <p>计算资料尚未检查，不代表道路可达或不可达。</p>
  return <>
    <p>{data.state === 'ready' ? '计算所需资料已就绪' : data.state === 'partial' ? '部分计算资料仍待补充' : '缺少计算所需资料'}，不代表已经算出可达路线。</p>
    <ul className="facility-readiness-checks">{data.checks.map(check => <li key={check.key} data-state={check.state}>
      <strong>{check.label}</strong><span>{readinessStateLabels[check.state] || '状态待核'}</span>
      <p>{check.state === 'restricted' ? '当前无权读取该项内容，不展示资料细节或数量。' : check.detail}</p>
      {check.state !== 'restricted' && !!check.evidence_refs?.length && <details><summary>核对依据</summary><ul>{check.evidence_refs.map(ref => <li key={ref}>{ref}</li>)}</ul></details>}
    </li>)}</ul><p>{data.boundary}</p>
  </>
}

export { FacilityTimeControls, facilityLocalTime, facilityQueryInstant } from './FacilityTimeControls'
