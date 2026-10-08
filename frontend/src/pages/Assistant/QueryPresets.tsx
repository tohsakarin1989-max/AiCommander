import { useState } from 'react'
import type { InitialQueryContext, QueryPreset, QueryPresetName } from '../../services/intelligentQueries'
import CaseSearch from '../../components/CaseSearch'
import FacilitySearch from '../../components/Facility/FacilitySearch'
import { useAuth } from '../../auth/AuthContext'

export const presetLabels: Record<QueryPresetName, string> = {
  case_count: '统计当前范围', case_process: '核对案件过程', case_result: '解释已有案件成果',
  facility_dossier: '查看设施档案', facility_history: '查看当时有效生产资料', coverage_scenario: '比较资源覆盖方案',
}
const positiveId = (value: string) => /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : null
export function presetArguments(name: QueryPresetName, values: Record<string, string>, context?: InitialQueryContext): QueryPreset {
  const base = { ...(context?.filters || {}), ...(context?.source_case_id ? { case_id: context.source_case_id } : {}) }
  const area = values.area ? positiveId(values.area) : context?.filters.operational_area_id
  if (values.area && !area) throw new Error('辖区编号无效。')
  if (name === 'case_count') return { name, arguments: base }
  const args: Record<string, unknown> = area ? { operational_area_id: area } : {}
  if (name === 'case_process' || name === 'case_result') {
    const id = context?.source_case_id || positiveId(values.caseId || '')
    if (!id) throw new Error('请先查找并选择案件。')
    args.case_id = id
  } else if (name !== 'coverage_scenario') {
    const id = positiveId(values.assetId || '')
    if (!id) throw new Error('请先查找并选择设施。')
    args.asset_id = id
  }
  function instant(key: string, label: string) {
    if (!values[key] || !Number.isFinite(new Date(values[key]).getTime())) throw new Error(`请填写${label}，系统不猜测时间。`)
    return new Date(values[key]).toISOString()
  }
  if (name === 'facility_history') { args.valid_at = instant('validAt', '业务适用时间'); args.known_at = instant('knownAt', '资料截止时间') }
  if (name === 'coverage_scenario') {
    if (!area) throw new Error('覆盖比较需要明确辖区。')
    args.as_of = instant('asOf', '比较时间')
    const ids = (values.disabled || '').split(/[,，\s]+/).filter(Boolean).map(positiveId)
    if (ids.some(id => !id)) throw new Error('停用资源须填写有效登记编号。')
    args.disabled_resource_ids = [...new Set(ids)]
    if (values.moveId || values.latitude || values.longitude) {
      const id = positiveId(values.moveId || ''), lat = Number(values.latitude), lon = Number(values.longitude)
      if (!id || !values.latitude || !values.longitude || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) throw new Error('移动方案需要有效资源编号和经纬度。')
      args.movements = [{ resource_id: id, latitude: lat, longitude: lon }]
    }
  }
  return { name, arguments: args }
}

type Props = {
  context?: InitialQueryContext; assetId?: string; disabled: boolean; onRun: (title: string, preset: QueryPreset) => void
}
export default function QueryPresets(props: Props) {
  const { user, sessionEpoch } = useAuth()
  return <QueryPresetsSession key={`${user?.id}:${sessionEpoch}:${props.assetId}:${JSON.stringify(props.context)}`} {...props} />
}
function QueryPresetsSession({ context, assetId, disabled, onRun }: Props) {
  const [name, setName] = useState<QueryPresetName>(assetId ? 'facility_dossier' : context?.source_case_id ? 'case_process' : 'case_count')
  const [values, setValues] = useState<Record<string, string>>({ assetId: assetId || '' })
  const [error, setError] = useState('')
  const [chosenLabel, setChosenLabel] = useState({ case: '', facility: '' })
  const field = (key: string, label: string, type = 'text') => <label key={key}>{label}<input type={type} value={values[key] || ''} disabled={disabled}
    onChange={event => { setValues(old => ({ ...old, [key]: event.target.value })); setError('') }} /></label>
  return <details className="query-presets" open={Boolean(context?.source_case_id || assetId)}>
    <summary>直接办理常用查询（不依赖模型）</summary>
    <p>明确选择业务操作，按同一授权和证据规则执行；不会修改案件或正式资源。</p>
    <form className="query-form" onSubmit={event => {
      event.preventDefault(); if (disabled) return
      try { const preset = presetArguments(name, values, context); setError(''); onRun(presetLabels[name], preset) }
      catch (cause) { setError(cause instanceof Error ? cause.message : '条件无效。') }
    }}>
      <label>要做什么<select value={name} disabled={disabled} onChange={event => { setName(event.target.value as QueryPresetName); setError('') }}>
        {Object.entries(presetLabels).map(([key, title]) => <option key={key} value={key}>{title}</option>)}
      </select></label>
      {['case_process', 'case_result'].includes(name) && (context?.source_case_id ? <p>使用已选择案件 #{context.source_case_id}</p> : <>
        {values.caseId && <p>已选案件：{chosenLabel.case}</p>}
        <CaseSearch areaId={context?.filters.operational_area_id} disabled={disabled} selectedIds={values.caseId ? [Number(values.caseId)] : []} onChoose={item => {
          setValues(old => ({ ...old, caseId: String(item.id) })); setChosenLabel(old => ({ ...old, case: item.case_number })); setError('')
        }} />
      </>)}
      {['facility_dossier', 'facility_history'].includes(name) && <>
        {values.assetId && <p>已选设施：{chosenLabel.facility || `从设施入口带入 #${values.assetId}`}</p>}
        <details><summary>{values.assetId ? '更换设施' : '查找并选择设施'}</summary><FacilitySearch areaId={context?.filters.operational_area_id} disabled={disabled} onChoose={item => {
          setValues(old => ({ ...old, assetId: String(item.id) })); setChosenLabel(old => ({ ...old, facility: item.name })); setError('')
        }} /></details>
      </>}
      {name === 'facility_history' && <div className="query-actions">{field('validAt', '业务适用时间', 'datetime-local')}{field('knownAt', '资料截止时间', 'datetime-local')}</div>}
      {name === 'coverage_scenario' && <>
        {context?.filters.operational_area_id ? <p>当前辖区 #{context.filters.operational_area_id}</p> : field('area', '辖区编号')}
        {field('asOf', '比较时间', 'datetime-local')}{field('disabled', '假设停用的登记资源编号（逗号分隔，可不填）')}
        <details><summary>增加一个资源位置假设（可选）</summary>{field('moveId', '登记资源编号')}
          <div className="query-actions">{field('latitude', '假设纬度')}{field('longitude', '假设经度')}</div></details>
        <p>使用已登记资源做名义覆盖比较，不代表真实视场或已证明防控效果，不保存正式位置变更。</p>
      </>}
      {error && <p role="alert">{error}</p>}<button className="btn-primary" disabled={disabled} type="submit">运行此项查询</button>
    </form>
  </details>
}
