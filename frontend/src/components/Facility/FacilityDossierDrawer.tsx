import { useEffect, useRef, useState } from 'react'
import { Alert, Drawer, Spin } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { facilityAnalysisApi, type FacilityDossier, type FacilitySection } from '../../services/facilityAnalysis'
import { dossierSourcePath, parseRegionalContext, writeRegionalContext, type RegionalSelection } from '../../services/regionalContext'
import { ComputabilityContent, FacilityIdentityContent, FacilityTemporalContent, FacilityTimeControls } from './FacilityIdentityPanel'
import FacilityCaseLinkForm, { FacilityCaseLinkRevoke } from './FacilityCaseLinkForm'
import FacilityMaterialActions from './FacilityMaterialActions'
import FacilityDataIssues, { LedgerOriginalButton } from './FacilityDataIssues'
import './FacilityAnalysis.css'

export const sectionLabels: Record<keyof FacilityDossier['sections'], string> = {
  production: '生产资料与台账来源', record_links: '有明确记录的案件关联', nearby_cases: '空间邻近案件',
  candidate_links: '待核验候选关联', events: '关联事件', results: '历史研判与报告', roads: '入口与道路条件',
  tech_defense: '技防资料', history_conditions: '历史条件对照',
}
export const evidenceStateLabels = { ready: '已有资料', empty: '未找到匹配记录', missing: '资料缺失', stale: '资料已过期',
  restricted: '资料受限', unavailable: '暂不可读', partial: '资料不完整' }

const fieldLabels: Record<string, string> = {
  occurred_time: '发生时间', created_at: '记录时间', source_id: '资料来源编号', source_revision: '台账来源版本',
  source_record_id: '台账记录编号', row_number: '原始台账行', version: '设施版本', external_id: '外部稳定编号',
  change_type: '变更类型', facility_link_verified: '设施入口归属核验', connection_status: '道路连接状态',
  review_id: '核验记录编号', verified: '资料核验', import_id: '道路资料批次', road_import_id: '参考道路批次',
  map_snapshot_id: '原成果地图版本', profile_id: '原案件画像版本', report_id: '历史报告编号', result_id: '研判成果编号',
  artifact_id: '道路附件编号', meeting_id: '来源会议', distance_km: '直线距离（公里）', review_status: '事件复核状态',
  case_in_window: '关联案件是否在本期', conditions: '已记录通行条件', valid_from: '有效起始', valid_to: '有效截止',
  analysis_at: '分析条件时刻', vehicle: '参考车型', network_id: '路网版本', policy_revision: '通行资料版本',
  allowed: '是否许可', allowed_vehicles: '允许车型', prohibited_vehicles: '限制车型', status: '记录状态',
  relation_type: '材料记载的关系', source_state: '来源版本状态', evidence_state: '材料状态',
  source_reference_id: '材料依据引用', source_revision_id: '登记时案件来源版本', note: '登记说明',
  sheet_name: '原工作表', header_row: '表头行', column: '原列名', column_number: '原列序号', cell: '原单元格',
  field: '对应字段', columns: '字段位置', parent_claim_id: '修正前声明编号', correction_note: '修正说明',
  locator_state: '行列定位状态', original: '原件目录', filename: '原文件名', sha256: '原文件校验摘要',
  download_access: '原件访问范围', run_id: '导入批次', field_group: '字段组', decision: '采用状态',
  state: '记录状态', source_claim_id: '来源声明编号', previous_decision_id: '此前采用依据',
  decision_id: '字段采用记录', known_at: '系统接收时间',
}
const valueLabels: Record<string, string> = { pending_review: '待复核', confirmed: '已复核确认（保留原记录含义）', rejected: '已驳回',
  connected: '已核验连接', disconnected: '未连接', unknown: '未知', inferred: '系统候选', pending: '待处理',
  recorded: '人工已登记', revoked: '已撤销（仅保留历史）', current: '当前版本', stale: '来源已变化，需重新核对',
  available: '材料当前可用', metadata_only: '仅有目录，未入库文件', unavailable: '材料暂不可用',
  incident_site: '记载为案发地点', recovery_site: '记载为回收地点', mentioned: '原文明确提及',
  map_administrator: '仅地图管理员可下载整份原件', legacy_unrecorded: '旧记录未保存完整行列位置',
  coordinates: '坐标与转换依据', geometry: '坐标与转换依据', water_cut: '含水率与测量口径', production: '产量与生产属性', identity: '身份信息',
  details: '名称与一般生产属性', accepted: '已采用', unchanged: '值未变化', conflict: '有冲突，未当作确定值',
  set: '明确登记值', not_provided: '本次未提供', clear: '已明确清空', withdraw: '已撤销该来源值' }
function EvidenceValue({ value }: { value: unknown }) {
  if (value == null) return <>未知</>
  if (typeof value === 'boolean') return <>{value ? '是' : '否'}</>
  if (typeof value === 'string' || typeof value === 'number') return <>{valueLabels[String(value)] || String(value)}</>
  if (Array.isArray(value)) return <>{value.map((item, i) => <span key={i}><EvidenceValue value={item} />{i < value.length - 1 ? '；' : ''}</span>)}</>
  if (typeof value === 'object') return <dl>{Object.entries(value).map(([key, item]) => <div key={key}><dt>{fieldLabels[key] || key}</dt><dd><EvidenceValue value={item} /></dd></div>)}</dl>
  return <>未提供</>
}

export function FacilitySectionContent({ section, params, allowRecord = false, allowManage = false }: { section: FacilitySection; params: URLSearchParams; allowRecord?: boolean; allowManage?: boolean }) {
  if (section.state === 'restricted') return <p role="status">资料受限，无法展示内容和数量。</p>
  if (section.state === 'unavailable') return <p role="status">资料暂不可读，请稍后重试；不能据此判断没有记录。</p>
  return <>
    <p className="facility-state">{evidenceStateLabels[section.state] || '状态待核'}{section.total != null ? ` · ${section.total} 条` : ''}</p>
    {section.boundary && <p>{section.boundary}</p>}
    {(section.items ?? []).map((item, index) => <article className="facility-evidence" key={`${item.id}:${index}`}>
      <strong>{item.label}</strong>{item.detail && <p>{item.detail}</p>}
      {item.case_id != null && <Link to={dossierSourcePath(`/cases?caseId=${item.case_id}`, params)}>查看案件 #{item.case_id}</Link>}
      {item.event_id != null && <Link to={dossierSourcePath(`/events?eventId=${item.event_id}`, params)}>查看事件 #{item.event_id}</Link>}
      <dl>{Object.entries(fieldLabels).filter(([key]) => item[key] != null).map(([key, label]) => <div key={key}><dt>{label}</dt><dd><EvidenceValue value={item[key]} /></dd></div>)}</dl>
      {item.case_in_window === false && <p>该关联案件位于时间窗外，保留关联依据，不纳入本期案件数。</p>}
      {item.routing_available === false && <p>当前只展示已登记入口，未取得本次道路路径结果。</p>}
      {!!item.versions && <details><summary>原成果条件与版本</summary><EvidenceValue value={item.versions} /></details>}
      {!!item.claim_trace && <details><summary>原件与行列出处</summary><EvidenceValue value={item.claim_trace} /></details>}
      {!!item.field_decisions && <details><summary>字段采用依据</summary><EvidenceValue value={item.field_decisions} /></details>}
      {allowManage && typeof item.run_id === 'string' && typeof item.original_filename === 'string'
        && <LedgerOriginalButton runId={item.run_id} filename={item.original_filename} />}
      {!!item.support?.length && <p>支持依据：{item.support.join('；')}</p>}
      {!!item.counter?.length && <p>反向依据：{item.counter.join('；')}</p>}
      {!!item.gaps?.length && <p>信息缺口：{item.gaps.join('；')}</p>}
      {!!item.evidence_refs?.length && <details><summary>来源引用</summary><ul>{item.evidence_refs.map((ref, i) => <li key={i}>{ref}</li>)}</ul></details>}
      {allowRecord && item.relation_kind === 'recorded_material_link' && typeof item.association_id === 'number' && item.status === 'recorded'
        && <FacilityCaseLinkRevoke key={item.association_id} associationId={item.association_id} />}
    </article>)}
    {!!section.gaps?.length && <p>资料缺口：{section.gaps.join('；')}</p>}
    {section.state === 'empty' && <p>未找到记录不等于没有相关情况。</p>}
  </>
}

export function FacilityDossierContent({ data, params, sourceSnapshot, changedSections = [], allowManage = false, allowRecord = false }: {
  data: FacilityDossier; params: URLSearchParams; sourceSnapshot?: string; changedSections?: string[]; allowManage?: boolean; allowRecord?: boolean
}) {
  const historical = params.has('valid_at') || params.has('valid_from') || params.has('known_at')
  return <div className="facility-dossier">
    <h2>{String(data.facility.name)} <small>稳定编号 {String(data.facility.id)}</small></h2>
    <p>{data.boundary}</p>
    {params.get('time_scope') === 'unknown' && <p role="status">来源案件时间不足，下面只读当前设施资料，不作为案发时条件。</p>}
    {sourceSnapshot && <p>从冻结地图 {sourceSnapshot} 打开；以下为按当前权限读取的设施资料，原成果版本保持不变。</p>}
    {params.get('resultRef') && <p>原成果引用：{params.get('resultRef')}。仅保留返回线索，不作为读取权限或当前资料版本。</p>}
    <section aria-label="设施身份与来源"><h3>设施身份与来源</h3><FacilityIdentityContent identity={data.identity} allowManage={allowManage} /></section>
    <section aria-label="业务有效资料"><h3>{historical ? '指定时间条件的生产资料' : '当下有效的生产资料'}</h3><FacilityTemporalContent temporal={data.temporal_context} /></section>
    <section aria-label="计算资料准备"><h3>计算资料准备</h3>{historical && <p>按所选时点与当前权限核对计算资料，不证明历史上实际可通行。</p>}<ComputabilityContent data={data.computability} /></section>
    {data.summary.state === 'restricted' ? <p role="status">生产资料摘要受限，无法展示历史摘要或版本数量。</p> : <>
      <p>资料摘要版本：{data.summary.revision ?? '尚未形成'} · {data.summary.state === 'ready' ? '已形成' : data.summary.state === 'stale' ? '待更新' : '待形成'}</p>
      {data.summary.state !== 'ready' && <p role="status">生产资料摘要待更新；以下关联仍按当前权限实时只读计算，不代表案件未办结。</p>}
    </>}
    {!!changedSections.length && <p role="status">本次读取变化：{changedSections.map(name => sectionLabels[name as keyof typeof sectionLabels] || name).join('、')}。</p>}
    {historical && <p className="facility-current-boundary" role="status">下方台账、案件关联、道路和成果按当前权限与资料读取。它们不是上述历史时点的完整还原，案件统计仍使用原来的起止时间窗。</p>}
    {Object.entries(sectionLabels).map(([key, label]) => <section key={key} aria-label={label}>
      <h3>{historical ? '当前读取 · ' : ''}{label}</h3>{data.sections[key as keyof typeof sectionLabels]
        ? <FacilitySectionContent section={data.sections[key as keyof typeof sectionLabels]} params={params} allowRecord={key === 'record_links' && allowRecord} allowManage={allowManage} />
        : <p>该项资料暂不可读，不能据此判断没有记录。</p>}
      {key === 'record_links' && allowRecord && !['restricted', 'unavailable'].includes(data.sections.record_links?.state)
        && <FacilityCaseLinkForm key={Number(data.facility.id)} assetId={Number(data.facility.id)} initialCaseId={parseRegionalContext(params).caseId} />}
      {key === 'production' && allowRecord && !['restricted', 'unavailable'].includes(data.sections.production?.state)
        && <FacilityDataIssues key={Number(data.facility.id)} assetId={Number(data.facility.id)} production={data.sections.production} />}
    </section>)}
    {!!data.gaps.length && <section><h3>资料缺口</h3><ul>{data.gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul></section>}
    <details><summary>版本依据</summary><dl>{Object.entries(data.versions).filter(([key, value]) => key !== 'section_versions' && typeof value !== 'object').map(([key, value]) =>
      <div key={key}><dt>{key}</dt><dd>{String(value ?? '未知')}</dd></div>)}</dl></details>
  </div>
}

export default function FacilityDossierDrawer() {
  const [params, setParams] = useSearchParams()
  const context = parseRegionalContext(params)
  const { user, sessionEpoch } = useAuth()
  const [changedSections, setChangedSections] = useState<string[]>([])
  const previous = useRef<{ identity: string; versions: Record<string, unknown> } | null>(null)
  const filters = { start_date: context.startDate, end_date: context.endDate, valid_at: context.validAt, known_at: context.knownAt,
    valid_from: context.validFrom, valid_to: context.validTo, knowledge_mode: context.knowledgeMode }
  const identity = `${user?.id}:${sessionEpoch}:${context.assetId}:${JSON.stringify(filters)}`
  useEffect(() => {
    const open = (event: Event) => {
      const detail = (event as CustomEvent<{ assetId: number; sourceSnapshot?: string; timeContext?: RegionalSelection }>).detail
      if (!Number.isSafeInteger(detail?.assetId) || detail.assetId <= 0) return
      setParams(current => {
        const temporal: RegionalSelection = {}
        for (const key of ['valid_at', 'valid_from', 'valid_to', 'known_at', 'knowledge_mode', 'time_scope', 'resultRef'] as const) {
          if (detail.timeContext && key in detail.timeContext) temporal[key] = detail.timeContext[key]
        }
        const next = writeRegionalContext(current, { ...temporal, assetId: detail.assetId })
        if (detail.sourceSnapshot && detail.sourceSnapshot !== 'current') next.set('mapSnapshot', detail.sourceSnapshot)
        else if (detail.sourceSnapshot === 'current') next.delete('mapSnapshot')
        next.delete('facility_source_snapshot')
        return next
      })
    }
    window.addEventListener('aic:open-facility', open)
    return () => window.removeEventListener('aic:open-facility', open)
  }, [setParams])
  const query = useQuery({ queryKey: ['facility-dossier', user?.id, sessionEpoch, context.assetId, filters],
    queryFn: ({ signal }) => facilityAnalysisApi.dossier(context.assetId!, filters, signal),
    enabled: context.assetId != null && !context.error, retry: false, gcTime: 0, staleTime: 0, refetchInterval: 30_000 })
  const data = !context.error && !query.isError && query.data?.facility.id === context.assetId ? query.data : undefined
  useEffect(() => {
    if (!data) { previous.current = null; setChangedSections([]); return }
    const versions = data.versions.section_versions as Record<string, unknown> | undefined
    if (!versions) return
    const last = previous.current
    setChangedSections(last?.identity === identity ? Object.keys(versions).filter(key => last.versions[key] !== versions[key]) : [])
    previous.current = { identity, versions }
  }, [data, identity])
  const close = () => setParams(current => { const next = writeRegionalContext(current, { assetId: null }); next.delete('facility_source_snapshot'); return next })
  return <Drawer title="设施综合档案" open={params.has('assetId')} onClose={close} width="min(720px, 94vw)"
    getContainer={() => (document.fullscreenElement as HTMLElement | null) ?? document.body} destroyOnClose>
    <FacilityTimeControls key={identity} validAt={context.validAt} validFrom={context.validFrom} validTo={context.validTo} knownAt={context.knownAt} knowledgeMode={context.knowledgeMode}
      onApply={selection => setParams(current => writeRegionalContext(current, selection), { replace: true })} />
    {context.error ? <Alert type="error" message={context.error} /> : query.isError
      ? <Alert type="warning" message="设施不存在、当前不可访问或资料读取失败；未展示旧缓存。" action={<button onClick={() => void query.refetch()}>重试</button>} />
      : data ? <><button className="btn-ghost" onClick={() => void query.refetch()} disabled={query.isFetching}>刷新资料</button>
        <FacilityMaterialActions key={identity} assetId={context.assetId!} allowed={user?.role === 'admin' || user?.role === 'analyst'} filters={filters} />
        <FacilityDossierContent data={data} params={params} sourceSnapshot={context.mapSnapshot ?? params.get('facility_source_snapshot') ?? undefined} changedSections={changedSections} allowManage={user?.role === 'admin'} allowRecord={user?.role === 'admin' || user?.role === 'analyst'} /></>
        : <div role="status"><Spin /> 正在读取设施资料…</div>}
  </Drawer>
}
